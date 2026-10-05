"""Extract scoped Python imports and evaluate a curated B-OCL boundary rule."""

import argparse
import ast
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import sys

from bocl.OCLWrapper import OCLWrapper
from besser.BUML.metamodel.object import (
    AttributeLink, DataValue, Link, LinkEnd, Object, ObjectModel,
)
from besser.BUML.metamodel.structural import (
    BinaryAssociation, Class, Constraint, DomainModel, Multiplicity,
    PrimitiveDataType, Property,
)


HERE = Path(__file__).resolve().parent
RULE_ID = "NoDirectApiDatabaseImport"


def load_components(path, root):
    """Layers are authored declarations, not guesses based on directory names."""
    components = json.loads(path.read_text())["components"]
    if not isinstance(components, list) or not components:
        raise ValueError("components must be a nonempty list")
    for field in ("id", "module", "path"):
        values = [item[field] for item in components]
        if len(values) != len(set(values)):
            raise ValueError(f"Duplicate component {field}")
    for item in components:
        if not isinstance(item["id"], str) or not item["id"]:
            raise ValueError("Each component needs a nonempty ID")
        if not re.fullmatch(r"[a-zA-Z_]\w*", item["module"]):
            raise ValueError("This pilot supports top-level Python modules only")
        if item["layer"] not in {"api", "service", "database"}:
            raise ValueError("This pilot's layers are api, service, and database")
        source = (root / item["path"]).resolve()
        if not source.is_relative_to(root) or source.suffix != ".py":
            raise ValueError("Component paths must be Python files inside the root")
        if Path(item["path"]).as_posix() != item["module"] + ".py":
            raise ValueError("A module must map to its top-level <module>.py file")
    return components


def extract(root, components):
    """An IMPORTS edge establishes an import, not a runtime call or DB write."""
    by_module = {item["module"]: item for item in components}
    edges, sources, unresolved = [], [], []
    for item in components:
        source = root / item["path"]
        content = source.read_bytes()
        source_hash = hashlib.sha256(content).hexdigest()
        sources.append({
            **item, "claim_status": "declared_component_and_layer",
            "sha256": source_hash,
        })
        tree = ast.parse(content, filename=item["path"])
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = ["." * node.level + (node.module or "")]
            else:
                continue
            for module in modules:
                anchor = {
                    "path": item["path"], "line": node.lineno,
                    "symbol": ast.unparse(node), "sha256": source_hash,
                }
                if module not in by_module:
                    unresolved.append({"from": item["id"], "module": module,
                                       "evidence": anchor})
                    continue
                edges.append({
                    "from": item["id"], "to": by_module[module]["id"],
                    "type": "IMPORTS", "claim_status": "observed",
                    "evidence": anchor,
                })
    edges.sort(key=lambda e: (e["from"], e["evidence"]["line"], e["to"]))
    declared_paths = {item["path"] for item in components}
    unmodeled = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*.py")
        if p.relative_to(root).as_posix() not in declared_paths
    )
    return edges, sources, unresolved, unmodeled


class BoundaryModel:
    """B-UML schema: Component(layer), Dependency(source, target)."""

    def __init__(self, expression):
        self.string = PrimitiveDataType("str")
        self.layer = Property(name="layer", type=self.string)
        self.component = Class(name="Component", attributes={self.layer})
        self.dependency = Class(name="Dependency")
        self.source = Property(name="source", type=self.component,
                               multiplicity=Multiplicity(1, 1))
        self.outgoing = Property(name="outgoing", type=self.dependency,
                                 multiplicity=Multiplicity(0, "*"))
        self.target = Property(name="target", type=self.component,
                               multiplicity=Multiplicity(1, 1))
        self.incoming = Property(name="incoming", type=self.dependency,
                                 multiplicity=Multiplicity(0, "*"))
        self.source_association = BinaryAssociation(
            name="DependencySource", ends={self.source, self.outgoing})
        self.target_association = BinaryAssociation(
            name="DependencyTarget", ends={self.target, self.incoming})
        self.rule = Constraint(name=RULE_ID, context=self.dependency,
                               expression=expression, language="OCL")
        self.domain = DomainModel(
            name="StructuralBoundaryPilot",
            types={self.component, self.dependency},
            associations={self.source_association, self.target_association},
            constraints={self.rule},
        )

    def evaluate_edge(self, source_layer, target_layer):
        def component(name, layer):
            return Object(name=name, classifier=self.component, slots=[
                AttributeLink(attribute=self.layer, value=DataValue(
                    classifier=self.string, value=layer))])

        source = component("sourceComponent", source_layer)
        target = component("targetComponent", target_layer)
        edge = Object(name="observedImport", classifier=self.dependency)
        # Evaluate each observation separately to return an attributable verdict.
        Link(name="sourceLink", association=self.source_association, connections=[
            LinkEnd(name="sourceEnd", association_end=self.source, object=source),
            LinkEnd(name="outgoingEnd", association_end=self.outgoing, object=edge),
        ])
        Link(name="targetLink", association=self.target_association, connections=[
            LinkEnd(name="targetEnd", association_end=self.target, object=target),
            LinkEnd(name="incomingEnd", association_end=self.incoming, object=edge),
        ])
        observed = ObjectModel(name="ObservedImport", objects={source, target, edge})
        observed.validate()
        result = OCLWrapper(self.domain, observed).evaluate(self.rule)
        if type(result) is not bool:
            raise ValueError("The interpreter did not return a Boolean verdict")
        return result


def check(root, manifest=HERE / "components.json", rule_path=HERE / "boundary.ocl"):
    root = root.resolve()
    components = load_components(manifest, root)
    edges, sources, unresolved, unmodeled = extract(root, components)
    expression = rule_path.read_text()
    model = BoundaryModel(expression)
    # Also validate the rule when the inspected graph has no dependencies.
    # This evaluates syntax and property resolution; it is not a correctness proof.
    model.evaluate_edge("api", "service")
    by_id = {item["id"]: item for item in components}
    results = []
    for edge in edges:
        satisfied = model.evaluate_edge(by_id[edge["from"]]["layer"],
                                        by_id[edge["to"]]["layer"])
        results.append({**edge, "rule_id": RULE_ID, "satisfied": satisfied})
    violations = [result for result in results if not result["satisfied"]]
    status = "violations" if violations else (
        "incomplete" if unresolved or unmodeled else "pass-within-scope")
    return {
        "schema_version": 1, "status": status,
        "engine_versions": {name: version(name) for name in
                            ("besser", "bocl", "antlr4-python3-runtime")},
        "declarations_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "scope": "Direct static imports between declared top-level Python modules",
        "rule": {"id": RULE_ID, "expression": expression.strip(),
                 "authority": "Authored demo policy; not an inferred repository rule",
                 "sha256": hashlib.sha256(expression.encode()).hexdigest()},
        "components": sources, "results": results, "violations": violations,
        "coverage": {"unresolved_imports": unresolved, "unmodeled_python_files": unmodeled,
                     "omissions": ["runtime calls", "dynamic imports", "re-exports",
                                   "external systems", "indirect dependencies"]},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing the mapped Python modules")
    parser.add_argument("--components", type=Path, default=HERE / "components.json")
    args = parser.parse_args()
    try:
        report = check(args.root, args.components)
    except Exception as error:
        # Syntax, missing inputs, and interpreter errors are never passing results.
        print(json.dumps({"status": "error", "error": str(error)}))
        return 2
    print(json.dumps(report, indent=2))
    return {"pass-within-scope": 0, "violations": 1, "incomplete": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())

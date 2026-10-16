"""Extract Python module imports and evaluate an authored, edge-local OCL rule."""

import argparse
import ast
from datetime import datetime, timezone
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


DEFAULT_LAYERS = {"api", "service", "database"}
TOKEN = re.compile(
    r"self\.(?:(?:source|target)\.layer|kind)\b|"
    r"'[A-Za-z0-9_.:-]+'|<>|=|\(|\)|\b(?:and|or|not|implies)\b|\s+"
)


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def read_declarations(path, root):
    """Layers and exclusions belong to project intent, not inferred filenames."""
    data = json.loads(path.read_text())
    components = data["components"]
    if not isinstance(components, list) or not components:
        raise ValueError("components must be a nonempty list")
    layers = data.get("layers", sorted(DEFAULT_LAYERS))
    if not isinstance(layers, list) or not layers or any(
        not isinstance(layer, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", layer)
        for layer in layers
    ) or len(set(layers)) != len(layers):
        raise ValueError("layers must be unique nonempty identifier strings")
    for field in ("id", "module", "path"):
        values = [item[field] for item in components]
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError(f"Each component needs a nonempty {field}")
        if len(values) != len(set(values)):
            raise ValueError(f"Duplicate component {field}")
    for item in components:
        if not re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*", item["module"]):
            raise ValueError("A module must be a qualified Python module name")
        if item["layer"] not in layers:
            raise ValueError("Component layer is outside the declared layers")
        relative = Path(item["path"])
        source = (root / relative).resolve()
        if relative.is_absolute() or not source.is_relative_to(root) or source.suffix != ".py":
            raise ValueError("Component paths must be Python files inside the root")
        module_path = item["module"].replace(".", "/")
        if item["path"] not in {module_path + ".py", module_path + "/__init__.py"}:
            raise ValueError("Map each module to <module>.py or <module>/__init__.py")
    exclusions = data.get("excluded_modules", [])
    if not isinstance(exclusions, list):
        raise ValueError("excluded_modules must be a list")
    for exclusion in exclusions:
        name = exclusion["module"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*", name):
            raise ValueError("An excluded module must have a qualified name")
        if not isinstance(exclusion.get("reason"), str) or not exclusion["reason"].strip():
            raise ValueError("Each exclusion needs a reason")
        if any(item["module"] == name or item["module"].startswith(name + ".")
               for item in components):
            raise ValueError("An exclusion cannot hide a declared component")
    return data


def load_components(path, root):
    return read_declarations(path, root)["components"]


def imported_modules(node, item, by_module):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    base = node.module or ""
    if node.level:
        package = item["module"] if item["path"].endswith("/__init__.py") else (
            item["module"].rpartition(".")[0])
        parts = package.split(".") if package else []
        if node.level > len(parts):
            return ["." * node.level + base]
        base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
    modules = []
    for alias in node.names:
        candidate = base + "." + alias.name if base else alias.name
        # A mapped child identifies a module import; otherwise target the base
        # module which supplies the imported symbol. Do not follow re-exports.
        modules.append(candidate if candidate in by_module else base or candidate)
    return list(dict.fromkeys(modules))


def extract(root, components, exclusions=()):
    """IMPORTS establishes a static import, not a call or a database write."""
    by_module = {item["module"]: item for item in components}
    edges, sources, unresolved, excluded = [], [], [], []
    for item in components:
        content = (root / item["path"]).read_bytes()
        source_hash = sha256(content)
        sources.append({**item, "claim_status": "declared_component_and_layer",
                        "sha256": source_hash})
        tree = ast.parse(content, filename=item["path"])
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for module in imported_modules(node, item, by_module):
                anchor = {"path": item["path"], "line": node.lineno,
                          "symbol": ast.unparse(node), "sha256": source_hash}
                if module not in by_module:
                    observation = {"from": item["id"], "module": module, "evidence": anchor}
                    exclusion = next((entry for entry in exclusions if module == entry["module"]
                                      or module.startswith(entry["module"] + ".")), None)
                    if exclusion:
                        excluded.append({**observation, "reason": exclusion["reason"]})
                    else:
                        unresolved.append(observation)
                    continue
                edges.append({"from": item["id"], "to": by_module[module]["id"],
                              "type": "IMPORTS", "claim_status": "observed", "evidence": anchor})
    edges.sort(key=lambda edge: (edge["from"], edge["evidence"]["line"], edge["to"]))
    declared_paths = {item["path"] for item in components}
    inventory = sorted(path.relative_to(root).as_posix() for path in root.rglob("*.py"))
    unmodeled = sorted(set(inventory) - declared_paths)
    return edges, sources, unresolved, unmodeled, excluded, inventory


class BoundaryModel:
    """B-UML schema: Component(layer), Dependency(kind, source, target).

    Each observed edge gets its own object model. Graph-wide invariants require
    a separate whole-graph adapter and are deliberately rejected here.
    """

    def __init__(self, expression):
        header = re.fullmatch(
            r"\s*context\s+Dependency\s+inv\s+([A-Za-z_]\w*)\s*:\s*(.+?)\s*",
            expression, re.DOTALL)
        if not header:
            raise ValueError("Expected one named invariant with context Dependency")
        body = header.group(2)
        position = 0
        while position < len(body):
            token = TOKEN.match(body, position)
            if token is None:
                raise ValueError("Unsupported OCL: use edge-local layer/kind comparisons and Boolean operators")
            position = token.end()
        self.rule_id = header.group(1)
        self.string = PrimitiveDataType("str")
        self.layer = Property(name="layer", type=self.string)
        self.kind = Property(name="kind", type=self.string)
        self.component = Class(name="Component", attributes={self.layer})
        self.dependency = Class(name="Dependency", attributes={self.kind})
        self.source = Property(name="source", type=self.component, multiplicity=Multiplicity(1, 1))
        self.outgoing = Property(name="outgoing", type=self.dependency, multiplicity=Multiplicity(0, "*"))
        self.target = Property(name="target", type=self.component, multiplicity=Multiplicity(1, 1))
        self.incoming = Property(name="incoming", type=self.dependency, multiplicity=Multiplicity(0, "*"))
        self.source_association = BinaryAssociation(name="DependencySource", ends={self.source, self.outgoing})
        self.target_association = BinaryAssociation(name="DependencyTarget", ends={self.target, self.incoming})
        self.rule = Constraint(name=self.rule_id, context=self.dependency, expression=expression, language="OCL")
        self.domain = DomainModel(name="StructuralBoundary", types={self.component, self.dependency},
                                  associations={self.source_association, self.target_association},
                                  constraints={self.rule})

    def evaluate_edge(self, source_layer, target_layer, kind="IMPORTS"):
        for value in (source_layer, target_layer, kind):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
                raise ValueError("Model attribute values must be identifier strings")

        def slot(attribute, value):
            return AttributeLink(attribute=attribute, value=DataValue(classifier=self.string, value=value))

        source = Object(name="sourceComponent", classifier=self.component, slots=[slot(self.layer, source_layer)])
        target = Object(name="targetComponent", classifier=self.component, slots=[slot(self.layer, target_layer)])
        edge = Object(name="observedImport", classifier=self.dependency, slots=[slot(self.kind, kind)])
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


def check(root, manifest, rule_path, authority):
    if not isinstance(authority, str) or not authority.strip():
        raise ValueError("Name the rule's project authority or explicitly mark it proposed/demo")
    root = root.resolve()
    declarations = read_declarations(manifest, root)
    components = declarations["components"]
    edges, sources, unresolved, unmodeled, excluded, inventory = extract(
        root, components, declarations.get("excluded_modules", []))
    expression = rule_path.read_text()
    model = BoundaryModel(expression)
    # Exercise parsing/navigation even when the graph has zero observed imports.
    # This synthetic result is not counted as an implementation observation.
    first_layer = components[0]["layer"]
    model.evaluate_edge(first_layer, first_layer)
    by_id = {item["id"]: item for item in components}
    results = [{**edge, "rule_id": model.rule_id,
                "satisfied": model.evaluate_edge(by_id[edge["from"]]["layer"],
                                                 by_id[edge["to"]]["layer"], edge["type"])}
               for edge in edges]
    violations = [result for result in results if not result["satisfied"]]
    status = "violations" if violations else (
        "incomplete" if unresolved or unmodeled else "pass-within-scope")
    return {
        "schema_version": 1, "status": status,
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(root), "enforcement": "advisory",
        "engine_versions": {name: version(name) for name in ("besser", "bocl", "antlr4-python3-runtime")},
        "declarations": {"path": str(manifest.resolve()), "sha256": sha256(manifest.read_bytes())},
        "declarations_sha256": sha256(manifest.read_bytes()),
        "scope": "Direct static imports between declared Python modules; no re-export traversal",
        "rule": {"id": model.rule_id, "path": str(rule_path.resolve()), "expression": expression.strip(),
                 "authority": authority, "sha256": sha256(rule_path.read_bytes())},
        "components": sources, "results": results, "violations": violations,
        "coverage": {
            "status": "partial" if unresolved or unmodeled else "complete-within-scope",
            "discovery_roots": ["."], "python_file_inventory": inventory,
            "unresolved_imports": unresolved, "unmodeled_python_files": unmodeled,
            "excluded_imports": excluded,
            "omissions": ["runtime calls", "dynamic imports", "re-exports", "external systems",
                          "indirect dependencies", "graph-wide constraints"],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Python import root for the selected subsystem")
    parser.add_argument("--components", type=Path, required=True)
    parser.add_argument("--rule", type=Path, required=True)
    parser.add_argument("--authority", required=True, help="Project rule citation, or explicit proposed/demo status")
    parser.add_argument("--output", type=Path, help="Also save the JSON observation outside the skill")
    args = parser.parse_args()
    if args.output:
        destination = args.output.resolve()
        if destination in {args.components.resolve(), args.rule.resolve()} or (
            destination.is_relative_to(args.root.resolve()) and destination.suffix == ".py"
        ):
            print(json.dumps({"status": "error", "error": "Report output cannot overwrite model inputs or Python source"}))
            return 2
    try:
        report = check(args.root, args.components, args.rule, args.authority)
    except Exception as error:
        report = {"schema_version": 1, "status": "error", "error": str(error)}
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded)
        except OSError as error:
            print(json.dumps({"status": "error", "error": str(error)}))
            return 2
    print(encoded, end="")
    return {"pass-within-scope": 0, "violations": 1, "incomplete": 2, "error": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())

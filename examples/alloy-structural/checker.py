"""Checker -- the single seam, mirroring examples/mermaid/checker.py's shape.

Orchestrates: load model, extract observed edges from source, generate Alloy
source, run two named Alloy checks, and assemble a JSON report an agent can
invoke via its shell tool.

Two checks, two different kinds of question:

- ``NoForbiddenObserved`` -- same question the OCL and JSON/Mermaid pilots
  ask, re-expressed as an Alloy assertion over one fixed instance (every
  observed edge declared as a ``one sig``). A counterexample names the exact
  violating edge via its skolem binding; mapped back to evidence via
  ``als_writer``'s identifier map.
- ``NoTransitiveApiToDatabase`` -- a question the matrix-lookup and OCL
  pilots cannot ask without separate graph code: does the authored policy,
  read as a directed graph over layers, admit a multi-hop permitted path
  from ``api`` to ``database``? Evaluated against the policy alone, not
  against any observed edge.
"""
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Optional

from model_loader import load_model, model_hash, ModelValidationError
from extractor import extract
from als_writer import build_als
from alloy_runner import find_jar, run_check, witness_atoms, AlloyError

STATUS_EXIT_CODES = {
    "pass-within-scope": 0,
    "violations": 1,
    "policy-transitive-path": 1,
    "incomplete": 2,
    "error": 2,
}


def check(root: Path, model: dict, jar_path: Optional[Path] = None, run_command=None) -> dict:
    """Main check function -- highest seam, pure aside from the Alloy
    subprocess, which is reachable only through the injectable run_command."""
    root = Path(root).resolve()
    edges, sources, unresolved, unmodeled = extract(root, model)
    als_source, identifier_map = build_als(model, edges)

    jar_path = find_jar(jar_path)
    if jar_path is None:
        raise AlloyError(
            "no Alloy jar found; pass --jar, set ALLOY_JAR, or place alloy.jar "
            "next to checker.py (see README for the download step)"
        )

    with tempfile.TemporaryDirectory() as tmp:
        als_path = Path(tmp) / "model.als"
        als_path.write_text(als_source)

        forbidden_hit, forbidden_json = run_check(
            als_path, "NoForbiddenObserved", jar_path, run_command=run_command
        )
        transitive_hit, _ = run_check(
            als_path, "NoTransitiveApiToDatabase", jar_path, run_command=run_command
        )

    violating_edge_names = set(witness_atoms(forbidden_json, "NoForbiddenObserved", "e"))
    violations = []
    for edge_name, edge in identifier_map["edges"].items():
        if edge_name in violating_edge_names:
            violations.append(edge)

    status = "pass-within-scope"
    if violations:
        status = "violations"
    elif transitive_hit:
        status = "policy-transitive-path"
    elif unresolved or unmodeled:
        status = "incomplete"

    report = {
        "schema_version": 1,
        "status": status,
        "coverage": {
            "unresolved_imports": unresolved,
            "unmodeled_python_files": unmodeled,
            "omissions": [
                "runtime calls", "dynamic imports", "re-exports",
                "external systems beyond declared aliases", "transitive layers beyond api/database",
            ],
        },
        "components": sources,
        "edges": edges,
        "violations": violations,
        "policy": {
            "canonical_hash": model_hash(model),
            "matrix": model.get("policy", {}).get("matrix", {}),
        },
        "alloy": {
            "jar": str(jar_path),
            "als_source_hash": hashlib.sha256(als_source.encode()).hexdigest(),
            "checks": {
                "NoForbiddenObserved": {
                    "counterexample_found": forbidden_hit,
                    "violating_edges": sorted(violating_edge_names),
                },
                "NoTransitiveApiToDatabase": {
                    "counterexample_found": transitive_hit,
                    "note": (
                        "checks whether the policy matrix, read as a layer graph, "
                        "admits any multi-hop permitted path from api to database"
                    ),
                },
            },
        },
        "generated_from_model_hash": model_hash(model),
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing the mapped Python modules")
    parser.add_argument("--model", type=Path, default=Path(__file__).resolve().parent / "model.json")
    parser.add_argument("--jar", type=Path, default=None, help="Path to org.alloytools.alloy.dist.jar")
    args = parser.parse_args()
    try:
        model = load_model(args.model)
        report = check(args.root, model, jar_path=args.jar)
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        return 2
    print(json.dumps(report, indent=2))
    return STATUS_EXIT_CODES.get(report["status"], 2)


if __name__ == "__main__":
    sys.exit(main())

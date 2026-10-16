"""Checker - main seam."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

from model_loader import load_model, model_hash, ModelValidationError
from extractor import extract
from policy_evaluator import is_aligned
from renderer import render, id_to_class_name


def check(root: Path, model: dict, base_model: Optional[dict] = None, 
          diagram_path: Optional[Path] = None) -> dict:
    """Main check function - highest seam."""
    root = Path(root).resolve()
    if base_model is None:
        eval_policy_model = model
    else:
        eval_policy_model = base_model
    edges, sources, unresolved, unmodeled = extract(root, model)
    results = []
    for edge in edges:
        aligned = is_aligned(edge, eval_policy_model)
        verdict = aligned[0]
        satisfied = (verdict == "permitted")
        results.append({
            **edge,
            "rule_id": "aligned",
            "satisfied": satisfied,
            "verdict": verdict,
            "reason": aligned[1],
        })
    violations = []
    for r in results:
        if r["verdict"] == "forbidden":
            violations.append(r)
    model_stale = False
    if diagram_path and Path(diagram_path).exists():
        rendered = render(model)
        existing = Path(diagram_path).read_text()
        if rendered != existing:
            model_stale = True
    status = "pass-within-scope"
    if model_stale:
        status = "model-stale"
    elif violations:
        status = "violations"
    elif any(r["verdict"] == "unresolved" for r in results) or unresolved or unmodeled:
        status = "incomplete"
    id_map = {c["id"]: id_to_class_name(c["id"]) for c in model.get("components", [])}
    rendered = render(model)
    report = {
        "schema_version": 1,
        "status": status,
        "coverage": {
            "unresolved_imports": unresolved,
            "unmodeled_python_files": unmodeled,
            "omissions": ["runtime calls", "dynamic imports", "re-exports", "external systems", "indirect dependencies"]
        },
        "components": sources,
        "results": results,
        "violations": violations,
        "policy": {
            "canonical_hash": model_hash(eval_policy_model),
            "matrix": eval_policy_model.get("policy", {}).get("matrix", {})
        },
        "diagram": {
            "class_name_mapping": id_map,
            "diagram_hash": hashlib.sha256(rendered.encode()).hexdigest()
        },
        "generated_from_model_hash": model_hash(model)
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing the mapped Python modules")
    parser.add_argument("--model", type=Path, default=Path(__file__).resolve().parent / "model.json")
    parser.add_argument("--diagram", type=Path)
    args = parser.parse_args()
    try:
        model = load_model(args.model)
        report = check(args.root, model, diagram_path=args.diagram)
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        return 2
    print(json.dumps(report, indent=2))
    return {"pass-within-scope": 0, "violations": 1, "incomplete": 2, "model-stale": 1, "policy-retired": 1}.get(report["status"], 2)


if __name__ == "__main__":
    sys.exit(main())

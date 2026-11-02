"""Function-level structural checker.

Wires ``function_extractor.extract_functions`` into the existing
``model_loader`` / ``policy_evaluator`` machinery instead of reimplementing
matrix evaluation: function and class components are overlaid onto a copy of
the declared model's ``components`` (each carries a ``parent`` so
``policy_evaluator.is_aligned`` resolves its layer by inheritance), and every
extracted ``CALLS``/``CONTAINS`` edge is evaluated with the *same*
``is_aligned`` predicate ``checker.py`` already uses for ``IMPORTS`` edges.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from model_loader import load_model, model_hash, ModelValidationError
from function_extractor import extract_functions
from policy_evaluator import is_aligned
from signature_rules import evaluate_signature_rules


def _overlay_model(model: dict, function_components, class_components) -> dict:
    overlay = dict(model)
    overlay["components"] = list(model.get("components", [])) + list(class_components) + list(function_components)
    return overlay


def _normalize_fine_grained_verdict(verdict: str, reason: str):
    """``is_aligned`` treats a matrix-"permitted" cell as only "permitted" when
    that *exact* edge is also individually listed in the model's
    ``relations`` -- a convention authored at file granularity, where
    enumerating every sanctioned import is tractable. It is not tractable to
    enumerate every sanctioned function call pair the same way, so at
    function/class granularity a matrix-"permitted" cell is treated as
    sufficient on its own: an "undeclared" verdict (permitted by layer, not
    individually listed) is reported as "permitted" here. "forbidden" and
    "unresolved" verdicts are unaffected and still reported as such.
    """
    if verdict == "undeclared":
        return "permitted", "permitted_by_layer_policy"
    return verdict, reason


def check_functions(root: Path, model: dict, base_model: Optional[dict] = None) -> dict:
    root = Path(root).resolve()
    eval_policy_model = base_model if base_model is not None else model

    functions, classes, contains_edges, calls_edges, unresolved_calls = extract_functions(root, model)
    overlay = _overlay_model(eval_policy_model, functions, classes)

    results = []
    violations = []
    for edge in calls_edges + contains_edges:
        verdict, reason, extra = is_aligned(edge, overlay)
        verdict, reason = _normalize_fine_grained_verdict(verdict, reason)
        entry = {
            **edge,
            "satisfied": verdict == "permitted",
            "verdict": verdict,
            "reason": reason,
        }
        results.append(entry)
        if verdict == "forbidden":
            violations.append(entry)

    rule_results = evaluate_signature_rules(functions, calls_edges, unresolved_calls, model.get("function_rules", []))
    rule_failures = [r for r in rule_results if r["result"] == "fail"]

    if violations or rule_failures:
        status = "violations"
    elif unresolved_calls or any(r["verdict"] == "unresolved" for r in results):
        status = "incomplete"
    else:
        status = "pass-within-scope"

    return {
        "schema_version": 1,
        "status": status,
        "functions": functions,
        "classes": classes,
        "results": results,
        "violations": violations,
        "coverage": {
            "unresolved_calls": unresolved_calls,
        },
        "signature_rules": rule_results,
        "generated_from_model_hash": model_hash(model),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Directory containing the mapped Python modules")
    parser.add_argument("--model", type=Path, default=Path(__file__).resolve().parent / "model.json")
    args = parser.parse_args()
    try:
        model = load_model(args.model)
        report = check_functions(args.root, model)
    except (ModelValidationError, FileNotFoundError) as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        return 2
    print(json.dumps(report, indent=2))
    return {"pass-within-scope": 0, "violations": 1, "incomplete": 2}.get(report["status"], 2)


if __name__ == "__main__":
    sys.exit(main())

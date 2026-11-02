"""Deterministic function-signature rule evaluation (Structural model, step 5).

A rule is a small structured record inside ``model.json["function_rules"]``
-- no new DSL:

    {
      "id": "FR1",
      "pattern": "<regex matched against the function's id>",
      "min_params": <int, optional>,
      "max_params": <int, optional>,
      "param_type": {"index": <int>, "type": "<annotation string>"},   # optional
      "return_type": "<annotation string>",                            # optional
      "must_call_pattern": "<regex matched against resolved callee ids>"  # optional
    }

Every present key is evaluated independently; a rule's overall result is
"fail" if any key fails, "insufficient-information" if none fail but at
least one could not be conclusively evaluated, else "pass". Absence of an
annotation, or of any calls at all, is reported as insufficient-information,
never silently treated as pass or fail -- matching the project's rule that
missing evidence is not itself a verdict.
"""
import re
from typing import Dict, List


def _check_param_count(function: dict, rule: dict):
    params = function.get("params", [])
    n = len(params)
    if "min_params" in rule and n < rule["min_params"]:
        return "fail", f"has {n} parameter(s), expected at least {rule['min_params']}"
    if "max_params" in rule and n > rule["max_params"]:
        return "fail", f"has {n} parameter(s), expected at most {rule['max_params']}"
    return "pass", None


def _check_param_type(function: dict, rule: dict):
    spec = rule.get("param_type")
    if not spec:
        return None
    params = function.get("params", [])
    idx = spec.get("index", 0)
    if idx >= len(params):
        return "insufficient-information", f"no parameter at index {idx}"
    annotation = params[idx].get("annotation")
    if annotation is None:
        return "insufficient-information", f"parameter {idx} has no type annotation"
    if annotation != spec.get("type"):
        return "fail", f"parameter {idx} annotated '{annotation}', expected '{spec.get('type')}'"
    return "pass", None


def _check_return_type(function: dict, rule: dict):
    expected = rule.get("return_type")
    if expected is None:
        return None
    actual = function.get("returns")
    if actual is None:
        return "insufficient-information", "function has no return type annotation"
    if actual != expected:
        return "fail", f"returns '{actual}', expected '{expected}'"
    return "pass", None


def _check_must_call(function_id: str, rule: dict, calls_by_caller, unresolved_by_caller):
    pattern = rule.get("must_call_pattern")
    if not pattern:
        return None
    regex = re.compile(pattern)
    resolved_targets = calls_by_caller.get(function_id, [])
    if any(regex.search(t) for t in resolved_targets):
        return "pass", None
    if unresolved_by_caller.get(function_id):
        # It called *something* we could not resolve; we cannot rule out
        # that the unresolved call was the approved target.
        return "insufficient-information", "function has unresolved calls; approved target cannot be confirmed or excluded"
    return "fail", f"no resolved call matches '{pattern}'"


def evaluate_signature_rules(functions: List[dict], calls_edges: List[dict],
                              unresolved_calls: List[dict], rules: List[dict]) -> List[dict]:
    functions_by_id = {f["id"]: f for f in functions}
    calls_by_caller: Dict[str, List[str]] = {}
    for edge in calls_edges:
        calls_by_caller.setdefault(edge["from"], []).append(edge["to"])
    unresolved_by_caller: Dict[str, int] = {}
    for call in unresolved_calls:
        unresolved_by_caller[call["from"]] = unresolved_by_caller.get(call["from"], 0) + 1

    results = []
    for rule in rules:
        pattern = re.compile(rule["pattern"])
        matched = [fid for fid in functions_by_id if pattern.search(fid)]
        for fid in sorted(matched):
            function = functions_by_id[fid]
            outcomes = [
                _check_param_count(function, rule),
                _check_param_type(function, rule),
                _check_return_type(function, rule),
                _check_must_call(fid, rule, calls_by_caller, unresolved_by_caller),
            ]
            outcomes = [o for o in outcomes if o is not None]
            if any(status == "fail" for status, _ in outcomes):
                status = "fail"
            elif any(status == "insufficient-information" for status, _ in outcomes):
                status = "insufficient-information"
            elif outcomes:
                status = "pass"
            else:
                status = "insufficient-information"
            reasons = [reason for status, reason in outcomes if reason]
            results.append({
                "rule_id": rule["id"],
                "function_id": fid,
                "result": status,
                "detail": "; ".join(reasons) if reasons else "all checked properties satisfied",
            })
    results.sort(key=lambda r: (r["rule_id"], r["function_id"]))
    return results

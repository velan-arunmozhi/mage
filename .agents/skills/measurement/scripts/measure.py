#!/usr/bin/env python3
"""Validate measurement inputs and recompute comparisons; never execute formulas."""

import argparse
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import sys

from jsonschema import Draft202012Validator, FormatChecker
from rfc3339_validator import validate_rfc3339


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "bundle.schema.json"
UNKNOWN = "unknown"
ENGINE_VERSION = "1"
FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("date-time")
def date_time(value):
    return not isinstance(value, str) or validate_rfc3339(value.upper())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def load(path):
    def reject_constant(value):
        raise ValueError("Non-finite JSON number: " + value)
    return json.loads(Path(path).read_text(), object_pairs_hook=reject_duplicates,
                      parse_constant=reject_constant)


def ensure_finite(value):
    if isinstance(value, dict):
        for item in value.values():
            ensure_finite(item)
    elif isinstance(value, list):
        for item in value:
            ensure_finite(item)
    elif type(value) in (int, float):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("Number outside supported finite arithmetic range")


def contains_unknown(value):
    if isinstance(value, dict):
        return any(contains_unknown(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_unknown(item) for item in value)
    return value == UNKNOWN


def same_number(left, right):
    if type(left) not in (int, float) or type(right) not in (int, float):
        return left == right
    if isinstance(left, int) and isinstance(right, int):
        return left == right
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12)


def index(records, label):
    result = {}
    for record in records:
        key = record["id"]
        if key in result:
            raise ValueError("Duplicate " + label + " ID: " + key)
        result[key] = record
    return result


def resolve(records, key, label):
    if key not in records:
        raise ValueError("Unresolved " + label + ": " + key)
    return records[key]


def calculate(definition, observation):
    quantity = definition["quantity"]
    aggregation = quantity["aggregation"]
    inputs = observation["inputs"]
    if aggregation == "ratio":
        if "numerator" not in inputs:
            raise ValueError("Ratio requires numerator and denominator: " + observation["id"])
        numerator, denominator = inputs["numerator"], inputs["denominator"]
        missing = sum(value == UNKNOWN for value in (numerator, denominator))
        value = UNKNOWN if missing or denominator == 0 else numerator / denominator
        reason = "zero_denominator" if denominator == 0 else "missing_inputs" if missing else None
        total = 2
    else:
        if "samples" not in inputs:
            raise ValueError("Sample aggregation requires samples: " + observation["id"])
        samples = inputs["samples"]
        total = len(samples)
        missing = samples.count(UNKNOWN)
        known = [sample for sample in samples if sample != UNKNOWN]
        if aggregation == "value" and len(samples) != 1:
            raise ValueError("Value aggregation requires exactly one sample")
        if aggregation not in ("count", "count_distinct") and any(
                type(sample) not in (int, float) for sample in known):
            raise ValueError("Numeric aggregation received a nonnumeric sample")
        reason = None
        no_samples = not samples and aggregation not in ("sum", "count", "count_distinct")
        propagate = missing and definition["missing_data"]["policy"] == "propagate_unknown"
        if no_samples or propagate or (missing and not known):
            value, reason = UNKNOWN, "missing_inputs"
        elif aggregation == "value":
            value = known[0]
        elif aggregation == "sum":
            value = sum(known)
        elif aggregation == "mean":
            value = sum(known) / len(known)
        elif aggregation == "count":
            value = len(known)
        else:
            value = len(set(known))
    if observation["evidence_state"] != "known" or not observation["evidence_refs"]:
        value, reason = UNKNOWN, "unavailable_evidence"
    if value != UNKNOWN:
        ensure_finite(value)
        if quantity["value_type"] == "integer" and int(value) != value:
            raise ValueError("Noninteger result for integer quantity: " + observation["id"])
        if value < quantity.get("minimum", -math.inf) or value > quantity.get("maximum", math.inf):
            raise ValueError("Result outside declared quantity range: " + observation["id"])
    if not same_number(value, observation["value"]):
        raise ValueError("Reported observation value does not match calculation: " + observation["id"])
    return {"value": value, "missing_count": missing, "input_count": total,
            "reason": reason, "uncertainty": observation["uncertainty"]}


def semantics(definition):
    """Descriptions and IDs may vary; quantitative meanings must agree exactly."""
    quantity = dict(definition["quantity"])
    quantity["filters"] = {key: sorted(value) for key, value in quantity["filters"].items()}
    return {"scope": definition["scope"], "quantity": quantity,
            "missing_data": definition["missing_data"]}


def compare(request, definitions, observations, references, calculated):
    observation = observations[request["observation_id"]]
    reference = references[request["reference_id"]]
    definition = definitions[observation["definition_id"]]
    reference_definition = definitions[reference["definition_id"]]
    current = calculated[observation["id"]]
    result = {
        "id": request["id"], "measurement_id": definition["id"],
        "observation_id": observation["id"], "reference_id": reference["id"],
        "run_id": observation["run_id"], "condition": observation["condition"],
        "unit": observation["unit"], "observed_value": current["value"],
        "reference_value": UNKNOWN, "delta": UNKNOWN, "relative_delta": UNKNOWN,
        "margin_to_bound": UNKNOWN, "status": UNKNOWN, "reasons": [],
        "uncertainty": current["uncertainty"],
        "missingness": {"observation": current["missing_count"], "reference": 0},
        "evidence_refs": sorted(set(observation["evidence_refs"] + reference["source_refs"]))
    }
    mismatches = []
    if any(contains_unknown(item[key]) for item in (definition, reference_definition)
           for key in ("scope", "quantity")):
        result["reasons"].append("unknown_quantity_semantics")
    if reference["source_authority"] == UNKNOWN:
        result["reasons"].append("unknown_reference_authority")
    if semantics(definition) != semantics(reference_definition):
        mismatches.append("quantity_definitions_differ")
    if reference["unit"] != observation["unit"]:
        mismatches.append("units_differ")
    if reference["kind"] == "matched_baseline":
        baseline = observations[reference["observation_id"]]
        baseline_definition = definitions[baseline["definition_id"]]
        previous = calculated[baseline["id"]]
        result["reference_value"] = previous["value"]
        result["reference_uncertainty"] = previous["uncertainty"]
        result["missingness"]["reference"] = previous["missing_count"]
        result["evidence_refs"] = sorted(set(result["evidence_refs"] + baseline["evidence_refs"]))
        if semantics(definition) != semantics(baseline_definition):
            mismatches.append("baseline_definition_differs")
        if baseline["unit"] != observation["unit"]:
            mismatches.append("baseline_unit_differs")
        if baseline["id"] == observation["id"] or baseline["run_id"] == observation["run_id"]:
            mismatches.append("baseline_is_same_run")
        if baseline["condition"] == observation["condition"]:
            mismatches.append("conditions_are_identical")
        for key, value in observation["context"].items():
            other = baseline["context"][key]
            if key == "tool_access" and isinstance(value, list) and isinstance(other, list):
                value, other = sorted(value), sorted(other)
            if contains_unknown(value) or contains_unknown(other):
                result["reasons"].append("unknown_context:" + key)
            elif value != other:
                mismatches.append("context_differs:" + key)
    else:
        result["reference_value"] = reference["value"]
    if mismatches:
        result["status"] = "not_comparable"
        result["reasons"].extend(mismatches)
        return result
    if current["value"] == UNKNOWN or contains_unknown(result["reference_value"]):
        result["reasons"].append("missing_or_unusable_value")
    if result["reasons"]:
        return result
    value, bound, tolerance = current["value"], result["reference_value"], reference["tolerance"]
    if reference["kind"] == "target_range":
        margin = min(value - bound["lower"], bound["upper"] - value)
        result["margin_to_bound"] = margin
        if tolerance != UNKNOWN:
            result["status"] = "within_range" if margin >= -tolerance else "outside_range"
    else:
        delta = value - bound
        result["delta"] = delta
        result["relative_delta"] = delta / abs(bound) if bound else UNKNOWN
        if reference["kind"] == "matched_baseline":
            if tolerance != UNKNOWN:
                result["status"] = "within_reference_tolerance" if abs(delta) <= tolerance else (
                    "lower_than_reference" if delta < 0 else "higher_than_reference")
        else:
            margin = -delta if reference["kind"] == "upper_bound" else delta
            result["margin_to_bound"] = margin
            if tolerance != UNKNOWN:
                result["status"] = "within_bound" if margin >= -tolerance else "outside_bound"
    if tolerance == UNKNOWN:
        result["reasons"].append("unknown_tolerance")
    ensure_finite(result)
    return result


def evaluate(bundle):
    ensure_finite(bundle)
    schema = load(SCHEMA)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
    errors = sorted(validator.iter_errors(bundle), key=lambda error: str(list(error.absolute_path)))
    if errors:
        raise ValueError("; ".join("/".join(map(str, error.absolute_path)) + ": " + error.message for error in errors))
    definitions = index(bundle["definitions"], "definition")
    observations = index(bundle["observations"], "observation")
    references = index(bundle["references"], "reference")
    index(bundle["comparisons"], "comparison")
    for definition in definitions.values():
        quantity = definition["quantity"]
        if quantity.get("minimum", -math.inf) > quantity.get("maximum", math.inf):
            raise ValueError("Quantity minimum exceeds maximum: " + definition["id"])
        if set(quantity["filters"]["include"]) & set(quantity["filters"]["exclude"]):
            raise ValueError("A filter cannot be both included and excluded")
    calculated = {}
    for observation in observations.values():
        definition = resolve(definitions, observation["definition_id"], "definition")
        if observation["unit"] != definition["quantity"]["unit"]:
            raise ValueError("Observation unit differs from its definition: " + observation["id"])
        if observation["context"]["repository"] != definition["scope"]["repository"]:
            raise ValueError("Observation repository differs from definition scope")
        calculated[observation["id"]] = calculate(definition, observation)
    for reference in references.values():
        definition = resolve(definitions, reference["definition_id"], "reference definition")
        if reference["unit"] != definition["quantity"]["unit"]:
            raise ValueError("Reference unit differs from its definition: " + reference["id"])
        if reference["kind"] == "matched_baseline":
            resolve(observations, reference["observation_id"], "baseline observation")
        elif reference["kind"] == "target_range":
            bounds = reference["value"]
            if bounds != UNKNOWN and (not isinstance(bounds, dict) or bounds["lower"] > bounds["upper"]):
                raise ValueError("Target range requires ordered lower and upper bounds")
        elif isinstance(reference["value"], dict):
            raise ValueError("Scalar bound requires a numeric value or unknown")
    for request in bundle["comparisons"]:
        resolve(observations, request["observation_id"], "comparison observation")
        resolve(references, request["reference_id"], "comparison reference")
    results = [compare(request, definitions, observations, references, calculated)
               for request in bundle["comparisons"]]
    incomplete = (not results or any(result["status"] in (UNKNOWN, "not_comparable") for result in results)
                  or any(result["value"] == UNKNOWN or result["missing_count"] > 0
                         for result in calculated.values()))
    return {
        "schema_version": 1, "model_class": "measurement", "synthetic": bundle["synthetic"],
        "status": "incomplete" if incomplete else "complete",
        "engine": {"version": ENGINE_VERSION, "python": sys.version.split()[0],
                   "jsonschema": version("jsonschema"),
                   "rfc3339_validator": version("rfc3339-validator"),
                   "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        "bundle_sha256": digest(bundle), "schema_sha256": digest(schema),
        "observations": calculated, "results": results,
        "limits": ["Supplied evidence references are not independently authenticated.",
                   "Samples must already be scoped, filtered, and expressed in canonical units.",
                   "No automatic unit conversion, statistical significance, or enforcement policy."]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--verify-report", type=Path, help="Recompute and verify a saved report")
    args = parser.parse_args()
    try:
        report = evaluate(load(args.bundle))
        if args.verify_report:
            previous = load(args.verify_report)
            if canonical(previous) != canonical(report):
                raise ValueError("Saved report differs from recomputed report (inputs, checker, or results changed)")
        print(json.dumps(report, indent=2, allow_nan=False))
        return 1 if report["status"] == "incomplete" else 0
    except (ValueError, OSError, OverflowError) as error:
        print(json.dumps({"status": "invalid", "error": str(error)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())

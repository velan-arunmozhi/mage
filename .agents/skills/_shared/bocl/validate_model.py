"""Evaluate scalar B-UML snapshots with separately authored B-OCL invariants.

The adapter validates a deliberately bounded OCL syntax and types before passing
fully parenthesized expressions to B-OCL. It never evaluates OCL itself.
"""

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import io
import json
import math
from pathlib import Path
import re
import sys


MODELS = {"structural", "behavioral", "ownership", "decision", "measurement", "provenance"}
TYPES = {"string": "str", "integer": "int", "real": "float", "boolean": "bool"}
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
SAFE_STRING = re.compile(r"[A-Za-z0-9_.:/@ -]*\Z")
TOKEN = re.compile(
    r"self\.[A-Za-z][A-Za-z0-9_]*\b|'[A-Za-z0-9_.:/@ -]*'|"
    r"\d+(?:\.\d+)?|<=|>=|<>|[=<>()+*\-]|"
    r"\b(?:and|or|not|implies|true|false)\b|\s+"
)
HEADER = re.compile(r"\s*context\s+([A-Za-z][A-Za-z0-9_]*)\s+inv\s+"
                    r"([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*?)\s*\Z", re.S)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(), object_pairs_hook=unique)


class Predicate:
    """Type-check and parenthesize the supported scalar OCL grammar."""

    def __init__(self, text, fields):
        self.fields = fields
        self.tokens = []
        position = 0
        while position < len(text):
            match = TOKEN.match(text, position)
            if match is None:
                raise ValueError(f"Unsupported OCL near {text[position:position + 30]!r}")
            if not match.group().isspace():
                self.tokens.append(match.group())
            position = match.end()
        self.position = 0
        expression, kind = self.expression()
        if self.position != len(self.tokens) or kind != "boolean":
            raise ValueError("The invariant must be one complete Boolean expression")
        self.normalized = expression

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self):
        token = self.peek()
        if token is None:
            raise ValueError("Incomplete OCL expression")
        self.position += 1
        return token

    def expression(self, minimum=0):
        precedence = {"implies": 1, "or": 2, "and": 3, "=": 4, "<>": 4,
                      "<": 4, ">": 4, "<=": 4, ">=": 4, "+": 5, "-": 5, "*": 6}
        left, left_type = self.atom()
        while self.peek() in precedence and precedence[self.peek()] >= minimum:
            op = self.take()
            right, right_type = self.expression(precedence[op] + (0 if op == "implies" else 1))
            numeric = left_type in {"integer", "real"} and right_type in {"integer", "real"}
            if op in {"and", "or", "implies"}:
                if left_type != "boolean" or right_type != "boolean":
                    raise ValueError(f"{op} needs Boolean operands")
                result_type = "boolean"
            elif op in {"+", "-", "*", "<", ">", "<=", ">="}:
                if not numeric:
                    raise ValueError(f"{op} needs numeric operands")
                result_type = ("real" if "real" in {left_type, right_type} else "integer")
                if op in {"<", ">", "<=", ">="}:
                    result_type = "boolean"
            else:
                if left_type != right_type and not numeric:
                    raise ValueError("Equality needs compatible operand types")
                result_type = "boolean"
            left, left_type = f"({left} {op} {right})", result_type
        return left, left_type

    def atom(self):
        token = self.take()
        if token == "(":
            result = self.expression()
            if self.take() != ")":
                raise ValueError("Unbalanced OCL parentheses")
            return result
        if token in {"not", "-"}:
            expression, kind = self.atom()
            if token == "not" and kind == "boolean":
                return f"(not {expression})", kind
            if token == "-" and kind in {"integer", "real"}:
                # The pinned visitor names unary minus 'unary_-', which the
                # B-UML name validator rejects. Preserve it as subtraction.
                return f"(0 - {expression})", kind
            raise ValueError(f"Invalid operand for {token}")
        if token.startswith("self."):
            field = token[5:]
            if field not in self.fields:
                raise ValueError(f"Unknown attribute: {field}")
            return token, self.fields[field]
        if token in {"true", "false"}:
            # BESSER 8.0.2's visitor retains lowercase Boolean literal text;
            # B-OCL 1.0.2 emits it into Python. Normalize these constants only.
            return "(1 = 1)" if token == "true" else "(1 = 0)", "boolean"
        if token.startswith("'"):
            return token, "string"
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            if not math.isfinite(float(token)):
                raise ValueError("Numeric literal must be finite")
            return token, "real" if "." in token else "integer"
        raise ValueError(f"Unexpected OCL token: {token}")


def validate_input(data, expected_model=None):
    if data.get("schema_version") != 1 or data.get("model_class") not in MODELS:
        raise ValueError("Expected schema_version 1 and a supported model_class")
    if expected_model and data["model_class"] != expected_model:
        raise ValueError(f"This skill requires model_class {expected_model}")
    for name in ("question", "repository", "basis"):
        if not isinstance(data.get(name), str) or not data[name].strip():
            raise ValueError(f"Supply a nonempty {name}")
    coverage = data.get("coverage", {})
    if coverage.get("status") not in {"complete-within-scope", "partial", "unknown"}:
        raise ValueError("Declare coverage.status")
    if not isinstance(coverage.get("scope"), str) or not coverage["scope"].strip():
        raise ValueError("Declare coverage.scope")
    if not isinstance(coverage.get("omissions"), list):
        raise ValueError("Declare coverage.omissions as a list")
    schema = data.get("schema")
    if not isinstance(schema, dict) or not schema:
        raise ValueError("Declare at least one B-UML class in schema")
    for context, fields in schema.items():
        if not IDENTIFIER.fullmatch(context) or not isinstance(fields, dict) or not fields:
            raise ValueError("Classes need identifier names and nonempty attribute maps")
        for field, kind in fields.items():
            if not IDENTIFIER.fullmatch(field) or kind not in TYPES:
                raise ValueError(f"Invalid schema attribute {context}.{field}")
    if not isinstance(data.get("objects"), list):
        raise ValueError("objects must be a list")
    seen = set()
    unknowns = []
    for obj in data["objects"]:
        if not isinstance(obj, dict) or not isinstance(obj.get("id"), str) or not obj["id"].strip():
            raise ValueError("Every object needs a stable id")
        if obj["id"] in seen:
            raise ValueError(f"Duplicate object id: {obj['id']}")
        seen.add(obj["id"])
        if obj.get("type") not in schema:
            raise ValueError(f"Unknown class for {obj['id']}")
        if not isinstance(obj.get("evidence"), list) or not obj["evidence"] or any(
            not isinstance(ref, str) or not ref.strip() for ref in obj["evidence"]
        ):
            raise ValueError(f"Supply evidence references for {obj['id']}")
        attributes = obj.get("attributes")
        fields = schema[obj["type"]]
        if not isinstance(attributes, dict) or set(attributes) != set(fields):
            raise ValueError(f"Attributes must match the schema exactly: {obj['id']}")
        for field, kind in fields.items():
            value = attributes[field]
            if value is None:
                unknowns.append({"id": obj["id"], "attribute": field})
                continue
            valid = {
                "string": lambda: isinstance(value, str) and SAFE_STRING.fullmatch(value),
                "integer": lambda: type(value) is int,
                "real": lambda: type(value) in {int, float} and math.isfinite(value),
                "boolean": lambda: type(value) is bool,
            }[kind]()
            if not valid:
                raise ValueError(f"Invalid {kind} value: {obj['id']}.{field}")
    return unknowns


class Engine:
    def __init__(self, schema):
        from bocl.OCLWrapper import OCLWrapper
        from besser.BUML.metamodel.object import AttributeLink, DataValue, Object, ObjectModel
        from besser.BUML.metamodel.structural import Class, Constraint, DomainModel, PrimitiveDataType, Property

        self.wrapper = OCLWrapper
        self.slot, self.value, self.object, self.object_model = AttributeLink, DataValue, Object, ObjectModel
        self.constraint = Constraint
        self.primitives = {key: PrimitiveDataType(name) for key, name in TYPES.items()}
        self.attributes = {name: {field: Property(name=field, type=self.primitives[kind])
                                  for field, kind in fields.items()} for name, fields in schema.items()}
        self.classes = {name: Class(name=name, attributes=set(fields.values()))
                        for name, fields in self.attributes.items()}
        self.domain = DomainModel(name="MageSnapshot", types=set(self.classes.values()))

    def rule(self, text, schema):
        match = HEADER.fullmatch(text)
        if match is None:
            raise ValueError("Use one named context Class inv RuleName: expression per rule file")
        context, name, body = match.groups()
        if context not in schema:
            raise ValueError(f"Unknown invariant context: {context}")
        normalized = Predicate(body, schema[context]).normalized
        constraint = self.constraint(name=name, context=self.classes[context],
                                     expression=f"context {context} inv {name}: {normalized}", language="OCL")
        return context, name, constraint

    def evaluate(self, context, attributes, constraint):
        slots = [self.slot(attribute=self.attributes[context][field], value=self.value(
            classifier=self.attributes[context][field].type, value=value)) for field, value in attributes.items()]
        obj = self.object(name="snapshot", classifier=self.classes[context], slots=slots)
        objects = self.object_model(name="Snapshot", objects={obj})
        objects.validate()
        result = self.wrapper(self.domain, objects).evaluate(constraint)
        if type(result) is not bool:
            raise ValueError("B-OCL did not return a Boolean verdict")
        return result


def check(model_path, rule_paths, authority, expected_model=None):
    if not isinstance(authority, str) or not authority.strip():
        raise ValueError("Cite the rule authority, or explicitly label it proposed/demo")
    if not rule_paths:
        raise ValueError("Supply at least one OCL rule")
    data = load_json(model_path)
    unknowns = validate_input(data, expected_model)
    engine = Engine(data["schema"])
    rules, results, empty = [], [], []
    names = set()
    for path in rule_paths:
        expression = path.read_text()
        context, name, constraint = engine.rule(expression, data["schema"])
        if (context, name) in names:
            raise ValueError(f"Duplicate invariant: {context}.{name}")
        names.add((context, name))
        # Compile and execute even when no complete observation exists.
        sample = {field: {"string": "sample", "integer": 1, "real": 1.0, "boolean": True}[kind]
                  for field, kind in data["schema"][context].items()}
        engine.evaluate(context, sample, constraint)
        rules.append({"id": name, "context": context, "path": str(path.resolve()),
                      "sha256": digest(path.read_bytes()), "authority": authority,
                      "expression": expression.strip(), "engine_expression": constraint.expression})
        complete = [obj for obj in data["objects"] if obj["type"] == context
                    and all(value is not None for value in obj["attributes"].values())]
        if not complete:
            empty.append(context + "." + name)
        for obj in complete:
            results.append({"id": obj["id"], "context": context, "rule_id": name,
                            "satisfied": engine.evaluate(context, obj["attributes"], constraint),
                            "attributes": obj["attributes"], "evidence": obj["evidence"]})
    covered_types = {rule["context"] for rule in rules}
    unchecked = [obj["id"] for obj in data["objects"] if obj["type"] not in covered_types]
    partial = data["coverage"]["status"] != "complete-within-scope" or bool(unknowns or empty or unchecked)
    violations = [result for result in results if not result["satisfied"]]
    return {
        "schema_version": 1, "model_class": data["model_class"],
        "status": "violations" if violations else "incomplete" if partial else "pass-within-scope",
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": data["repository"], "question": data["question"], "basis": data["basis"],
        "enforcement": "advisory",
        "engine_versions": {name: version(name) for name in ("besser", "bocl", "antlr4-python3-runtime")},
        "input": {"path": str(model_path.resolve()), "sha256": digest(model_path.read_bytes())},
        "rules": rules, "results": results, "violations": violations,
        "coverage": {**data["coverage"], "declared_status": data["coverage"]["status"],
                     "status": "partial" if partial else "complete-within-scope",
                     "basis": "Supplied records only; source correspondence and evidence references not verified",
                     "unknown_attributes": unknowns, "rules_without_observations": empty,
                     "unchecked_objects": unchecked},
    }


def main(expected_model=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--rule", type=Path, action="append", required=True)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    # Input paths, symlinks, and hard links cannot be report destinations.
    if args.output:
        inputs = [args.model, *args.rule, Path(__file__)]
        if any(args.output.resolve() == path.resolve() or (
            args.output.exists() and path.exists() and args.output.samefile(path)) for path in inputs
        ):
            print(json.dumps({"status": "error", "error": "Report output cannot overwrite inputs or the runner"}))
            return 2
    try:
        # Upstream diagnostics must not corrupt machine-readable stdout.
        with redirect_stdout(io.StringIO()):
            report = check(args.model, args.rule, args.authority, expected_model)
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

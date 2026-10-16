"""Fixture runner for the reusable structural skill's B-UML/OCL checker."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SKILL_SCRIPT = HERE.parents[1] / ".agents/skills/structural/scripts/validate_structure.py"
spec = importlib.util.spec_from_file_location("mage_structural_ocl", SKILL_SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
BoundaryModel = checker.BoundaryModel
RULE_ID = "NoDirectApiDatabaseImport"


def check(root, manifest=HERE / "components.json", rule_path=HERE / "boundary.ocl"):
    return checker.check(root, manifest, rule_path,
                         "Authored demo policy; not an inferred repository rule")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--components", type=Path, default=HERE / "components.json")
    parser.add_argument("--rule", type=Path, default=HERE / "boundary.ocl")
    args = parser.parse_args()
    try:
        report = check(args.root, args.components, args.rule)
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        return 2
    print(json.dumps(report, indent=2))
    return {"pass-within-scope": 0, "violations": 1, "incomplete": 2}[report["status"]]


if __name__ == "__main__":
    sys.exit(main())

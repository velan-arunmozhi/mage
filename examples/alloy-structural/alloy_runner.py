"""Thin, injectable wrapper around the Alloy 6 headless CLI.

``java -jar org.alloytools.alloy.dist.jar exec --command <name> -t json -o -
<file.als>`` prints nothing to stdout when the named ``check`` finds no
counterexample, and prints a JSON object with a non-empty ``instances`` array
when it does. The process exit code is 0 in both cases, so pass/fail must be
read from stdout content, not the return code -- this was confirmed by
running both outcomes against a scratch model before relying on it here.

The counterexample JSON's ``skolems`` map names the existentially-skolemized
witness for a universally-quantified assertion variable as
``$<AssertionName>_<varname>``, bound to the atom that falsifies the
assertion. For ``assert NoForbiddenObserved { all e: Edge | ... }`` a
violation's witness key is ``$NoForbiddenObserved_e``, bound to the specific
``Edge`` atom (e.g. ``E3$0``) that violates the policy -- Alloy names the
exact violating edge directly, no separate evidence search required.
"""
import json
import os
import subprocess
from pathlib import Path


class AlloyError(Exception):
    pass


ALLOY_JAR_ENV = "ALLOY_JAR"


def find_jar(explicit=None):
    """Resolve the Alloy jar path: explicit arg, then $ALLOY_JAR, then a jar
    sitting next to this file. Returns None if none exist."""
    for candidate in (
        explicit,
        os.environ.get(ALLOY_JAR_ENV),
        str(Path(__file__).resolve().parent / "alloy.jar"),
    ):
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


def default_run_command(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def run_check(als_path, command_name, jar_path, run_command=None):
    """Run one named Alloy ``check`` command.

    Returns ``(counterexample_found, parsed_json_or_None)``. ``run_command``
    is injectable -- ``callable(list[str]) -> object with .stdout,
    .stderr, .returncode`` -- so tests can supply a canned response instead
    of invoking Java.
    """
    if run_command is None:
        run_command = default_run_command
    args = [
        "java", "-jar", str(jar_path), "exec",
        "--command", command_name, "-t", "json", "-o", "-", str(als_path),
    ]
    result = run_command(args)
    if result.returncode != 0:
        raise AlloyError(
            f"alloy exec failed for {command_name} (exit {result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()}"
        )
    stdout = (result.stdout or "").strip()
    if not stdout:
        return False, None
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise AlloyError(f"could not parse alloy output for {command_name}: {error}")
    instances = parsed.get("instances", [])
    return (len(instances) > 0), parsed


def witness_atoms(parsed_json, assertion_name, variable_name):
    """Every skolem-bound atom name for ``assertion_name``'s quantified
    ``variable_name``, across all reported counterexample instances, with the
    Alloy ``$N`` tuple-instance suffix stripped (``E3$0`` -> ``E3``)."""
    if not parsed_json:
        return []
    key = f"${assertion_name}_{variable_name}"
    out = []
    for instance in parsed_json.get("instances", []):
        skolem = instance.get("skolems", {}).get(key)
        if not skolem:
            continue
        for row in skolem.get("data", []):
            for atom in row:
                out.append(atom.split("$")[0])
    return out

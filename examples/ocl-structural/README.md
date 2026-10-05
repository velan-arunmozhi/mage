# Structural model and OCL pilot

This runnable example asks one question: does an API module directly import a
database module? It extracts imports from Python source, builds BESSER structural
and object models, and evaluates an OCL invariant with B-OCL. A violation includes
component IDs, the importing file, the import statement, its line, and its source
hash. The existing MAGE skills and benchmark runner are not changed.

## Run it

From the repository root, using Python 3.10 or newer (tested with Python 3.13.2):

```bash
python3 -m venv examples/ocl-structural/.venv
examples/ocl-structural/.venv/bin/python -m pip install --no-deps -r examples/ocl-structural/core-requirements.txt
examples/ocl-structural/.venv/bin/python examples/ocl-structural/check.py examples/ocl-structural/fixtures/valid
examples/ocl-structural/.venv/bin/python examples/ocl-structural/check.py examples/ocl-structural/fixtures/invalid
examples/ocl-structural/.venv/bin/python -m unittest discover -s examples/ocl-structural -v
```

The valid example exits `0` with `pass-within-scope`. The invalid example exits
`1` with one violation at `api.py:1`. Exit `2` means an input/interpreter error or
incomplete coverage, not architectural conformance. Output is JSON, so an agent
can invoke the checker using its shell tool and read the result. Redirect stdout
to a file when you need a saved observation.

The pinned setup deliberately installs only the three core packages. B-OCL 1.0.2
uses a visitor API absent from BESSER 7.0.0, while its declared ANTLR dependency
(`==4.13.1`) conflicts with BESSER 8.0.2's (`>=4.13.2`). A normal dependency-resolved
installation can select an incompatible older BESSER. The three-package combination
here has been tested for this pilot; it bypasses upstream dependency metadata and
omits unrelated BESSER generators, database drivers, and web integrations.
It is not a fully dependency-satisfied installation of the entire BESSER platform.
Keep it in the isolated environment and run the tests before changing versions.

## What owns each fact

`components.json` declares component IDs, top-level Python module mappings, and
layers (`api`, `service`, or `database`). These declarations are authored; the extractor does not infer a component's
architectural responsibility from its filename.

`check.py` defines a small B-UML metamodel:

```text
Component(layer: str)
Dependency(source: Component[1], target: Component[1])
```

Every observed static import becomes a `Dependency` instance with links to its
source and target `Component` instances. B-UML is BESSER's modeling implementation;
this pilot does not require a UML editor or claim full OMG UML/OCL conformance.

`boundary.ocl` owns the rule, independently of the observed dependencies:

```ocl
context Dependency inv NoDirectApiDatabaseImport:
    self.source.layer = 'api' implies self.target.layer <> 'database'
```

This is an authored demonstration policy. It must be replaced or adopted by an
actual project authority before calling a real repository's dependency forbidden.
The rule checks direct imports only. API → service → database is allowed.

The valid fixture imports `service` from `api` and `database` from `service`.
The invalid fixture imports `database` directly from `api`. Each import is evaluated
separately so the verdict can be joined to its source evidence. Tests exercise all
nine layer pairs, mixed passing/failing edges, rule replacement, source changes,
incomplete extraction, malformed OCL, misspelled layers, and CLI exit codes.

## Use it on a first subsystem

1. Choose a small Python subsystem that can use this pilot's top-level-module mapping.
2. Write its component IDs, module names, filenames, and explicit layer declarations
   in a separate JSON file following `components.json`.
3. Confirm the intended rule with the project's existing architecture declaration.
4. Run the checker with the subsystem directory and `--components path/to/components.json`.
5. Inspect the returned evidence and coverage before giving the result to an agent.

Other MAGE models can reference the returned component IDs and source hashes.
They do not have to be converted to OCL. A later adapter can write these observations
to the structural skill's `.mage/structural/` index, slice, and manifest contract.

## Coverage and next step

The inspected scope is the declared top-level Python files. Every run re-reads those
files and computes hashes; saved output describes that run and is not automatically
fresh later. Undeclared imports (including external libraries) and additional Python
files are reported as incomplete. Missing files, broken Python, and OCL errors do not pass.

The model does not establish runtime calls, database reads/writes, dynamic imports,
package/re-export resolution, cross-service communication, or transitive conformance.
An import inside a conditional still counts as a static import. No imports means
the direct-import rule is vacuously satisfied within the declared scope.

The interpreter internally evaluates generated Python expressions. This example
uses a curated local rule and restricts layer strings; arbitrary agent-generated
rules need a separately isolated evaluation environment.
Its supported language subset also has limitations: the tested release raises an
evaluation error for a standalone OCL `true` literal. The pilot's rule uses tested
navigation, comparison, and implication constructs; an evaluation error is never a pass.

The next extension is a package-aware extractor for one real subsystem. Keep the
metamodel and rule fixed initially, then compare agent tasks with and without checker
feedback. This demo validates the toolchain; it is not evidence of agent improvement.

Sources: [B-OCL](https://github.com/BESSER-PEARL/B-OCL-Interpreter),
[BESSER](https://github.com/BESSER-PEARL/BESSER).

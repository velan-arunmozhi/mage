# Structural model and OCL pilot

This runnable example asks one question: does an API module directly import a
database module? It extracts imports from Python source, builds BESSER structural
and object models, and evaluates an OCL invariant with B-OCL. A violation includes
component IDs, the importing file, the import statement, its line, and its source
hash. Its checker now delegates to the reusable adapter bundled with the
[structural skill](../../.agents/skills/structural/SKILL.md); the benchmark runner is unchanged.

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

## Open the visual viewer

```bash
examples/ocl-structural/.venv/bin/python examples/ocl-structural/view.py --serve
```

Open http://127.0.0.1:8765 in a browser. Switch between the valid and invalid
fixtures, select a component or import arrow, and inspect its source evidence and
OCL result. The dashed violation arrow shows the API importing the database directly.
The graph is drawn from the same checker reports as the command-line output.
Reloading the page re-reads the fixture source and re-evaluates the rule.

To create a self-contained HTML snapshot instead, run `view.py` without `--serve`.
It writes `examples/ocl-structural/structure.html`, which can be opened directly
in a browser. A snapshot's reload button only reloads its saved data; regenerate
the snapshot to reflect code changes. No additional packages are needed.

## What owns each fact

`components.json` declares component IDs, top-level Python module mappings, and
layers (`api`, `service`, or `database`). These declarations are authored; the extractor does not infer a component's
architectural responsibility from its filename.

`check.py` invokes the structural skill’s reusable checker, which defines a small B-UML metamodel:

```text
Component(layer: str)
Dependency(kind: str, source: Component[1], target: Component[1])
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

## Use it through the structural skill

The skill now bundles the source-to-object adapter, configurable layer declarations,
project-authored rule inputs, JSON reports, package and relative-import resolution,
and instructions for saving observations alongside its Markdown models. Read its
[OCL workflow](../../.agents/skills/structural/references/ocl.md) for setup, input
contracts, coverage limits, and handoffs to the other MAGE models.

The fixture runner retains its simple defaults for demonstration. For a real
subsystem, invoke the skill checker directly and supply the project declarations,
rule, and authority explicitly. Other models can read its JSON reports and join
stable component IDs without changing their native representations.

## Coverage and next step

The inspected scope is the declared top-level Python files. Every run re-reads those
files and computes hashes; saved output describes that run and is not automatically
fresh later. Undeclared imports (including external libraries) and additional Python
files are reported as incomplete. Missing files, broken Python, and OCL errors do not pass.

The model does not establish runtime calls, database reads/writes, dynamic imports,
package/re-export resolution, cross-service communication, or transitive conformance.
An import inside a conditional still counts as a static import. No imports means
the direct-import rule is vacuously satisfied within the declared scope.

The interpreter internally evaluates generated Python expressions. The skill adapter
accepts a restricted edge-local subset and identifier-valued attributes. Keep rule
files curated; the adapter is not an execution sandbox for hostile input.
Its supported language subset also has limitations: the tested release raises an
evaluation error for a standalone OCL `true` literal. The pilot's rule uses tested
navigation, comparison, and implication constructs; an evaluation error is never a pass.

The skill adapter now supports packages and relative imports. Apply it to one real
subsystem with an independently established boundary, then compare agent tasks with
and without checker feedback. This demo validates the toolchain; it is not evidence
of agent improvement.

Sources: [B-OCL](https://github.com/BESSER-PEARL/B-OCL-Interpreter),
[BESSER](https://github.com/BESSER-PEARL/BESSER).

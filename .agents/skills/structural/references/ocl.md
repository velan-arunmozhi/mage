# Executable structural boundaries

Use the bundled checker when a structural question involves a declared boundary
between Python modules. It extracts actual imports, builds BESSER/B-UML objects,
and evaluates a separately authored OCL invariant through B-OCL. This is an advisory
validator; it does not install a gate or enforce a repository policy.

## Inputs and authority

Keep project inputs and reports in the target project's model location, normally
`.mage/structural/`. Resolve the skill directory from the installed `SKILL.md`,
following symlinks; it need not live inside the target repository.

Start declarations from [components.example.json](../assets/components.example.json).
The example describes fixtures, not the architecture of another repository.
Each component represents one Python module and has:

- `id`: the existing stable component ID, or a documented qualified ID.
- `module`: its qualified import name, such as `orders.api`.
- `path`: relative to the selected Python import root, such as `orders/api.py`
  or `orders/__init__.py` for a package named `orders`.
- `layer`: an authored value in the manifest's `layers` domain. The default domain
  is `api`, `service`, `database`; declare another domain when appropriate.

Map package `__init__.py` files as components when they are inside the selected root.
Every discovered, unmapped Python file makes coverage partial. Choose a bounded
source root without virtualenvs or generated artifacts. For dependencies outside
the question, `excluded_modules` accepts objects such as
`{"module": "json", "reason": "Standard library outside this boundary question"}`.
An exclusion covers that module and its children and cannot hide a mapped component.
Exclusions are visible in the report; they do not establish external conformance.

Put the project's boundary in a separate `.ocl` file. The bundled
[boundary.example.ocl](../assets/boundary.example.ocl) is a demo policy only. Cite
the actual project requirement using `--authority`, or explicitly label the rule
`proposed`/`demo`. Never treat a rule derived from the observed imports as an
independent correctness oracle. One invocation checks one named invariant.

## Run

Use Python 3.10 or later. Reuse a verified core environment where available;
otherwise create an isolated virtualenv in the target project's model location:

```bash
# Set this to the directory containing the installed structural SKILL.md.
structural_skill=/absolute/path/to/structural
python3 -m venv .mage/structural/.venv
.mage/structural/.venv/bin/python -m pip install --no-deps -r "$structural_skill/scripts/requirements.txt"
.mage/structural/.venv/bin/python "$structural_skill/scripts/validate_structure.py" src \
  --components .mage/structural/components.json \
  --rule .mage/structural/boundary.ocl \
  --authority 'docs/architecture.md#module-boundaries' \
  --output .mage/structural/reports/module-boundary.json
```

Replace `src` with the directory relative to which the declared import names resolve.
Inputs are read-only. JSON is printed to stdout; `--output` also saves it and creates
its parent directory. Save each rule's report separately so findings stay attributable.

Exit `0` is `pass-within-scope`; exit `1` reports violations; exit `2` means incomplete
coverage or an input/interpreter error. A violation may coexist with partial coverage:
read `coverage.status` separately. An error replaces a saved report with an error
record, so a previous passing result does not masquerade as the current run.

The pinned core setup is tested with BESSER 8.0.2, B-OCL 1.0.2, and ANTLR 4.13.1.
B-OCL requires ANTLR `==4.13.1`, while BESSER declares `>=4.13.2`; dependency resolution
can instead select BESSER 7.0.0, which lacks B-OCL's needed visitor API. `--no-deps`
bypasses that metadata conflict and omits unrelated BESSER platform dependencies.
This is a tested core combination, not a fully dependency-satisfied BESSER install.
Keep it isolated; rerun the checker tests before changing versions. In this repository:

```bash
examples/ocl-structural/.venv/bin/python -m unittest discover -s .agents/skills/structural/tests -v
```

## Conversion and supported OCL

```text
Python AST + component declarations
    -> observed IMPORTS edges with source anchors and hashes
    -> Component(layer) and Dependency(kind, source, target) B-UML objects
    -> object-model validation + OCL evaluation
    -> per-edge Boolean verdict joined to stable component IDs and evidence
```

`BoundaryModel.evaluate_edge()` creates a source component, target component, and
dependency object for each observed import. The source and target associations each
have multiplicity one. Stable IDs live in the JSON observations and findings; the
temporary object names are not new canonical component identities.

This adapter accepts an edge-local subset:

- `context Dependency inv RuleName: ...`
- `self.source.layer`, `self.target.layer`, `self.kind` (currently `IMPORTS`).
- Equality `=`, inequality `<>`, `and`, `or`, `not`, `implies`, and parentheses.
- Single-quoted identifier strings containing letters, digits, `_`, `.`, `:`, `-`.

Other syntax is rejected rather than evaluated over a misleading three-object graph.
Whole-graph constraints (`allInstances`, collections, cycles, transitive paths),
different contexts, multiple invariants, and OCL comments need another adapter.
This is not a full OMG UML/OCL implementation or a SysML parser. B-OCL internally
evaluates generated Python; keep rule files curated and local. The restricted input
subset reduces exposure but is not an execution sandbox for hostile rules.

Static extraction supports qualified imports, packages, relative imports, and
`from package import mapped_child`. Otherwise a `from` import targets the mapped
base module; it does not follow symbol aliases or re-exports. Unknown imports are
reported as unresolved unless explicitly excluded. Dynamic imports, runtime calls,
data access, external systems, and indirect dependencies remain outside coverage.
Do not invent these edges from import evidence. Conditional imports still count.
Zero observed imports means the edge rule is vacuously satisfied within coverage;
the synthetic parser check is not counted as an observed edge.

## Persist and hand off

Treat JSON as the machine-readable observation backing the existing Markdown slice,
not as an additional editable source of project policy:

1. Update the slice's entities and relationships from `components` and `results`.
   Preserve `claim_status`: component layers are declared; import edges are observed.
2. Link the rule, authority, and report in architectural intent and validation findings.
   Keep proposed rules labeled as proposed even when they evaluate to `False`.
3. In freshness metadata, record the report's UTC extraction time, discovery roots,
   Python inventory, component source hashes, declarations and rule hashes, extraction
   method, coverage, and omissions. Add repository identity, revision, and relevant
   dirty/untracked changes using the structural skill's normal freshness procedure.
4. Generate diagrams from the same report; update the index to link the slice,
   freshness entry, and saved report. Preserve unrelated and user-authored content.
5. Hand other skills stable IDs, the report path, rule ID, source evidence, coverage,
   findings, and freshness. They can read JSON directly and retain their native formats.

Reports describe one run; re-extract after relevant source, inventory, declaration,
or rule changes. Hash agreement does not prove semantic correctness, and a scoped
pass does not prove architecture-wide conformance or agent improvement.

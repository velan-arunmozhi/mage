# Shared B-UML / B-OCL snapshot contract

All six MAGE model skills use this runtime for scalar snapshots. Each skill owns
the meaning of its records and its source-to-snapshot correspondence. The
structural skill additionally retains its Python AST dependency extractor and
association-based boundary checker. Install `_shared/` alongside the six skill
directories; it is a runtime resource, not a seventh skill.

The pipeline is:

```text
inspected source / dated observations / authoritative declarations
  -> typed JSON snapshot + independently authored .ocl predicates
  -> B-UML Class, Property, Object, AttributeLink, DataValue, ObjectModel
  -> B-UML object validation + B-OCL OCLWrapper.evaluate(Constraint)
  -> object/rule verdicts, evidence references, versions, hashes, coverage
```

Use JSON as the portable serialization of the B-UML schema and object population.
OCL is the executable predicate language. Markdown explains the model, authority,
correspondence, findings, and remaining questions. Derive snapshots and reports
from existing authoritative sources where available; avoid two editable histories
or policy declarations. Diagrams and summary tables are projections.

## Installation

Use Python 3.10+ and an isolated environment. Resolve the selected installed skill
through symlinks, then locate its sibling `_shared/bocl/` directory.

```bash
runtime=/absolute/path/to/skills/_shared/bocl
python3 -m venv .mage/bocl-venv
.mage/bocl-venv/bin/python -m pip install --no-deps -r "$runtime/requirements.txt"
```

The tested core pins are BESSER 8.0.2, B-OCL 1.0.2, and ANTLR runtime 4.13.1.
B-OCL requires ANTLR 4.13.1 while BESSER declares >=4.13.2; normal dependency
resolution can select an older BESSER without the required OCL visitor. The
`--no-deps` core installation intentionally bypasses that metadata conflict and
omits unrelated BESSER platform dependencies. Keep this environment isolated and
run the suite tests when changing pins. This is not a fully dependency-satisfied
installation of the entire BESSER platform.

In this repository, reuse the verified structural pilot environment if present:

```bash
examples/ocl-structural/.venv/bin/python -m unittest discover \
  -s .agents/skills/_shared/bocl/tests -v
examples/ocl-structural/.venv/bin/python -m unittest discover \
  -s .agents/skills/structural/tests -v
```

## JSON model

Start from the selected skill's `assets/model.example.json`. Required fields:

- `schema_version`: `1`.
- `model_class`: the skill name: structural, behavioral, ownership, decision,
  measurement, or provenance. Each skill wrapper rejects another model class.
- `question`, `repository`, `basis`: nonempty strings naming the engineering
  question, repository identity, and source/observation basis. Include revision,
  timestamps, source hashes, discovery coverage, and method in linked evidence
  or extra metadata. These strings alone do not verify freshness.
- `coverage`: `status` (`complete-within-scope`, `partial`, or `unknown`), a
  nonempty `scope`, and an `omissions` list. Coverage is a declaration by the
  source adapter/caller; the runtime does not discover omitted code or cases.
- `schema`: maps class names to attribute/type maps. Types are `string`,
  `integer`, `real`, and `boolean`. Class and attribute names start with an ASCII
  letter and contain only letters, digits, and underscores.
- `objects`: records with a globally unique stable `id`, schema class `type`,
  `attributes` exactly matching that class, and a nonempty `evidence` list of
  nonempty reference strings. Extra record metadata can retain claim status,
  run, timestamp, authority, or source hashes. Evidence references are retained,
  not resolved or authenticated by the runtime.

Attribute types are strict: a Boolean is not an integer; real values must be
finite; strings contain ASCII letters, digits, spaces, `_ . : / @ -` or are
empty. This narrow alphabet reflects B-OCL's generated-Python evaluator. Keep
free text, Unicode, quotes, and arbitrary paths in metadata/evidence rather than
OCL-evaluated attributes. Use canonical safe IDs for those facts in predicates.
Duplicate JSON keys, IDs, unknown classes, and invalid types are errors.

Use JSON `null` for an unknown attribute. The entire affected row is excluded
from evaluation, the missing attribute is listed, and coverage becomes partial.
Missing schema keys are input errors. Never coerce missing observations to zero,
false, empty text, or a current owner. An explicit empty string is a known value
and can violate a record-presence invariant.

## Supported OCL

One named invariant per file:

```ocl
context Comparison inv DeltaConsistent:
  self.delta = self.observed - self.reference
```

Repeat `--rule` to evaluate more files. Duplicate context/rule names are errors.
All objects must belong to a context covered by at least one supplied rule for
complete coverage. Each rule evaluates independently for every fully known row
of its context, creating a single-object B-UML population for that evaluation.

Supported syntax:

- Scalar attributes `self.attribute`, safe single-quoted strings, decimal
  integers/reals, Boolean attributes and `true`/`false` literals.
- `=`, `<>`; numeric `<`, `<=`, `>`, `>=`; numeric `+`, `-`, `*` and unary minus.
- `and`, `or`, `not`, `implies`, and parentheses.

The adapter validates syntax and operand types, then parenthesizes expressions
before invoking B-OCL. `implies` associates to the right. Boolean constants are
normalized to `(1 = 1)` / `(1 = 0)` because the pinned visitor passes lowercase
Boolean literal text to an evaluator that emits Python. Both original and engine
expressions are retained. There is no Python replacement for evaluating OCL.
Unary minus is normalized to subtraction from zero because the pinned visitor's
`unary_-` operation name is rejected by B-UML's identifier validator.

Unsupported: collections, associations/navigation chains, `allInstances`,
quantifiers, temporal operators, `@pre`, postconditions, comments, null/invalid
logic, functions, division, and multi-invariant files. Unsupported expressions
are errors. This bounded adapter is not full OMG OCL or a temporal model checker.
For a richer model add a tested B-UML adapter or use an appropriate analysis tool;
do not flatten away facts required by the question to obtain a passing report.

## Results and limits

Exit codes: `0` = `pass-within-scope`, `1` = `violations`, `2` = `incomplete` or
`error`. Stdout is JSON; `--output` also saves that record and creates parent
directories. Errors replace a previous report with an error record so an old
pass is not presented as current. Outputs cannot overwrite model/rule inputs,
including symlink and hard-link aliases.

Read `coverage.status` even when status is `violations`; violations can coexist
with incomplete coverage. No known objects for a rule, unchecked object types,
unknown values, or declared partial/unknown coverage prevent a passing status.
Each rule gets a synthetic engine smoke check even without observations. It is
not evidence about the implementation and is excluded from result counts.

Reports retain model/rule hashes, authority, engine versions, generation time,
object IDs, checked values, references, omissions, and the individual verdicts.
An input hash proves which snapshot was checked, not that its upstream evidence
is true, complete, or current. Verify source hashes, discovery inventories, dirty
and untracked changes, source correspondence, and observation times before reuse.

The adapter is advisory. A satisfied invariant concerns only supplied records.
It cannot establish reachability, global exclusivity, case-space completeness,
liveness, experiment comparability, causal truth, or runtime enforcement unless
a separate inspected mechanism supplies the required evidence. Keep normative
authority separate from observed behavior and distinguish hypothetical fixtures
from realized history. Do not install gates or mutate live claims as a side
effect of modeling.

B-OCL uses generated Python internally. Use curated local models/rules; these
syntax and value restrictions are not a sandbox for hostile inputs.

Upstream references: [B-OCL](https://github.com/BESSER-PEARL/B-OCL-Interpreter)
and [BESSER](https://github.com/BESSER-PEARL/BESSER). Version-specific behavior
above is checked against the installed pinned source and executable tests.

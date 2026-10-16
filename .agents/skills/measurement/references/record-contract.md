# Measurement record contract v1

This contract makes the measurement model executable without imposing a common
representation on the other MAGE models. JSON Schema checks record structure;
Python checks identities, calculations, comparability, and reported margins.
Neither check authenticates observations or enforces a response policy.

## Files and authority

- `schemas/bundle.schema.json` is the authoritative Draft 2020-12 input shape.
- `scripts/measure.py` implements the supported numerical semantics. Only the
  listed aggregations execute; formulas from input strings are never evaluated.
- `examples/four-chains.json` is a complete synthetic fixture, not a measurement
  of this repository or evidence of MAGE improvement.
- `examples/budget.json` compares a synthetic duration of 12 seconds against an
  upper bound of 10 seconds. Its result is `outside_bound`, with delta `2` and
  raw margin `-2`. The calculation succeeds; enforcement remains a separate choice.

Keep real definitions, evidence, and reports in the target project's experiment
store or `.mage/measurement/<scope-id>/`. Existing YAML/Markdown records may stay
as human views, but must be explicitly adapted to this schema before this checker
can validate them. Do not claim that arbitrary legacy records have been checked.

## Bundle sections

The top level requires `schema_version: 1`, `model_class: "measurement"`, and an
explicit `synthetic` Boolean, followed by four arrays:

| Section | Meaning |
| --- | --- |
| `definitions` | Stable measurement ID, question, property, quality attribute, scope, authority, generation metadata, quantity semantics, and missing-data policy |
| `observations` | Run and condition IDs, run controls, dated inputs, reported value, canonical unit, evidence status/references, derivation version, and uncertainty |
| `references` | Independently sourced upper/lower bound, target interval, or link to a matched-baseline observation; tolerance is declared here |
| `comparisons` | Stable request ID linking an observation to a reference |

IDs must be unique within each section and links must resolve. An observation's
unit and repository must match its definition. References use their definition's
unit. Extra fields are rejected so misspelled constraints cannot silently disappear.

Definitions are declarations or derivations of meaning; observations are dated
data. Do not label a quantity definition itself as an observed run result. Shared
metadata from the other skills can be retained in their native handoff records;
this schema does not replace those contracts.

## Quantity meaning and inputs

Each definition includes a canonical unit token, numeric type, optional range,
direction, aggregation, named event window, include/exclude filters, and repository
and unit-of-analysis scope. Use a different definition when the meaning changes.
An event cannot appear in both filter lists. Filter lists name exact event classes
in this v1 contract; they do not execute arbitrary predicates.

| Aggregation | Observation `inputs` | Calculation |
| --- | --- | --- |
| `value` | `{"samples": [12]}` | One already normalized quantity |
| `sum` | `{"samples": [2, 3]}` | Sum of known numeric samples |
| `mean` | `{"samples": [2, 4]}` | Arithmetic mean of known numeric samples |
| `count` | `{"samples": ["a", "a", "b"]}` | Number of known samples, including repeats |
| `count_distinct` | `{"samples": ["a", "a", "b"]}` | Number of distinct known scalar values |
| `ratio` | `{"numerator": 9, "denominator": 10}` | Nonnegative numerator divided by nonnegative denominator |

Every ratio definition names the denominator's meaning, such as `attempted_tasks`.
An acceptance rate should declare range `[0, 1]`; a defect count per accepted task
can exceed one and should not inherit that range. These are distinct quantities.

Samples must already be normalized, scoped to the declared window, and filtered.
This checker does not extract telemetry or verify the collector's filtering logic.
Supply evidence references and inspect the collector when that interpretation
matters. It recomputes the reported observation `value` from those supplied inputs.
It cannot establish that a manually supplied count or sample is a true observation.

Units are exact canonical identifiers, including currency and denominator where
needed. There is no implicit conversion from milliseconds to seconds, tokens to
dollars, or differently defined denominators. Normalize with a documented,
versioned conversion upstream and preserve its evidence before comparing.

## Missingness and uncertainty

Use the literal string `"unknown"` for absent numbers, tolerances, controls, or
uncertainty. Do not use `null`, NaN, infinity, zero, or false. The `evidence_state`
is `known`, `missing`, `stale`, or `invalid`. Missing/stale/invalid evidence, or no
evidence references, requires the reported value to be unknown even if samples exist.

Definitions choose one missing-input policy:

- `propagate_unknown`: any unknown sample makes the result unknown.
- `exclude_and_report`: exclude unknown samples and retain the missing count.
  The report remains incomplete when inputs are missing. A ratio still requires
  both operands; the policy cannot repair a missing or zero denominator.

A known, evidenced empty sample list sums/counts to zero. An empty mean or a list
containing only unknown samples is unknown. `value` always requires one sample.
Missing observations must be marked unavailable; do not disguise them as a known
empty collection. Missing counts describe supplied inputs, not unobserved events
that a collector failed to record.

`uncertainty` is a nonnegative absolute value in the quantity's unit, or unknown.
It is retained for each side of a baseline comparison. The checker does not infer
confidence intervals, propagate uncertainty, or determine statistical significance.
Unknown uncertainty does not prevent arithmetic but prevents claims of certainty.

## Comparisons and margins

Matched baseline and treatment observations need compatible scope, quantity
definitions, missing-data policy, units, event windows, filters, and denominators.
Their repository, revision, task, harness, foundation model, tool access, resource
limits, and retry policy must match. Tool/filter ordering is immaterial. Conditions
and run IDs must differ. Equal unknown controls produce `unknown`, not a match.
Known mismatches produce `not_comparable`, while retaining both observed values.

Compatibility uses explicit definitions, not just quantity names. Definitions may
have different IDs or descriptive wording if their quantitative meanings match.
No unit conversion or judgment about semantically equivalent formulas is inferred.

For scalar references:

```text
delta = observed - reference
relative_delta = delta / abs(reference)     # unknown when reference is zero
upper_bound_margin = reference - observed
lower_bound_margin = observed - reference
```

For an interval `[lower, upper]`, raw margin is
`min(observed - lower, upper - observed)`. A positive margin is inside the
reference; a negative margin is outside its exact boundary. An absolute tolerance
in the same unit permits a margin down to `-tolerance`. Keep the raw margin even
when a tolerance makes the classification acceptable. Scalar bounds/intervals
apply to their declared definition scope; they are not matched experiments.

Unknown tolerances leave classification unknown while preserving calculable
deltas/margins. Baselines report lower/higher/within-tolerance descriptively;
they do not manufacture a bound margin or an overall success verdict. A lower
value is not automatically better: consult the declared direction and study outcomes.

Numeric recomputation tolerates floating-point rounding with relative tolerance
`1e-9` and absolute tolerance `1e-12` (integer-to-integer checks are exact). These
are arithmetic checking tolerances, not declared measurement tolerances. Version
the checker when changing them. Values outside finite supported arithmetic fail.

## Run and verify

Use a Python 3.9+ virtual environment; install the skill's `requirements.txt`.
For example, from the repository root:

```bash
python3 -m venv /tmp/mage-measurement-venv
/tmp/mage-measurement-venv/bin/python -m pip install -r .agents/skills/measurement/requirements.txt
/tmp/mage-measurement-venv/bin/python .agents/skills/measurement/scripts/measure.py .agents/skills/measurement/examples/four-chains.json > /tmp/mage-measurement-report.json
/tmp/mage-measurement-venv/bin/python .agents/skills/measurement/scripts/measure.py .agents/skills/measurement/examples/four-chains.json --verify-report /tmp/mage-measurement-report.json
/tmp/mage-measurement-venv/bin/python -m unittest discover -s .agents/skills/measurement/tests -v
```

The report retains input/schema/checker hashes, engine and library versions,
calculated observations and missingness, comparisons, evidence references, and
limitations. Verification recomputes the entire report; input, schema, engine,
library-version, or result changes require a fresh report. Hashes detect changes
relative to the supplied artifacts; they do not authenticate their origin.

| Exit | Meaning |
| --- | --- |
| `0` | Completed arithmetic and comparisons, including outside-bound results |
| `1` | Incomplete evidence, missing inputs, unknown classification, incompatible comparison, or no requested comparisons |
| `2` | Invalid schema, identity/reference error, inconsistent input arithmetic, invalid JSON, unreadable input, or altered saved report |

`complete` means the supplied checks completed. It does not establish complete
repository/task coverage, true evidence, statistical improvement, implementation
correctness, or runtime enforcement. Do not turn this diagnostic command into a
production admission policy without a separately authorized policy decision.

## Why this mix

Measurement's immediate checks concern record types, numeric relations, and
cross-record context. JSON Schema plus explicit calculation code handles those
without mirroring definitions into a second language. Add a SysML projection for
a concrete cross-model requirement, not as a second editable source of truth.
OCL, Alloy, and TLA+ are not required by this measurement workflow.

Basis: MAGE book §2.6 (quantities, references, tolerances, and margins), §2.8
(shared identities and correspondence), and the measurement skill's primary-outcome
priority. No experiment threshold or baseline is established by these fixtures.

Implementation references: [JSON Schema validation](https://json-schema.org/draft/2020-12/json-schema-validation)
and [python-jsonschema validation](https://python-jsonschema.readthedocs.io/en/stable/validate/).

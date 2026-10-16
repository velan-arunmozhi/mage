# Measurement with B-OCL

Use [scripts/validate_model.py](../scripts/validate_model.py) to instantiate the
project's typed B-UML snapshot and evaluate separately authored OCL invariants
with B-OCL. Read the [shared contract](../../_shared/bocl/reference.md) for the
JSON schema, installation, supported syntax, exit codes, and evidence limits.
The shared runtime must be installed alongside the six skills.

## Representation and limits

A Comparison row retains a quantity/run ID, observation and reference units, both values, delta, and margin. Its evidence must point to the quantity definition, aggregation/window/filter/scope metadata, raw observations, and independently declared reference. This example checks arithmetic for an upper bound, with margin = reference - observed; a negative margin remains valid measurement evidence and is not automatically a validation failure. Missing values are null, never zero. Define tolerance explicitly for inexact real arithmetic; checking unit labels does not establish compatible experimental conditions or perform unit conversion.

The bundled [model](../assets/model.example.json) and
[invariant](../assets/snapshot.example.ocl) are synthetic examples. They declare
no policy or finding about the target repository. Replace the schema, rows,
evidence, and rule with the facts and authority for the question. Preserve
canonical IDs and record source hashes/revisions and dated observations in the
linked evidence. The adapter hashes the snapshot and rules; it does not verify
those upstream sources.

## Run

Resolve `skill` to the real directory containing this installed `SKILL.md`,
following symlinks. Set `python` to an isolated interpreter prepared using the
shared contract. To exercise the bundled example:

```bash
skill=/absolute/path/to/measurement
python=/absolute/path/to/bocl-venv/bin/python
"$python" "$skill/scripts/validate_model.py" "$skill/assets/model.example.json" \
  --rule "$skill/assets/snapshot.example.ocl" --authority 'demo: bundled fixture'
```

For actual work, save the snapshot and rules under `.mage/measurement/` (or the
project's existing model store), then run:

```bash
"$python" "$skill/scripts/validate_model.py" .mage/measurement/model.json \
  --rule .mage/measurement/rules.ocl --authority 'project requirement or proposed rule' \
  --output .mage/measurement/reports/check.json
```

Repeat `--rule` for additional named invariants. Findings retain the object ID,
values, evidence references, rule authority, versions, and input hashes. Generate
the human-readable model and diagrams from those inputs/results, linking the
report rather than maintaining a second editable fact set. A report is an
advisory check of supplied records, not a production gate.

# Behavioral with B-OCL

Use [scripts/validate_model.py](../scripts/validate_model.py) to instantiate the
project's typed B-UML snapshot and evaluate separately authored OCL invariants
with B-OCL. Read the [shared contract](../../_shared/bocl/reference.md) for the
JSON schema, installation, supported syntax, exit codes, and evidence limits.
The shared runtime must be installed alongside the six skills.

## Representation and limits

A Step row carries the component ID, pre-state, post-state, trigger, and the evaluated guard at that step. Record whether the row is an observed execution or a modeled possibility in its evidence. The OCL file independently declares the allowed relation. Extract each required guard fact rather than guessing guard_satisfied; extend the schema for guard-specific predicates. This adapter checks step safety only: it does not discover reachable states, check adjacency between trace rows, or prove eventual completion.

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
skill=/absolute/path/to/behavioral
python=/absolute/path/to/bocl-venv/bin/python
"$python" "$skill/scripts/validate_model.py" "$skill/assets/model.example.json" \
  --rule "$skill/assets/snapshot.example.ocl" --authority 'demo: bundled fixture'
```

For actual work, save the snapshot and rules under `.mage/behavioral/` (or the
project's existing model store), then run:

```bash
"$python" "$skill/scripts/validate_model.py" .mage/behavioral/model.json \
  --rule .mage/behavioral/rules.ocl --authority 'project requirement or proposed rule' \
  --output .mage/behavioral/reports/check.json
```

Repeat `--rule` for additional named invariants. Findings retain the object ID,
values, evidence references, rule authority, versions, and input hashes. Generate
the human-readable model and diagrams from those inputs/results, linking the
report rather than maintaining a second editable fact set. A report is an
advisory check of supplied records, not a production gate.

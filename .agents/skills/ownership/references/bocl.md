# Ownership with B-OCL

Use [scripts/validate_model.py](../scripts/validate_model.py) to instantiate the
project's typed B-UML snapshot and evaluate separately authored OCL invariants
with B-OCL. Read the [shared contract](../../_shared/bocl/reference.md) for the
JSON schema, installation, supported syntax, exit codes, and evidence limits.
The shared runtime must be installed alongside the six skills.

## Representation and limits

A ClaimAction row is a dated action snapshot: actor, resource, presented claim, recorded current grant and holder, protocol clock values, and whether the protected effect occurred. The example assumes an exclusive timed lease and strict observed_at < expires_at, with both integers in the same clock/unit. It checks stale-action isolation, including reacquisition by the same holder. For untimed grants replace the time fields and invariant with the actual termination protocol. This is not evidence that a runtime comparison and mutation are atomic, nor a check of global exclusivity.

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
skill=/absolute/path/to/ownership
python=/absolute/path/to/bocl-venv/bin/python
"$python" "$skill/scripts/validate_model.py" "$skill/assets/model.example.json" \
  --rule "$skill/assets/snapshot.example.ocl" --authority 'demo: bundled fixture'
```

For actual work, save the snapshot and rules under `.mage/ownership/` (or the
project's existing model store), then run:

```bash
"$python" "$skill/scripts/validate_model.py" .mage/ownership/model.json \
  --rule .mage/ownership/rules.ocl --authority 'project requirement or proposed rule' \
  --output .mage/ownership/reports/check.json
```

Repeat `--rule` for additional named invariants. Findings retain the object ID,
values, evidence references, rule authority, versions, and input hashes. Generate
the human-readable model and diagrams from those inputs/results, linking the
report rather than maintaining a second editable fact set. A report is an
advisory check of supplied records, not a production gate.

---
name: provenance
description: >-
  Apply the MAGE Provenance Model to capture and query consequential realized
  history: what changed, what caused it, who or what performed it, what it
  affected, and what evidence supports the account. Use when designing agent
  runs, change attribution, audit trails, lineage, root-cause analysis, or
  provenance alignment.
---

# Provenance

Use this skill when the engineering question is backward-looking:

> What did the system actually do, and what evidence did it retain about what happened?

Provenance models realized execution or realized change. It is distinct from:

- **Structural modeling:** what exists.
- **Behavioral modeling:** what may happen.
- **Decision modeling:** what is permitted — [`../decision/SKILL.md`](../decision/SKILL.md).
- **Ownership:** who holds a valid claim now; a past acquisition is not current ownership —
  [`../ownership/SKILL.md`](../ownership/SKILL.md).
- **Logging and tracing:** what raw execution signals were observed.
- **Replay:** whether a realized change can be reproduced.

## Core rule

Retain consequential history, not every observed event. Choose a useful grain—usually
a consequential mutation, produced artifact, validation result, or committed change.
Do not turn provenance into a second distributed trace.

The useful chain is:

```text
cause/task → actor/run → operation → affected entity/artifact → result/evidence
```

Capture the causal relationship when the action occurs. Do not reconstruct “why” later
from a diff, logs, tickets, and guesses.

## Minimal provenance record

Store provenance records in Markdown files in the codebase, unless the project
explicitly chooses a different backing store. Keep the file version-controlled
and preserve these semantics:

```yaml
id: operation-01922
cause: task/SWE-204
actor: coding-agent/run-132
operation: modify_function
target: component.auth_service/refresh_token
mechanism: patch
timestamp: 2026-09-28T14:30:00Z
result: commit/a81f23
evidence:
  - test/test_refresh_expired_token: passed
  - test/test_refresh_valid_token: passed
```

Prefer one append-only provenance file for the project or subsystem, such as
`.mage/provenance.md`. Use headings and labeled fields for each record so the
history remains structured and queryable; do not replace it with an unstructured
changelog.

Stable identities matter more than a particular schema. Reuse the same entity
identity across structural, behavioral, decision, and provenance models when a
real engineering query benefits from joining them. Do not add joins merely because
they are possible.

## Attribution questions

A good provenance model should answer:

- What changed this artifact?
- Which operation produced the change?
- What task, incident, or requirement caused it?
- Which actor or run performed it, and by what mechanism?
- What other entities or artifacts were affected?
- What result and evidence support the account?

Prefer structured facts that can derive audit views, changelogs, debugging context,
lineage, and root-cause analysis. Record the consequential action once; do not
maintain separate hand-written histories that can drift.

## MAGE alignment

The provenance model states what a record means. Alignment makes the expectation
authoritative:

```text
MODEL: sanctioned consequential mutations have provenance records
ALIGN: every sanctioned mutation must emit one
CHECK: validator, lint, or gate verifies record presence and required attribution
```

Presence checks do not prove that an explanation is semantically true. Keep that
limitation explicit.

Use the engineering move **Make Cause Travel with Consequence**: attach the task or
reason to the agent operation, carry that identity into the commit and generated
artifacts, and preserve the evidence at each consequential boundary.

## Practical default for coding agents

Treat these as likely provenance units:

```text
task introduced
decision made
file/function/model modified
validator or test executed
result produced
commit/artifact created
```

Tool calls such as grep, file reads, retries, and model tokens are evidence sources,
not automatically provenance records. Promote them only when they explain a
consequential outcome.

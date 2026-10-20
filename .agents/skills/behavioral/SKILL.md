---
name: behavioral
description: >-
  Apply the MAGE Behavioral Model to what may happen to a component and in what
  order. Use for execution order, state lifecycles, finite-state machines, crash
  recovery, race conditions, and whether a state transition is legal or forbidden.
  Extracts states, permitted and forbidden transitions with code anchors, and
  checkable safety and liveness invariants, saving each slice under
  `.mage/behavioral/` with the freshness metadata a later question needs in order
  to decide whether the slice may be reused.
---

# Behavioral Model

Use this skill when the engineering question is about order:

> What states may this component occupy, and in what order may it move between them?

Behavioral modeling represents states and permitted transitions. It is distinct from:

- **Structural modeling:** what exists and how it connects —
  [`../structural/SKILL.md`](../structural/SKILL.md).
- **Decision modeling:** what is permitted; a transition being possible is not permission
  to take it — [`../decision/SKILL.md`](../decision/SKILL.md).
- **Ownership:** who holds a valid claim while a transition runs —
  [`../ownership/SKILL.md`](../ownership/SKILL.md).
- **Provenance:** which transitions actually executed —
  [`../provenance/SKILL.md`](../provenance/SKILL.md).
- **Tracing and profiling:** the raw execution signals a behavioral model is extracted from.

## Core rule

Preserve only the states and transitions needed to answer an ordering question. Exclude
component inventories, dependency edges, permission rules, and measured timings; those
belong to other models.

Keep two kinds of claim apart throughout. A transition the implementation can perform is
an observed fact about code. A transition the protocol sanctions is declared intent. The
two diverge often, and the divergence is usually the finding rather than a bookkeeping
error to reconcile away.

A missing edge forbids a transition only inside a transition relation declared complete.
Outside inspected coverage an absent transition is unknown, never prohibited.

## 1. Establish the question and scope

- Identify the repository root and follow its applicable agent instructions.
- Scope one component lifecycle per slice. Reuse the component IDs established by
  [structural](../structural/SKILL.md) so the two models join; record an alias when the
  behavioral scope is narrower than the structural component.
- Find the authoritative protocol, specification, or requirement before deciding what
  *should* hold. Source describes the implementation; it does not establish intended
  policy. It is useful to model a protocol that has defects, so extraction must not be
  read as validating the design.
- Model at one consistent grain: lifecycle phases, not every intermediate local variable.
  Descend to individual statements only where the ordering question requires it.

## 2. Check saved models before extracting

Saved slices live under `.mage/behavioral/`. Read `index.md` first, then only the relevant
component slice.

1. Verify repository identity, requested scope, and coverage against the slice's entry in
   `manifest.md`. File existence and timestamps do not establish freshness.
2. Where Git is available, compare the saved revision with HEAD and inspect staged,
   unstaged, deleted, renamed, and relevant untracked files. A matching commit does not
   establish freshness in a dirty working tree.
3. Compare saved content hashes for the inspected source files, and re-check the recorded
   discovery roots for new transition sites. A new handler or a new enum member introduces
   states that unchanged hashes on previously inspected files cannot reveal.
4. Reuse a verified, covered slice. Refresh affected states and transitions when stale,
   preserving authored intent and unrelated content.
5. When verification is unavailable, mark freshness unknown and inspect the relevant
   sources before answering. Never upgrade an existing file to a current fact.

Only when no covered slice exists, read the target component's lifecycle and state-handling
sources and extract one using the next section.

## 3. Extract states, transitions, and invariants

Ignore implementation noise — formatting, logging, helper utilities — and extract:

1. **Model card:** the engineering question, the component in scope, the represented
   property, the quality attribute at stake (crash-safety, lifecycle integrity,
   concurrency safety), and the detail deliberately omitted.
2. **States:** every valid phase with its code anchor as `path :: symbol`, for example
   `worker/job.py :: JobState` or `scripts/scholar-session :: server_pid`. Record whether
   each state is initial, terminal, or neither.
3. **Permitted transitions:** `From | To | Trigger | Guard | Code anchor | Claim status`.
   Claim status distinguishes a transition observed in the implementation from one
   declared legal by an authority.
4. **Forbidden or absent transitions:** state skips and backward jumps the protocol
   forbids, each with the authority that forbids it. Where no authority speaks, record the
   transition as unspecified rather than forbidden.
5. **Checkable invariants:** one to three safety properties ("this bad state is never
   reached") or liveness properties ("this terminal state is eventually reached"). State
   the fairness or scheduling assumption each liveness property depends on.

Record unresolved dynamic dispatch, reflection, generated state machines, and
externally-driven transitions explicitly. Do not invent an edge to close a diagram.

## 4. Save a small, navigable model

Write these files, adapting the names to an existing project convention while preserving
the equivalent fields. Do not create an empty slice.

- **`index.md`** — repository identity, model schema version (`1`), the model card, a table
  of modeled components with their stable IDs and slice links, coverage status, and a link
  to freshness metadata.
- **`<component-id>.md`** — one lifecycle per file, carrying the five extraction products
  above plus an unknowns-and-coverage section listing inspected paths and unresolved
  transitions, a validation-findings section, and a link to this slice's manifest entry.
- **`manifest.md`** — schema version, repository identity, extraction time in UTC, revision
  and dirty-worktree status where available, and per slice: scope, discovery roots,
  inspected source paths with content hashes, extraction method, verification time, and
  status (`complete-within-scope`, `partial`, `stale`, or `unknown`).

Without the manifest the freshness check in section 2 cannot run, so a slice saved without
one is `unknown`, not reusable. Mark an interrupted slice `partial` and record the exact
next source to inspect.

A small Mermaid `stateDiagram-v2` is worth adding where it clarifies a lifecycle. Generate
it from the same states and transitions and keep the tables authoritative; conventions live
in [`../self-communicate/drawing/diagrams.md`](../self-communicate/drawing/diagrams.md).

## 5. Validate before relying on the model

- Check that every transition endpoint is a declared state, that initial and terminal
  states exist, and that each code anchor still resolves.
- Reconcile the extracted transitions against their sources. An unreachable state or an
  unexpectedly sparse edge set is a possible coverage gap, not automatically a defect.
- Know what each analysis establishes. A per-step or per-snapshot check — an OCL invariant
  over one transition, or a guard assertion — establishes that an individual step is legal.
  It cannot establish trace continuity, reachability, or liveness, because it never
  composes steps. Those need state-space exploration or temporal reasoning with explicit
  scheduling assumptions.
- Separate the checks actually executed from the checks being suggested, and name every
  analysis left unrun along with its limit. A hypothetical trace is reasoning, not an
  observed execution; a successful recovery does not establish liveness.

## 6. Answer from the smallest verified slice

Lead with the requested answer, then name the states, transitions, code evidence, and
consequential unknowns behind it. State whether the model was created, reused, or
refreshed, and list the saved paths and the coverage left unfinished.

Hand other skills the stable IDs, slice paths, evidence, findings, and freshness status
described in
[`../mage-orchestrate/references/model-contract.md`](../mage-orchestrate/references/model-contract.md).
Do not claim reduced tokens, latency, or reconstruction cost without measurement; the
required fields live in [`../measurement/SKILL.md`](../measurement/SKILL.md).

## MAGE alignment

The behavioral model states which orderings are legal. Alignment gives one of them
authority:

```text
MODEL: the declared states and the transitions the protocol sanctions
ALIGN: an attempted transition must correspond to a sanctioned one
CHECK: a guard, state-machine library, or runtime assertion rejects an unsanctioned attempt
```

Describe a transition rule as enforced only where a mechanism actually rejects the
violation. This skill produces a model and findings; it does not enforce the lifecycle it
represents. Deciding which transition deserves a guard is an Alignment decision —
[`../self-governance/alignment/repertoire.md`](../self-governance/alignment/repertoire.md).

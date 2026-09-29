---
name: decision
description: >-
  Apply the MAGE Decision Model to declare what a system may do: the alternatives and
  the rules that permit, require, or forbid them. Use for permission and policy
  questions — who may act on what, which call or path edges are sanctioned, which
  option combinations are valid — and when replacing a decision duplicated across
  implementation sites with an explicit decision table, access-control matrix, policy
  graph, feature model, or constraint system.
---

# Decision Model

Use this skill when the engineering question is normative:

> What may this system do, which alternatives are admissible, and which are forbidden?

The models before this one were descriptive: they say what the system *is* or *does*. A
decision model says what the system *may* do. It is distinct from:

- **Structural modeling:** what exists, how it connects, and the permissions its declared
  architecture sanctions — [`../structural/SKILL.md`](../structural/SKILL.md).
- **Behavioral modeling:** which states and transitions can occur; a transition being
  possible is not a permission to take it —
  [`../behavioral/SKILL.md`](../behavioral/SKILL.md).
- **Provenance:** what actually happened — [`../provenance/SKILL.md`](../provenance/SKILL.md).
- **Measurement:** what quantity was observed against which declared bound —
  [`../measurement/SKILL.md`](../measurement/SKILL.md).
- **Alignment:** what turns a declared rule into a control —
  [`../self-governance/alignment/repertoire.md`](../self-governance/alignment/repertoire.md).

That single change in mood — from *does* to *may* — is the subject of this skill. A
structural edge and a decision edge draw identically and mean opposite kinds of thing:
`A → B` as a structural edge says "A calls B," a fact about what happens; the same
arrow as a decision edge says "A **may** call B," a rule about what is permitted.

**The absence carries the weight.** A missing structural edge means "no such call
happens." A missing decision edge means "no such call is allowed." That gap between
the two readings is the reason this model exists, and it is the test that keeps the
families apart: a structural slice may *cite* a sanctioned edge, but a permission the
code has to ask about is owned here.

The local repertoire carries declared architectural intent as one column of
*structure and boundaries*; this skill owns the case where the permission is the
engineering question itself — [`repertoire.md`](../self-governance/modeling/repertoire.md),
moves in [`moves.md`](../self-governance/modeling/moves.md).

## Core rule

Two obligations, and neither is optional.

1. **Enumerate; absence is a verdict.** Every alternative the system can present appears
   in the model with an explicit verdict — permitted, required, or prohibited. Derive the
   case space from the dimensions the verdict turns on — who acts, on what, doing what,
   under which conditions — and cover every combination the system can present. An
   unenumerated case is not undecided in effect: it is decided by whatever the
   implementation does. Declare what happens to a case the model does not cover, and
   justify any allow-by-default.
2. **Preserve every distinction the question requires.** List the facts the decision
   question depends on; the representation must carry each one through to the verdict.
   A reduction that drops a fact the code holds is a representation failure, not an
   information-availability failure, even when the conditional it feeds is locally
   correct.

## 1. Establish the question and scope

- State the question in the normative mood, naming the subject, the object, the action,
  and the conditions. "May this user submit this document, and under which authority?"
  is a decision question; "how is the user's authority computed?" is a structural one.
- Enumerate the decision sites: every place the decision is actually made — server,
  client, CLI, background job, cached preflight, migration, admin tool. A decision with
  no model is duplicated by definition, so this site list is the work list.
- Look for an existing authority before authoring one: a requirements or constraint
  provider, a policy document, a configuration file, a historical decision record. A
  repository is not automatically the model of intent; it tells you what implementation
  exists. See
  [`../self-governance/system/model-access.md`](../self-governance/system/model-access.md).
  When one exists, reuse and cite it rather than restating it — a second editable copy is
  a second source of disagreement.
- Where the policy is genuinely unsettled, do not invent it. Mark the model `proposed`
  and name the open decision. Permission recorded before it is settled becomes a gate
  over a guess.

## 2. Check saved models before extracting

This repository keeps each authored model definition beside its skill, under
`.agents/skills/<model>/SKILL.md`, and the models extracted from a specific repository
under `.mage/`. Save decision slices to `.mage/decision/`, alongside
`.mage/structural/` and `.mage/provenance.md`. Use a project's own location when it
already has one. Keep these skill instructions separate from the outputs they produce.

1. Read `index.md` first, then only the relevant decision files and their freshness
   metadata.
2. Reuse the identities the structural model already mints. A subject that is already a
   component in `.mage/structural/` is the same subject here; a decision that joins two
   components is only queryable when both sides carry the same ID.
3. Verify repository identity, requested scope, coverage, source anchors, and source
   changes. File existence and timestamps do not establish freshness.
4. Where Git is available, compare the saved revision with HEAD and inspect staged,
   unstaged, deleted, renamed, and relevant untracked files. A matching commit does not
   establish freshness in a dirty working tree. Compare saved content hashes for
   inspected sources. Without Git, use file inventories plus content hashes. When
   verification is unavailable, mark freshness unknown and verify the relevant sources
   before answering.
5. Reuse verified, covered slices; refresh affected alternatives when stale. Expand
   coverage only where the question requires it. Bootstrap missing slices without
   overwriting unrelated or user-authored material. Treat an unenumerated case as a
   coverage gap, never as permission.

## 3. Choose the form, then close the case space

Permission has several familiar shapes. What unifies them is not their form but their
mood, so pick the smallest form that answers the question and do not stop there.

| The policy is a function of… | Use |
| --- | --- |
| A small set of conditions mapped to actions | a decision table |
| Which subject may act on which object | an access-control matrix |
| Which call, path, or service edges are permitted | a policy graph |
| Which combinations of options are valid | a feature model |
| Which assignments are admissible | a constraint system |

Whichever form you pick, every alternative carries a verdict and the enumerated case
space is closed. An open-ended case space is not a decision model. A *constraint system*
here is a solver-level form, not the constraint rung of
[`../self-governance/alignment/repertoire.md`](../self-governance/alignment/repertoire.md).

Graph-shaped models get one rule of their own: an absent edge is a prohibition, so the
node set and the edge set are both part of the declaration. A completeness check can
then require every gated edge to be specified before anything is wired — and that check
governs the *declaration's* internal consistency, not the calls that follow from it.

## 4. Record each alternative with a verdict

Create these Markdown files using the contracts below. Adapt the names to an existing
project convention and preserve the equivalent fields. Do not create an empty decision
file.

### `index.md`

A compact entry point, at most about 150 lines:

- Repository identity and model schema version (`1`).
- Model card: engineering question, mood (`normative`), form, scope, represented
  property, quality attribute, deliberate omissions. Follow the card used in
  [`../measurement/SKILL.md`](../measurement/SKILL.md).
- Decision table: stable ID, question, form, model-file link.
- Cross-cutting summary: which decision questions are covered, which are deliberately
  not, and the one authority each verdict came from.
- Coverage status: inspected regions, exclusions, unresolved regions.
- Link to freshness metadata and the next work item.

### `decisions/<subject-id>.md`

One decision per file, keyed on the subject the decision is about so the ID joins with
the structural model's components rather than minting a parallel namespace:

1. **Model card:** question, mood (`normative`), form, scope, property, quality
   attribute, omitted detail.
2. **Alternatives:** `Case | Verdict | Condition | Authority | Source anchor`. The case
   column is the case space, not a sample of it.
3. **Forbidden and default:** the cases declared prohibited, the verdict applied to a
   case absent from the model, and the authority for both.
4. **Decision sites:** `Site | Role in the decision | Consumes the model? | Source
   anchor`. A site that does not consume the model is a correspondence gap; record it
   as one rather than as a defect in the site.
5. **Properties:** 1–3 checkable rules — safety ("a case the model does not cover
   resolves by the model's declared default, never by the implementation") and liveness
   ("an admitted case names the authority that permitted it").
6. **Validation findings:** check, inspected domain, result, evidence, limitations.
7. **Freshness:** link to this decision's entry in `manifest.md`.

A Mermaid diagram is worth adding where the form is a graph or a wide table. Generate
it from the same alternatives, keep the tables authoritative within the saved
projection, and follow the conventions in
[`../self-communicate/drawing/diagrams.md`](../self-communicate/drawing/diagrams.md).

### `manifest.md`

Record enough to resume work and to detect drift:

- Schema version, repository identity, extraction time in UTC, revision where
  available, and dirty-worktree status.
- Per decision: question, scope, discovery roots, relevant file inventory, inspected
  source paths with content hashes, extraction method, verification time, and status —
  `complete-within-scope`, `partial`, `stale`, or `unknown`.
- Every evidence-bearing source hash, including untracked sources. For a large
  inventory, link per-decision manifest files rather than loading the whole inventory
  into context.
- Completed work, remaining work, blockers, and the exact next region to inspect.

Save each completed decision and update its index and manifest before continuing. Mark
an interrupted decision `partial`. After a context reset, resume from the checkpoint; do
not repeat a repository-wide scan unless change evidence requires it. On a read-only
filesystem, or where the caller forbids writing, return the proposed model text and state
plainly that it was not persisted.

## 5. Validate before relying on the model

Once permission is declared, the claims a policy designer wants become checkable. Run
the checks the question warrants, and name the ones you did not.

- **Permitted or forbidden:** every enumerated case carries a verdict, and no case is
  silently absent.
- **Mutual exclusion:** no two alternatives are both fireable on the same case with
  contradictory verdicts.
- **Prerequisites:** a permitted alternative's required conditions are themselves
  satisfiable in the declared domain.
- **Internal consistency:** no contradiction, no unreachable rule, no case that decides
  nothing.
- **Completeness:** every case the system can present is covered; an uncovered case is
  reported, not passed by default.
- **Least privilege:** no alternative is permitted beyond what its case requires.
- **Correspondence:** each decision site reaches the model's verdict for the same case.
  This compares an observed fact with a declared rule; where they disagree, report the
  divergence rather than assuming which side is wrong.

**Correspondence is not correctness.** Agreement establishes that the implementation
matches the declared intent; it does not establish that the intent was the right rule.
A faithfully obeyed rule can still be the wrong rule, and no analysis of this model
decides that. Where a rendered status, a cached preflight, or a summary count is still
consulted as an authority for the decision, that is a finding regardless of what the
model says.

Separate the checks you executed from the checks you are suggesting. Report concrete
evidence and coverage for every result, and describe a rule as enforced only where a
mechanism actually rejects violations.

## 6. Answer from the model, and hand off the control

- Lead with the requested answer, then name the cases, the verdicts, the authority that
  declared them, and the consequential unknowns.
- State whether the model was created, reused, or refreshed. List the saved paths, the
  inspected scope, and the coverage left unfinished.
- Hand other skills stable IDs, model paths, evidence, findings, and freshness. Read
  [`../self-governance/SKILL.md`](../self-governance/SKILL.md),
  [`../self-operations/SKILL.md`](../self-operations/SKILL.md), and
  [`../self-communicate/SKILL.md`](../self-communicate/SKILL.md) before assuming their
  interfaces.
- Derive subjects, conditions, and verdicts from the target repository. Do not transfer
  a policy from another project, and do not import a plausible rule set because it is
  conventional.
- Do not claim token savings, lower latency, or benchmark improvement without measured
  evaluation; the measures and their required fields live in
  [`../measurement/SKILL.md`](../measurement/SKILL.md).
- Work one decision at a time. A model spanning every permission in the system is
  unreadable and unenforceable; save progress before expanding scope, and deliver a
  partial checkpoint rather than a claim of completion.

## MAGE alignment

The decision model states what is permitted. Alignment gives the declaration authority:

```text
MODEL: the declared alternatives and their verdicts, closed over the case space
ALIGN: an observed decision site must reach the model's verdict for the same case
CHECK: a validator or gate rejects a case the model prohibits
```

This skill produces a model and findings; it does not itself enforce the policy it
represents. Deciding which declared rule deserves a control is an Alignment decision —
[`../self-governance/alignment/repertoire.md`](../self-governance/alignment/repertoire.md).

A decision model is not a runtime firewall. Its internal checks hold the declaration,
not the system; whether real calls stay on the declared edges is the correspondence this
skill hands to Alignment.

## Source notes

- §2.4 of *Model-Based Agentic Software Engineering*; the access-control matrix traces to
  Butler W. Lampson, "Protection," *ACM SIGOPS Operating Systems Review* 8, no. 1 (1974):
  18–24, https://doi.org/10.1145/775265.775268.

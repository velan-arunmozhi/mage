---
name: mage-orchestrate
description: >-
  Coordinate the six MAGE model skills around an engineering question: structural,
  behavioral, ownership, decision, measurement, and provenance. Use when a task spans
  several model classes, when bootstrapping or refreshing connected repository knowledge,
  when reconciling models with implementation, or when carrying an investigation through
  modeling, evidence, and an Alignment proposal. Route a question that needs only one
  model directly to that skill.
---

# MAGE Orchestration

Coordinate purposeful models of one system. Begin with the engineering question, select
the views that make it answerable, and join them through stable identities and evidence.
Load another view only when the question requires a fact it owns.

The fundamental model is a **task-directed traversal through six peer models**. There is
no fixed order among them. A lease question can begin with ownership; an incident can
begin with provenance; an architectural change can begin with structure. The connected
slice supports the MAGE loop:

```text
need -> select and connect models -> analyze / explore / implement
                  ^                            |
                  |                            v
       preserve a justified lesson <- evaluate evidence
```

**Modeling** makes knowledge and intent explicit. **Alignment** gives selected obligations
consequence through mechanisms in the engineering environment. Governance conversion
feeds useful lessons back into those activities. This skill supplies coordination and
judgment; it does not enforce a policy by being loaded.

## 1. Frame the work

Establish the target repository, the question or requested change, the relevant entities,
and the evidence needed to answer it. Respect the user's scope and applicable repository
instructions. Separate known obligations from hypotheses that still need exploration.

Assess reasoning burden and assurance need independently. A small permission change can
need strong evidence; a large disposable prototype can tolerate uncertainty. Choose a
bounded unit whose result can be evaluated before the next step depends on it.

For a simple question, route directly to one model skill. For a connected task, keep a
short working plan: sub-question, owning skill, required input, expected output, and
dependency. Skill invocation usually means reading and applying its instructions in the
current agent. This skill does not require or authorize spawning agents.

## 2. Discover before reconstructing

Resolve this skill's real filesystem directory first, following installation symlinks.
The links below address sibling skills in that suite. If a link is unavailable, use the
active skill catalog or the target project's installation; name a missing capability
instead of inventing its interface. Read only selected model entrypoints and relevant
resources. References to other skill families are not prerequisites for this workflow.

Look for existing model indexes, authoritative declarations, schemas, relevant evidence,
and actual query tools. Use the project's model location, otherwise `.mage/`. A conceptual
provider contract is not an installed API: query real tools when available, or inspect
the relevant model files and source slice.

Before relying on a saved slice, establish repository identity, scope, coverage, source
anchors, revision, and relevant working-tree changes. Verify source hashes and discovery
roots where available; include new, removed, renamed, staged, unstaged, and untracked
sources that can affect the slice. An unchanged commit or an existing file is insufficient.
Without adequate metadata, mark freshness unknown and inspect the relevant sources.
Refresh affected facts, preserving authored intent and unrelated content.

Use the [model contract](references/model-contract.md) for handoffs, freshness, and the
behavioral and measurement adapters. Those adapters are required when using the current
suite's behavioral or measurement files.

## 3. Select the models by question

| Question to answer | Skill | Contribution to the connected task |
| --- | --- | --- |
| What exists, connects, or depends on this? | [structural](../structural/SKILL.md) | Entities, typed relations, boundaries, and impact paths |
| What may happen, and in what order? | [behavioral](../behavioral/SKILL.md) | States, guarded transitions, executions, safety, and liveness |
| Who holds a valid claim, and for how long? | [ownership](../ownership/SKILL.md) | Holder, resource, claim identity, validity, transfer, and reclamation |
| What is permitted, required, or forbidden? | [decision](../decision/SKILL.md) | Admissible cases, verdicts, conditions, and their authority |
| How much, compared with which reference? | [measurement](../measurement/SKILL.md) | Quantity, unit, scope, aggregation, bound or baseline, and margin |
| What actually happened, caused it, and supports the account? | [provenance](../provenance/SKILL.md) | Consequential history joining cause, actor, operation, target, and evidence |

The skills own their extraction procedures and model contents. This coordinator owns
selection, dependencies, handoffs, reconciliation, and the answer across views. Do not
reproduce the extraction manuals here or invoke every skill as a checklist.

Use existing canonical IDs wherever possible. If none exist, establish the minimum
qualified identities needed for the task; a structural bootstrap is not mandatory.
Read [coordination patterns](references/coordination-patterns.md) when a task needs an
investigation, bootstrap, change, or recovery sequence.

## 4. Compose the smallest useful slice

Pass the question, canonical IDs, model/source references, claim status, freshness,
coverage, findings, and unknowns at each handoff. Reference or derive facts owned by
another model. Keep a lifecycle in its behavioral view and link an ownership overlay to
it, rather than maintaining two editable transition tables. One representation may serve
several questions without requiring duplicate files.

Follow dependencies between results, rather than a universal skill order. Revisit a view
when new evidence changes the question or its assumptions. Stop traversing when the
requested answer has adequate support or a consequential gap is identified.

Preserve these distinctions across joins:

- An observed call is different from permission to make that call.
- A possible transition is different from an observed execution of it.
- Role permission is different from a valid current ownership claim.
- Capacity limits count work; they do not identify the worker allowed to mutate it.
- A past acquisition event does not establish current ownership.
- A quantity comparison supplies evidence; response policy supplies consequence.
- An absent fact outside inspected coverage is unknown. Absence means prohibition only
  in a declared closed policy or transition domain that gives it that meaning.

Join temporal evidence only when its repository, version, run, and time scopes are
compatible. A current source model and an old incident record can explain evolution;
their combination does not establish that the old incident describes current behavior.

When models disagree, record the specific claims, sources, scope, and freshness. Determine
whether the representation is wrong, its grain is wrong, the implementation is wrong, or
the evidence describes different versions. Do not edit one side merely to manufacture
agreement. Continue unaffected work and surface unresolved authority decisions with the
evidence needed to settle them.

## 5. Evaluate and decide what deserves authority

Keep three claims separate: **correspondence** between representations, **conformance**
to an independently established obligation, and **acceptance** by the receiving
environment. A model faithfully derived from defective code establishes description,
not correctness. Resolving source anchors establishes navigation, not semantic truth.

Choose evidence that can challenge the claim: source reconciliation for dependencies,
case-space analysis for policy, bounded state exploration for reachable bad states,
temporal reasoning for eventual progress, or compatible observations for a numeric
comparison. State assumptions, checked domain, and omitted behavior. A hypothetical
trace is reasoning; it is not an observed incident or an exhaustive check. A successful
recovery does not establish liveness. Report only checks actually performed; honor the
task's limits on testing and side effects.

For a stable obligation that warrants an Alignment proposal, identify:

1. The independent requirement and the domain or tolerance it governs.
2. The evidence needed and the earliest boundary where the obligation is decidable.
3. The role needed: constraint, sensor, validator, gate, or a combination.
4. Existing mechanisms, bypasses, interactions, and the authority to change them.
5. Verification at a later consequential boundary if intervening changes can stale the evidence.

Prefer prevention when the legitimate action space can honestly be closed. Otherwise
produce evidence and evaluate it at an appropriate boundary. A validator judges; a gate
controls admission. A model, written rule, or proposed check is not an enforced control.
Describe enforcement only for an inspected mechanism that actually binds the consequence.

In an inherited system, reconcile and audit first, drain relevant legacy violations, then
promote a justified obligation to blocking authority. The discovery detector may remain
advisory while a narrower mechanism enforces the actual rule. Modeling does not authorize
installing hooks, changing permissions, deploying, or performing live claim changes.
Carry out separately authorized implementation within its existing scope.

## 6. Preserve useful work and return the answer

Keep system-specific outputs outside the skill. Respect each selected skill's storage
contract and the project's conventions. For repeated connected work, a `.mage/index.md`
may link useful slices and canonical entry entities; it should contain navigation rather
than copied model facts. Keep a task checkpoint only when work spans sessions or needs
resumption: completed outputs, evidence version, unresolved joins, and exact next step.

Record consequential changes and meaningful results once through provenance, carrying
their cause as they occur. Preserve rejected hypotheses and conflicts when they explain
the outcome. Ordinary searches and file reads need not become permanent history.

When a failure or repeated judgment exposes a durable gap, diagnose the missing element:
representation, obligation, evidence, evaluation, consequence, or reusable procedure.
Preserve the smallest useful lesson when future value exceeds upkeep. A catastrophic
known failure can warrant prevention before recurrence; a cheap one-off may need only its
point fix. If progress stalls, distinguish a searcher problem, a missing model, a weak
oracle, and an unsettled target before adding machinery. Reconcile or retire assets whose
assumptions or benefits no longer hold.

Lead the response with the requested answer or completed change. Include the model slices
created, reused, or refreshed; evidence and actual check results; consequential unknowns;
enforcement status where relevant; and saved paths or the next blocked decision. Claims
about reduced tokens, latency, reconstruction, or human effort require measurement.

## Basis

Derived from James C. Davis, *The MAGE Method: Model-Based Agentic Software Engineering*,
edition modified 2026-09-02, especially §§2.1–2.8, §§3.1–3.5, §§4.1–4.5, Appendix C,
Appendix E, and Appendix F. The [coordination reference](references/coordination-patterns.md)
maps these design choices to book pages. The installed skill works without the PDF.

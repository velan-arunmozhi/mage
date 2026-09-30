---
name: ownership
description: >-
  Apply the MAGE Ownership Model to who holds a valid claim on a resource and for
  how long. Use for competing workers, stale actions, acquisition, release,
  transfer, expiry, reclamation, and crash/retry races. Distinguish current
  ownership from role permission, component responsibility, and capacity limits.
---

# Ownership Model

Use this skill when the engineering question is:

> Who controls this resource now, on what terms, and for how long?

Ownership relates a holder to a resource through a claim. The claim's identity or
generation distinguishes successive grants; its lifetime determines applicability.
A worker can retain an old token after its grant expires or another grant replaces it.
Represent that distinction rather than equating the worker's identity with its authority.

## Core rule

Preserve enough information to distinguish a current claim from an expired or
superseded one, and inspect the actions each claim may affect. A single stored owner
does not establish that stale workers cannot mutate the resource.

The representation follows the target protocol. Leases, locks, and allocations need
not share a schema, clock, or expiry mechanism. Do not prescribe a TTL, generation
encoding, or storage primitive merely because an example uses one. For a grant without
timed expiry, establish how it ends and how obsolete actions are distinguished.

## 1. Establish the question, authority, and current evidence

- Scope the resource, holders, protected actions, and relevant lifecycle. Reuse the
  component and resource IDs from [Structural](../structural/SKILL.md).
- Find the authoritative protocol or requirements before deciding what should hold.
  Source describes implementation; it does not automatically establish intended policy.
  Separate authored intent, derived implementation, observations, and inference.
- Read relevant saved models before extracting again. Verify scope, coverage, source
  anchors, and source hashes, including relevant staged, unstaged, deleted, renamed,
  and untracked changes. File existence or an unchanged commit does not establish
  freshness. Refresh affected facts and preserve unrelated or authored content.
- Use available model providers or inspect the smallest relevant source/configuration
  slice. Do not assume an adapter exists because another skill describes its interface.
  Keep source, authority, freshness, evidence, and conflicts explicit.
- A source model explains how ownership works. Current ownership requires an
  observation with its own time and scope; a source hash cannot make a holder snapshot
  current. Missing observations mean unknown, not unowned.

## 2. Represent claims and their changes

Identify the holder, resource, presented claim, recorded current grant, and validity
conditions. Distinguish expired from superseded claims and physical record presence
from valid ownership. Expiry need not erase a stored record or stop its worker.

For each operation the actual protocol supports, record the initiating actor,
presented claim, prior-state guard, next state, and rejected-action outcome:

- **Acquire:** establish a grant under the protocol's conditions. Include competing
  attempts when exclusivity matters.
- **Release:** end the applicable grant without clearing a replacement grant.
- **Transfer:** change holders through the declared protocol, authorized from the
  current claim. Determine whether the generation changes and whether intermediate
  states are observable; do not assume an atomic handoff.
- **Expire:** change validity or reclaim eligibility according to the declared
  lifetime. For time-based claims, establish the time source, expiry comparison,
  and renewal behavior where present.
- **Reclaim:** recover abandoned work under its own authority and guard. Preserve
  the old token in the model so a returning worker can still attempt an action.

An unsupported operation stays outside the model. Link surrounding lifecycle states
and transitions to [Behavioral](../behavioral/SKILL.md), rather than maintaining a
second editable lifecycle. Include pending sub-operations when implementation steps
can interleave; a comparison followed by a separate write is not one atomic transition.

Keep definitions separate from properties. If "leased" is defined by claim presence,
that equivalence is a definition. If status and owner are stored independently,
their agreement becomes a consistency property to check.

## 3. State the properties that matter

For each property, name its authority, domain, assumptions, and precise condition.
The canonical exclusive-ownership model asks whether:

- **Exclusive ownership — safety:** at most one claim is valid for the resource at a
  time. Establish the actual cardinality rule before applying exclusivity elsewhere.
- **Stale-action isolation — safety:** an action presenting a superseded claim cannot
  alter the current grant or protected state. Inspect action effects, not only owner
  counts; a stale release can leave zero owners and still violate the protocol.
- **Authorized change — safety:** release and transfer operate through the applicable
  current claim. Reclamation has a distinct recovery guard; it need not be initiated
  by the missing holder.
- **Eventual reclamation — liveness:** abandoned work is eventually reclaimed under
  stated assumptions about time, recovery scheduling, and availability. Becoming
  eligible for reclaim is weaker than actually being reclaimed.

Apply lifecycle-specific properties only when the protocol calls for them, such as
not reclaiming completed work or respecting a declared acquisition order. Do not import
an example's terminal states or fairness policy into an unrelated system.

### A claim identity example

`A@7 → expire/reclaim → A@8 → release(A@7)` must leave `A@8` intact.
Comparing the holder name alone accepts the stale release even though both grants
belong to A. Replacing A with B must also preserve B's newer grant. The important
distinction is the grant, not just the actor. These are hypothetical traces until
observed or executed, not records of incidents.

## 4. Analyze the model and check the implementation

Choose evidence appropriate to the property. State initial conditions, actions,
atomicity assumptions, bounds, and omitted behavior. Examine competing acquisition,
expiry/release, reclaim/returning-worker, transfer, and retry interleavings where
they apply, including reacquisition by the same holder.

Use available tests or analysis tools for mechanical checks. Report what actually
ran, the model/source version, checked domain, assumptions, results, and any
counterexample. A reasoned trace is useful but is not exhaustive verification.
An exhaustive finite-state result covers only that bounded model. Neither a successful
reclaim trace nor a safety search establishes eventual progress; a liveness claim
needs temporal reasoning with explicit scheduling and environmental assumptions.

Keep three questions separate:

1. Does the model satisfy the stated property within the analyzed domain?
2. Do the inspected implementation paths correspond to the modeled transitions?
3. What mechanism actually rejects invalid actions or controls admission?

For stale-action protection, locate the claim comparison, protected mutation,
atomicity or serialization boundary, and relevant bypass paths. A guarded model
transition does not prove that the runtime comparison and update are atomic.
Correspondence can faithfully describe defective code; it does not establish that
the intended protocol is correct.

A lease can enable recovery without authorizing repetition of a consequential effect.
Inspect any separate publication, payment, or completion admission condition. A model,
validator, or recommended gate does not itself enforce production ownership. Hand
mechanism selection to [Alignment](../self-governance/alignment/repertoire.md), naming
the obligation, authority, evidence, and enforcement gap. Do not install controls or
perform a live claim change as a side effect of modeling.

## 5. Save the useful slice and hand off findings

Use the project's model location; otherwise save a scoped Markdown model to
`.mage/ownership/<scope-id>.md`. Keep system-specific outputs outside this skill.
An index is useful when several slices need navigation, not a prerequisite for one.

Retain the engineering question, scope and omissions, canonical identities, claim
semantics, applicable operations, properties and assumptions, source/observation
evidence and freshness, analysis limits, actual enforcement status, and unknowns.
Preserve unresolved authority conflicts. Mark partial coverage and the next unresolved
question. State whether the slice was created, reused, or refreshed; on a read-only
task return its contents without claiming it was saved.

Return the answer with its evidence and consequential unknowns. Use the other models
for the facts they own:

- [Decision](../decision/SKILL.md) owns normative permission. A role may permit an
  action while its presented claim is stale; permission and current ownership may
  both be required at the protected mutation.
- [Provenance](../provenance/SKILL.md) owns realized consequential history. Link
  changes and meaningful check results with their cause, actor/run, target, and
  evidence. An old acquisition event is not proof of a current grant.
- [Measurement](../measurement/SKILL.md) owns quantities, units, references, and
  comparisons. Supply dated claim observations or scoped check evidence; a capacity
  ceiling does not identify which worker may mutate a resource.

The same representation can support several model questions. Preserve shared IDs
and link evidence rather than duplicating another model's facts or assuming that
these handoffs are implemented APIs.

Based on *The MAGE Method*, §2.4 (pp. 70–73), §2.8 (pp. 87–98), §3.3
(pp. 113–118), and Appendix C.2 (pp. 368–369).

# Coordination patterns and book basis

Read the pattern that matches the task. The arrows below represent dependencies for an
example question; they are not fixed skill sequences. Each scenario is hypothetical until
grounded in the target system's evidence.

## Bootstrap useful repository knowledge

**Question:** Which parts and boundaries must future work understand?

Start with manifests, entrypoints, existing model indexes, and authored intent. Structural
usually provides a shallow entity map. Choose one actual task, subsystem, or recurring
question and add the views it needs. A job pipeline might need behavioral and ownership
models; a permissions subsystem might need decision; a cost investigation might need
measurement. Preserve omissions and coverage rather than manufacturing all six outputs.

Save completed slices and freshness metadata before expanding coverage. Link identities
through a small navigation index when useful. Check that a fresh agent can reach the
needed slice and its evidence without loading the whole model collection. Model size or
the number of files produced is not evidence of improved engineering performance.

## A change across an interface or subsystem

**Question:** What must change together, and what must continue to hold?

Structural identifies relevant producers, consumers, stores, and boundaries. Decision
supplies independently declared policy where admission or access changes. Behavioral
supplies ordering and recovery obligations; ownership supplies valid claims if concurrent
actors can mutate shared work. Select only those views the change implicates.

Retain the source of each obligation and the affected implementation sites. Make the
change through authorized capabilities. Refresh affected derived facts or regenerate
authorized model-owned artifacts, and inspect the relevant joins again. Measurement is
needed when the change makes a quantitative claim. Provenance carries the task and
meaningful outcomes through consequential changes.

An observed dependency map can define impact; it cannot independently prove the new
architecture is acceptable. Matching declarations on both sides of an interface can
establish correspondence while missing a real producer's different behavior.

## A stale worker clears a newer claim

**Question:** Can an obsolete action alter the current grant or protected state?

Enter through ownership. Identify resource, holders, successive grants, validity rules,
and protected effects. Follow behavioral transitions only as needed to reason about
acquire, expire, reclaim, return, and release. Use structural to locate the comparison,
mutation, serialization boundary, and bypass paths when those locations are unknown.

`A@7 -> reclaim -> A@8 -> release(A@7)` is a candidate counterexample scenario. Same-holder
reacquisition matters: comparing holder names alone cannot distinguish those grants.
Decision adds role or recovery permission when it is part of the action's guard.
Measurement adds active-claim counts only if the question involves capacity. Provenance
can establish an incident's actual sequence when adequate events were retained.

State three conclusions separately: the analyzed model's property, correspondence of
inspected implementation paths, and the actual mechanism controlling the mutation.
Checking an epoch before a separate write is not automatically an atomic guard. Recovery
eligibility is different from permission to repeat a payment or publication effect.

## A crash leaves a record pointing at an unpublished artifact

**Question:** Which order preserves a durable reference through failure?

Enter through behavioral and distinguish local staging, durable publication, and updating
the referencing record. Structural identifies the stores and writes. Decision supplies
the publication rule if its authority is unclear. Ownership participates only when another
actor can overlap recovery. Provenance supplies realized ordering if the task concerns
an incident rather than possible behavior.

The proposed safety property is that the reference is updated only after publication.
Determine whether the target's actual requirements call for it. Explore the relevant
failure boundaries and recovery routes. Do not treat a complete modeled ordering as
proof that every implementation path follows it, or one successful recovery as proof
that every submitted job eventually terminates.

## A forbidden call or disputed permission

**Question:** Does what occurs conform to what is permitted?

Structural supplies observed call edges and their inspected coverage. Decision supplies
declared subjects, actions, conditions, case space, and defaults. Join the same component
IDs and compare the observed edge to its policy verdict. Behavioral supplies context if
permission depends on lifecycle state; ownership supplies claim validity if that is an
independent requirement.

An undeclared edge is prohibited in a closed policy graph that defines that meaning.
An absent entry in a partial source scan or a missing policy source establishes unknown
coverage, not an inferred permission or prohibition. Policy conflicts stay explicit.
If enforcement is requested, locate where the rule is decidable and inspect how real
calls can bypass it before proposing a constraint or validator/gate.

## A performance, capacity, or cost investigation

**Question:** Which quantity differs from its reference, and what explains it?

Enter through measurement: declare quantity, unit, scope, aggregation, time window,
denominator, and a separately sourced baseline or bound. Link measurements to the same
components, requests, jobs, or runs used elsewhere. Structural can expose dependencies
or residency; behavioral can expose waiting and retries; ownership can expose contention;
provenance can connect a measured run to its actual change or configuration.

Retain observed values, reference values, deltas, margin where meaningful, missingness,
and uncertainty. A measured regression can motivate investigation without establishing
causality. A benchmark improvement does not automatically imply correct retained work.
For the initial MAGE experiment, use the existing specification's outcome priorities and
matched-condition constraints; do not import that study design into unrelated analysis.

## An incident or recurring failure

**Question:** What happened, what can the evidence establish, and what should persist?

Enter through provenance or dated observations. Preserve actual events separately from
inference. Structural identifies affected paths; behavioral describes candidate execution
and recovery; ownership and decision identify claim and policy conditions where relevant;
measurement quantifies consequence or recurrence when records permit it.

An observability gap is a finding. Avoid inventing a complete causal narrative to fill it.
After authorized recovery, diagnose the durable gap: missing representation, obligation,
evidence, evaluation, consequence, or procedure. Recommend a proportionate response with
scope, assumptions, interaction risks, and upkeep. Improving a model or keeping ordinary
judgment can be the right result. Do not turn every incident into a new gate.

## Book basis and limits

Source: James C. Davis, *The MAGE Method: Model-Based Agentic Software Engineering*,
first published 2026-07-22, edition modified 2026-09-02. Source supplied for authoring:
`/Users/rickywong/Downloads/mage-book.pdf`. Page references use that edition's printed
page numbers. These notes preserve design rationale; the skill has no runtime dependency
on that local PDF or the author's companion tools.

| Coordination choice | Book location |
| --- | --- |
| Select a purposeful reduction by engineering question; leave uncertainty and degrees of freedom explicit | §2.1, pp. 43–54 |
| Six classes distinguish semantics and can overlap; one lease can serve several questions | §§2.2–2.7, pp. 55–82; especially §2.4.3, p. 69 |
| Use shared identities and task-driven traversal; join useful views without a seventh universal model | §2.8, pp. 83–91; Appendix C.6, pp. 351–352 |
| Derive, generate, or trace and check according to the source of truth | §2.8.2, pp. 86–90 |
| Guidance differs from authority; correspondence, conformance, and acceptance support different claims | §§3.1–3.2, pp. 95–105 |
| Match constraint, sensor, validator, and gate to the obligation and decidable boundary | §3.3, pp. 106–114 |
| Diagnose failures before conversion and check control interactions and continuing value | §§3.4–3.5, pp. 115–126 |
| Let successive representations change the investigation as evidence exposes new questions | Interlude, pp. 127–140 |
| Model, align, work, evaluate, convert; size work by reasoning burden and assurance need | §4.1, pp. 143–147 |
| Recover existing knowledge, migrate a bounded surface, audit/drain/promote, price upkeep | §4.2, pp. 148–159 |
| Independent evidence, claim-appropriate analyses, obligation coverage, and freshness at consequential boundaries | §4.3, pp. 160–170 |
| Healthy lifecycles and typed operational steps preserve repeatable work and judgment | §4.4, pp. 171–179 |
| Keep context selective, measure benefit, and preserve explicit composition interfaces | §4.5, pp. 180–186; Appendix E, pp. 370–380 |
| Use a fundamental model, separate facets, and a governing principle in a mastery skill | Appendix E.1, pp. 372–374 |
| Local adoption is valid; models have different temporal purposes; useful lifecycle connections can accumulate | Appendix F, pp. 381–404 |

The local handoff fields, optional navigation/checkpoint paths, and adapters in this skill
are implementation choices informed by the book and inspected model files. They are not
requirements imposed by the book. Coordination is guidance; its performance benefits
and any later enforcement must be established through appropriate evidence.

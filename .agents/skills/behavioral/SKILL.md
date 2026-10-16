---
name: behavioral
description: >-
  Apply the MAGE Behavioral Model to what may happen to a component and in what
  order. Use for execution order, state lifecycles, finite-state machines, crash
  recovery, race conditions, and whether a state transition is legal or forbidden.
  Extracts states, permitted and forbidden transitions with code anchors, and
  checkable safety and liveness invariants, caching each result under
  `.mage/behavioral/` so later questions reuse it instead of re-reading source.
  Uses typed B-UML snapshots and executable B-OCL invariants.
---

# Behavioral Model

## Executable representation: B-UML and B-OCL

For new or refreshed behavioral slices, store machine-readable facts in a typed
B-UML snapshot (`model.json`) and independently authored obligations in `.ocl`
files. Use the [B-OCL workflow](references/bocl.md), its
[snapshot template](assets/model.example.json), and
[example invariant](assets/snapshot.example.ocl). Run
[scripts/validate_model.py](scripts/validate_model.py) and save the report beside
the project model. Keep project outputs outside the installed skill.

The Markdown contracts below are human-readable projections and evidence notes;
the JSON snapshot owns the executable facts and OCL owns the checked predicates.
Preserve any established authoritative source and derive the snapshot from it.
Migrate saved slices when they are next used: retain IDs, authority, evidence,
freshness, and omissions, and verify source correspondence before reuse.
Do not invent data or policy to obtain a Boolean result. Unknown values remain
`null`; incomplete coverage remains incomplete. Report only the checks actually
executed. B-OCL snapshot checks establish neither liveness nor runtime enforcement.


What may happen, and in what order?

## When to Use This Skill
Use this skill whenever a task asks about execution order, state lifecycles, crash recovery, race conditions, or whether a state transition is legal.

## Step 1: File Cache Check (Do Not Exhaust Context!)
1. First check if `.mage/structural/` exists to locate the relevant files.
2. Check if `.mage/behavioral/<component_name>.md` already exists.
3. **If it exists:** Read the slice and its snapshot/report. Verify repository, scope, discovery inventory, source hashes, relevant staged/unstaged/untracked changes, and observation time before reuse. Without that evidence mark freshness unknown and inspect the relevant sources; file existence alone is insufficient.
4. **If it does NOT exist:** Read ONLY the target component's lifecycle/state files and generate `.mage/behavioral/<component_name>.md` using Step 2.

## Step 2: How to Extract a Behavioral Model (Purposeful Reduction)
Ignore implementation noise (UI formatting, logging, helper utilities) and extract ONLY:
1. **Model Card:**
   - **Engineering Question:** What states may this component occupy, and in what order?
   - **Model:** Finite-state transition system over the component lifecycle.
   - **Property (Invariant):** What ordering rule must always hold?
   - **Quality Attribute:** (e.g., Crash-safety, lifecycle integrity, concurrency safety).
2. **States (Nodes):** List every valid state/phase and its code anchor (`file.ts :: EnumOrVariable`).
3. **Permitted Transitions (Edges):** A Markdown table of `From State | To State | Trigger / Method | Code Anchor`.
4. **Forbidden / Absent Transitions:** Keep independently declared legality separate from transitions extracted from implementation. An absent edge is forbidden only in an explicitly closed transition domain; outside inspected coverage it is unknown.
5. **Checkable Invariants:** 1–3 safety ("bad state never reached") or liveness ("terminal state eventually reached") rules.

Use OCL for snapshot/step safety. Establish trace continuity and reachability with a suitable trace or state-space tool; liveness requires temporal reasoning and explicit scheduling assumptions. Name unexecuted analyses and preserve their limits.

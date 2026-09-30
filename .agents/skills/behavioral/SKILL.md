---
name: behavioral
description: >-
  Apply the MAGE Behavioral Model to what may happen to a component and in what
  order. Use for execution order, state lifecycles, finite-state machines, crash
  recovery, race conditions, and whether a state transition is legal or forbidden.
  Extracts states, permitted and forbidden transitions with code anchors, and
  checkable safety and liveness invariants, caching each result under
  `.mage/behavioral/` so later questions reuse it instead of re-reading source.
---

# Behavioral Model

What may happen, and in what order?

## When to Use This Skill
Use this skill whenever a task asks about execution order, state lifecycles, crash recovery, race conditions, or whether a state transition is legal.

## Step 1: File Cache Check (Do Not Exhaust Context!)
1. First check if `.mage/structural/` exists to locate the relevant files.
2. Check if `.mage/behavioral/<component_name>.md` already exists.
3. **If it exists:** Read that `.md` file directly to answer the question. Do NOT grep or read raw source code unless verifying a specific line.
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
4. **Forbidden / Absent Transitions:** Explicitly list state skips or backward jumps that the system forbids (e.g., jumping from `Starting` to `Eventually` without `Ready`, or moving backward in phase).
5. **Checkable Invariants:** 1–3 safety ("bad state never reached") or liveness ("terminal state eventually reached") rules.
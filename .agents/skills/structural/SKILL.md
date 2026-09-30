---
name: structural
description: >-
  Apply the MAGE Structural Model to build, reuse, and incrementally refresh an
  evidence-backed account of a codebase: what parts exist, how they connect, and which
  dependencies are permitted. Use for repository architecture questions, component and
  dependency mapping, architectural boundaries, structural change impact, and
  bootstrapping persistent structural knowledge for coding agents.
---

# Structural Model

Use this skill when the engineering question is about what exists:

> What are the parts of this system, how do they connect, and which connections are sanctioned?

Structural modeling represents parts and permitted relationships. It is distinct from:

- **Behavioral modeling:** which states and transitions may occur.
- **Decision modeling:** what is permitted, required, or prohibited —
  [`../decision/SKILL.md`](../decision/SKILL.md).
- **Provenance:** what actually happened — [`../provenance/SKILL.md`](../provenance/SKILL.md).
- **Measurement:** what quantity was observed against which declared bound —
  [`../measurement/SKILL.md`](../measurement/SKILL.md).
- **Search and reading:** the raw repository facts a structural model is extracted from.

The model family this skill instantiates is *structure and boundaries*, described in
[`../self-governance/modeling/repertoire.md`](../self-governance/modeling/repertoire.md).
Two engineering moves apply most often: **make dependencies queryable** and **check
correspondence** ([`../self-governance/modeling/moves.md`](../self-governance/modeling/moves.md)).

## Core rule

Preserve only the structure needed to answer an engineering question. Exclude execution
histories, state transitions, timings, and retry sequences; those belong to other models.
Do not build the whole picture because the question happens to span it.

## 1. Establish the question and scope

- Identify the repository root and follow its applicable agent instructions.
- Use the structural question to select a subsystem. When asked to bootstrap a repository
  with no specific question, start with: "What are the major components, their
  responsibilities, and the boundaries between them?"
- Read file listings, package and workspace manifests, entry points, registrations,
  architecture documents, and existing model indexes before reading implementation bodies.
  Prefer `rg --files` and targeted searches; use equivalent tools where unavailable.
- Reuse existing component identities and authoritative declarations. Do not infer an
  architectural role from a folder name.
- Model services, packages, modules, interfaces, stores, and external systems at one
  consistent granularity. Descend to classes and functions only when the question requires it.
- Do not modify application code, add enforcement gates, or redesign the architecture during
  extraction unless that work was separately requested.

## 2. Check saved models before extracting

This repository keeps each authored model definition beside its skill, under
`.agents/skills/<model>/SKILL.md`, and the models extracted from a specific repository under
`.mage/`. Save structural slices to `.mage/structural/`, alongside `.mage/provenance.md`. Use
a project's own location when it already has one. Keep these skill instructions separate from
the repository-specific outputs they produce.

1. Read `index.md` first, then only the relevant subsystem files and their freshness metadata.
2. Verify repository identity, requested scope, coverage, source anchors, and source changes.
   File existence and timestamps do not establish freshness.
3. Where Git is available, compare the saved revision with HEAD and inspect staged, unstaged,
   deleted, renamed, and relevant untracked files. A matching commit does not establish
   freshness in a dirty working tree.
4. Compare saved content hashes for inspected source files. Check the recorded discovery roots
   for new or deleted files and for changed manifests and registrations, which can introduce
   components and relations. Without Git, use file inventories plus content hashes. When
   verification is unavailable, mark freshness unknown and verify the relevant sources before
   answering.
5. Reuse verified, covered slices; refresh affected components and their relationships when
   stale. Expand coverage only where the question requires it. Bootstrap missing slices without
   overwriting unrelated or user-authored material.
6. Treat an absent relationship outside inspected coverage as unknown, never as proof that no
   dependency exists.

## 3. Extract components, relationships, and boundaries

- Derive observed structure from source, imports, build references, routes, dependency
  injection registrations, schemas, or explicit composition declarations. Use existing parsers
  and extractors where they exist. A text search yields candidates that require inspection, not
  a language-aware dependency analysis.
- Give each entity a stable ID, preferably an existing canonical identifier; otherwise a
  documented qualified component name. Preserve IDs through renames once continuity is
  established, and record aliases.
- Attach evidence to every entity and relationship: repository-relative path, symbol or
  configuration key, and the relevant source hash. Line numbers are supplementary navigation
  only; re-resolve anchors against current source.
- Distinguish observed implementation, declared intent, and inference. Record unresolved
  dynamic imports, reflection, generated code, and indirect calls explicitly. Do not invent an
  edge to make a diagram look complete.
- Type the relations rather than flattening everything into "depends on": `CONTAINS`,
  `IMPORTS`, `CALLS`, `IMPLEMENTS`, `READS`, `WRITES`, `DATA_FLOW`, `CONTROL_GATE`,
  `CROSS_SERVICE`. Define any additional type locally.
- State direction. `CONTAINS` runs parent to child. Imports, calls, implements, reads, and
  writes run actor to target. Data flow runs producer to consumer. A control gate runs from the
  signal producer to the gated computation. A cross-service edge runs from payload sender to
  receiver. An import is not proof of a call or of a payload transfer.
- Where computations declare produced and consumed facets, derive payload edges from the
  produces-consumes intersection and control edges from the produces-consumes-for-control
  intersection. Inspect evidence for inferred read and write composition when no declarations
  exist.
- For mutation-focused questions, classify effects as typed or bounded patch, direct edit,
  read-only, or unknown — and only where the evidence supports the classification. A direct
  editor is not automatically a defect.
- Keep observed edges separate from permitted ones. Record sanctioned interfaces, forbidden
  bypasses, and exceptions only from authoritative project intent, with citations. Where intent
  is missing, say it is unspecified and label any recommendation as proposed.

## 4. Save a small, navigable model

Create these Markdown files using the contracts below. Adapt the names to an existing project
convention and preserve the equivalent fields. Do not create an empty subsystem file.

### `index.md`

A compact repository entry point, at most about 150 lines:

- Repository identity and model schema version (`1`).
- Model card: engineering question, scope, represented property, quality attribute, deliberate
  omissions. Follow the card used in
  [`../measurement/SKILL.md`](../measurement/SKILL.md).
- Component table: stable ID, responsibility, model-file link.
- Cross-subsystem relationship summary with links to the supporting slices.
- Coverage status: inspected regions, exclusions, unresolved regions.
- Link to freshness metadata and the next work item.

### `components/<subsystem-id>.md`

One coherent subsystem or task slice per file:

1. **Model card:** question, scope, property, quality attribute, omitted detail.
2. **Entities:** `ID | Kind | Responsibility | Source anchor | Evidence status`.
3. **Relationships:** `From ID | Type | To ID | Meaning/facet | Source anchor | Evidence status`.
4. **Architectural intent:** `Rule ID | Permitted/forbidden relation | Authority | Observed conformance | Existing enforcement`.
5. **Unknowns and coverage:** inspected paths, and unresolved or dynamic relations. An inferred
   relation is not a verified fact; keep the two labeled apart.
6. **Validation findings:** check, inspected domain, result, evidence, limitations.
7. **Freshness:** link to this slice's entry in `manifest.md`.

A small Mermaid diagram is worth adding where it clarifies a boundary. Generate it from the
same entities and relationships, and keep the tables authoritative within the saved
projection; diagram conventions live in
[`../self-communicate/drawing/diagrams.md`](../self-communicate/drawing/diagrams.md). Do not
copy whole source files into the model.

### `manifest.md`

Record enough to resume work and to detect drift:

- Schema version, repository identity, extraction time in UTC, revision where available, and
  dirty-worktree status.
- Per slice: question and scope, discovery roots, relevant file inventory, inspected source
  paths with content hashes, extraction method, verification time, and status —
  `complete-within-scope`, `partial`, `stale`, or `unknown`.
- Every evidence-bearing source hash, including untracked sources. For a large inventory, link
  per-slice manifest files rather than loading the whole inventory into context.
- Completed work, remaining work, blockers, and the exact next source or region to inspect.

Save each completed slice and update its index and manifest before continuing. Mark an
interrupted slice `partial`. After a context reset, resume from the checkpoint; do not repeat a
repository-wide scan unless change evidence requires it. On a read-only filesystem, return the
proposed model text and state plainly that it was not persisted.

## 5. Validate before relying on the model

- Check unique IDs, defined relation types, existing edge endpoints, resolvable source anchors,
  and valid index links.
- Reconcile derived declarations with their source inside the inspected domain. A disconnected
  node or an unexpectedly sparse edge set is a possible coverage gap, not automatically a defect.
- Compare observed dependencies against documented architectural rules. Report confirmed
  violations, conflicting intent, and unresolved cases separately.
- Inspect cycles only where they are relevant, and call one a violation only when an
  authoritative rule forbids it.
- Separate the checks you executed from the checks you are suggesting. Report concrete evidence
  and coverage for every result.
- Structural correspondence is narrower than architectural correctness. An anchor can resolve
  and still support a mistaken interpretation; inspect semantics when the task depends on them.

## 6. Answer from the smallest verified slice

- Lead with the requested answer, then name the relevant components, relationships, source
  evidence, and consequential unknowns.
- For a change-impact question, traverse the relevant incoming and outgoing relation types,
  separate direct impact from possible transitive impact, and name the traversal limits. Do not
  claim that every dependent is affected at runtime.
- State whether the model was created, reused, or refreshed. List the saved paths, the
  inspected scope, and the coverage left unfinished.
- In a large repository, use a shallow component index and targeted slices rather than loading
  the entire model or codebase. Save progress before expanding scope. When a requested full map
  exceeds the available work budget, deliver a clearly partial checkpoint — not a claim of
  completion.
- Hand other skills stable IDs, model paths, evidence, findings, and freshness. Read
  [`../self-governance/SKILL.md`](../self-governance/SKILL.md),
  [`../self-operations/SKILL.md`](../self-operations/SKILL.md), and
  [`../self-communicate/SKILL.md`](../self-communicate/SKILL.md) before assuming their
  interfaces.
- Derive component names, counts, and architecture from the target repository. Do not transfer
  assumptions from another project.
- Do not claim token savings, lower latency, or benchmark improvement without measured
  evaluation; the measures and their required fields live in
  [`../measurement/SKILL.md`](../measurement/SKILL.md).

## MAGE alignment

The structural model states what the architecture is. Alignment gives a declared boundary
authority:

```text
MODEL: declared components, their seams, and the permitted dependencies across them
ALIGN: an observed edge must correspond to a permitted one
CHECK: a boundary lint or admission gate rejects a crossing with no sanctioning rule
```

Describe an architectural rule as enforced only where a mechanism actually rejects violations.
This skill produces a model and findings; it does not itself enforce the architecture it
represents. Deciding which declared boundary deserves a control is an Alignment decision —
[`../self-governance/alignment/repertoire.md`](../self-governance/alignment/repertoire.md).

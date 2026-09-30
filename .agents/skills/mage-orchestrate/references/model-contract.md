# Model handoffs and suite adapters

Read this when composing models, deciding whether to reuse a saved slice, or selecting
the behavioral or measurement file in the current suite.

## The handoff

Use the native model formats. At the boundary between skills, preserve these semantics
in a short Markdown record or equivalent existing metadata. Add fields only where the
question needs them; do not require a new universal schema or backing service.

| Field | Meaning |
| --- | --- |
| Question and scope | The sub-question answered, repository/subsystem, and deliberate omissions |
| Identities | Canonical component, resource, actor, claim, artifact, operation, or run IDs needed for the join |
| Model reference | Path plus section/record ID and model version, where available |
| Claim status | Authored intent, observed fact, derived fact, inference, proposal, or unknown |
| Authority source | Requirement, policy, maintainer decision, protocol, or source of an observation; unknown when absent |
| Freshness | Relevant revision and source hashes, working-tree coverage, verification time, or stale/unknown status |
| Evidence | Resolvable source/configuration anchors, observations, checks, and their versions or timestamps |
| Coverage | Inspected domain, exclusions, bounds, assumptions, and partial/complete-within-scope status |
| Findings | Conflicts, counterexamples, correspondence gaps, and unresolved questions |
| Enforcement | Actual mechanism and boundary, or proposed/advisory/absent/unknown |
| Next dependency | The question another skill must answer before the result can be used |

Claim status, freshness, and enforcement are separate axes. A fresh policy can be advisory;
a current derived graph can describe a policy violation; an old incident can be valid
history without describing current state. Preserve a record's temporal purpose: historical
intent is assessed against its historical revision, not automatically refreshed to HEAD.

## Join discipline

Reuse the same identity for the same entity. Match versions and time scopes where the
answer requires contemporaneous facts. If identity continuity is uncertain, record a
proposed mapping rather than silently merging entities. Preserve aliases through an
established rename.

Keep relation semantics intact: `CALLS` is an observation of structure, a policy verdict
is normative, a transition is possible behavior, and an operation record is realized
history. Do not substitute one for another because their diagrams use the same arrows.

Choose one owner for a reusable fact. Other models should link, query, or derive it. For
each model/implementation correspondence, declare one of three directions:

- **Derive:** implementation owns the represented fact; refresh the projection from source.
- **Generate:** a settled model owns the declaration; regenerate downstream artifacts.
- **Trace and check:** neither side determines the other; preserve resolvable anchors and
  inspect the decidable correspondences. State semantic questions that still need judgment.

These directions do not settle whether the governing obligation is correct. Do not
regenerate code from a descriptive model merely because it is structured.

## Freshness before cache reuse

Verify the slice's repository identity and scope, then compare relevant sources with its
saved basis. With Git, include dirty and relevant untracked files; a matching HEAD does
not establish a current working-tree projection. Check discovery roots and declarations
that could introduce new entities, edges, cases, or transition sites.

Source hashes detect changed inspected files, but cannot detect a newly added handler
unless discovery coverage includes its registration or directory. Source anchors that
still resolve can have changed meaning. Check semantics where the requested claim
depends on them. Without metadata, inspect the smallest relevant source slice and
record what remains unknown. Never upgrade file existence to verified freshness.

Current ownership, measured quantities, and live state require their own dated
observations. A freshly extracted protocol does not establish which claim is valid now.
A past acquisition record or cached dashboard cannot supply missing current evidence.

## Current suite adapters

The table describes the files inspected while creating this coordinator. Reinspect the
selected entrypoint if its contents change; do not treat these notes as permanent facts
about every installation.

| Model | Current entrypoint | Coordination adjustment |
| --- | --- | --- |
| Structural | [SKILL.md](../../structural/SKILL.md) | Apply its index/slice/manifest contract; share its existing entity IDs. |
| Behavioral | [SKILL.md](../../behavioral/SKILL.md) | It is an instruction file without YAML skill metadata and tells the reader to reuse an existing cache. Read it explicitly and perform the freshness check above before reuse. |
| Ownership | [SKILL.md](../../ownership/SKILL.md) | Use claim identity and validity; obtain current observations separately; link to behavioral transitions. |
| Decision | [SKILL.md](../../decision/SKILL.md) | Preserve a declared case domain and default. Outside an established policy's coverage, report unknown policy rather than inventing a verdict. |
| Measurement | [SKILL.md](../../measurement/SKILL.md) | It is the initial experiment's measurement specification without YAML skill metadata. Read it as a reference; adapt applicable semantics to the actual quantitative question. |
| Provenance | [SKILL.md](../../provenance/SKILL.md) | Capture consequential history once; carry its cause, actor/run, targets, results, and evidence. |

The behavioral adapter supplies the missing metadata: scope, source anchors/hashes,
discovery coverage, freshness, claim/authority status, and analysis limits. Separate
transitions extracted from code from transitions independently declared legal. It is
useful to model a protocol with defects; extraction does not validate its intent. A
missing edge forbids a transition only in a declared complete transition relation.

The measurement adapter retains quantities, units, scope, aggregation, windows,
denominators, separately sourced references, margin, uncertainty, and explicit missingness.
Its baseline/treatment design and fixture priorities apply when the user is running that
experiment; they are not universal requirements for cost, latency, or capacity analysis.
The document's `agent-guidance-docs/` links are not present in this repository. Name that
missing authority if the task depends on it; do not treat those paths as available tools
or silently supply experiment thresholds. Unknown values remain unknown, never zero.

## Storage and checkpoints

Use established project locations first. Defaults from the current model skills are:

| Output | Default |
| --- | --- |
| Structural slices and their index/manifest | `.mage/structural/` |
| Behavioral component lifecycle | `.mage/behavioral/<component_name>.md` |
| Ownership slice | `.mage/ownership/<scope-id>.md` |
| Decision slices and their index/manifest | `.mage/decision/` |
| Consequential history | `.mage/provenance.md` |
| Measurement definitions/results | Use the project's experiment store; otherwise a scoped `.mage/measurement/<scope-id>.md` is a coordinator convention |

Preserve skill-specific shapes without creating empty directories or index files for
unused classes. For a connected task, an optional `.mage/index.md` is navigation across
existing slices. An optional `.mage/work/<task-id>.md` holds resumption state. These are
coordinator conventions, not additional model classes or copied sources of truth.

A checkpoint retains the question, model paths and versions, completed work, actual
evidence, partial coverage, conflicts, and exact next step. Update affected slice metadata
after authorized source changes. On read-only work, return the answer or proposed model
contents and state that nothing was persisted.

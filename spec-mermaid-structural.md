# Mermaid Ground-Truth Structural Model and Deterministic Conformance Check

Status: draft for review. Unresolved decisions are listed in **Open decisions** at the
end; they are the only items blocking implementation.

## Problem Statement

An engineering agent reasoning about a codebase must reconstruct its architecture,
dependencies, and constraints from low-level source on every task. MAGE's position is
that this knowledge should be externalised into reusable engineering representations
instead.

The existing structural OCL pilot shows that this is mechanically possible: it extracts
Python imports, represents them in BESSER, and evaluates one OCL invariant per observed
edge, returning attributable JSON with evidence and coverage. That pilot asks a single
narrow question — does an API module import a database module — and it works, but it
delimits itself severely. Its OCL invariant only exists because BESSER supplies a
constraint language; the whole dependency-pinning discussion in its README exists to
keep B-OCL and BESSER mutually compatible. It models three flat modules and one rule.

That shape does not scale to the actual goal. A real codebase has external systems,
packages, internal modules, classes, and functions, and a ground-truth model of it needs
to answer two questions an agent asks constantly: *may I depend on this?* and *did my
change break the architecture?* Mermaid is the obvious rendering — it renders in
Markdown, needs no toolchain, and an agent can read the source text without a
viewer.

Mermaid is also the trap. `classDiagram` expresses classes, attributes, methods,
visibility, `<<Annotation>>`, namespaces, relation types, and cardinality, and nothing
else. It has no constraint semantics, so a Mermaid diagram cannot be *evaluated* the way
the OCL pilot's invariant is. If a Mermaid file is treated as the source of truth, an
agent can satisfy any architectural rule by redrawing the diagram. A ground-truth model
whose truth an agent may edit in the same change it is being judged against is not a
ground truth.

The developer wants that model anyway, wants Mermaid in it, and wants the conformance
check to be a hard CI gate. The problem to solve is how to get Mermaid's legibility
without Mermaid's mutability becoming a loophole.

## Solution

Build a second runnable example alongside the OCL pilot in which a JSON model is the
authority, a Mermaid `classDiagram` is a generated and freshness-checked projection of
it, and a checker evaluates observed code against the policy recorded in the JSON.

Three properties make it non-vacuous:

1. **The checker never parses Mermaid.** Mermaid is output. The authored authority is
   JSON. An agent cannot pass the check by editing a diagram, because the diagram is
   not read.
2. **Conformance is evaluated against the base revision of the policy, not the working
   copy.** A change that both violates a rule and edits the model to permit itself still
   fails, because the rule it violated is the rule that existed before the change. This
   is the direct implementation of "a new addition must not violate prior constraints."
3. **Policy edits are findings in their own right.** Retiring a rule that would otherwise
   fail is reported as `policy-retired` and blocks, so the gate cannot be satisfied by
   deleting the standard.

The model also gains a shape the OCL pilot deliberately lacks: a **policy matrix** over
(layer × layer × relation type) with three-valued cells — `permitted`, `forbidden`,
`unspecified`. Every conformance decision is a lookup in that matrix. `unspecified` is a
first-class outcome that is never a pass, which is what lets the same checker enforce
both a closed world and an open world depending on the cell.

## User Stories

1. As a coding agent, I want to read one Mermaid file to see a codebase's components and
   their sanctioned relationships, so that I do not reconstruct architecture from source
   on every task.
2. As a coding agent, I want each component in that file to carry its identity, layer, and
   responsibility, so that I can name it precisely in code I write.
3. As a coding agent, I want to know whether a dependency I am about to add is permitted,
   so that I do not introduce a boundary violation.
4. As a coding agent, I want the check to be runnable as a shell command returning JSON
   and an exit code, so that I can invoke it from my own tools and parse the result.
5. As a coding agent, I want every violation to name the source path, line, symbol, and
   source hash that produced it, so that my report cites evidence rather than assertion.
6. As a coding agent, I want a violation I am looking at to be attributable to one
   specific observed edge rather than to the codebase as a whole, so that I can fix exactly
   one thing.
7. As a coding agent, I want the tool to distinguish "this dependency is forbidden" from
   "I could not determine whether this is permitted", so that I do not mistake silence for
   approval.
8. As a coding agent, I want an absent relationship outside the inspected scope reported as
   unknown rather than as proof of absence, so that I do not claim a codebase is clean
   because it was not fully read.
9. As a coding agent, I want the Mermaid file to carry a marker identifying the model
   version it was generated from, so that I can tell whether the file I read is current.
10. As a reviewer, I want a change that edits the model to be evaluated against the rules
    that existed before it, so that approving the change does not depend on whether I read
    the model diff carefully.
11. As a reviewer, I want the deletion of a rule to surface as a distinct finding, so that
    loosening a boundary is as visible as crossing one.
12. As a reviewer, I want the addition of a rule to take effect prospectively rather than
    to retroactively fail unrelated changes already in flight, so that tightening a
    boundary does not block work it was not meant to judge.
13. As a reviewer, I want the check to fail when the committed diagram no longer matches
    the model it was generated from, so that the diagram cannot silently go stale.
14. As a reviewer, I want the gate to distinguish its failure modes, so that I can tell a
    real boundary violation from a stale artifact or an inspection gap.
15. As a reviewer, I want the exact rule that was violated reported alongside the
    violation, so that I can judge whether the rule is still correct.
16. As an engineer browsing the repository, I want the structural model to be Mermaid I
    can read without installing anything, so that I do not need a separate modelling tool.
17. As an engineer browsing the repository, I want external systems — databases, cloud
    services, third-party servers — represented alongside internal modules, so that the
    diagram describes what the system actually talks to rather than only its own folders.
18. As an engineer writing the model, I want the boundary policy expressed as a table
    rather than as prose or code, so that it is reviewable at a glance and does not require
    a constraint-language interpreter to evaluate.
19. As an engineer writing the model, I want an unknown or misspelled layer or relation
    type to be rejected at load time rather than treated as permission, so that a typo
    cannot open a hole in the boundary.
20. As an engineer adopting this on another repository, I want the example to demonstrate
    one subsystem end to end, so that I can copy the model format and the run command
    without reverse-engineering them.
21. As an engineer evaluating whether this helps agents, I want the result comparable in
    shape to the OCL pilot's, so that the two can be assessed on the same terms.
22. As an engineer maintaining this, I want the checker to depend on nothing outside the
    Python standard library, so that no dependency pinning is required to run it.
23. As an engineer maintaining this, I want the model format documented as a contract with
    an explicit statement of what it does not establish, so that nobody treats an absence
    of findings as an architectural certification.
24. As an agent running later MAGE models against the same repository, I want stable
    component identities that survive refactoring, so that a provenance or impact model
    built today can still refer to those components later.

## Implementation Decisions

### Modules

Five modules, no third-party dependencies, Python 3.10 or newer:

- **model loader** — read and validate the model document; produce a canonical
  serialisation and its SHA-256. Rejects duplicate IDs, unknown layers, unknown relation
  types, unknown cell values, and malformed entries at load time.
- **extractor** — walk the declared root, parse Python with `ast`, produce observed edges
  with evidence, resolved external-system references, and a coverage report. Deliberately
  mirrors the pilot's extractor, including its treatment of an import inside a conditional
  as a static import and its refusal to establish runtime calls.
- **policy evaluator** — the `aligned` predicate. Pure function over observed edge,
  component attributes, declared relations, and a policy matrix. No I/O.
- **renderer** — model document to Mermaid source. Deterministic.
- **checker** — the single seam. Orchestrates load, extract, evaluate, render-drift check,
  and assemble the report. Owns the CLI and the exit-code mapping.

### Test seams

Two, both pure, both injected:

- `check(root, model, base_model=None, diagram_path=None) -> report` — highest seam; takes
  the base policy as an argument rather than reaching for git, so base-revision semantics
  are testable without a repository. Returns a plain dict.
- `render(model) -> str` — deterministic; tested for byte-stability.

Resolving the base revision from git happens in the CLI only, by reading the model
document at `HEAD`. When the base cannot be resolved, the working copy is used and the run
is marked accordingly rather than silently downgraded.

### Model document shape

Decision-encoding, inline because the schema *is* the decision:

```json
{
  "schema_version": 1,
  "repository": "org/repo",
  "components": [
    {"id": "orders.api", "path": "api.py", "layer": "api",
     "responsibility": "HTTP surface", "external": false}
  ],
  "external_systems": [
    {"id": "orders.db", "alias": "ORDERS_DSN", "kind": "database",
     "layer": "database"}
  ],
  "relations": [
    {"from": "orders.api", "to": "orders.service", "type": "IMPORTS",
     "status": "sanctioned"}
  ],
  "policy": {
    "layers": ["api", "service", "database"],
    "relation_types": ["IMPORTS", "CONTAINS", "CALLS", "READS", "WRITES"],
    "matrix": {
      "IMPORTS": {
        "api":       {"service": "permitted", "database": "forbidden"},
        "service":   {"database": "permitted"}
      }
    }
  },
  "constraints": [
    {"id": "C1", "text": "api may not reach persistence directly", "authority": "authored"}
  ]
}
```

`components[].path` maps a component to the file the extractor reads, replacing the
pilot's separate `module` field; a component is a file, which is the granularity v1
supports. `external_systems` are declared, never inferred — databases and cloud services
do not appear in an import graph. `relations[].status` separates sanctioned edges from
observed ones, as the structural model requires. `constraints` are declared intent only:
validated for shape and rendered as `<<Annotation>>` on the component diagram, never
evaluated. KPI fields are deliberately absent; see **Out of Scope**.

### The aligned predicate

An observed edge from component A to component B with relation type T is aligned iff the
matrix cell at `[T][A.layer][B.layer]` is `permitted`. Consequences, all deliberate:

- `forbidden` produces a `violation`. Blocking.
- `permitted` with no matching sanctioned relation in `relations` produces an `undeclared`
  finding. Non-blocking: the boundary is respected, the model is stale.
- `unspecified`, or either endpoint with an unknown layer, produces an `unresolved`
  finding. Non-blocking, and the run cannot report `pass-within-scope`.
- An external system reached by code but absent from `external_systems` produces
  `unresolved`. An alias that resolves produces an observed edge with evidence.

This is the "both" answer to closed-versus-open world: the cell value decides, not a
global switch. It is also the direct analogue of the pilot's nine-case truth table, which
becomes a matrix test over layers × relation types.

### Base-revision evaluation

When the CLI resolves a base model from `HEAD`, violations are evaluated against the base
matrix and base relation set. Consequences:

- A change that adds `api → database` and flips the cell to `permitted` still reports a
  `violation` for the added edge.
- A change that deletes a rule which would have failed reports `policy-retired`. Blocking,
  distinct status. This is the mechanism that stops the gate from being satisfied by
  removing the standard.
- A change that *adds* a rule does not retroactively fail. New rules apply from the next
  run. Tightening cannot mask a violation, so prospectivity is safe.

### Renderer determinism

- Components emitted sorted by ID; relations sorted by (from, type, to).
- One directed edge per relation. Mermaid's two-way relation notation is never emitted,
  because its rendering order is not stable and would break byte-comparison.
- No namespaces in v1. A component ID is mapped to a class name by replacing every
  character outside `[A-Za-z0-9_-]` with `_`. Mermaid does not permit dots in class names,
  so this is required. The ID-to-class-name mapping is emitted in the report so an agent
  reading the diagram can resolve a node back to its ID.
- The first line is a generated-from comment carrying the canonical model SHA-256. This is
  the freshness mechanism visible to a reader of the diagram; Mermaid ignores `%%`
  comments, so it does not affect rendering.
- Members are omitted in v1, since components are files and have no member declarations.

### Drift detection

If a diagram file is present on disk, the checker renders from the model and compares
bytes. A mismatch is `model-stale`. Comparison is byte-exact because the renderer is
deterministic; a normalisation tolerance is not permitted, since tolerance would hide
exactly the hand-edit this is meant to catch.

### Statuses and exit codes

Mutually exclusive, resolved by this precedence, highest first:

`error` → 2, `violations` → 1, `policy-retired` → 1, `model-stale` → 1, `incomplete` → 2,
`pass-within-scope` → 0.

`error` and `incomplete` share exit 2, following the pilot: an inspection gap or an
interpreter failure is never a pass. Every non-zero exit blocks a hard gate.

### Report shape

Follows the pilot so the two examples are assessable on the same terms: `schema_version`,
`status`, `coverage` including unresolved references and unmodelled files plus an explicit
omissions list, `components` with hashes, `results` per observed edge with evidence and
verdict, `violations`, `policy` with the canonical hash and the matrix, and a generated
`diagram` section carrying the class-name mapping and the diagram hash.

### Relationship to the existing pilot

The OCL pilot is unchanged. The new example is a sibling, not a replacement. The two
differ in the source of constraint semantics — OCL evaluates, a matrix looks up — and in
that the new one has no third-party dependencies at all. Its README should say plainly
which properties came from the pilot and which are new, and must carry the pilot's warning
that a passing result is conformance within an inspected scope, not architectural
correctness.

## Testing Decisions

A good test here asserts externally observable behaviour: the status, the exit code, and
the evidence attached to a finding. Tests must not inspect the policy evaluator's
internals, and must not assert on rendered diagram text except where the rendered text is
itself the contract — drift detection and determinism.

Prior art is the OCL pilot's test module. Where a test exists there, the new example
should have a recognisable counterpart, because the pilot's suite is the best available
statement of what this kind of tool must be able to prove.

Modules tested: the checker, the renderer, and the model loader. The extractor is tested
through the checker against fixtures, as the pilot does.

Required tests:

- **Policy matrix truth table.** Every layer pair × relation type cell evaluates to its
  declared value. Direct analogue of the pilot's nine-case table, which is the single
  strongest determinism evidence in the repository and must not be dropped.
- **`unspecified` is never a pass.** An unlisted cell yields `incomplete`, not
  `pass-within-scope`. An unknown layer or relation type is rejected at load, following
  the pilot's `test_unknown_layer_is_not_treated_as_permission`.
- **Valid and invalid fixtures.** Conforming fixture exits 0 with two results; violating
  fixture exits 1 with one violation carrying the expected component IDs, symbol text,
  line, and source hash.
- **Base policy binds.** Given a working-copy model that legalises a forbidden edge, the
  violation is still reported when the base model is supplied, and is absent when it is
  not. This is the test that would fail if the loophole reopens.
- **Rule retirement is reported and blocking.** Deleting a rule that would have failed
  yields `policy-retired` and exit 1.
- **New rules are prospective.** A working-copy model adding a rule does not fail the
  current run.
- **Renderer determinism.** The same model presented in a different order produces
  byte-identical output and an identical canonical hash.
- **Drift is caught.** A diagram file edited by hand yields `model-stale` and exit 1. This
  test edits the file directly, because hand-editing is the actual threat.
- **Source changes are re-extracted and rehashed.** Mirrors the pilot's
  `test_source_change_is_reextracted_and_rehashed`.
- **External systems.** A declared alias resolves to an observed edge with evidence; an
  undeclared reference yields `unresolved` and `incomplete`.
- **Coverage gaps.** An unmodelled Python file and an import of an undeclared module both
  yield `incomplete`, mirroring the pilot.
- **CLI exit codes.** One subprocess test per status, mirroring
  `test_cli_exit_codes_and_json`.
- **No third-party dependencies.** An assertion that importing the tool and running the
  suite pulls nothing outside the standard library. Cheap, and it protects the one
  property the OCL pilot's README spends a third of its length defending.

Fixtures: two conforming/violating module sets for the boundary rule, one exercising an
external system alias, one exercising coverage gaps. Reuse the pilot's fixture shape —
three small modules declaring a `pass`-level dependency edge and a direct violation.

## Out of Scope

- **Class and function granularity.** v1 models files. Internal logic below the module
  level is a later version. The pilot restricts itself to top-level modules and names a
  package-aware extractor as its own next extension; going straight to symbols multiplies
  the drift surface and requires Mermaid member blocks to become meaningful. This is the
  decision most worth overriding — see **Open decisions**.
- **KPIs.** A KPI needs a declared baseline and a bound to be interpretable, and that
  bookkeeping is measurement-model work, not structure. Shipping numbers without it
  produces figures nobody can act on. No KPI field in the v1 model.
- **Constraint enforcement.** `constraints` are rendered, not evaluated. They are declared
  intent. Making them binding is decision-model work.
- **Languages other than Python.** The extractor is Python-specific by design.
- **Writing to `.mage/structural/`.** An adapter that writes the report into the
  structural model's index, slice, and manifest contract is a later step, as the OCL
  pilot's own README already anticipates.
- **Validating generated Mermaid against Mermaid's parser.** This would require the Node
  Mermaid CLI, reintroducing the toolchain the design removes. Instead the renderer emits
  only constructs from a documented allowlist, and a test asserts that. Rendering the
  fixtures through `mermaid-cli` is a reasonable follow-up.
- **Runtime, dynamic, and transitive analysis.** No calls, dynamic imports, re-export
  resolution, cross-service traffic, or transitive conformance. An import inside a
  conditional counts as a static import.
- **Human-facing visualisation tooling.** The `.mmd` is rendered by whatever the reader
  already uses. A dedicated viewer is separate work and may reveal that the diagram
  carries too much for a human.

## Further Notes

Three tensions in the original request were resolved rather than left open. Each is a
decision worth reviewing, because a different answer changes the design rather than
tuning it.

**"The agent may update the model in the same change" versus "prior constraints bind."**
Resolved by evaluating against the base revision and reporting rule retirement separately.
Without this the gate cannot be non-vacuous, and the alternative is that the agent may not
edit the model at all.

**"JSON is truth" versus "agents read the `.mmd`."** Resolved by making the diagram a
committed, byte-reproducible generated artefact whose header comment carries the model
hash, with drift checked in CI. An agent may read either; it cannot read a stale diagram
without the check failing. Evidence anchors stay in the JSON report rather than the
diagram, on the reasoning that a diagram carrying per-node hashes stops being a diagram.

**"External dependencies plus internal logic plus constraints plus KPIs in one model."**
The structural model treats structure, decision, and measurement as separate concerns and
this preserves that separation: constraints are declared and rendered but unevaluated, KPIs
are absent. If the intent is genuinely one unified model, that is a larger piece of work
and should be scoped as its own spec rather than folded in here.

The single largest simplification available: this example has **zero third-party
dependencies**. The OCL pilot's README is largely an argument about B-OCL and BESSER
version compatibility, and replacing constraint evaluation with a matrix lookup removes
that entire surface. If the implementing agent starts designing around a Mermaid parser
or a UML library, that is a signal it has misread the design — Mermaid is output.

Per the repository's own discipline, this example validates a toolchain. It is not
evidence that agent performance improves, and neither its README nor its report should
claim otherwise.

## Open decisions

These block implementation. Each is a question the original request raised and did not
settle; the resolution above is a recommendation, not a fait accompli.

1. **Granularity.** The specification recommends files for v1, classes and functions
   deferred. The original request asked for classes and functions. Confirm, or widen.
2. **Enforcement of declared constraints.** Currently rendered and unevaluated. If these
   are meant to be binding — "key constraints" suggests they might be — they need an
   enforcement mechanism comparable to the matrix, and that is decision-model work.
3. **First real subsystem.** This is an example with fixtures, as the pilot is. Applying
   it to a real subsystem is the next piece of work and is not in this spec.
4. **Human-facing rendering.** Whether engineers get raw Mermaid source, a rendered view,
   or both. The diagram is readable as text today; this only becomes a problem if the
   model grows beyond what is legible in source form.
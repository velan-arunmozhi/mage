# Structural model and Alloy pilot

This is a third sibling to [`examples/ocl-structural`](../ocl-structural/README.md)
and [`examples/mermaid`](../mermaid/): it answers the same structural question
using a different modeling language, on the **same model document and the
same fixtures**, so the three can be compared on equal terms rather than on
inputs that merely look similar.

`model.json`, `fixtures/valid/`, and `fixtures/invalid/` are copied verbatim
from `examples/mermaid`. `model_loader.py` and `extractor.py` are mirrored
byte-for-byte from there too, following that pilot's own precedent of
mirroring the OCL pilot's extractor rather than sharing code across examples.
The only new part is the backend: a generated Alloy model and two `check`
commands evaluated by the Alloy Analyzer, in place of a Mermaid-matrix lookup
or a B-OCL invariant.

## Run it

Requires Java 17+ and the Alloy 6 distribution jar (not vendored here, same
posture as the OCL pilot's pinned, non-default Python environment — an
~80 MB third-party binary should be a documented download, not a committed
asset):

```bash
curl -L -o alloy.jar \
  https://github.com/AlloyTools/org.alloytools.alloy/releases/download/v6.2.0/org.alloytools.alloy.dist.jar
export ALLOY_JAR="$(pwd)/alloy.jar"   # or pass --jar explicitly, or drop the
                                       # jar next to checker.py
python examples/alloy-structural/checker.py examples/alloy-structural/fixtures/valid
python examples/alloy-structural/checker.py examples/alloy-structural/fixtures/invalid
python -m unittest discover -s examples/alloy-structural -v
```

The unit tests that only exercise `als_writer.py` and the JSON-parsing seam
in `alloy_runner.py` need no jar at all (they inject a fake process runner).
The `TestLiveAlloyIntegration` class actually shells out to Java and is
skipped, not failed, when no jar is resolvable.

The Python side has zero third-party dependencies; only the backend it
shells out to is external. `test_no_third_party_python_dependencies` asserts
this.

## What owns each fact

Same split as the Mermaid pilot: `model.json` is authored and declares
components, layers, external systems, and the policy matrix. `extractor.py`
walks the given root, parses Python with `ast`, and produces observed edges
with evidence (file, line, import statement, source hash) — nothing here is
inferred from Alloy; Alloy only evaluates what the extractor already found.

`als_writer.py` is the translation layer: every component, external system,
layer, relation type, and observed edge becomes a `one sig` in generated
Alloy source, so each run evaluates exactly one fixed instance — no open
population for the solver to search over, which keeps the per-edge question
below directly comparable to the matrix lookup and the OCL invariant rather
than a bounded search over possibilities.

## Two checks, two different kinds of question

**`NoForbiddenObserved`** asks exactly what the other two pilots ask: does
any one observed edge land on a `forbidden` cell of the policy matrix?

```alloy
assert NoForbiddenObserved {
  all e: Edge | permitted[e.relType, e.src.layer, e.dst.layer]
}
check NoForbiddenObserved for 0
```

When it fails, Alloy's counterexample names the exact violating `Edge` atom
via a skolem binding (`$NoForbiddenObserved_e` -> `E0$0`), which
`alloy_runner.witness_atoms` maps straight back to that edge's evidence — no
separate search for "which edge" is needed; Alloy already names it.

**`NoTransitiveApiToDatabase`** asks a question the matrix lookup and the OCL
invariant cannot ask without hand-written graph code: does the authored
policy, read as a directed graph over *layers* rather than components, admit
any multi-hop permitted path from `api` to `database`?

```alloy
fun permitsLayer: Layer -> Layer {
  { a: Layer, b: Layer | some t: RelType | permitted[t, a, b] }
}
assert NoTransitiveApiToDatabase {
  Database not in Api.^permitsLayer
}
check NoTransitiveApiToDatabase for 0
```

`^` is Alloy's transitive-closure operator. This check is evaluated against
the policy matrix alone, independent of which edges were actually observed
in a given fixture — it is a property of the *rule*, not of the *instance*.

## What this pilot found that the others don't

Running this against `model.json` as authored, `NoTransitiveApiToDatabase`
**fails on both fixtures**, including the valid one. This is not a bug in
the checker. `model.json`'s own policy permits `api -> service` and
`service -> database`, which composes into exactly the path the transitive
check is asking about. The per-edge matrix lookup (and the OCL invariant)
never see this, because neither composes relations across edges — each
evaluates one edge against one cell, and an `api -> database` edge never
occurs in the valid fixture to flag.

This is the empirical, not hypothetical, version of the comparison the
broader modeling-language evaluation is after: a relational language with a
transitive-closure operator can cheaply state a property ("no indirect path
between these two layers") that a flat permitted/forbidden matrix encodes
one hop at a time and can silently fail to enforce across hops. Whether
`model.json`'s declared constraint `C1` ("api may not reach persistence
directly") was ever meant to rule out the indirect, layered path is a
modeling decision for whoever owns the policy, not something this checker
should decide — but the fact that Alloy can even *pose* the question
distinguishes it from the two existing pilots, which structurally cannot.

Exit code reflects this: both fixtures currently exit `1` with status
`policy-transitive-path` (valid) or `violations` (invalid, which also trips
the direct check). Treating the transitive finding as blocking by default is
a choice this pilot makes explicitly, documented here rather than left
implicit — a project adopting this approach should decide deliberately
whether transitive reachability between two layers is something its own
architecture intends to forbid.

## Coverage and next step

Same scope boundaries as `examples/mermaid`: file-granularity components,
static imports only, no runtime calls, dynamic imports, re-exports, or
cross-service traffic. `coverage.unresolved_imports` and
`coverage.unmodeled_python_files` report the same inspection gaps the
sibling pilot reports, under the same `incomplete`-is-never-a-pass
discipline (though `incomplete` here only takes effect when neither of the
two blocking statuses above already applies).

Not implemented in this v1, unlike `examples/mermaid`: base-revision
evaluation and policy-retirement detection (the "a change that edits the
model is judged against the rules that existed before it" discipline from
`spec-mermaid-structural.md`). Porting that discipline here — evaluating
both Alloy checks against a base-revision `model.json` pulled from `HEAD` —
is the natural next extension, not a redesign.

A further extension worth trying deliberately, since it's the other half of
what a relational solver is for: loosen `Component` and `Edge` from `one
sig` to an unscoped population (`check ... for 5` or similar) and ask
whether the *declared* components and policy, independent of any specific
observed codebase, admit an architecture that violates the boundary at all
— i.e. use Alloy to search, not just to evaluate one fixed instance. This
pilot deliberately does not do that yet, to keep its primary check
comparable to the other two pilots' per-instance semantics.

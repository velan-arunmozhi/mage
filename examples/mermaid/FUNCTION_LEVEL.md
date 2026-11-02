# Function-level structural modeling (extends the mermaid/matrix pilot)

This extends the existing file-level pilot (`extractor.py` / `model_loader.py`
/ `policy_evaluator.py` / `checker.py`) one level down to functions and
classes, and generalizes extraction beyond Python via SCIP (preferred) or a
tree-sitter fallback. It reuses the existing matrix-validation machinery
rather than duplicating it; see each module's docstring for the specific
seam it hooks into.

## What's new

| File | Purpose |
|---|---|
| `function_extractor.py` | AST-based Python extractor for function/class components, `CONTAINS` edges, and `CALLS` edges. Conservative: only resolves a call when syntax makes the target unambiguous (`self.method()`, a same-file name, or a name/module traced through an import); everything else goes to `unresolved_calls`, never a guessed edge. |
| `function_checker.py` | Overlays extracted function/class components onto the declared model and runs every `CALLS`/`CONTAINS` edge through the *existing* `policy_evaluator.is_aligned`. |
| `signature_rules.py` | Minimal deterministic rule evaluator for `model.json["function_rules"]` (parameter count/type, return type, "must call an approved target"). Reports `pass` / `fail` / `insufficient-information` -- never treats missing evidence as a verdict. |
| `scip_loader.py` | Converts a parsed SCIP index into the same component/edge shape, for any language with a SCIP indexer (`scip-python`, `scip-typescript`, `scip-java`, `scip-go`, ...). Protobuf bindings are an optional, lazily-imported dependency. |
| `treesitter_fallback.py` | Name-based `CALLS`/import extraction for languages without a SCIP indexer. All output is tagged `claim_status: "observed-heuristic"`, distinct from the `"observed"` used everywhere else. `tree_sitter_languages` is an optional, lazily-imported dependency. |

## Schema additions (backward compatible)

- A component may omit `"layer"` if it declares `"parent": "<existing component id>"` instead; `model_loader.load_model` walks the parent chain to require it terminate at a layer-bearing component (cycle-checked). Every pre-existing model keeps declaring `"layer"` directly and is unaffected.
- A component may declare `"kind"` (`"function"` / `"class"`; absent means a file/module, as before).
- `model.json` may declare `"function_rules"`: a list of structured signature rules (see `signature_rules.py`'s docstring for the shape).
- The `policy.matrix` may add a `"CALLS"` block alongside `"IMPORTS"` (already a declared, unused `relation_types` entry before this change) -- see `model.json` for the `orders.*` example.

## Running it

```bash
cd examples/mermaid
python function_checker.py fixtures/valid       # function-level report for the valid fixture
python function_checker.py fixtures/invalid     # flags orders.api.submit_order -> orders.db.save_order as a violation
python -m unittest discover -p "test_*.py" -v   # all tests, including the pre-existing file-level suite
```

## Configuring SCIP for another language

1. Install and run the language's indexer to produce a `.scip` file, e.g. `scip-python index .`, `scip-typescript index`, `scip-java index`, `scip-go index`.
2. Generate `scip_pb2.py` once (not committed, kept optional):
   ```bash
   curl -O https://raw.githubusercontent.com/sourcegraph/scip/main/scip.proto
   protoc --python_out=. scip.proto
   ```
3. `scip_loader.load_scip_index("index.scip")`, then `scip_loader.convert_index(index, file_component_by_relative_path)` where the mapping is the same `{relative_path: component_dict}` shape `model.json` already declares for Python.

Not every indexer exposes identical features (e.g. enclosing-range precision varies); `convert_index` only trusts what's present and puts a reference in `unresolved` rather than guessing when a call's enclosing function can't be determined.

## Verified against a real TypeScript repository (not just mocks)

`scip_loader.py` and `treesitter_fallback.py` were run end-to-end against a
real, standalone 4-file TypeScript fixture repo (controller/service/
repository/utils, a class with cross-method calls, aliased imports, an
external-library call, a dynamic/ambiguous call, and one intentional
layering violation), indexed with the real `scip-typescript` CLI (not a
fabricated `.scip` file) and read back with real generated `scip_pb2.py`
protobuf bindings. This is not committed to the repo (both the fixture repo
and the generated bindings are regenerable scratch artifacts per the setup
steps above), but it found and fixed three real bugs the mock-only tests had
missed -- regression tests for all three now live in
`test_scip_and_treesitter.py`:

1. **`SymbolInformation.kind` is unreliable.** A real `scip-typescript` index
   leaves `kind` at `0` (Unspecified) for every symbol. The original
   classifier keyed on `kind` and so misclassified every real definition.
   Fixed by classifying from the symbol string's descriptor suffix instead
   (`().` for a function/method, `#` for a class/interface) -- which SCIP's
   spec actually guarantees, unlike `kind`.
2. **Methods were parented to the file, not their class.** The code that
   located a method's enclosing class stripped the wrong suffix and never
   matched. Fixed in `_enclosing_class_symbol`.
3. **A reference was not necessarily a call.** SCIP has no "this occurrence
   is a call expression" role -- a function passed by name (`{ get: handler
   }`) produces the same kind of Reference occurrence as an actual call
   (`handler()`). The original code treated every resolved reference inside
   a function body as a `CALLS` edge, which silently fabricated an edge for
   the by-value case. Fixed by requiring `source_by_path` and confirming the
   character immediately after the occurrence is `(` before counting it as
   a call; without source text, the reference is reported `unresolved`
   (reason `call_site_unconfirmed_no_source`), never assumed.

Against that real repository, after the fixes: 13 functions, 2 classes
(`UserRecord`, `UserService`), 15 `CONTAINS` edges, and 9 `CALLS` edges were
extracted correctly (cross-file, same-file, and class-method calls all
resolved to the right definition); 18 references were correctly excluded
from `CALLS` and landed in `unresolved` (TypeScript/DOM stdlib calls, the
lodash external-library call, and the one dynamic-dispatch call through a
local variable). Running the real extracted `CALLS` edges through
`policy_evaluator.is_aligned` against a Controller→Service→Repository policy
flagged exactly the one intentional controller→repository violation and
flagged none of the valid calls.

`treesitter_fallback.py` was separately run against the same four files and
correctly extracted call-site names and import module names, all tagged
`observed-heuristic`; it also picked up `String(...)` and the dynamic
`handler(...)` call as bare names (expected -- it has no type resolution,
which is exactly why its output is never tagged `observed`).

## Known limitations

- Python call resolution does not model real lexical scoping (closures, comprehension scopes) or inheritance (`super()`, inherited methods looked up on a base class are not resolved) -- these are left unresolved rather than guessed.
- `scip_loader.convert_index` requires `source_by_path` to safely exclude by-value references from `CALLS`. Without it, every potentially-a-call reference is reported `unresolved` rather than risking a false edge -- correct, but less useful; always pass source text in real usage.
- `treesitter_fallback.py`'s name-based call matching has no concept of builtins/globals -- `String(...)` shows up as a call-site name like any other identifier. Resolving it is left to the caller's name→component mapping (a global like `String` simply won't match any declared component and is correctly dropped by `resolve_heuristic_calls`).
- Function-level `"permitted"` verdicts do not require an exact per-call entry in `model.json["relations"]` the way file-level `IMPORTS` edges do (see `function_checker._normalize_fine_grained_verdict`): enumerating every sanctioned call pair isn't tractable, so the matrix cell alone is treated as authoritative at function granularity. This is a deliberate, documented relaxation of the file-level convention, not an oversight.
- SCIP indexers other than `scip-typescript` (Java, Go) were not exercised in this verification pass -- `scip-python`/`scip-java`/`scip-go` emit the same `.scip` protobuf format, so `convert_index` should apply unchanged, but that is an inference from the spec, not something separately confirmed here.

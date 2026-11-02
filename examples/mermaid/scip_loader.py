"""SCIP (Sourcegraph Code Intelligence Protocol) adapter.

Converts a parsed SCIP index into the same ``components``/edges shape every
other extractor in this pilot produces, so ``model_loader.py``,
``policy_evaluator.is_aligned``, and ``function_checker.py`` work unchanged
regardless of which language produced the index. This is the generalization
path for languages with a mature SCIP indexer (``scip-python``,
``scip-typescript``, ``scip-java``, ``scip-go``, ...): run the indexer once to
produce a ``.scip`` file, then call ``load_scip_index`` / ``convert_index``.

Why SCIP over hand-rolled per-language parsing: SCIP indexers do real,
compiler-grade symbol resolution (type-aware), not name matching, so edges
built from it carry ``claim_status: "observed"`` -- the same confidence level
as this repo's own ``ast``-based Python extraction, not the lower
"observed-heuristic" level ``treesitter_fallback.py`` has to use.

Dependency note: reading an actual ``.scip`` file needs the compiled
protobuf bindings for ``scip.proto`` (see
https://github.com/sourcegraph/scip/blob/main/scip.proto), which this module
does NOT require at import time -- only ``load_scip_index`` imports it, and
only when actually reading a file. ``convert_index`` itself works against any
object exposing the small subset of the SCIP message shape used below (see
the fake objects in ``test_scip_loader.py``), so the conversion logic is
fully unit-testable without that dependency installed, and without any
network access or an installed indexer.
"""
import re
from typing import Dict, List, Optional


# SCIP symbol_roles is a bitflag; role 0x1 marks a Definition occurrence.
# See the `SymbolRole` enum in scip.proto.
DEFINITION_ROLE = 0x1

# A real scip-typescript index (verified against v0.3.x) leaves every
# SymbolInformation.kind at 0 (Unspecified) -- it is not a reliable signal in
# practice, despite being the field this module originally classified on.
# What IS reliable is the symbol *string* itself: SCIP mandates a descriptor
# syntax (https://github.com/sourcegraph/scip/blob/main/scip.proto,
# "descriptor" comment) where a method/function descriptor always ends in
# "().", a type/class descriptor always ends in "#", and a parameter
# descriptor is a function descriptor followed by "(name)". Classifying on
# that suffix works regardless of whether an indexer bothers to set `kind`.
_PARAMETER_SUFFIX = re.compile(r"\(\)\.\([^)]*\)$")


def _classify_symbol(symbol: str) -> str:
    """Return "function", "class", or "other" from the symbol's descriptor
    suffix alone (see module note above for why `kind` is not trusted)."""
    if _PARAMETER_SUFFIX.search(symbol):
        return "other"
    if symbol.endswith("()."):
        return "function"
    if symbol.endswith("#"):
        return "class"
    return "other"


def _symbol_name(symbol: str) -> str:
    last_segment = symbol.rsplit("/", 1)[-1]
    last_segment = re.sub(r"\(\)\.$", "", last_segment)  # strip function suffix
    last_segment = last_segment.rstrip("#")               # strip class suffix
    if "#" in last_segment:
        last_segment = last_segment.rsplit("#", 1)[-1]     # Class#method -> method
    return last_segment


def _enclosing_class_symbol(symbol: str, kind: str) -> Optional[str]:
    """For a function/method symbol, return the class symbol it is nested
    under (e.g. "...UserService#lookup()." -> "...UserService#"), or None
    for a top-level function.

    Stripping only the "()." function suffix leaves "...UserService#lookup"
    -- the method's *own* name is still attached, so a naive
    ``.endswith("#")`` check on that never matches and every method was
    wrongly parented to the file instead of its class. The class prefix is
    everything up to and including the *last* "#" still present once the
    function suffix is gone.
    """
    if kind != "function" or not symbol.endswith("()."):
        return None
    without_suffix = symbol[: -len("().")]
    if "#" not in without_suffix:
        return None
    class_part, _method_name = without_suffix.rsplit("#", 1)
    return class_part + "#"


def load_scip_index(path):
    """Read a ``.scip`` file via the compiled protobuf bindings.

    Raises ImportError with actionable setup steps when the bindings are not
    installed -- this keeps them an optional dependency, not a mandatory one,
    for pilots that never touch SCIP.
    """
    try:
        import scip_pb2  # type: ignore
    except ImportError as error:
        raise ImportError(
            "Reading a .scip file requires generated protobuf bindings for "
            "scip.proto, which are not installed. Generate them with:\n"
            "  curl -O https://raw.githubusercontent.com/sourcegraph/scip/main/scip.proto\n"
            "  protoc --python_out=. scip.proto\n"
            "then place the resulting scip_pb2.py on the Python path. "
            "Produce the .scip file itself with a language indexer, e.g.:\n"
            "  scip-python index .          # Python\n"
            "  scip-typescript index        # TypeScript/JavaScript\n"
            "  scip-java index              # Java (via a build tool plugin)\n"
            "  scip-go index                # Go"
        ) from error
    index = scip_pb2.Index()
    with open(path, "rb") as handle:
        index.ParseFromString(handle.read())
    return index


def _line_span(r) -> "tuple[int, int]":
    """A SCIP range is either [start_line, start_char, end_char] (single
    line -- confirmed this is what a real scip-typescript index emits for
    most reference occurrences) or [start_line, start_char, end_line,
    end_char]. Reading index -2 as "end line" is only correct for the
    4-element form; a naive version of this function misread a 3-element
    range's start_char as its end line, which would silently corrupt
    containment checks for a single-line enclosing range (e.g. a one-line
    arrow function body) -- handle both lengths explicitly instead.
    """
    if len(r) <= 3:
        return r[0], r[0]
    return r[0], r[2]


def _range_contains(outer, inner) -> bool:
    """Whether the (line-only) span of ``inner`` falls within ``outer``'s.
    Column precision is not needed here: this is used to attribute a call
    occurrence to its enclosing function definition, and this repo's other
    extractors also only key anchors on line number, not column.
    """
    if not outer or not inner:
        return False
    o_start, o_end = _line_span(outer)
    i_start, _i_end = _line_span(inner)
    return o_start <= i_start <= o_end


def _symbol_to_id(file_component_id: str, symbol: str) -> str:
    # SCIP symbols are globally unique and already encode package/descriptor
    # path; just make them filesystem/identifier-friendly and namespace them
    # under the owning file component for consistency with the ast-based
    # extractors' "<file_id>.<name>" convention.
    cleaned = symbol.replace(" ", "_").replace("`", "")
    return f"{file_component_id}::{cleaned}"


def _is_confirmed_call_site(source_lines, range_) -> Optional[bool]:
    """Whether the character immediately after ``range_`` (skipping
    whitespace) is "(" -- i.e. this occurrence is the callee of an actual
    call expression, not merely a reference to the symbol's name.

    This check exists because a real scip-typescript index was found (via
    end-to-end testing against an actual repository, not a mock) to emit an
    identical Reference occurrence, with identical symbol_roles, for BOTH
    `handler()` (an actual call) and `{ key: handler }` (passing the same
    function by value, never invoked). SCIP's `SymbolRole` bitflags do not
    distinguish these -- there is no "this is a call" role -- so without
    this source-text check, every such reference was wrongly turned into a
    CALLS edge. Returns None (cannot confirm) when ``source_lines`` is
    unavailable, rather than guessing.
    """
    if source_lines is None:
        return None
    end_line, end_char = (range_[0], range_[-1]) if len(range_) == 3 else (range_[-2], range_[-1])
    if end_line < 0 or end_line >= len(source_lines):
        return None
    line = source_lines[end_line]
    rest = line[end_char:].lstrip()
    return rest.startswith("(")


def convert_index(index, file_component_by_relative_path: Dict[str, dict],
                   source_by_path: Optional[Dict[str, str]] = None):
    """Convert a (real or fake) SCIP ``Index`` into model fragments.

    ``file_component_by_relative_path`` maps each document's relative path
    (as declared in ``model.json``) to its already-declared file component,
    the same contract ``extractor.build_mod_to_comp`` establishes for the
    ast-based path -- SCIP tells us about symbols *within* a file; which file
    is a declared component, and what layer it lives in, stays the model
    author's decision, not something inferred from the index.

    ``source_by_path`` (relative_path -> full source text) lets a reference
    be confirmed as an actual call site rather than a bare name reference --
    see ``_is_confirmed_call_site``. Passing it is strongly recommended: a
    real scip-typescript index (verified end-to-end) was found to produce
    false "calls" without this check. When omitted, a reference that
    resolves to a known function is reported as unresolved rather than
    assumed to be a call, since neither outcome can be confirmed.

    Returns (function_components, class_components, contains_edges,
    calls_edges, unresolved_references).
    """
    source_lines_by_path: Dict[str, Optional[List[str]]] = {}
    if source_by_path:
        source_lines_by_path = {path: text.splitlines() for path, text in source_by_path.items()}
    function_components: List[dict] = []
    class_components: List[dict] = []
    contains_edges: List[dict] = []
    calls_edges: List[dict] = []
    unresolved: List[dict] = []

    for document in index.documents:
        file_comp = file_component_by_relative_path.get(document.relative_path)
        if file_comp is None:
            continue  # out of scope: not a declared component
        file_id = file_comp["id"]

        # definitions: classified from the symbol string itself (see
        # _classify_symbol) -- SymbolInformation.kind is not used, since a
        # real scip-typescript index leaves it at 0/Unspecified.
        definitions = {}  # symbol -> (component_dict, enclosing_range)
        def_occurrences = [o for o in document.occurrences if o.symbol_roles & DEFINITION_ROLE]
        class_symbol_to_id = {}  # populated below, used to parent methods to their class

        # Pass A: classes first, so a method's enclosing-class lookup (pass B)
        # can resolve regardless of occurrence order in the index.
        for occ in def_occurrences:
            if _classify_symbol(occ.symbol) != "class":
                continue
            comp_id = _symbol_to_id(file_id, occ.symbol)
            comp = {
                "id": comp_id, "kind": "class", "parent": file_id,
                "name": _symbol_name(occ.symbol), "path": document.relative_path, "symbol": occ.symbol,
            }
            class_components.append(comp)
            class_symbol_to_id[occ.symbol] = comp_id
            contains_edges.append({
                "from": file_id, "to": comp_id, "type": "CONTAINS",
                "claim_status": "observed", "evidence": {"path": document.relative_path, "symbol": occ.symbol},
            })
            definitions[occ.symbol] = (comp, list(getattr(occ, "enclosing_range", [])))

        # Pass B: functions/methods, parented to their class when the
        # symbol's descriptor shows it is nested under one (see
        # _enclosing_class_symbol), else to the file.
        for occ in def_occurrences:
            kind = _classify_symbol(occ.symbol)
            if kind != "function":
                continue
            comp_id = _symbol_to_id(file_id, occ.symbol)
            class_symbol = _enclosing_class_symbol(occ.symbol, kind)
            parent_id = class_symbol_to_id.get(class_symbol, file_id)
            comp = {
                "id": comp_id, "kind": "function", "parent": parent_id,
                "name": _symbol_name(occ.symbol), "path": document.relative_path, "symbol": occ.symbol,
            }
            function_components.append(comp)
            contains_edges.append({
                "from": parent_id, "to": comp_id, "type": "CONTAINS",
                "claim_status": "observed", "evidence": {"path": document.relative_path, "symbol": occ.symbol},
            })
            definitions[occ.symbol] = (comp, list(getattr(occ, "enclosing_range", [])))

        # references: find the enclosing definition (the caller), resolve
        # the referenced symbol (the callee) only if it is itself a known
        # function definition (anywhere already converted, not just in this
        # document) -- cross-file calls resolve because SCIP symbols are
        # globally unique, so the same symbol string appearing as a
        # definition in another document is the correct callee.
        source_lines = source_lines_by_path.get(document.relative_path)
        ref_occurrences = [o for o in document.occurrences if not (o.symbol_roles & DEFINITION_ROLE)]
        for occ in ref_occurrences:
            occ_range = list(getattr(occ, "range", []) or [])
            caller_comp = None
            for comp, enclosing_range in definitions.values():
                if comp["kind"] == "function" and _range_contains(enclosing_range, occ_range):
                    caller_comp = comp
            if caller_comp is None:
                continue  # reference outside any known function body: not a call we can attribute

            is_call = _is_confirmed_call_site(source_lines, occ_range)
            if is_call is False:
                continue  # confirmed NOT a call (e.g. the symbol passed by name/value) -- exclude entirely

            target_symbol = occ.symbol
            target_comp = _global_function_lookup(target_symbol, function_components)
            if target_comp is None or is_call is None:
                # Either the target isn't a known function, or we could not
                # confirm this occurrence is actually a call (no source
                # text supplied) -- either way, do not fabricate a CALLS
                # edge; surface it for review instead.
                unresolved.append({
                    "from": caller_comp["id"], "symbol": target_symbol,
                    "evidence": {"path": document.relative_path},
                    "reason": "unresolved_target" if target_comp is None else "call_site_unconfirmed_no_source",
                })
                continue
            calls_edges.append({
                "from": caller_comp["id"], "to": target_comp["id"], "type": "CALLS",
                "claim_status": "observed", "evidence": {"path": document.relative_path, "symbol": target_symbol},
            })

    contains_edges.sort(key=lambda e: (e["from"], e["to"]))
    calls_edges.sort(key=lambda e: (e["from"], e["to"]))
    return function_components, class_components, contains_edges, calls_edges, unresolved


def _global_function_lookup(symbol: str, function_components: List[dict]):
    for comp in function_components:
        if comp.get("symbol") == symbol:
            return comp
    return None

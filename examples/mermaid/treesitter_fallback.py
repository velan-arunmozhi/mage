"""tree-sitter fallback extractor for languages with no SCIP indexer available.

Used only when ``scip_loader`` has no indexer to call for a language. Unlike
SCIP's compiler-grade resolution, this does bare name matching against
``call_expression``/``import`` queries (the same style of query used by
tools like memd/treeloom), so it WILL miss overloads, shadowed names, and
dynamic dispatch, and it CAN match the wrong same-named symbol across files.
Every edge this module produces is therefore tagged
``claim_status: "observed-heuristic"`` -- never ``"observed"`` -- so
downstream consumers (and a human reading a report) can tell confirmed,
compiler-resolved edges apart from a plausible guess.

``tree_sitter`` + the per-language grammar packages are optional dependencies
and are imported lazily, only inside the functions that need them, so
pilots/tests that never touch a non-Python language do not need them
installed.
"""
from typing import Dict, List

# One tree-sitter query pair per language. Kept as plain strings (not
# compiled) until a language is actually requested, matching the "no
# mandatory heavyweight dependency when the feature is unused" requirement.
CALL_QUERIES = {
    "javascript": "(call_expression function: (identifier) @callee) @call",
    "typescript": "(call_expression function: (identifier) @callee) @call",
    "go": "(call_expression function: (identifier) @callee) @call",
}

IMPORT_QUERIES = {
    "javascript": '(import_statement source: (string) @source)',
    "typescript": '(import_statement source: (string) @source)',
    "go": "(import_spec path: (interpreted_string_literal) @import)",
}


class TreeSitterUnavailable(Exception):
    pass


def _load_parser(language: str):
    try:
        from tree_sitter_languages import get_parser  # type: ignore
    except ImportError as error:
        raise TreeSitterUnavailable(
            f"tree-sitter fallback for '{language}' requires the optional "
            "'tree_sitter_languages' package (pip install tree_sitter_languages). "
            "It is not installed, and this pilot does not require it unless "
            "this fallback path is actually used."
        ) from error
    try:
        return get_parser(language)
    except Exception as error:  # unsupported language name, missing grammar, etc.
        raise TreeSitterUnavailable(f"No tree-sitter grammar available for '{language}'") from error


def _load_language(language: str):
    # Verified against a real install: tree_sitter_languages.get_parser()'s
    # returned Parser has no ".language" attribute on the tree_sitter version
    # paired with tree_sitter_languages (an earlier assumption that it did
    # would raise AttributeError on first real use) -- the Language object
    # needed to build a Query must be fetched separately.
    from tree_sitter_languages import get_language  # type: ignore
    return get_language(language)


def is_available(language: str) -> bool:
    try:
        _load_parser(language)
        return True
    except TreeSitterUnavailable:
        return False


def extract_calls_heuristic(source_bytes: bytes, language: str, file_id: str, path: str) -> List[dict]:
    """Return a list of heuristic edges: ``{"from": file_id, "callee_name":
    str, "line": int, "claim_status": "observed-heuristic"}``.

    Deliberately returns bare callee *names*, not resolved component ids --
    resolving a name-only match to a specific declared component is exactly
    the ambiguity this fallback cannot remove, so that step is left to the
    caller, who has the model's component list and can decide how
    conservative to be about accepting a name match.
    """
    if language not in CALL_QUERIES:
        raise TreeSitterUnavailable(f"No call query defined for language '{language}'")
    parser = _load_parser(language)
    tree = parser.parse(source_bytes)
    query = _load_language(language).query(CALL_QUERIES[language])
    results = []
    for node, capture_name in query.captures(tree.root_node):
        if capture_name != "callee":
            continue
        results.append({
            "from": file_id,
            "callee_name": source_bytes[node.start_byte:node.end_byte].decode("utf-8", "replace"),
            "line": node.start_point[0] + 1,
            "path": path,
            "claim_status": "observed-heuristic",
        })
    return results


def extract_imports_heuristic(source_bytes: bytes, language: str, file_id: str, path: str) -> List[dict]:
    if language not in IMPORT_QUERIES:
        raise TreeSitterUnavailable(f"No import query defined for language '{language}'")
    parser = _load_parser(language)
    tree = parser.parse(source_bytes)
    query = _load_language(language).query(IMPORT_QUERIES[language])
    results = []
    for node, _capture_name in query.captures(tree.root_node):
        text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", "replace").strip("\"'")
        results.append({
            "from": file_id,
            "module": text,
            "line": node.start_point[0] + 1,
            "path": path,
            "claim_status": "observed-heuristic",
        })
    return results


def resolve_heuristic_calls(calls: List[dict], name_to_component_ids: Dict[str, List[str]]) -> List[dict]:
    """Turn ``callee_name`` edges into ``to``-targeted edges only when the
    name matches exactly one declared component; anything with zero or more
    than one candidate is omitted here (never guessed), by design.
    """
    resolved = []
    for call in calls:
        candidates = name_to_component_ids.get(call["callee_name"], [])
        if len(candidates) != 1:
            continue
        resolved.append({
            "from": call["from"],
            "to": candidates[0],
            "type": "CALLS",
            "claim_status": "observed-heuristic",
            "evidence": {"path": call["path"], "line": call["line"]},
        })
    return resolved

"""One anchor contract shared by every structural node, plus ID aliasing.

Two different extractors currently mint function and class components, and
before this module they produced different node shapes:

- ``function_extractor.py`` (Python ``ast``) recorded ``path`` and ``lineno``
  but no source hash and no symbol, while the ``CONTAINS``/``CALLS`` edges it
  emitted alongside them carried a full ``{path, line, symbol, sha256}``
  anchor.
- ``scip_loader.py`` (any SCIP-indexed language) recorded ``path`` and the
  SCIP ``symbol`` but no line number and no source hash.

So a node could not be verified the same way regardless of where it came
from, and no node carried the source hash that freshness checking depends
on. ``../../.agents/skills/structural/SKILL.md`` asks for the same evidence on
every entity: repository-relative path, symbol or configuration key, and the
relevant source hash.

This module defines that one shape and the rules for reading it.

## The anchor

``path``, ``symbol``, and ``sha256`` are required. ``lineno``, ``end_lineno``,
and ``col_offset`` are positional detail: present when the extractor knows
them, omitted when it does not, never invented.

An anchor that is missing a required field is not silently dropped. It is
recorded with ``status: "incomplete"`` and the ``missing`` list that explains
why, following this example's existing habit of reporting
``call_site_unconfirmed_no_source`` rather than assuming. A consumer can then
decide whether the gap matters; it cannot mistake absence for completeness.

``make_anchor`` is the only supported way to build one, so ``status`` can
never disagree with the fields actually present.

## Aliases

Component IDs here are positional: ``function_extractor`` mints
``f"{parent_id}.{node.name}"``. Renaming a function, or moving a method to a
different class, therefore produces a *different node* rather than the same
node under a new name, and any behavioral or provenance record pointing at
the old ID silently stops resolving.

A component may declare ``aliases``: previously-used IDs that refer to this
same entity. The structural skill requires identity continuity to be
*established* rather than guessed, so nothing here infers a rename. An alias
is an authored claim; this module only enforces that the claim is
unambiguous -- one alias may not name two components, and an alias may not
collide with a live component ID.
"""

REQUIRED_FIELDS = ("path", "symbol", "sha256")
POSITION_FIELDS = ("lineno", "end_lineno", "col_offset")

STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"


class AnchorError(ValueError):
    """An anchor is malformed, or claims a completeness it does not have."""


def make_anchor(path=None, symbol=None, sha256=None,
                lineno=None, end_lineno=None, col_offset=None):
    """Build an anchor, labelling it complete only when it really is.

    Position fields are omitted entirely when unknown rather than stored as
    ``None``, so a reader never has to distinguish "absent" from "null".
    """
    anchor = {"path": path, "symbol": symbol, "sha256": sha256}
    for field, value in (("lineno", lineno), ("end_lineno", end_lineno),
                         ("col_offset", col_offset)):
        if value is not None:
            anchor[field] = value
    missing = [field for field in REQUIRED_FIELDS if not anchor.get(field)]
    if missing:
        anchor["status"] = STATUS_INCOMPLETE
        anchor["missing"] = missing
    else:
        anchor["status"] = STATUS_COMPLETE
    return anchor


def anchor_issues(anchor):
    """Return the reasons ``anchor`` is unusable, or ``[]`` when it is sound.

    Checks shape and internal consistency only. It cannot establish that the
    hash matches the file on disk today; that is a freshness question for the
    caller holding the working tree.
    """
    if not isinstance(anchor, dict):
        return ["anchor must be an object"]
    issues = []
    missing = [field for field in REQUIRED_FIELDS if not anchor.get(field)]
    status = anchor.get("status")
    if status not in (STATUS_COMPLETE, STATUS_INCOMPLETE):
        issues.append(f"unknown anchor status: {status!r}")
    if status == STATUS_COMPLETE and missing:
        # The case this check exists for: a hand-edited anchor asserting
        # completeness it does not have would otherwise pass every later
        # check that trusts the label instead of the fields.
        issues.append("status is complete but missing " + ", ".join(missing))
    if status == STATUS_INCOMPLETE:
        declared = anchor.get("missing")
        if not isinstance(declared, list) or sorted(declared) != sorted(missing):
            issues.append("missing list does not match the absent fields")
    for field in POSITION_FIELDS:
        if field in anchor and not isinstance(anchor[field], int):
            issues.append(f"{field} must be an integer line or column")
    if "lineno" in anchor and "end_lineno" in anchor:
        if anchor["end_lineno"] < anchor["lineno"]:
            issues.append("end_lineno precedes lineno")
    return issues


def is_complete(anchor):
    return isinstance(anchor, dict) and anchor.get("status") == STATUS_COMPLETE


def build_alias_index(model):
    """Map every declared alias to the canonical component ID it stands for.

    Raises ``AnchorError`` when an alias is ambiguous, because resolving it
    either way would silently attach evidence to the wrong entity.
    """
    live_ids = {item.get("id") for item in model.get("components", [])}
    live_ids |= {item.get("id") for item in model.get("external_systems", [])}
    index = {}
    for item in list(model.get("components", [])) + list(model.get("external_systems", [])):
        aliases = item.get("aliases")
        if aliases is None:
            continue
        if not isinstance(aliases, list):
            raise AnchorError(f"{item.get('id')}: aliases must be a list")
        for alias in aliases:
            if not isinstance(alias, str) or not alias:
                raise AnchorError(f"{item.get('id')}: alias must be a nonempty string")
            if alias in live_ids:
                raise AnchorError(
                    f"alias {alias!r} on {item.get('id')!r} collides with a live component ID"
                )
            if alias in index and index[alias] != item.get("id"):
                raise AnchorError(
                    f"alias {alias!r} names both {index[alias]!r} and {item.get('id')!r}"
                )
            index[alias] = item.get("id")
    return index


def resolve_id(identifier, live_ids, alias_index):
    """Resolve a live ID or a declared alias to its canonical component ID.

    Returns ``None`` when the identifier is neither, so a caller reports an
    unresolved reference rather than inventing a component.
    """
    if identifier in live_ids:
        return identifier
    return alias_index.get(identifier)

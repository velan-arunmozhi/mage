from pathlib import Path
import json
import hashlib

from node_anchor import AnchorError, anchor_issues, build_alias_index, resolve_id

FINE_GRAINED_KINDS = ("function", "class")


class ModelValidationError(Exception):
    pass


def load_model(model_path):
    model_path = Path(model_path)
    if not model_path.exists():
        raise ModelValidationError()
    data = json.loads(model_path.read_text())
    if data.get("schema_version") != 1:
        raise ModelValidationError()
    policy = data.get("policy", {})
    layers = set(policy.get("layers", []))
    relation_types = set(policy.get("relation_types", []))
    components = data.get("components", [])
    comp_ids = []
    for item in components:
        if not item.get("id"):
            raise ModelValidationError()
        # A component declares its layer directly (every pre-existing model
        # does this), or it may instead declare a "parent" and inherit the
        # layer transitively -- this is how function/class components, which
        # have no layer of their own, attach to the file component that does.
        if "layer" in item and item["layer"] is not None:
            if item["layer"] not in layers:
                raise ModelValidationError()
        elif not item.get("parent"):
            raise ModelValidationError()
        # A function or class node must carry the shared anchor. File and
        # module components predate it and are left alone, so every model
        # written before function-level extraction still loads unchanged.
        if item.get("kind") in FINE_GRAINED_KINDS:
            if "anchor" not in item:
                raise ModelValidationError()
            if anchor_issues(item["anchor"]):
                raise ModelValidationError()
        comp_ids.append(item["id"])
    if len(comp_ids) != len(set(comp_ids)):
        raise ModelValidationError()
    comp_by_id = {item["id"]: item for item in components}
    for item in components:
        if "layer" in item and item["layer"] is not None:
            continue
        # Walk the parent chain and require it to terminate at a
        # layer-bearing component, with a cycle guard.
        seen = set()
        cursor = item
        while True:
            parent_id = cursor.get("parent")
            if parent_id is None or parent_id not in comp_by_id:
                raise ModelValidationError()
            if parent_id in seen:
                raise ModelValidationError()
            seen.add(parent_id)
            cursor = comp_by_id[parent_id]
            if cursor.get("layer"):
                break
    ext_systems = data.get("external_systems", [])
    ext_ids = []
    for item in ext_systems:
        if not item.get("id"):
            raise ModelValidationError()
        if item.get("layer") and item["layer"] not in layers:
            raise ModelValidationError()
        ext_ids.append(item["id"])
    if len(ext_ids) != len(set(ext_ids)):
        raise ModelValidationError()
    all_ids = set(comp_ids) | set(ext_ids)
    # Aliases let a relation keep resolving after a rename. build_alias_index
    # rejects an ambiguous one rather than picking a side.
    try:
        alias_index = build_alias_index(data)
    except AnchorError:
        raise ModelValidationError()
    relations = data.get("relations", [])
    for item in relations:
        if item.get("type") not in relation_types:
            raise ModelValidationError()
        if resolve_id(item.get("from"), all_ids, alias_index) is None:
            raise ModelValidationError()
        if resolve_id(item.get("to"), all_ids, alias_index) is None:
            raise ModelValidationError()
    matrix = policy.get("matrix", {})
    for rel_type, layer_map in matrix.items():
        if rel_type not in relation_types:
            raise ModelValidationError()
        for from_layer, to_map in layer_map.items():
            if from_layer not in layers:
                raise ModelValidationError()
            for to_layer, cell in to_map.items():
                if to_layer not in layers:
                    raise ModelValidationError()
                if cell not in ("permitted", "forbidden", "unspecified"):
                    raise ModelValidationError()
    constraints = data.get("constraints", [])
    for item in constraints:
        if not item.get("id") or not item.get("text"):
            raise ModelValidationError()
    return data


def canonicalize_model(model):
    m = json.loads(json.dumps(model))
    # Alias order is not meaningful, so sort it before hashing; otherwise two
    # models declaring the same renames in a different order would produce
    # different canonical hashes and read as drift.
    for item in list(m.get("components", [])) + list(m.get("external_systems", [])):
        if isinstance(item.get("aliases"), list):
            item["aliases"] = sorted(item["aliases"])
    if "components" in m:
        m["components"].sort(key=lambda c: c["id"])
    if "external_systems" in m:
        m["external_systems"].sort(key=lambda e: e["id"])
    if "relations" in m:
        m["relations"].sort(key=lambda r: (r.get("from", ""), r.get("type", ""), r.get("to", "")))
    if "constraints" in m:
        m["constraints"].sort(key=lambda c: c["id"])
    return json.dumps(m, sort_keys=True, separators=(",", ":"))


def model_hash(model):
    return hashlib.sha256(canonicalize_model(model).encode("utf-8")).hexdigest()

"""Policy evaluator - aligned predicate."""

from node_anchor import AnchorError, build_alias_index


def _alias_index(model):
    """Alias map for this model, empty when the overlay is malformed.

    ``is_aligned`` is called on overlays assembled outside
    ``model_loader.load_model`` (``function_checker`` builds one), so an
    ambiguous alias must not raise here. An empty index degrades to
    exact-ID matching, which is the pre-alias behavior.
    """
    try:
        return build_alias_index(model)
    except AnchorError:
        return {}


def _resolve_layer(comp_id, components, _seen=None):
    """Resolve a component's effective layer, walking "parent" when the
    component has none of its own (e.g. a function/class component that
    inherits its layer from the file/module that contains it).

    Returns None, rather than raising, when the chain is missing or cyclic;
    callers already treat a missing layer as "unresolved", not an error --
    this keeps that behavior for malformed overlays built outside
    ``model_loader.load_model`` (which otherwise guarantees termination).
    """
    _seen = _seen or set()
    comp = components.get(comp_id)
    if comp is None or comp_id in _seen:
        return None
    layer = comp.get("layer")
    if layer:
        return layer
    parent_id = comp.get("parent")
    if not parent_id:
        return None
    return _resolve_layer(parent_id, components, _seen | {comp_id})


def is_aligned(observed_edge: dict, model: dict) -> tuple:
    """
    Determine alignment of observed edge.
    Returns (verdict, reason, extra_info)
    verdict in ('permitted', 'forbidden', 'unresolved', 'undeclared')
    """
    from_id = observed_edge["from"]
    to_id = observed_edge["to"]
    rel_type = observed_edge["type"]
    
    components = {c["id"]: c for c in model.get("components", [])}
    ext_systems = {e["id"]: e for e in model.get("external_systems", [])}
    
    if from_id not in components:
        # An edge we cannot attribute to a declared component is an inspection gap, not a verdict.
        return ("unresolved", "unknown_source", {"from": from_id})
    from_comp = components[from_id]
    from_layer = _resolve_layer(from_id, components)
    
    to_comp = components.get(to_id)
    to_layer = None
    if to_comp:
        to_layer = _resolve_layer(to_id, components)
    elif to_id in ext_systems:
        ext = ext_systems[to_id]
        to_layer = ext.get("layer")
    else:
        return ("unresolved", "unknown_target", {"to": to_id})
    
    policy = model.get("policy", {})
    layers = set(policy.get("layers", []))
    rel_types = set(policy.get("relation_types", []))
    
    if rel_type not in rel_types:
        return ("unresolved", "unknown_relation_type", {"type": rel_type})
    if from_layer not in layers or to_layer not in layers:
        return ("unresolved", "unknown_layer", {"from_layer": from_layer, "to_layer": to_layer})
    
    matrix = policy.get("matrix", {})
    rel_matrix = matrix.get(rel_type, {})
    from_cell = rel_matrix.get(from_layer, {})
    cell = from_cell.get(to_layer, "unspecified")
    
    if cell == "unspecified":
        return ("unresolved", "unspecified", {"cell": cell})
    elif cell == "forbidden":
        return ("forbidden", "forbidden_by_policy", {"cell": cell})
    elif cell == "permitted":
        # Check if sanctioned in relations. A relation may name either
        # endpoint by a declared alias, so a sanctioned edge authored before
        # a rename keeps matching the renamed component instead of silently
        # becoming undeclared.
        aliases = _alias_index(model)
        sanctioned = False
        for rel in model.get("relations", []):
            rel_from = aliases.get(rel["from"], rel["from"])
            rel_to = aliases.get(rel["to"], rel["to"])
            if rel_from == from_id and rel_to == to_id and rel["type"] == rel_type:
                sanctioned = True
                break
        if sanctioned:
            return ("permitted", "permitted_and_sanctioned", {"cell": cell})
        else:
            return ("undeclared", "permitted_but_undeclared", {"cell": cell})
    return ("unresolved", "unknown_cell", {"cell": cell})

"""Policy evaluator - aligned predicate."""


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
    from_layer = from_comp.get("layer")
    
    to_comp = components.get(to_id)
    to_layer = None
    if to_comp:
        to_layer = to_comp.get("layer")
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
        # Check if sanctioned in relations
        sanctioned = False
        for rel in model.get("relations", []):
            if rel["from"] == from_id and rel["to"] == to_id and rel["type"] == rel_type:
                sanctioned = True
                break
        if sanctioned:
            return ("permitted", "permitted_and_sanctioned", {"cell": cell})
        else:
            return ("undeclared", "permitted_but_undeclared", {"cell": cell})
    return ("unresolved", "unknown_cell", {"cell": cell})

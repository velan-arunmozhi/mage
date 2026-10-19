"""Model document loader and canonical hashing.

Mirrored byte-for-byte from ``examples/mermaid/model_loader.py``. Both pilots
author the same model document shape (components, external systems, a
layer x relation-type policy matrix); only the constraint-checking backend
differs. Sharing the loader format, not the code, keeps each example
self-contained while keeping the two directly comparable.
"""
from pathlib import Path
import json
import hashlib


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
        if item["layer"] not in layers:
            raise ModelValidationError()
        comp_ids.append(item["id"])
    if len(comp_ids) != len(set(comp_ids)):
        raise ModelValidationError()
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
    relations = data.get("relations", [])
    for item in relations:
        if item.get("type") not in relation_types:
            raise ModelValidationError()
        if item.get("from") not in all_ids:
            raise ModelValidationError()
        if item.get("to") not in all_ids:
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

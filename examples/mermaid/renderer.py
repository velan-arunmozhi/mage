from model_loader import model_hash
import re


def id_to_class_name(comp_id: str) -> str:
    name = re.sub(r'[^A-Za-z0-9_-]', '_', comp_id)
    return name


def render(model: dict) -> str:
    lines = []
    mhash = model_hash(model)
    lines.append(f"%% generated-from: {mhash}")
    lines.append("classDiagram")
    components = sorted(model.get("components", []), key=lambda c: c["id"])
    for comp in components:
        cls = id_to_class_name(comp["id"])
        lines.append(f"  class {cls} {{")
        lines.append("  }")
    relations = sorted(model.get("relations", []), key=lambda r: (r["from"], r["type"], r["to"]))
    for rel in relations:
        from_cls = id_to_class_name(rel["from"])
        to_cls = id_to_class_name(rel["to"])
        rel_type = rel["type"]
        lines.append(f"  {from_cls} --> {to_cls} : {rel_type}")
    return "\n".join(lines) + "\n"

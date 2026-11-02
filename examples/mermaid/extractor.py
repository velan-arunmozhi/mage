"""Extractor for observed edges from Python source."""
import ast
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple


def build_mod_to_comp(components: List[dict]) -> Dict[str, dict]:
    """Map an importable module name (and bare filename) to its declared component.

    Factored out so other extractors (e.g. ``function_extractor.py``) resolve
    ``from <module> import <name>`` the same way this module resolves
    ``import <module>`` / ``from <module> import ...`` edges, instead of
    duplicating the matching rule.
    """
    mod_to_comp = {}
    for item in components:
        mod_to_comp[Path(item["path"]).with_suffix("").name] = item
        # also allow direct match by basename
        mod_to_comp[Path(item["path"]).name] = item
    return mod_to_comp


def extract(root: Path, model: dict) -> Tuple[List[dict], List[dict], List[dict], List[str]]:
    """Extract edges, sources, unresolved, unmodeled."""
    root = root.resolve()
    components = model.get("components", [])
    ext_systems = model.get("external_systems", [])

    edges = []
    sources = []
    unresolved = []

    mod_to_comp = build_mod_to_comp(components)

    for item in components:
        source_path = root / item["path"]
        if not source_path.exists():
            raise FileNotFoundError(f"Missing source: {source_path}")
        content = source_path.read_bytes()
        source_hash = hashlib.sha256(content).hexdigest()
        sources.append({
            **item,
            "claim_status": "declared_component_and_layer",
            "sha256": source_hash,
        })
        tree = ast.parse(content, filename=item["path"])
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # handles level properly but we only care about top-level module names in this context
                modules = [node.module] if node.module else []
            else:
                continue
            for module in modules:
                anchor = {
                    "path": item["path"],
                    "line": node.lineno,
                    "symbol": ast.unparse(node) if hasattr(ast, "unparse") else repr(node),
                    "sha256": source_hash,
                }
                # check if matches component
                matched = False
                for k, comp in mod_to_comp.items():
                    if module == k or module == Path(comp["path"]).with_suffix("").name:
                        edges.append({
                            "from": item["id"],
                            "to": comp["id"],
                            "type": "IMPORTS",
                            "claim_status": "observed",
                            "evidence": anchor,
                        })
                        matched = True
                        break
                if not matched:
                    unresolved.append({
                        "from": item["id"],
                        "module": module,
                        "evidence": anchor,
                    })
    
    edges.sort(key=lambda e: (e["from"], e["evidence"]["line"], e["to"]))
    
    declared_paths = {item["path"] for item in components}
    unmodeled = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*.py")
        if p.relative_to(root).as_posix() not in declared_paths
    )
    
    return edges, sources, unresolved, unmodeled

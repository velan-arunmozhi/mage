"""Function-level structural extraction for Python source.

Extends the file-level extraction in ``extractor.py`` one level down: it
represents classes and functions as components (``kind: "class"`` /
``kind: "function"``), connects them to their enclosing file via ``CONTAINS``
edges, and connects callers to callees via ``CALLS`` edges.

Design choice: resolve conservatively. A ``CALLS`` edge is only produced when
the call target can be identified from syntax alone, with no name-shadowing
ambiguity:

  - ``self.method()`` / ``cls.method()`` inside a class body, resolved against
    that class's own methods.
  - a bare ``name()`` call resolved against a function defined at module level
    in the *same* file, or against a name brought in by
    ``from <module> import name`` where ``<module>`` resolves to a declared
    component (the same module-resolution rule ``extractor.py`` already uses
    for IMPORTS, reused via ``build_mod_to_comp``).
  - ``module.name()`` resolved against a plain ``import module`` the same way.

Anything else -- calls through an unknown object, calls through a local
variable, builtins, dynamic dispatch -- is recorded in ``unresolved_calls``
instead of being guessed at. An edge that cannot be justified by syntax is
omitted, never invented.
"""
import ast
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple

from extractor import build_mod_to_comp
from node_anchor import make_anchor


def _annotation_to_str(node):
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _params_of(fn: ast.AST) -> List[dict]:
    args = fn.args
    params = []
    all_args = (
        list(getattr(args, "posonlyargs", []))
        + list(args.args)
        + ([args.vararg] if args.vararg else [])
        + list(args.kwonlyargs)
        + ([args.kwarg] if args.kwarg else [])
    )
    for a in all_args:
        if a is None:
            continue
        params.append({"name": a.arg, "annotation": _annotation_to_str(a.annotation)})
    return params


class _DefinitionCollector(ast.NodeVisitor):
    """Pass 1: discover classes/functions and build CONTAINS edges.

    Tracks a qualname + component-id stack so nested defs (methods, nested
    functions) get a parent that is itself a function/class component, not
    the file.
    """

    def __init__(self, file_id: str, path: str, source_hash: str):
        self.file_id = file_id
        self.path = path
        self.source_hash = source_hash
        self.classes: Dict[str, dict] = {}       # class_id -> component dict
        self.functions: Dict[str, dict] = {}      # function_id -> component dict
        self.contains_edges: List[dict] = []
        self.toplevel_funcs: Dict[str, str] = {}  # name -> function_id (module scope only)
        self.toplevel_classes: Dict[str, str] = {}  # name -> class_id (module scope only)
        self.methods_by_class: Dict[str, Dict[str, str]] = {}  # class_id -> {name: function_id}
        self.duplicate_ids: List[dict] = []
        self._stack = [(file_id, 0)]  # (parent_component_id, depth); depth 0 == module scope
        self._qual_stack: List[str] = []  # names only, for the anchor symbol

    def _anchor(self, node):
        return {"path": self.path, "line": node.lineno, "sha256": self.source_hash}

    def _node_anchor(self, node, name):
        """The shared node contract, with the symbol qualified within its file.

        ``symbol`` is the dotted path from module scope, so it stays readable
        and stays stable under a file rename -- the file component's ``path``
        already carries where the file lives.
        """
        return make_anchor(
            path=self.path,
            symbol=".".join(self._qual_stack + [name]),
            sha256=self.source_hash,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", None),
            col_offset=getattr(node, "col_offset", None),
        )

    def _claim_id(self, component_id, node, name):
        """Record a collision instead of letting the later definition win.

        ``f"{parent_id}.{name}"`` is not unique: a ``@property`` and its
        setter, or two definitions under different branches of an ``if``,
        produce the same ID. Silently overwriting the first would drop a real
        definition and attach its evidence to the wrong body.
        """
        if component_id in self.classes or component_id in self.functions:
            self.duplicate_ids.append({
                "id": component_id,
                "path": self.path,
                "line": node.lineno,
                "name": name,
            })
            return False
        return True

    def visit_ClassDef(self, node: ast.ClassDef):
        parent_id, depth = self._stack[-1]
        class_id = f"{parent_id}.{node.name}"
        if self._claim_id(class_id, node, node.name):
            self.classes[class_id] = {
                "id": class_id,
                "kind": "class",
                "parent": parent_id,
                "name": node.name,
                "path": self.path,
                "lineno": node.lineno,
                "anchor": self._node_anchor(node, node.name),
            }
            self.contains_edges.append({
                "from": parent_id,
                "to": class_id,
                "type": "CONTAINS",
                "claim_status": "observed",
                "evidence": self._anchor(node),
            })
            if depth == 0:
                self.toplevel_classes[node.name] = class_id
            self.methods_by_class.setdefault(class_id, {})
        self._stack.append((class_id, depth + 1))
        self._qual_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self._qual_stack.pop()
        self._stack.pop()

    def _visit_function(self, node):
        parent_id, depth = self._stack[-1]
        fn_id = f"{parent_id}.{node.name}"
        is_method = parent_id in self.classes
        if self._claim_id(fn_id, node, node.name):
            self.functions[fn_id] = {
                "id": fn_id,
                "kind": "function",
                "parent": parent_id,
                "name": node.name,
                "path": self.path,
                "lineno": node.lineno,
                "params": _params_of(node),
                "returns": _annotation_to_str(node.returns),
                "is_method": is_method,
                "anchor": self._node_anchor(node, node.name),
            }
            self.contains_edges.append({
                "from": parent_id,
                "to": fn_id,
                "type": "CONTAINS",
                "claim_status": "observed",
                "evidence": self._anchor(node),
            })
            if depth == 0:
                self.toplevel_funcs[node.name] = fn_id
            if is_method:
                self.methods_by_class[parent_id][node.name] = fn_id
        self._stack.append((fn_id, depth + 1))
        self._qual_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self._qual_stack.pop()
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._visit_function(node)


class _CallCollector(ast.NodeVisitor):
    """Pass 2: walk call sites, tracking the enclosing function/class, and
    resolve each call against the registries pass 1 built (for this file and,
    via ``import_map``/``other_files``, across files).
    """

    def __init__(self, file_id, path, source_hash, defs: _DefinitionCollector,
                 import_map: Dict[str, Tuple[str, str]], all_files: Dict[str, _DefinitionCollector]):
        self.file_id = file_id
        self.path = path
        self.source_hash = source_hash
        self.defs = defs
        self.import_map = import_map  # local_name -> (target_file_id, original_name)
        self.all_files = all_files
        self.calls_edges: List[dict] = []
        self.unresolved_calls: List[dict] = []
        self._fn_stack: List[str] = []   # enclosing function ids
        self._class_stack: List[str] = []  # enclosing class ids

    def _anchor(self, node):
        try:
            symbol = ast.unparse(node)
        except Exception:
            symbol = None
        return {"path": self.path, "line": node.lineno, "symbol": symbol, "sha256": self.source_hash}

    def _record(self, node, callee_id):
        caller_id = self._fn_stack[-1] if self._fn_stack else self.file_id
        if callee_id is None:
            self.unresolved_calls.append({
                "from": caller_id,
                "call": self._describe(node.func),
                "evidence": self._anchor(node),
            })
            return
        self.calls_edges.append({
            "from": caller_id,
            "to": callee_id,
            "type": "CALLS",
            "claim_status": "observed",
            "evidence": self._anchor(node),
        })

    @staticmethod
    def _describe(func_node):
        try:
            return ast.unparse(func_node)
        except Exception:
            return repr(func_node)

    def _resolve(self, func_node) -> "str | None":
        # self.method() / cls.method()
        if (isinstance(func_node, ast.Attribute)
                and isinstance(func_node.value, ast.Name)
                and func_node.value.id in ("self", "cls")
                and self._class_stack):
            class_id = self._class_stack[-1]
            return self.defs.methods_by_class.get(class_id, {}).get(func_node.attr)

        # module.name() where "module" was imported with a plain `import module`
        # and that module resolves to another declared component.
        if isinstance(func_node, ast.Attribute) and isinstance(func_node.value, ast.Name):
            target = self.import_map.get(func_node.value.id)
            if target:
                target_file_id, _ = target
                target_defs = self.all_files.get(target_file_id)
                if target_defs:
                    return target_defs.toplevel_funcs.get(func_node.attr)
            return None

        # bare name()
        if isinstance(func_node, ast.Name):
            name = func_node.id
            if name in self.defs.toplevel_funcs:
                return self.defs.toplevel_funcs[name]
            if name in self.import_map:
                target_file_id, original_name = self.import_map[name]
                target_defs = self.all_files.get(target_file_id)
                if target_defs:
                    return target_defs.toplevel_funcs.get(original_name)
            return None

        return None

    def visit_ClassDef(self, node: ast.ClassDef):
        parent_id = self._fn_stack[-1] if self._fn_stack else self.file_id
        class_id = f"{parent_id}.{node.name}"
        self._class_stack.append(class_id)
        self.generic_visit(node)
        self._class_stack.pop()

    def _visit_function(self, node):
        parent_id = self._fn_stack[-1] if self._fn_stack else (
            self._class_stack[-1] if self._class_stack else self.file_id
        )
        fn_id = f"{parent_id}.{node.name}"
        self._fn_stack.append(fn_id)
        self.generic_visit(node)
        self._fn_stack.pop()

    def visit_FunctionDef(self, node):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_function(node)

    def visit_Call(self, node: ast.Call):
        callee_id = self._resolve(node.func)
        self._record(node, callee_id)
        self.generic_visit(node)


def _build_import_map(tree: ast.AST, mod_to_comp: Dict[str, dict]) -> Dict[str, Tuple[str, str]]:
    """local_name -> (target_component_id, original_name_in_target)."""
    import_map: Dict[str, Tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                comp = mod_to_comp.get(alias.name)
                if comp:
                    local = alias.asname or alias.name
                    import_map[local] = (comp["id"], None)
        elif isinstance(node, ast.ImportFrom):
            comp = mod_to_comp.get(node.module) if node.module else None
            if comp:
                for alias in node.names:
                    local = alias.asname or alias.name
                    import_map[local] = (comp["id"], alias.name)
    return import_map


def extract_functions(root: Path, model: dict) -> Tuple[List[dict], List[dict], List[dict], List[dict], List[dict]]:
    """Extract function-level structure.

    Returns (function_components, class_components, contains_edges,
    calls_edges, unresolved_calls).

    Kept at this arity because five call sites unpack it positionally. Use
    ``extract_structure`` when you also need the colliding IDs it reports.
    """
    result = extract_structure(root, model)
    return (result["functions"], result["classes"], result["contains_edges"],
            result["calls_edges"], result["unresolved_calls"])


def extract_structure(root: Path, model: dict) -> dict:
    """Extract function-level structure, including collision reporting.

    Every function and class component carries an ``anchor`` built by
    ``node_anchor.make_anchor``, so a node extracted here and a node loaded
    from a SCIP index can be verified the same way.

    ``duplicate_ids`` lists definitions whose generated ID was already taken.
    They are dropped rather than overwriting the earlier definition, and
    reported so the caller can treat the coverage gap as a gap.
    """
    root = root.resolve()
    components = model.get("components", [])
    mod_to_comp = build_mod_to_comp(components)

    trees: Dict[str, ast.AST] = {}
    hashes: Dict[str, str] = {}
    defs_by_file: Dict[str, _DefinitionCollector] = {}
    import_maps: Dict[str, Dict[str, Tuple[str, str]]] = {}

    # Pass 1: parse + collect definitions for every declared file component.
    for item in components:
        source_path = root / item["path"]
        if not source_path.exists():
            raise FileNotFoundError(f"Missing source: {source_path}")
        content = source_path.read_bytes()
        source_hash = hashlib.sha256(content).hexdigest()
        tree = ast.parse(content, filename=item["path"])
        trees[item["id"]] = tree
        hashes[item["id"]] = source_hash
        collector = _DefinitionCollector(item["id"], item["path"], source_hash)
        collector.visit(tree)
        defs_by_file[item["id"]] = collector
        import_maps[item["id"]] = _build_import_map(tree, mod_to_comp)

    # Pass 2: resolve calls now that every file's definitions are known.
    all_calls: List[dict] = []
    all_unresolved: List[dict] = []
    for item in components:
        file_id = item["id"]
        caller = _CallCollector(
            file_id, item["path"], hashes[file_id], defs_by_file[file_id],
            import_maps[file_id], defs_by_file,
        )
        caller.visit(trees[file_id])
        all_calls.extend(caller.calls_edges)
        all_unresolved.extend(caller.unresolved_calls)

    function_components: List[dict] = []
    class_components: List[dict] = []
    contains_edges: List[dict] = []
    duplicate_ids: List[dict] = []
    for file_id, collector in defs_by_file.items():
        class_components.extend(collector.classes.values())
        function_components.extend(collector.functions.values())
        contains_edges.extend(collector.contains_edges)
        duplicate_ids.extend(collector.duplicate_ids)

    function_components.sort(key=lambda c: c["id"])
    class_components.sort(key=lambda c: c["id"])
    contains_edges.sort(key=lambda e: (e["from"], e["evidence"]["line"], e["to"]))
    all_calls.sort(key=lambda e: (e["from"], e["evidence"]["line"], e["to"]))
    all_unresolved.sort(key=lambda e: (e["from"], e["evidence"]["line"]))
    duplicate_ids.sort(key=lambda d: (d["path"], d["line"], d["id"]))

    return {
        "functions": function_components,
        "classes": class_components,
        "contains_edges": contains_edges,
        "calls_edges": all_calls,
        "unresolved_calls": all_unresolved,
        "duplicate_ids": duplicate_ids,
    }

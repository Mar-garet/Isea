import os
import ast
import json
from typing import List, Dict
from tqdm import tqdm
from pathlib import Path
import sys
from utils.paths import walk_source_tree

sys.path.append(str(Path(__file__).resolve().parent.parent))
# Increase recursion limit to handle deep ASTs in complex files
sys.setrecursionlimit(10000)


def try_parse_with_2to3(src: str):
    tree = None
    try:
        from lib2to3.refactor import RefactoringTool, get_fixers_from_package

        fixer_tool = RefactoringTool(get_fixers_from_package("lib2to3.fixes"))
        fixed = str(fixer_tool.refactor_string(src, "<2to3>"))
        tree = ast.parse(fixed)
    except Exception:
        pass
    return tree


# 全局项目根，用于解析同级目录的导入
project_root = None
project_root_name = None


def add_parents(tree: ast.AST):
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child.parent = parent


class SimpleClassVisitor(ast.NodeVisitor):
    """
    简化版 ClassVisitor，保留原有功能并加入同级目录类全限定名解析：
      - name
      - full_qualified_name
      - parent_class（同级目录或同级文件）
      - methods, constants 等
    """

    def __init__(
        self,
        file_content: str,
        file_path: str,
        class_stack: List[str],
        module_prefix: str,
        import_map: Dict[str, str],
    ):
        self.file_content = file_content
        self.file_path = file_path
        self.class_stack = class_stack.copy()
        self.module_prefix = module_prefix
        self.package_prefix = module_prefix.rsplit(".", 1)[0]
        self.import_map = import_map
        self.classes: List[Dict] = []

    def resolve_parent(self, base: ast.expr) -> str:
        # 只处理简单 Name
        if isinstance(base, ast.Name):
            name = base.id
            # 优先用 import_map，否则同级
            return self.import_map.get(name, f"{self.package_prefix}.{name}")
        return ast.unparse(base).strip()

    def visit_ClassDef(self, node: ast.ClassDef):
        self.class_stack.append(node.name)

        # 解析 parent_class
        parent_fqn = None
        if node.bases:
            parent_fqn = self.resolve_parent(node.bases[0])

        # 收集 methods
        func_vis = FunctionVisitor(
            self.file_content, self.file_path, self.class_stack, self.module_prefix
        )
        func_vis.visit(node)
        # 收集 constants
        const_vis = ConstantVisitor(
            self.file_content, self.file_path, self.class_stack, self.module_prefix
        )
        const_vis.visit(node)

        # 本类全限定名
        cls_fqn = ".".join(self.module_prefix.split(".") + self.class_stack)
        self.classes.append(
            {
                "name": node.name,
                "full_qualified_name": cls_fqn,
                "absolute_path": self.file_path,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "content": "\n".join(
                    self.file_content.splitlines()[node.lineno - 1 : node.end_lineno]
                ),
                "class_type": "inner" if len(self.class_stack) > 1 else "normal",
                "parent_class": parent_fqn,
                "methods": func_vis.functions,
                "constants": const_vis.constants,
            }
        )

        self.generic_visit(node)
        self.class_stack.pop()


class ConstantVisitor(ast.NodeVisitor):
    # 保留原实现
    def __init__(
        self,
        file_content: str,
        file_path: str,
        class_stack: List[str],
        module_prefix: str,
    ):
        self.file_content = file_content
        self.file_path = file_path
        self.class_stack = class_stack.copy()
        self.module_prefix = module_prefix
        self.constants = []
        self.current_class = (
            ".".join(self.module_prefix.split(".") + self.class_stack)
            if self.class_stack
            else None
        )

    def visit_Assign(self, node: ast.Assign):
        if not isinstance(node.targets[0], ast.Name):
            return
        in_class_scope = False
        current = node
        while hasattr(current, "parent"):
            if isinstance(current.parent, ast.ClassDef):
                in_class_scope = True
                break
            current = current.parent
        if not self.class_stack and in_class_scope:
            return
        if self.class_stack and not in_class_scope:
            return
        target = node.targets[0]
        try:
            data_type = type(ast.literal_eval(node.value)).__name__
        except Exception:
            data_type = ast.unparse(node.value).strip()
        fqn = ".".join(self.module_prefix.split(".") + self.class_stack + [target.id])
        content = "\n".join(
            self.file_content.splitlines()[node.lineno - 1 : node.end_lineno]
        )
        self.constants.append(
            {
                "name": target.id,
                "full_qualified_name": fqn,
                "absolute_path": self.file_path,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "content": content,
                "modifiers": [],
                "data_type": data_type,
                "class_name": self.current_class,
            }
        )
        self.generic_visit(node)


class FunctionVisitor(ast.NodeVisitor):
    # 保留原实现
    def __init__(
        self,
        file_content: str,
        file_path: str,
        class_stack: List[str],
        module_prefix: str,
    ):
        self.file_content = file_content
        self.file_path = file_path
        self.class_stack = class_stack.copy()
        self.module_prefix = module_prefix
        self.functions = []
        self.current_class = (
            ".".join(self.module_prefix.split(".") + self.class_stack)
            if self.class_stack
            else None
        )
        self.scope_stack = []

    def visit_ClassDef(self, node: ast.ClassDef):
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        is_method = len(self.scope_stack) > 0
        modifiers = [ast.unparse(d).strip() for d in node.decorator_list]
        access = (
            "private"
            if node.name.startswith("__") and not node.name.endswith("__")
            else "public"
        )
        signature = ast.unparse(node.args).replace("\n", " ")
        params = [
            {"name": a.arg, "type": ast.unparse(a.annotation) if a.annotation else None}
            for a in node.args.args
        ]
        fqn = ".".join(self.module_prefix.split(".") + self.class_stack + [node.name])
        self.functions.append(
            {
                "name": node.name,
                "full_qualified_name": fqn,
                "absolute_path": self.file_path,
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "content": "\n".join(
                    self.file_content.splitlines()[node.lineno - 1 : node.end_lineno]
                ),
                "params": params,
                "modifiers": modifiers + [access],
                "signature": f"{'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'} {node.name}({signature})",
                "class_name": self.current_class,
                "type": "constructor" if node.name == "__init__" else "normal",
                "is_class_method": is_method,
            }
        )
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)


# def parse_python_file(
#     file_path: str,
#     module_prefix: str,
#     file_content: str = None
# ):
#     if file_content is None:
#         with open(file_path, encoding="utf-8") as f:
#             file_content = f.read()
#     try:
#         tree = ast.parse(file_content)
#     except SyntaxError:
#         tree = try_parse_with_2to3(file_content)
#         if tree is None:
#             print(f"[Warning] 无法解析，跳过 {file_path}")
#             return [], [], [], file_content.splitlines()
#     add_parents(tree)

#     # 构造 import_map，只处理顶层 from X import Y
#     import_map: Dict[str,str] = {}
#     for node in tree.body:
#         if isinstance(node, ast.ImportFrom) and node.level == 0:
#             pkg = node.module or ""
#             for alias in node.names:
#                 import_map[alias.name] = f"{module_prefix.rsplit('.',1)[0]}.{pkg}.{alias.name}"

#     # 调用 SimpleClassVisitor
#     cls_vis = SimpleClassVisitor(file_content, file_path, [], module_prefix, import_map)
#     cls_vis.visit(tree)

#     # 全局函数和变量保留原逻辑
#     func_vis = FunctionVisitor(file_content, file_path, [], module_prefix)
#     func_vis.visit(tree)
#     independent_funcs = [f for f in func_vis.functions if not f["is_class_method"]]
#     const_vis = ConstantVisitor(file_content, file_path, [], module_prefix)
#     const_vis.visit(tree)

#     return cls_vis.classes, independent_funcs, const_vis.constants, file_content.splitlines()


def parse_python_file(file_path: str, module_prefix: str, file_content: str = None):
    # 读取文件时支持多种编码，避免 UnicodeDecodeError
    if file_content is None:
        try:
            # 尝试以 UTF-8 读取
            with open(file_path, encoding="utf-8") as f:
                file_content = f.read()
        except UnicodeDecodeError:
            # 读取失败时退回到 Latin-1 并替换无法解码的字节
            with open(file_path, encoding="latin-1", errors="replace") as f:
                file_content = f.read()
    try:
        tree = ast.parse(file_content)
    except SyntaxError:
        tree = try_parse_with_2to3(file_content)
        if tree is None:
            print(f"[Warning] 无法解析，跳过 {file_path}")
            return [], [], [], file_content.splitlines()
    add_parents(tree)

    # 构造 import_map，只处理顶层 from X import Y
    import_map: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            pkg = node.module or ""
            for alias in node.names:
                import_map[alias.name] = (
                    f"{module_prefix.rsplit('.', 1)[0]}.{pkg}.{alias.name}"
                )

    try:
        # 调用 SimpleClassVisitor
        cls_vis = SimpleClassVisitor(
            file_content, file_path, [], module_prefix, import_map
        )
        cls_vis.visit(tree)

        # 全局函数和变量保留原逻辑
        func_vis = FunctionVisitor(file_content, file_path, [], module_prefix)
        func_vis.visit(tree)
        independent_funcs = [f for f in func_vis.functions if not f["is_class_method"]]
        const_vis = ConstantVisitor(file_content, file_path, [], module_prefix)
        const_vis.visit(tree)
    except RecursionError:
        print(
            f"[Warning] Recursion limit exceeded while parsing {file_path}. Skipping detailed analysis."
        )
        return [], [], [], file_content.splitlines()
    except Exception as e:
        print(f"[Warning] Error parsing {file_path}: {e}")
        return [], [], [], file_content.splitlines()

    return (
        cls_vis.classes,
        independent_funcs,
        const_vis.constants,
        file_content.splitlines(),
    )


def create_structure(directory_path: str) -> Dict:
    """
    创建代码结构，不再写入 kg.json，直接返回数据结构
    """
    global project_root, project_root_name
    project_root = os.path.abspath(directory_path)
    project_root_name = os.path.basename(project_root)

    structure: Dict = {}
    total_py = sum(
        1
        for root, _, files in walk_source_tree(Path(project_root))
        for fn in files
        if fn.endswith(".py")
    )
    pbar = tqdm(total=total_py, desc="Parsing .py files")

    for root, _, files in walk_source_tree(Path(project_root)):
        rel = os.path.relpath(root, project_root)
        parts = [project_root_name] + (rel.split(os.sep) if rel != "." else [])
        curr = structure
        for p in parts:
            curr = curr.setdefault(p, {})

        for fn in files:
            full = os.path.join(root, fn)
            if fn.endswith(".py"):
                abs_py = Path(full).resolve()

                rel_path = abs_py.relative_to(Path(project_root))

                rel_no_ext = rel_path.with_suffix("")
                mod_pref = ".".join(rel_no_ext.as_posix().lstrip(os.sep).split(os.sep))

                cls, funcs, consts, lines = parse_python_file(full, mod_pref)
                curr[fn] = {
                    "classes": cls,
                    "functions": funcs,
                    "variables": consts,
                    "text": lines,
                }
                pbar.update(1)
            else:
                curr[fn] = None
    pbar.close()
    return structure


if __name__ == "__main__":
    root_dir = "D:\\pyKG\\Test_0404"  # 改成你的项目根目录
    struct = create_structure(root_dir)
    with open(os.path.join(os.getcwd(), "kg.json"), "w", encoding="utf-8") as f:
        json.dump(struct, f, indent=4, ensure_ascii=False)
    print(f"🚀 Successfully constructed the dict for repo directory {root_dir}")

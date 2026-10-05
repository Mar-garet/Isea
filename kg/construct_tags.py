"""Build Python symbol tags by parsing source; never import the target project."""

import ast
from collections import namedtuple
from pathlib import Path

import chardet
from tqdm import tqdm

from kg.utils import create_structure
from utils.paths import python_files

Tag = namedtuple("Tag", "rel_fname fname line name kind category info")


class CodeGraph:
    def __init__(self, root=None, structure=None):
        self.root = str(Path(root or Path.cwd()).resolve())
        self.structure = (
            structure if structure is not None else create_structure(self.root)
        )

    def get_rel_fname(self, fname):
        return str(Path(fname).relative_to(self.root))

    def get_tags(self, fname, rel_fname):
        return list(self.get_tags_raw(fname, rel_fname))

    def get_tags_raw(self, fname, rel_fname):
        raw = Path(fname).read_bytes()
        try:
            code = raw.decode("utf-8")
        except UnicodeDecodeError:
            code = raw.decode(
                chardet.detect(raw).get("encoding") or "latin-1", errors="replace"
            )
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # Python 2 files can still contribute structure via the 2to3 fallback.
            return
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                category = "class" if isinstance(node, ast.ClassDef) else "function"
                yield Tag(
                    rel_fname,
                    str(fname),
                    [node.lineno, node.end_lineno],
                    node.name,
                    "def",
                    category,
                    "",
                )
            if isinstance(node, ast.Call):
                name = self._symbol_name(node.func)
                if name:
                    yield Tag(
                        rel_fname,
                        str(fname),
                        [node.lineno, node.end_lineno],
                        name,
                        "ref",
                        "function",
                        "",
                    )
            elif isinstance(node, ast.ClassDef):
                for base in node.bases:
                    name = self._symbol_name(base)
                    if name:
                        yield Tag(
                            rel_fname,
                            str(fname),
                            [base.lineno, base.end_lineno],
                            name,
                            "ref",
                            "class",
                            "",
                        )

    @staticmethod
    def _symbol_name(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def find_files(self, paths):
        files = []
        for path in paths:
            path = Path(path).resolve()
            if path.is_dir():
                files.extend(str(file) for file in python_files(path))
            elif path.suffix == ".py":
                files.append(str(path))
        return files


def run(dir_name: str, structure=None):
    graph = CodeGraph(root=dir_name, structure=structure)
    tags = []
    for file in tqdm(graph.find_files([graph.root]), desc="Parsing symbol references"):
        tags.extend(graph.get_tags(file, graph.get_rel_fname(file)))
    return graph.structure, tags


if __name__ == "__main__":
    import sys

    run(sys.argv[1])

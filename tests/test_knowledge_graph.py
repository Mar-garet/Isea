import sys

from kg.construct_tags import run
from retriever.ckg_retriever import CKGRetriever
from settings import settings
from tools.fixer_tools import edit_file_by_lineno
from tools.retriever_tools import get_retriever


def test_source_indexing_does_not_import_target_code(isolated_project, monkeypatch):
    marker = isolated_project.parent / "imported"
    (isolated_project / "probe_module.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    (isolated_project / "app.py").write_text(
        "import probe_module\ndef app():\n    return 1\n"
    )
    monkeypatch.syspath_prepend(str(isolated_project))
    run(str(isolated_project))
    assert not marker.exists()
    assert "probe_module" not in sys.modules


def test_async_functions_and_one_line_calls_are_indexed(isolated_project):
    file = isolated_project / "app.py"
    file.write_text(
        "def target(): return 1\n"
        "def caller(): target()\n"
        "async def async_caller(): target()\n"
        "class Worker:\n"
        "    async def run(self): target()\n"
    )
    graph = get_retriever()
    assert graph.search_method_fuzzy("async_caller")[0].signature.startswith(
        "async def"
    )
    for name in ["app.caller", "app.async_caller", "app.Worker.run"]:
        related = graph.get_relevant_entities(str(file), name)
        assert [method["name"] for method in related["CALLS"]] == ["target"]


def test_indexes_refresh_after_tool_edits_external_edits_and_root_changes(
    isolated_project, monkeypatch
):
    file = isolated_project / "app.py"
    file.write_text("def before(): return 1\n")
    first = get_retriever()
    assert first.search_method_fuzzy("before")
    assert edit_file_by_lineno("app.py", "def after(): return 2", 1, 1).startswith(
        "Successfully"
    )
    second = get_retriever()
    assert second is not first and second.search_method_fuzzy("after")
    assert not second.search_method_fuzzy("before")
    file.write_text("async def external_change(): return 123\n")
    assert get_retriever().search_method_fuzzy("external_change")
    other = isolated_project.parent / "other"
    other.mkdir()
    (other / "other.py").write_text("def independent(): pass\n")
    monkeypatch.setattr(settings, "TEST_BED", str(other))
    assert get_retriever().search_method_fuzzy("independent")
    assert not get_retriever().search_method_fuzzy("external_change")


def test_retrievers_are_not_a_process_singleton():
    assert CKGRetriever({}, []) is not CKGRetriever({}, [])


def test_index_excludes_virtualenvs_and_external_symlinks(isolated_project):
    ignored = isolated_project / ".venv"
    ignored.mkdir()
    (ignored / "hidden.py").write_text("def hidden(): pass\n")
    external = isolated_project.parent / "external.py"
    external.write_text("def external(): pass\n")
    (isolated_project / "link.py").symlink_to(external)
    graph = get_retriever()
    assert not graph.search_method_fuzzy("hidden")
    assert not graph.search_method_fuzzy("external")

import json
from pathlib import Path

import pytest

import localizer
import suggester
import fixer
from agents.context import Action, Location, Locations, Suggestion, Suggestions
from settings import settings
from tools.retriever_tools import read_file_lines
from utils.artifacts import project_relative_output


async def test_stage_artifacts_remain_usable_in_three_independent_workspaces(
    isolated_project, tmp_path, monkeypatch
):
    runner = tmp_path / "runner"
    runner.mkdir()
    monkeypatch.chdir(runner)
    first = isolated_project
    (first / "app.py").write_text("value = 1\n")

    class FakeLocalizer:
        async def run(self, instruction, context):
            return Locations(
                locations=[
                    Location(path=str(first / "app.py"), start_line=1, end_line=1)
                ]
            )

    monkeypatch.setattr(localizer, "LocalizerAgent", FakeLocalizer)
    await localizer.AgentOrchestrator().run()
    locations = json.loads(Path("results/locations/unit-test.json").read_text())
    assert locations["locations"][0]["path"] == "app.py"

    second = tmp_path / "stage-two"
    second.mkdir()
    (second / "app.py").write_text("value = 2\n")
    monkeypatch.setattr(settings, "TEST_BED", str(second))

    class FakeSuggester:
        async def run(self, instruction, context):
            assert context.locations.locations[0].path == "app.py"
            assert "value = 2" in read_file_lines(
                context.locations.locations[0].path, 1, 1
            )
            return Suggestions(
                suggestions=[
                    Suggestion(
                        title="repair",
                        actions=[
                            Action(
                                path=str(second / "app.py"),
                                operation="replace",
                                start_line=1,
                                end_line=1,
                                patch_preview="value = 3",
                            )
                        ],
                        tests=["regression test"],
                        risks=["compatibility"],
                        references=["app.py:1"],
                    )
                ]
            )

    monkeypatch.setattr(suggester, "SuggesterAgent", FakeSuggester)
    await suggester.AgentOrchestrator().run()
    suggestions = json.loads(Path("results/suggestions/unit-test.json").read_text())
    assert suggestions["suggestions"][0]["actions"][0]["path"] == "app.py"

    third = tmp_path / "stage-three"
    third.mkdir()
    (third / "app.py").write_text("value = 3\n")
    monkeypatch.setattr(settings, "TEST_BED", str(third))

    class FakeFixer:
        async def run(self, instruction, context):
            action = context.suggestions.suggestions[0].actions[0]
            assert context.locations.locations[0].path == action.path == "app.py"
            assert "value = 3" in read_file_lines(action.path, 1, 1)
            assert context.suggestions.suggestions[0].tests == ["regression test"]
            assert context.suggestions.suggestions[0].risks == ["compatibility"]

    monkeypatch.setattr(fixer, "FixerAgent", FakeFixer)
    orchestrator = fixer.AgentOrchestrator()
    await orchestrator.fixer.run("repair", context=orchestrator.context)


def test_artifact_normalization_rejects_paths_outside_project(isolated_project):
    result = Locations(
        locations=[
            Location(
                path=str(isolated_project.parent / "outside.py"),
                start_line=1,
                end_line=1,
            )
        ]
    )
    with pytest.raises(ValueError, match="stay inside"):
        project_relative_output(result)

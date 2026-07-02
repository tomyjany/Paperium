from paperium.paths import PaperiumPaths


def test_root_and_experiment_paths(tmp_path):
    repo = tmp_path / "repo"
    exp = repo / "questions/q001/experiments/exp001"
    exp.mkdir(parents=True)
    paths = PaperiumPaths(repo)
    assert paths.root_dir == repo / ".paperium"
    assert paths.state_path == repo / ".paperium/state.json"
    assert paths.experiment_analysis_path(exp) == exp / ".paperium/analysis.md"
    assert paths.experiment_fact_check_path(exp) == exp / ".paperium/fact-check.json"


def test_named_artifact_paths(tmp_path):
    repo = tmp_path / "repo"
    paths = PaperiumPaths(repo)

    assert paths.ranking_md_path == repo / ".paperium/ranking.md"
    assert paths.ranking_json_path == repo / ".paperium/ranking.json"
    assert paths.dispositions_path == repo / ".paperium/dispositions.md"
    assert paths.question_focus_path == repo / ".paperium/question-focus.md"
    assert paths.question_focus_json_path == repo / ".paperium/question-focus.json"
    assert paths.worker_dir("worker-001") == repo / ".paperium/workers/worker-001"
    assert (
        paths.context_request_path("request-001")
        == repo / ".paperium/context-requests/request-001.json"
    )
    assert (
        paths.context_decision_path("request-001")
        == repo / ".paperium/context-requests/request-001.decision.json"
    )
    assert paths.section_path("abstract") == repo / ".paperium/sections/abstract.md"
    assert paths.section_review_path("abstract") == repo / ".paperium/sections/abstract.review.json"


def test_v2_paths(tmp_path):
    paths = PaperiumPaths(tmp_path / "repo")
    root = tmp_path / "repo/.paperium"
    assert paths.style_path == root / "style.md"
    assert paths.report_template_path == root / "report-template.md"
    assert paths.report_path == root / "REPORT.md"
    assert paths.report_draft_path == root / "REPORT.draft.md"
    assert paths.section_facts_path("ch1-s1") == root / "sections/ch1-s1.facts.md"
    assert paths.section_prompt_path("ch1-s1", 2) == root / "prompts/ch1-s1.round2.prompt.md"

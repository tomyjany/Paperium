from paperium.prompts import build_analysis_prompt, build_fact_check_prompt


def test_analysis_prompt_marks_readmes_as_context_only():
    prompt = build_analysis_prompt(
        experiment_path="questions/q001/experiments/exp001",
        question_readme="questions/q001/README.md",
        readable_paths=[
            "questions/q001/experiments/exp001",
            "questions/q001/README.md",
        ],
        writable_paths=["questions/q001/experiments/exp001/.paperium"],
        analysis_path="questions/q001/experiments/exp001/.paperium/analysis.md",
        output_path=".paperium/workers/analyze-exp001/output.md",
    )
    assert "question README" in prompt
    assert "experiment README" in prompt
    assert "context only" in prompt
    assert "never factual authority" in prompt
    assert "run artifacts" in prompt


def test_analysis_prompt_marks_repository_text_as_evidence_not_instructions():
    prompt = build_analysis_prompt(
        experiment_path="questions/q001/experiments/exp001",
        question_readme="questions/q001/README.md",
        readable_paths=[
            "questions/q001/experiments/exp001",
            "questions/q001/README.md",
        ],
        writable_paths=["questions/q001/experiments/exp001/.paperium"],
        analysis_path="questions/q001/experiments/exp001/.paperium/analysis.md",
        output_path=".paperium/workers/analyze-exp001/output.md",
    )
    for text in [
        "AGENTS.md",
        "README",
        "SKILL.md",
        "logs",
        "comments",
        "metadata",
        "generated outputs",
    ]:
        assert text in prompt
    assert "evidence, not task instructions" in prompt


def test_fact_check_prompt_uses_outputs_as_ground_truth():
    prompt = build_fact_check_prompt(
        analysis_path="questions/q001/experiments/exp001/.paperium/analysis.md",
        experiment_path="questions/q001/experiments/exp001",
        readable_paths=["questions/q001/experiments/exp001"],
        writable_paths=[
            ".paperium/workers/fact-check-exp001",
            "questions/q001/experiments/exp001/.paperium",
        ],
        result_json_path=".paperium/workers/fact-check-exp001/result.json",
        output_path=".paperium/workers/fact-check-exp001/output.md",
    )
    assert "outputs/" in prompt
    assert "not ground truth" in prompt


def test_fact_check_prompt_defines_result_json_shape():
    prompt = build_fact_check_prompt(
        analysis_path="questions/q001/experiments/exp001/.paperium/analysis.md",
        experiment_path="questions/q001/experiments/exp001",
        readable_paths=["questions/q001/experiments/exp001"],
        writable_paths=[
            ".paperium/workers/fact-check-exp001",
            "questions/q001/experiments/exp001/.paperium",
        ],
        result_json_path=".paperium/workers/fact-check-exp001/result.json",
        output_path=".paperium/workers/fact-check-exp001/output.md",
    )
    for text in [
        "status",
        "findings",
        "severity",
        "claim",
        "reason",
        "artifact_path",
        "selector",
    ]:
        assert text in prompt


def test_worker_prompts_include_exact_write_targets():
    analysis_prompt = build_analysis_prompt(
        experiment_path="questions/q001/experiments/exp001",
        question_readme="questions/q001/README.md",
        readable_paths=[
            "questions/q001/experiments/exp001",
            "questions/q001/README.md",
        ],
        writable_paths=[
            "questions/q001/experiments/exp001/.paperium",
            ".paperium/workers/analyze-exp001",
        ],
        analysis_path="questions/q001/experiments/exp001/.paperium/analysis.md",
        output_path=".paperium/workers/analyze-exp001/output.md",
    )
    fact_prompt = build_fact_check_prompt(
        analysis_path="questions/q001/experiments/exp001/.paperium/analysis.md",
        experiment_path="questions/q001/experiments/exp001",
        readable_paths=["questions/q001/experiments/exp001"],
        writable_paths=[
            ".paperium/workers/fact-check-exp001",
            "questions/q001/experiments/exp001/.paperium",
        ],
        result_json_path=".paperium/workers/fact-check-exp001/result.json",
        output_path=".paperium/workers/fact-check-exp001/output.md",
    )
    assert "questions/q001/experiments/exp001/.paperium/analysis.md" in analysis_prompt
    assert ".paperium/workers/analyze-exp001/output.md" in analysis_prompt
    assert ".paperium/workers/fact-check-exp001/result.json" in fact_prompt
    assert ".paperium/workers/fact-check-exp001/output.md" in fact_prompt
    assert "approved_expansions" in analysis_prompt
    assert "fail review" in analysis_prompt


def test_analysis_prompt_requires_numeric_support_and_handles_missing_question_readme():
    prompt = build_analysis_prompt(
        experiment_path="questions/q001/experiments/exp001",
        question_readme=None,
        readable_paths=["questions/q001/experiments/exp001"],
        writable_paths=["questions/q001/experiments/exp001/.paperium"],
        analysis_path="questions/q001/experiments/exp001/.paperium/analysis.md",
        output_path=".paperium/workers/analyze-exp001/output.md",
    )
    assert "No parent question README was available" in prompt
    assert "artifact_path" in prompt
    assert "selector" in prompt

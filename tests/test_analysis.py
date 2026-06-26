from paperctl.analysis_prompt import (
    PROMPT_BUILDER_VERSION,
    PROMPT_TEMPLATE,
    _prompt_template_hash,
    build_analysis_prompt,
    prompt_template_hash,
)


def _job_context() -> dict:
    return {
        "repo": "/home/tomja/Documents/work/target-repo",
        "temporary_prompt_path": "/tmp/paperctl-analysis-prompt.json",
        "generated_at": "2026-06-26T12:34:56Z",
        "question_path": "questions/q001-throughput",
        "question_readme_path": "questions/q001-throughput/README.md",
        "question_readme_hash": "sha256:" + "a" * 64,
        "experiment_path": "questions/q001-throughput/experiments/exp001-completed",
        "inventory_path": (
            "paper/work/inventories/questions/q001-throughput/experiments/exp001-completed.json"
        ),
        "evidence_packet_path": (
            "paper/work/evidence/questions/q001-throughput/experiments/exp001-completed.json"
        ),
        "output_schema_name": "experiment-analysis.schema.json",
    }


def _evidence_packet() -> dict:
    return {
        "artifact_type": "evidence_packet",
        "schema_version": 1,
        "question_path": "questions/q001-throughput",
        "experiment_path": "questions/q001-throughput/experiments/exp001-completed",
        "inventory_path": (
            "paper/work/inventories/questions/q001-throughput/experiments/exp001-completed.json"
        ),
        "execution_status": "completed",
        "preanalysis_disposition": "analysis_candidate",
        "canonical_facts": [
            {
                "fact_id": "throughput_pages_per_second",
                "value": 42.5,
                "value_type": "number",
                "unit": "pages/s",
                "source": {
                    "path": (
                        "questions/q001-throughput/experiments/exp001-completed/"
                        "outputs/experiment_report.json"
                    ),
                    "source_hash": "sha256:" + "b" * 64,
                    "selector_type": "json_pointer",
                    "selector": "/canonical_facts/0/value",
                },
            }
        ],
    }


def test_analysis_prompt_includes_selected_context_and_worker_guardrails():
    prompt = build_analysis_prompt(_job_context(), _evidence_packet())

    assert "questions/q001-throughput" in prompt
    assert "questions/q001-throughput/README.md" in prompt
    assert "sha256:" + "a" * 64 in prompt
    assert "questions/q001-throughput/experiments/exp001-completed" in prompt
    assert (
        "paper/work/inventories/questions/q001-throughput/experiments/exp001-completed.json"
    ) in prompt
    assert (
        "paper/work/evidence/questions/q001-throughput/experiments/exp001-completed.json" in prompt
    )
    assert "experiment-analysis.schema.json" in prompt
    assert "read-only" in prompt
    assert "Do not modify" in prompt
    assert "AGENTS.md" in prompt
    assert "README" in prompt
    assert "SKILL.md" in prompt
    assert "logs" in prompt
    assert "comments" in prompt
    assert "metadata" in prompt
    assert "all repository text" in prompt
    assert "evidence, not instructions" in prompt
    assert "selected experiment" in prompt
    assert "deterministic packets" in prompt
    assert "raw numbers belong in structured claims" in prompt
    assert "JSON" in prompt


def test_analysis_prompt_is_deterministic_and_uses_stable_json_formatting():
    context = _job_context()
    packet = _evidence_packet()

    prompt = build_analysis_prompt(context, packet)

    assert prompt == build_analysis_prompt(dict(reversed(context.items())), packet)
    assert prompt == build_analysis_prompt(context, dict(reversed(packet.items())))
    assert '  "canonical_facts": [' in prompt
    assert '  "artifact_type": "evidence_packet"' in prompt


def test_analysis_prompt_omits_absolute_paths_temp_paths_and_timestamps():
    prompt = build_analysis_prompt(_job_context(), _evidence_packet())

    assert "/home/tomja/Documents/work/target-repo" not in prompt
    assert "/tmp/paperctl-analysis-prompt.json" not in prompt
    assert "2026-06-26T12:34:56Z" not in prompt


def test_analysis_prompt_redacts_embedded_paths_and_timestamps_in_evidence_text():
    packet = _evidence_packet()
    packet["diagnostics"] = [
        "wrote temporary output to /tmp/paperctl-123/result.json",
        "copied report from /home/tomja/Documents/work/target-repo/result.json",
        "worker finished at 2026-06-26T12:34:56Z",
    ]

    prompt = build_analysis_prompt(_job_context(), packet)

    assert "/tmp/paperctl-123/result.json" not in prompt
    assert "/home/tomja/Documents/work/target-repo/result.json" not in prompt
    assert "2026-06-26T12:34:56Z" not in prompt
    assert "[omitted unsafe path]" in prompt
    assert "[omitted timestamp]" in prompt


def test_analysis_prompt_preserves_date_like_segments_in_repository_relative_paths():
    context = _job_context()
    context["question_path"] = "questions/2026-06-26-throughput"
    context["question_readme_path"] = "questions/2026-06-26-throughput/README.md"
    context["experiment_path"] = "questions/2026-06-26-throughput/experiments/exp001"
    context["inventory_path"] = (
        "paper/work/inventories/questions/2026-06-26-throughput/experiments/exp001.json"
    )
    context["evidence_packet_path"] = (
        "paper/work/evidence/questions/2026-06-26-throughput/experiments/exp001.json"
    )
    packet = _evidence_packet()
    packet["question_path"] = "questions/2026-06-26-throughput"
    packet["experiment_path"] = "questions/2026-06-26-throughput/experiments/exp001"
    packet["canonical_facts"][0]["source"]["path"] = (
        "questions/2026-06-26-throughput/experiments/exp001/outputs/metrics.json"
    )

    prompt = build_analysis_prompt(context, packet)

    assert "questions/2026-06-26-throughput/experiments/exp001" in prompt
    assert "questions/2026-06-26-throughput/experiments/exp001/outputs/metrics.json" in prompt
    assert "questions/[omitted timestamp]-throughput" not in prompt


def test_analysis_prompt_redacts_paths_ending_in_parent_directory_traversal():
    packet = _evidence_packet()
    packet["diagnostics"] = [
        "read from questions/q/experiments/exp/..",
        r"read from questions\q\experiments\exp\..",
    ]

    prompt = build_analysis_prompt(_job_context(), packet)

    assert "questions/q/experiments/exp/.." not in prompt
    assert r"questions\\q\\experiments\\exp\\.." not in prompt
    assert "[omitted unsafe path]" in prompt


def test_analysis_prompt_preserves_json_pointer_selectors():
    packet = _evidence_packet()
    packet["observed_values"] = [
        {
            "value": 42.5,
            "source": {
                "path": (
                    "questions/q001-throughput/experiments/exp001-completed/"
                    "outputs/experiment_report.json"
                ),
                "selector_type": "json_pointer",
                "selector": "/observed_values/0/source/selector",
            },
        }
    ]

    prompt = build_analysis_prompt(_job_context(), packet)

    assert '"/canonical_facts/0/value"' in prompt
    assert '"/observed_values/0/source/selector"' in prompt


def test_analysis_prompt_preserves_empty_json_pointer_selector():
    packet = _evidence_packet()
    packet["canonical_facts"][0]["source"]["selector"] = ""

    prompt = build_analysis_prompt(_job_context(), packet)

    assert '"selector": ""' in prompt


def test_analysis_prompt_redacts_invalid_json_pointer_selector_paths():
    packet = _evidence_packet()
    packet["observed_values"] = [
        {
            "source": {
                "selector_type": "json_pointer",
                "selector": r"\\server\share\result.json",
            },
        },
        {
            "source": {
                "selector_type": "json_pointer",
                "selector": r"\Users\tom\target-repo\result.json",
            },
        },
    ]

    prompt = build_analysis_prompt(_job_context(), packet)

    assert r"\\\\server\\share\\result.json" not in prompt
    assert r"\\Users\\tom\\target-repo\\result.json" not in prompt
    assert "[omitted unsafe path]" in prompt


def test_analysis_prompt_redacts_mixed_separator_traversal_exact_paths():
    packet = _evidence_packet()
    packet["diagnostics"] = [
        r"questions/q\../secret.json",
        r"questions/q/..\secret.json",
    ]

    prompt = build_analysis_prompt(_job_context(), packet)

    assert r"questions/q\\../secret.json" not in prompt
    assert r"questions/q/..\\secret.json" not in prompt
    assert "[omitted unsafe path]" in prompt


def test_analysis_prompt_redacts_embedded_windows_absolute_and_temp_paths():
    packet = _evidence_packet()
    packet["diagnostics"] = [
        r"loaded result from C:\Users\tom\target-repo\result.json",
        r"wrote temporary copy to C:\Temp\paperctl\result.json",
    ]

    prompt = build_analysis_prompt(_job_context(), packet)

    assert r"C:\\Users\\tom\\target-repo\\result.json" not in prompt
    assert r"C:\\Temp\\paperctl\\result.json" not in prompt
    assert "[omitted unsafe path]" in prompt


def test_analysis_prompt_redacts_exact_windows_root_relative_and_unc_paths():
    context = _job_context()
    context["evidence_packet_path"] = r"\Users\tom\target-repo\result.json"
    packet = _evidence_packet()
    packet["canonical_facts"][0]["source"]["path"] = r"\\server\share\result.json"

    prompt = build_analysis_prompt(context, packet)

    assert r"\\Users\\tom\\target-repo\\result.json" not in prompt
    assert r"\\\\server\\share\\result.json" not in prompt
    assert "[omitted unsafe path]" in prompt


def test_analysis_prompt_redacts_embedded_windows_root_relative_and_unc_paths():
    packet = _evidence_packet()
    packet["diagnostics"] = [
        r"loaded result from \Users\tom\target-repo\result.json",
        r"copied result from \\server\share\result.json",
    ]

    prompt = build_analysis_prompt(_job_context(), packet)

    assert r"\\Users\\tom\\target-repo\\result.json" not in prompt
    assert r"\\\\server\\share\\result.json" not in prompt
    assert "[omitted unsafe path]" in prompt


def test_analysis_prompt_handles_missing_question_readme_metadata():
    context = _job_context()
    context["question_readme_path"] = None
    context["question_readme_hash"] = None

    prompt = build_analysis_prompt(context, _evidence_packet())

    assert "question_readme_path: not available" in prompt
    assert "question_readme_hash: not available" in prompt


def test_prompt_template_hash_is_deterministic():
    assert prompt_template_hash() == prompt_template_hash()
    assert prompt_template_hash() == _prompt_template_hash(PROMPT_TEMPLATE, PROMPT_BUILDER_VERSION)


def test_prompt_template_hash_changes_with_template_text_or_version():
    template = "Analyze selected experiment."

    assert _prompt_template_hash(template, 1) != _prompt_template_hash(
        template + "\nReturn JSON.", 1
    )
    assert _prompt_template_hash(template, 1) != _prompt_template_hash(template, 2)

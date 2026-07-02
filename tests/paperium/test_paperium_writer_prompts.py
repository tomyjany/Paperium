from paperium.writer_prompts import FACT_LOCK, build_writer_prompt


def test_initial_prompt_contains_contract_facts_and_style():
    prompt = build_writer_prompt(
        title="GPU propustnost",
        facts="- throughput 13,585 pages/s",
        style="- Czech decimal commas",
        output_path=".paperium/workers/w1/output.md",
    )
    assert "You are writing one section of a client-facing report." in prompt
    assert "Output only the final Markdown section" in prompt
    assert "## GPU propustnost" in prompt
    assert "- throughput 13,585 pages/s" in prompt
    assert "- Czech decimal commas" in prompt
    assert ".paperium/workers/w1/output.md" in prompt
    assert FACT_LOCK not in prompt


def test_revision_prompt_has_fact_lock_notes_and_draft():
    draft = "Text /remove this sentence/ rest.\nMore /use word run instead/ text."
    prompt = build_writer_prompt(
        title="GPU propustnost",
        facts="- facts",
        style="- style rule",
        output_path=".paperium/workers/w1/output.md",
        draft=draft,
    )
    assert "You are revising one section of a client-facing report." in prompt
    assert FACT_LOCK in prompt
    assert "1. remove this sentence" in prompt
    assert "2. use word run instead" in prompt
    assert draft in prompt
    assert "- style rule" in prompt


def test_blank_draft_selects_initial_prompt():
    prompt = build_writer_prompt(
        title="T", facts="f", style="s", output_path="o.md", draft="  \n"
    )
    assert "You are writing one section" in prompt

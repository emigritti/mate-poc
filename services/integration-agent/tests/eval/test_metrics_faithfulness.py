from tests.eval.metrics.faithfulness import substring_faithfulness, llm_judge_faithfulness


def test_substring_faithfulness_all_present():
    answer = "The status mapping uses uppercase transformation."
    must_contain = ["status", "uppercase"]
    assert substring_faithfulness(answer, must_contain) == 1.0


def test_substring_faithfulness_partial():
    answer = "The status uses transformation."
    must_contain = ["status", "uppercase", "lifecycle"]
    # 1/3
    assert abs(substring_faithfulness(answer, must_contain) - 1/3) < 1e-9


def test_substring_faithfulness_case_insensitive():
    answer = "STATUS uses UPPERCASE."
    assert substring_faithfulness(answer, ["status", "uppercase"]) == 1.0


def test_llm_judge_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    score = llm_judge_faithfulness(
        query="anything", answer="anything", contexts=["c1"],
    )
    assert score is None

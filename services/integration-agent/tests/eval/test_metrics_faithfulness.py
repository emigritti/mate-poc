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


def test_substring_faithfulness_empty_must_contain_returns_zero():
    assert substring_faithfulness("any answer", []) == 0.0


def test_substring_faithfulness_zero_hits_returns_zero():
    assert substring_faithfulness("totally unrelated content", ["xyz", "qwe"]) == 0.0


def test_llm_judge_parses_digit_from_response(monkeypatch):
    """Verifies the digit-extraction parse path (the only fragile bit of llm_judge)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    class FakeContent:
        text = "  4 (high faithfulness)"

    class FakeMsg:
        content = [FakeContent()]

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        class messages:
            @staticmethod
            def create(**kwargs):
                return FakeMsg()

    monkeypatch.setattr("anthropic.Anthropic", FakeClient)
    score = llm_judge_faithfulness(
        query="q", answer="a", contexts=["c"],
    )
    assert score == 4.0


def test_llm_judge_returns_none_on_non_numeric_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    class FakeContent:
        text = "no number here"

    class FakeMsg:
        content = [FakeContent()]

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        class messages:
            @staticmethod
            def create(**kwargs):
                return FakeMsg()

    monkeypatch.setattr("anthropic.Anthropic", FakeClient)
    score = llm_judge_faithfulness(query="q", answer="a", contexts=["c"])
    assert score is None

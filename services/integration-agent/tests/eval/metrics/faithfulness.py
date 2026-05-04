"""Faithfulness metrics — substring (cheap, deterministic) + LLM-judge (opt-in).

LLM-judge requires ANTHROPIC_API_KEY in the environment; without it returns None
and the harness reports 'n/a' for the metric.
"""
import os


def substring_faithfulness(answer: str, must_contain: list[str]) -> float:
    """Fraction of `must_contain` tokens present (case-insensitive) in answer."""
    if not must_contain:
        return 0.0
    answer_lower = answer.lower()
    hits = sum(1 for token in must_contain if token.lower() in answer_lower)
    return hits / len(must_contain)


def llm_judge_faithfulness(
    query: str,
    answer: str,
    contexts: list[str],
    *,
    model: str = "claude-haiku-4-5",
) -> float | None:
    """Score answer faithfulness 0-5 via Claude judge.

    Returns None when ANTHROPIC_API_KEY is absent (graceful skip).

    CALLER CONTRACT (CLAUDE.md §1): inputs MUST be synthetic / public /
    Accenture-Internal data only.  This function forwards `query`, `answer`,
    and `contexts` to the Claude API over the public network.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()
    prompt = (
        "Score how well the ANSWER is supported by the CONTEXTS for the QUERY.\n"
        "Return only a single number 0-5 (5 = fully grounded, 0 = hallucinated).\n\n"
        f"QUERY: {query}\n\n"
        f"CONTEXTS:\n{chr(10).join('- ' + c[:500] for c in contexts)}\n\n"
        f"ANSWER: {answer}\n\nSCORE:"
    )
    try:
        msg = client.messages.create(
            model=model, max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Extract first digit
        for ch in raw:
            if ch.isdigit():
                return float(ch)
        return None
    except Exception:
        return None

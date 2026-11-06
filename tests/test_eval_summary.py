"""Per-round metrics in the eval summary."""
from chatdify.evaluation.runner import _by_round


def _rounds(*pairs):
    """(duration, cumulative_tokens) per round."""
    return [{"round": i + 1, "duration": d, "cumulative_tokens": t} for i, (d, t) in enumerate(pairs)]


def test_by_round_counts_finished_cases_in_later_rows():
    results = {
        "a": {"status": "succeeded", "attempts": 1, "rounds": _rounds((10, 100))},
        "b": {"status": "succeeded", "attempts": 2, "rounds": _rounds((10, 100), (20, 300))},
        "c": {"status": "failed", "attempts": 3, "rounds": _rounds((10, 100), (20, 300), (30, 600))},
        "d": {"status": "error", "duration": 1.0},
    }
    rows = {r["round"]: r for r in _by_round(results, max_rounds=3)}

    assert [rows[n]["success_rate"] for n in (1, 2, 3)] == [25.0, 50.0, 50.0]
    # N=1: 10+10+10; N=2: 10 + 30 + 30; N=3: 10 + 30 + 60; always over 4 cases
    assert [rows[n]["avg_duration"] for n in (1, 2, 3)] == [7.5, 17.5, 25.0]
    # N=1: 100*3; N=2: 100+300+300; N=3: 100+300+600
    assert [rows[n]["avg_tokens"] for n in (1, 2, 3)] == [75, 175, 250]


def test_by_round_cache_hit_rate():
    def rnd(i, input_tokens, cached):
        return {"round": i, "duration": 1, "cumulative_tokens": input_tokens,
                "cumulative_input_tokens": input_tokens, "cumulative_cached_tokens": cached}

    results = {
        "a": {"status": "succeeded", "attempts": 1, "rounds": [rnd(1, 100, 0)]},
        "b": {"status": "succeeded", "attempts": 2, "rounds": [rnd(1, 100, 50), rnd(2, 300, 200)]},
    }
    rows = {r["round"]: r for r in _by_round(results, max_rounds=2)}
    # N=1: 50 / 200; N=2: (0 + 200) / (100 + 300)
    assert (rows[1]["cache_hit_rate"], rows[2]["cache_hit_rate"]) == (25.0, 50.0)


def test_by_round_covers_max_retries_even_if_all_pass_early():
    results = {"a": {"status": "succeeded", "attempts": 1, "rounds": _rounds((5, 50))}}
    rows = _by_round(results, max_rounds=3)

    assert [r["round"] for r in rows] == [1, 2, 3]
    assert all(r["success_rate"] == 100.0 and r["avg_tokens"] == 50 for r in rows)

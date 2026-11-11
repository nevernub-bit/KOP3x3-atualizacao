"""Unit tests for the official KOP 3x3 scoring rules (v2).

These tests exercise `backend/scoring.py` directly: no database, no network.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scoring  # noqa: E402

A = ["a1", "a2", "a3"]
B = ["b1", "b2", "b3"]
TEAMS = {"A": {"id": "A", "players": A}, "B": {"id": "B", "players": B}}


def make_match(eliminated=(), penalties=(), **extra):
    m = {
        "team_a": "A",
        "team_b": "B",
        "eliminations": [{"eliminated_id": p} for p in eliminated],
        "penalties": list(penalties),
    }
    m.update(extra)
    return m


def calc(eliminated=(), penalties=(), **extra):
    return scoring.compute_result(make_match(eliminated, penalties, **extra), TEAMS)


# ---------------------------------------------------------------- raw scores
def test_0x0_is_draw_with_zero_points():
    r = calc()
    assert r["is_draw"] is True and r["winner_team_id"] is None
    assert (r["points_a"], r["points_b"]) == (0, 0)


def test_1x0_timeout_draw_keeps_elimination_point():
    r = calc(["b1"])
    assert r["is_draw"] is True
    assert (r["elims_a"], r["elims_b"]) == (1, 0)
    assert (r["points_a"], r["points_b"]) == (1, 0)


def test_1x1_is_draw_one_point_each():
    r = calc(["b1", "a1"])
    assert r["is_draw"] is True
    assert (r["points_a"], r["points_b"]) == (1, 1)


def test_2x1_timeout_draw():
    r = calc(["b1", "b2", "a1"])
    assert r["is_draw"] is True
    assert (r["points_a"], r["points_b"]) == (2, 1)


def test_2x2_timeout_draw():
    r = calc(["b1", "b2", "a1", "a2"])
    assert r["is_draw"] is True
    assert (r["points_a"], r["points_b"]) == (2, 2)


def test_3x0_wipe_win_five_points_perfect():
    r = calc(["b1", "b2", "b3"])
    assert r["winner_team_id"] == "A"
    assert r["is_draw"] is False
    assert (r["points_a"], r["points_b"]) == (5, 0)
    assert r["perfect_a"] is True and r["perfect_b"] is False


def test_3x1_winner_five_loser_one_not_perfect():
    r = calc(["b1", "b2", "b3", "a1"])
    assert r["winner_team_id"] == "A"
    assert (r["points_a"], r["points_b"]) == (5, 1)
    assert r["perfect_a"] is False


def test_3x2_winner_five_loser_two_not_perfect():
    r = calc(["b1", "b2", "b3", "a1", "a2"])
    assert r["winner_team_id"] == "A"
    assert (r["points_a"], r["points_b"]) == (5, 2)
    assert r["perfect_a"] is False


def test_team_b_can_win():
    r = calc(["a1", "a2", "a3"])
    assert r["winner_team_id"] == "B"
    assert (r["points_a"], r["points_b"]) == (0, 5)
    assert r["perfect_b"] is True


# ------------------------------------------------- simultaneous eliminations
def test_simultaneous_last_players_is_draw_not_5x5():
    r = calc(["b1", "b2", "b3", "a1", "a2", "a3"])
    assert r["is_draw"] is True and r["winner_team_id"] is None
    assert (r["points_a"], r["points_b"]) == (3, 3)
    assert (r["points_a"], r["points_b"]) != (5, 5)
    assert r["perfect_a"] is False and r["perfect_b"] is False


def test_declared_draw_2x2_stays_2x2():
    r = calc(["b1", "b2", "a1", "a2"], declared_draw=True)
    assert r["is_draw"] is True and r["winner_team_id"] is None
    assert (r["points_a"], r["points_b"]) == (2, 2)
    assert r["perfect_a"] is False and r["perfect_b"] is False


def test_declared_draw_never_applies_bonus():
    r = calc(["b1", "b2", "b3", "a1", "a2"], declared_draw=True, draw_reason="SIMULTANEA")
    assert r["is_draw"] is True
    assert (r["points_a"], r["points_b"]) == (3, 2)
    assert r["perfect_a"] is False


def test_duplicate_elimination_entries_count_once():
    r = calc(["b1", "b1", "b1"])
    assert (r["elims_a"], r["points_a"]) == (1, 1)
    assert r["winner_team_id"] is None


# ------------------------------------------------------------------ perfects
def test_perfect_only_when_no_own_player_was_eliminated():
    perfect = calc(["b1", "b2", "b3"])
    not_perfect = calc(["b1", "b2", "b3", "a3"])
    assert perfect["perfect_a"] is True
    assert not_perfect["perfect_a"] is False


def test_perfect_does_not_add_points_beyond_five():
    perfect = calc(["b1", "b2", "b3"])
    assert perfect["points_a"] == 5
    assert perfect["base_points_a"] == 5


# ---------------------------------------------------------------------- W.O.
def test_legacy_wo_without_wo_team_id_keeps_five_x_zero():
    # Old documents have wo=True and winner_team_id, but no wo_team_id.
    r = calc(wo=True, wo_team_id=None, winner_team_id="A")
    assert r["wo"] is True and r["points_a"] == 5 and r["points_b"] == 0
    assert r["elims_a"] == 0 and r["elims_b"] == 0


def test_wo_grants_five_points_without_inventing_eliminations():
    r = calc(wo=True, wo_team_id="A")
    assert r["winner_team_id"] == "A"
    assert (r["points_a"], r["points_b"]) == (5, 0)
    assert (r["elims_a"], r["elims_b"]) == (0, 0)
    assert r["eliminated_players_a"] == [] and r["eliminated_players_b"] == []
    assert r["admin_perfect_a"] is True
    assert r["perfect_a"] is False  # W.O. is not a real PERFECT for tie-breaks
    assert "W.O." in r["wo_score"]


def test_wo_for_team_b():
    r = calc(wo=True, wo_team_id="B")
    assert (r["points_a"], r["points_b"]) == (0, 5)
    assert r["admin_perfect_b"] is True


# ----------------------------------------------------------------- penalties
def test_penalty_during_match_subtracts_one_point():
    pen = [{"team_id": "A", "points": 1, "reason": "eliminação não declarada"}]
    r = calc(["b1", "b2", "b3", "a1"], penalties=pen)
    assert r["base_points_a"] == 5
    assert r["penalty_points_a"] == 1
    assert (r["points_a"], r["points_b"]) == (4, 1)


def test_penalty_after_match_is_applied_the_same_way():
    pen = [{"team_id": "B", "points": 1, "reason": "conduta antidesportiva",
            "match_status": "ENCERRADA"}]
    r = calc(["b1", "b2", "b3", "a1", "a2"], penalties=pen)
    assert (r["points_a"], r["points_b"]) == (5, 1)


def test_penalty_never_makes_points_negative():
    pen = [{"team_id": "A", "points": 3, "reason": "reincidência"}]
    r = calc(["b1"], penalties=pen)
    assert r["points_a"] == 0
    assert r["base_points_a"] == 1


def test_multiple_penalties_accumulate():
    pen = [
        {"team_id": "A", "points": 1, "reason": "x"},
        {"team_id": "A", "points": 1, "reason": "y"},
    ]
    r = calc(["b1", "b2", "b3"], penalties=pen)
    assert r["penalty_points_a"] == 2
    assert r["points_a"] == 3  # 5 - 2


# ----------------------------------------------------------------- standings
def row(team_id, points=0, wins=0, diff=0, perfects=0, **extra):
    r = {"team_id": team_id, "points": points, "wins": wins, "diff": diff,
         "perfects": perfects}
    r.update(extra)
    return r


def test_standings_order_by_points_first():
    rows = [row("A", points=5), row("B", points=10)]
    out = scoring.sort_standings(rows, [])
    assert [r["team_id"] for r in out] == ["B", "A"]


def test_standings_order_by_wins_after_points():
    rows = [row("A", points=5, wins=1), row("B", points=5, wins=2)]
    out = scoring.sort_standings(rows, [])
    assert [r["team_id"] for r in out] == ["B", "A"]


def test_standings_order_by_elimination_diff():
    rows = [row("A", points=5, wins=1, diff=1), row("B", points=5, wins=1, diff=3)]
    out = scoring.sort_standings(rows, [])
    assert [r["team_id"] for r in out] == ["B", "A"]


def test_standings_order_by_perfects():
    rows = [row("A", points=5, wins=1, diff=2, perfects=1),
            row("B", points=5, wins=1, diff=2, perfects=2)]
    out = scoring.sort_standings(rows, [])
    assert [r["team_id"] for r in out] == ["B", "A"]


def test_standings_order_by_head_to_head():
    rows = [row("A", points=5, wins=1, diff=2, perfects=0),
            row("B", points=5, wins=1, diff=2, perfects=0)]
    matches = [{"team_a": "A", "team_b": "B", "points_a": 0, "points_b": 3}]
    out = scoring.sort_standings(rows, matches)
    assert [r["team_id"] for r in out] == ["B", "A"]


def test_standings_reserved_criteria_are_not_used():
    rows = [row("A", points=5, tiebreak_6=99), row("B", points=5, tiebreak_6=0)]
    out = scoring.sort_standings(rows, [])
    assert [r["team_id"] for r in out] == ["A", "B"]  # stable, no invented rule


def test_three_way_head_to_head_orders_by_mini_table():
    rows = [row("A", points=5, wins=1, diff=2),
            row("B", points=5, wins=1, diff=2),
            row("C", points=5, wins=1, diff=2)]
    matches = [
        {"team_a": "A", "team_b": "B", "points_a": 5, "points_b": 0},
        {"team_a": "A", "team_b": "C", "points_a": 5, "points_b": 0},
        {"team_a": "B", "team_b": "C", "points_a": 5, "points_b": 0},
    ]
    out = scoring.sort_standings(rows, matches)
    assert [r["team_id"] for r in out] == ["A", "B", "C"]
    assert not any(r.get("tiebreak_pending") for r in out)


def test_three_way_cycle_marks_pending_and_never_invents_a_rule():
    rows = [row("A", points=5, wins=1, diff=2),
            row("B", points=5, wins=1, diff=2),
            row("C", points=5, wins=1, diff=2)]
    matches = [
        {"team_a": "A", "team_b": "B", "points_a": 5, "points_b": 0},
        {"team_a": "B", "team_b": "C", "points_a": 5, "points_b": 0},
        {"team_a": "C", "team_b": "A", "points_a": 5, "points_b": 0},
    ]
    out = scoring.sort_standings(rows, matches)
    assert [r["team_id"] for r in out] == ["A", "B", "C"]  # stable, deterministic
    assert all(r.get("tiebreak_pending") for r in out)


def test_two_way_h2h_draw_is_flagged_pending():
    rows = [row("A", points=2), row("B", points=2)]
    matches = [{"team_a": "A", "team_b": "B", "points_a": 2, "points_b": 2}]
    out = scoring.sort_standings(rows, matches)
    assert [r["team_id"] for r in out] == ["A", "B"]
    assert all(r.get("tiebreak_pending") for r in out)


def test_head_to_head_points_only_counts_matches_between_tied_teams():
    matches = [
        {"team_a": "A", "team_b": "B", "points_a": 2, "points_b": 3},
        {"team_a": "A", "team_b": "C", "points_a": 5, "points_b": 0},
    ]
    pts = scoring.head_to_head_points(["A", "B"], matches)
    assert pts == {"A": 2, "B": 3}


# ------------------------------------------------------------ undo behaviour
def test_undoing_an_elimination_recalculates_bonus_and_perfect():
    before = calc(["b1", "b2", "b3"])
    after = calc(["b1", "b2"])  # last elimination undone
    assert before["points_a"] == 5 and before["perfect_a"] is True
    assert after["points_a"] == 2 and after["perfect_a"] is False
    assert after["winner_team_id"] is None


def test_undo_restores_winner_and_loser_points():
    before = calc(["b1", "b2", "b3", "a1"])
    after = calc(["b1", "b2", "a1"])  # undo only the last wipe elimination
    assert before["points_b"] == 1
    assert after["elims_b"] == 1 and after["points_b"] == 1
    assert after["points_a"] == 2

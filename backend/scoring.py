"""Official KOP 3x3 scoring rules — single source of truth.

Pure functions only (no database / network access) so every rule can be unit
tested directly. The API layer stores the result produced here; the frontend
only renders it.

Rules (v2):
- Each opponent eliminated is worth 1 point for the team that eliminated them.
- The +2 full-wipe bonus only exists when there is a single winning team
  (a simultaneous wipe of the last players is a DRAW and grants no bonus).
- A draw keeps the elimination points of each team (never 5 x 5).
- PERFECT = wipe + zero own players eliminated. It is a tie-break only and
  never adds points.
- W.O. = administrative 5 x 0, no invented eliminations, administrative
  PERFECT for display only (not a real PERFECT for tie-breaks).
- Team penalties subtract from the match points, never below zero.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

POINTS_PER_ELIMINATION = 1
FULL_WIPE_BONUS = 2
MAX_MATCH_POINTS = 15  # defensive upper bound, not a rule

WO_WIN_POINTS = 5
WO_LOSS_POINTS = 0
WO_SCORE_TEXT = "5 x 0 — W.O."


def _roster(team: Optional[dict]) -> List[str]:
    if not team:
        return []
    return [p for p in (team.get("players") or []) if isinstance(p, str)]


def _unique_eliminated(match: dict) -> List[str]:
    """Elimination entries are append-only; a repeated player counts once."""
    seen = set()
    out: List[str] = []
    for entry in match.get("eliminations") or []:
        pid = (entry or {}).get("eliminated_id")
        if pid and pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


def _sum_penalties(match: dict, team_id: Optional[str]) -> int:
    total = 0
    for pen in match.get("penalties") or []:
        if (pen or {}).get("team_id") != team_id:
            continue
        try:
            total += int(pen.get("points") or 0)
        except (TypeError, ValueError):
            continue
    return max(0, total)


def compute_result(match: dict, teams_by_id: Dict[str, dict]) -> dict:
    """Return every derived field of a match.

    Keys returned are persisted on the match document by the API layer, so the
    database always holds the same numbers the frontend renders.
    """
    team_a = match.get("team_a")
    team_b = match.get("team_b")
    a_ids = _roster(teams_by_id.get(team_a))
    b_ids = _roster(teams_by_id.get(team_b))
    a_set, b_set = set(a_ids), set(b_ids)

    eliminated = _unique_eliminated(match)
    eliminated_a = [pid for pid in eliminated if pid in a_set]
    eliminated_b = [pid for pid in eliminated if pid in b_set]

    # Eliminations realized BY each team = opponents they took out.
    elims_by_a = len(eliminated_b)
    elims_by_b = len(eliminated_a)
    alive_a = max(0, len(a_ids) - elims_by_b)
    alive_b = max(0, len(b_ids) - elims_by_a)

    wo_team = match.get("wo_team_id") if match.get("wo") else None
    if wo_team not in (team_a, team_b):
        # Legacy W.O. documents only stored `wo` + `winner_team_id`. Without
        # this fallback a historical recalculation would erase the awarded 5 x 0.
        wo_team = match.get("winner_team_id") if match.get("wo") else None
    if wo_team not in (team_a, team_b):
        wo_team = None

    # --- Sporting result -------------------------------------------------
    winner_id: Optional[str] = None
    is_draw = False
    draw_reason: Optional[str] = None

    if wo_team:
        winner_id = wo_team
    elif match.get("declared_draw"):
        # Referee decision (e.g. simultaneous elimination without precedence).
        is_draw = True
        draw_reason = match.get("draw_reason") or "SIMULTANEA"
    elif alive_a == 0 and alive_b == 0:
        # Both rosters wiped at the same time: no winner, no +2 bonus.
        is_draw = True
        draw_reason = "SIMULTANEA"
    elif alive_b == 0 and alive_a > 0:
        winner_id = team_a
    elif alive_a == 0 and alive_b > 0:
        winner_id = team_b
    else:
        # Time expired (or ended by the referee) with survivors on both sides.
        is_draw = True
        draw_reason = "TEMPO"

    # --- Points ----------------------------------------------------------
    # W.O. is administrative: 5 x 0 regardless of the recorded elimination list
    # (which must stay empty; we never invent player eliminations).
    if wo_team:
        base_a = WO_WIN_POINTS if wo_team == team_a else WO_LOSS_POINTS
        base_b = WO_WIN_POINTS if wo_team == team_b else WO_LOSS_POINTS
    else:
        bonus_a = FULL_WIPE_BONUS if (winner_id == team_a and len(b_ids) > 0) else 0
        bonus_b = FULL_WIPE_BONUS if (winner_id == team_b and len(a_ids) > 0) else 0
        base_a = elims_by_a * POINTS_PER_ELIMINATION + bonus_a
        base_b = elims_by_b * POINTS_PER_ELIMINATION + bonus_b

    pen_a = _sum_penalties(match, team_a)
    pen_b = _sum_penalties(match, team_b)
    # A penalty can never push a team below zero in that match.
    points_a = max(0, base_a - pen_a)
    points_b = max(0, base_b - pen_b)

    # --- PERFECT (tie-break only) ---------------------------------------
    perfect_a = bool(
        winner_id == team_a and len(b_ids) > 0 and elims_by_b == 0
        and elims_by_a >= len(b_ids)
    )
    perfect_b = bool(
        winner_id == team_b and len(a_ids) > 0 and elims_by_a == 0
        and elims_by_b >= len(a_ids)
    )
    # Administrative PERFECT (W.O.) is display-only and never a real PERFECT.
    admin_perfect_a = bool(wo_team == team_a)
    admin_perfect_b = bool(wo_team == team_b)

    return {
        "elims_a": elims_by_a,
        "elims_b": elims_by_b,
        "base_points_a": base_a,
        "base_points_b": base_b,
        "penalty_points_a": pen_a,
        "penalty_points_b": pen_b,
        "points_a": points_a,
        "points_b": points_b,
        "eliminated_players_a": eliminated_a,
        "eliminated_players_b": eliminated_b,
        "alive_a": alive_a,
        "alive_b": alive_b,
        "winner_team_id": winner_id,
        "is_draw": is_draw,
        "draw_reason": draw_reason,
        "perfect_a": perfect_a,
        "perfect_b": perfect_b,
        "admin_perfect_a": admin_perfect_a,
        "admin_perfect_b": admin_perfect_b,
        "wo": bool(wo_team),
        "wo_team_id": wo_team,
        "wo_score": WO_SCORE_TEXT if wo_team else None,
    }


def head_to_head_points(team_ids: Iterable[str], matches: Iterable[dict]) -> Dict[str, int]:
    """Points each tied team earned in the matches played among themselves."""
    ids = set(team_ids)
    pts = {tid: 0 for tid in ids}
    for m in matches:
        a, b = m.get("team_a"), m.get("team_b")
        if a in ids and b in ids:
            pts[a] += int(m.get("points_a") or 0)
            pts[b] += int(m.get("points_b") or 0)
    return pts


def sort_standings(rows: List[dict], matches: Iterable[dict]) -> List[dict]:
    """Official order: points, wins, elimination diff, PERFECTs, head-to-head.

    With two tied teams, head-to-head is the direct result between them. With
    three or more tied teams, it is a mini-table of the points each one earned
    in the matches played among the tied teams. If that mini-table is still
    tied, no extra rule is invented here: the affected rows are marked with
    `tiebreak_pending = True`, keep a deterministic stable order, and wait for
    the organization to define criteria 6 and 7. The reserved `tiebreak_6` /
    `tiebreak_7` fields are never read.
    """
    matches = list(matches)

    def primary(row: dict):
        return (
            -int(row.get("points") or 0),
            -int(row.get("wins") or 0),
            -int(row.get("diff") or 0),
            -int(row.get("perfects") or 0),
        )

    ordered = sorted(rows, key=primary)
    out: List[dict] = []
    i = 0
    while i < len(ordered):
        j = i + 1
        key = primary(ordered[i])
        while j < len(ordered) and primary(ordered[j]) == key:
            j += 1
        group = ordered[i:j]
        if len(group) > 1:
            h2h = head_to_head_points([r["team_id"] for r in group], matches)
            group = sorted(group, key=lambda r: -h2h.get(r["team_id"], 0))
            counts = {}
            for value in h2h.values():
                counts[value] = counts.get(value, 0) + 1
            for row_ in group:
                if counts.get(h2h.get(row_["team_id"], 0), 0) > 1:
                    row_["tiebreak_pending"] = True
        out.extend(group)
        i = j
    return out

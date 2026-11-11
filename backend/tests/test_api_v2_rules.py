"""End-to-end API tests for the v2 rules, using an in-memory MongoDB.

No real database is touched: `server.db` is replaced by mongomock before the
test client starts. Covers scoring, undo, penalties, W.O., declared draws,
redo, Ranger permissions, rules and banner.
"""
import asyncio
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mongomock_motor  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

server.db = mongomock_motor.AsyncMongoMockClient()["kop_api_test"]

TEAMS = [
    {"id": "ta", "name": "TEAM A", "order": 0, "group": "A",
     "players": ["a1", "a2", "a3"], "created_at": "2026-01-01T00:00:00+00:00"},
    {"id": "tb", "name": "TEAM B", "order": 1, "group": "A",
     "players": ["b1", "b2", "b3"], "created_at": "2026-01-01T00:00:00+00:00"},
]


def make_player(pid, team):
    return {
        "id": pid, "name": pid.upper(), "nickname": None, "level": "INICIANTE",
        "photo": None, "status": "CONFIRMADO", "team_id": team,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def make_match(mid, number, **extra):
    m = {
        "id": mid, "number": number, "phase": "GROUP", "group": "A",
        "team_a": "ta", "team_b": "tb", "status": "AGUARDANDO",
        "winner_team_id": None, "elims_a": 0, "elims_b": 0,
        "points_a": 0, "points_b": 0,
        "eliminated_players_a": [], "eliminated_players_b": [],
        "eliminations": [], "duration_seconds": 300,
        "started_at": None, "paused_at": None, "pause_accumulated_ms": 0,
        "ended_at": None, "is_draw": False, "locked": False,
        "perfect_a": False, "perfect_b": False,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    m.update(extra)
    return m


def seed():
    async def _run():
        await server.db.teams.insert_many([dict(t) for t in TEAMS])
        await server.db.players.insert_many(
            [make_player(p, "ta") for p in ("a1", "a2", "a3")]
            + [make_player(p, "tb") for p in ("b1", "b2", "b3")])
        await server.db.matches.insert_many([
            make_match("m1", 1),
            make_match("m2", 2),
            make_match("m3", 3),
            make_match("m4", 4),
        ])
    asyncio.run(_run())


seed()


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        yield c


@pytest.fixture(scope="module")
def admin(client):
    r = client.post("/api/auth/login", json={
        "email": server.ADMIN_EMAIL, "password": server.ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def get(client, mid):
    r = client.get(f"/api/matches/{mid}")
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ scoring
def test_01_bootstrap(client):
    teams = client.get("/api/teams").json()
    assert {t["id"] for t in teams} >= {"ta", "tb"}


def test_02_eliminations_are_one_point_each(client, admin):
    assert client.post("/api/matches/m1/start", headers=admin).status_code == 200
    r = client.post("/api/matches/m1/eliminate", headers=admin, json={"eliminated_id": "b1"})
    assert r.status_code == 200, r.text
    assert (r.json()["points_a"], r.json()["points_b"]) == (1, 0)
    r = client.post("/api/matches/m1/eliminate", headers=admin, json={"eliminated_id": "b2"})
    assert (r.json()["points_a"], r.json()["points_b"]) == (2, 0)
    assert r.json()["status"] == "EM_ANDAMENTO"


def test_03_duplicate_elimination_is_rejected(client, admin):
    r = client.post("/api/matches/m1/eliminate", headers=admin, json={"eliminated_id": "b1"})
    assert r.status_code == 409
    assert get(client, "m1")["elims_a"] == 2


def test_04_client_token_makes_retry_idempotent(client, admin):
    body = {"eliminated_id": "a1", "client_token": "tok-1"}
    first = client.post("/api/matches/m1/eliminate", headers=admin, json=body)
    second = client.post("/api/matches/m1/eliminate", headers=admin, json=body)
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["elims_b"] == 1  # counted once
    assert len(second.json()["eliminations"]) == 3


def test_05_undo_specific_elimination_recalculates(client, admin):
    entry = [e for e in get(client, "m1")["eliminations"] if e["eliminated_id"] == "b2"][0]
    r = client.delete(f"/api/matches/m1/eliminations/{entry['id']}", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["elims_a"], d["points_a"]) == (1, 1)
    assert "b2" not in d["eliminated_players_b"]


def test_06_wipe_grants_five_points_but_not_perfect_when_hit(client, admin):
    client.post("/api/matches/m1/eliminate", headers=admin, json={"eliminated_id": "b2"})
    r = client.post("/api/matches/m1/eliminate", headers=admin, json={"eliminated_id": "b3"})
    d = r.json()
    assert d["status"] == "ENCERRADA"
    assert d["winner_team_id"] == "ta"
    assert (d["points_a"], d["points_b"]) == (5, 1)
    # A lost a1 earlier, so this is a 3x1 win: five points, no PERFECT.
    assert d["perfect_a"] is False
    assert d["base_points_a"] == 5


def test_07_penalty_after_match_and_audit(client, admin):
    r = client.post("/api/matches/m1/penalty", headers=admin, json={
        "team_id": "ta", "points": 1, "reason": "eliminação não declarada",
        "type": "ELIMINACAO_NAO_DECLARADA"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["points_a"], d["base_points_a"], d["penalty_points_a"]) == (4, 5, 1)
    assert d["penalties"][-1]["reason"] == "eliminação não declarada"
    assert d["penalties"][-1]["match_status"] == "ENCERRADA"
    # The audit trail is admin-only and no longer part of the public payload.
    audit_payload = client.get("/api/matches/m1/audit", headers=admin).json()
    audit = [a for a in audit_payload["audit_log"] if a["action"] == "PENALTY"][-1]
    assert audit["before"]["points"] == 5 and audit["after"]["points"] == 4


def test_08_penalty_removal_recalculates(client, admin):
    pid = get(client, "m1")["penalties"][-1]["id"]
    r = client.delete(f"/api/matches/m1/penalty/{pid}", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["points_a"] == 5


def test_09_undo_on_finished_match_recalculates_without_5x5(client, admin):
    entry = [e for e in get(client, "m1")["eliminations"] if e["eliminated_id"] == "b3"][0]
    r = client.delete(f"/api/matches/m1/eliminations/{entry['id']}", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["points_a"], d["points_b"]) == (2, 1)
    assert d["perfect_a"] is False
    assert (d["points_a"], d["points_b"]) != (5, 5)
    # The wipe was undone before time expired, so the match continues.
    assert d["status"] == "EM_ANDAMENTO"


def test_10_ranger_can_eliminate_but_not_administer(client, admin):
    r = client.post("/api/rangers", headers=admin, json={
        "name": "Ranger 1", "email": "ranger1@example.com", "password": "senha123"})
    assert r.status_code == 200, r.text
    login = client.post("/api/auth/login", json={
        "email": "ranger1@example.com", "password": "senha123"})
    assert login.status_code == 200, login.text
    ranger = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # forbidden administrative endpoints
    assert client.get("/api/rangers", headers=ranger).status_code == 403
    assert client.post("/api/draw", headers=ranger, json={}).status_code == 403
    assert client.post("/api/matches/m4/redo", headers=ranger,
                       json={"confirm": True}).status_code == 403

    # allowed live match operations
    assert client.post("/api/matches/m4/start", headers=ranger).status_code == 200
    r = client.post("/api/matches/m4/eliminate", headers=ranger, json={"eliminated_id": "b1"})
    assert r.status_code == 200, r.text
    assert r.json()["elims_a"] == 1


def test_11_deactivated_ranger_cannot_login(client, admin):
    rid = [x for x in client.get("/api/rangers", headers=admin).json()][0]["id"]
    assert client.delete(f"/api/rangers/{rid}", headers=admin).status_code == 200
    r = client.post("/api/auth/login", json={
        "email": "ranger1@example.com", "password": "senha123"})
    assert r.status_code == 403


def test_12_wo_is_five_zero_without_invented_eliminations(client, admin):
    r = client.post("/api/matches/m2/wo", headers=admin, json={
        "team_id": "ta", "reason": "equipe B não compareceu"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["points_a"], d["points_b"]) == (5, 0)
    assert d["elims_a"] == 0 and d["elims_b"] == 0
    assert d["eliminations"] == []
    assert d["admin_perfect_a"] is True and d["perfect_a"] is False
    assert d["wo"] is True and "W.O." in d["wo_score"]


def test_13_declared_simultaneous_draw_is_never_5x5(client, admin):
    async def _prime():
        await server.db.matches.update_one({"id": "m3"}, {"$set": {
            "status": "EM_ANDAMENTO", "started_at": "2026-01-01T00:00:00+00:00",
            "eliminations": [
                {"id": "e1", "eliminated_id": pid, "at_ms": 1000}
                for pid in ("b1", "b2", "b3", "a1", "a2", "a3")
            ],
        }})
    asyncio.run(_prime())
    r = client.post("/api/matches/m3/declare-draw", headers=admin, json={
        "reason": "eliminação simultânea", "simultaneous": True})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "ENCERRADA"
    assert d["is_draw"] is True and d["winner_team_id"] is None
    assert (d["points_a"], d["points_b"]) == (3, 3)
    assert d["perfect_a"] is False
    assert (d["points_a"], d["points_b"]) != (5, 5)


def test_14_redo_only_touches_the_selected_match(client, admin):
    before_m1 = get(client, "m1")
    r = client.post("/api/matches/m2/redo", headers=admin, json={
        "confirm": True, "reason": "erro de arbitragem"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "AGUARDANDO"
    assert (d["points_a"], d["points_b"]) == (0, 0)
    assert d["eliminations"] == [] and d["wo"] is False
    assert d["redo_count"] == 1
    hist = client.get("/api/matches/m2/history", headers=admin).json()
    assert len(hist) == 1 and hist[0]["snapshot"]["wo"] is True
    # other match preserved
    after_m1 = get(client, "m1")
    assert (after_m1["points_a"], after_m1["eliminations"]) == (
        before_m1["points_a"], before_m1["eliminations"])


def test_15_redo_requires_explicit_confirmation(client, admin):
    assert client.post("/api/matches/m2/redo", headers=admin,
                       json={"confirm": False}).status_code == 400


def test_16_public_rules_are_editable_and_versioned(client, admin):
    r = client.get("/api/rules")
    assert r.status_code == 200 and r.json()["content"]
    v1 = r.json()["version"]
    new_content = "# REGULAMENTO\n\n- Regra atualizada pelo administrador"
    r = client.put("/api/rules", headers=admin, json={"content": new_content})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == v1 + 1
    assert client.get("/api/rules").json()["content"] == new_content
    hist = client.get("/api/rules/history", headers=admin).json()
    assert len(hist) >= 1


def test_17_rules_cannot_be_edited_by_anonymous(client):
    assert client.put("/api/rules", json={"content": "hack"}).status_code in (401, 403)


def test_18_banner_upload_validation_and_lifecycle(client, admin):
    assert client.get("/api/banner").json()["image"] is None
    bad = client.post("/api/banner", headers=admin, json={"image": "not-an-image"})
    assert bad.status_code == 400
    img = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    assert client.post("/api/banner", headers=admin,
                       json={"image": img, "filename": "banner.png"}).status_code == 200
    assert client.get("/api/banner").json()["image"] == img
    assert client.delete("/api/banner", headers=admin).status_code == 200
    assert client.get("/api/banner").json()["image"] is None


def test_19_standings_use_official_order_and_expose_perfects(client, admin):
    # A fresh 3x0 win (no own player eliminated) is a real PERFECT.
    async def _add():
        await server.db.matches.insert_one(make_match("m5", 5))
    asyncio.run(_add())
    client.post("/api/matches/m5/start", headers=admin)
    for pid in ("b1", "b2", "b3"):
        client.post("/api/matches/m5/eliminate", headers=admin,
                    json={"eliminated_id": pid})
    perfect = get(client, "m5")
    assert perfect["perfect_a"] is True and perfect["points_a"] == 5

    rows = client.get("/api/standings").json()["A"]
    assert all("perfects" in r for r in rows)
    # points are non-increasing; on equal points, wins are non-increasing
    for a, b in zip(rows, rows[1:]):
        assert a["points"] >= b["points"]
        if a["points"] == b["points"]:
            assert a["wins"] >= b["wins"]
    team_a = [r for r in rows if r["team_id"] == "ta"][0]
    assert team_a["points"] >= 2
    assert team_a["perfects"] >= 1  # from the 3x0 win in m5


def test_20_score_is_always_calculated_by_the_backend(client, admin):
    # Sending forged derived values changes nothing: the API ignores them.
    r = client.post("/api/matches/m4/eliminate", headers=admin, json={
        "eliminated_id": "b2", "points_a": 999, "elims_a": 999})
    assert r.status_code == 409 or r.status_code == 200
    d = get(client, "m4")
    assert d["elims_a"] == (2 if r.status_code == 200 else 1)
    assert d["points_a"] <= 5


def test_21_score_recalculation_is_previewable_and_reversible(client, admin):
    async def _legacy():
        await server.db.matches.insert_one(make_match(
            "m6", 6, status="ENCERRADA", ended_at="2026-01-01T00:10:00+00:00",
            points_a=0, points_b=0,
            eliminations=[{"id": f"le{i}", "eliminated_id": pid, "at_ms": 1000}
                          for i, pid in enumerate(("b1", "b2", "b3", "a1"))]))
    asyncio.run(_legacy())

    preview = client.post("/api/admin/recalculate-scores", headers=admin,
                          json={"dry_run": True, "confirm": True})
    assert preview.status_code == 200, preview.text
    assert any(c["match_id"] == "m6" for c in preview.json()["changes"])
    assert get(client, "m6")["points_a"] == 0  # preview never writes

    applied = client.post("/api/admin/recalculate-scores", headers=admin,
                          json={"dry_run": False, "confirm": True})
    assert applied.status_code == 200, applied.text
    d = get(client, "m6")
    assert (d["points_a"], d["points_b"]) == (5, 1)
    assert (d["legacy_points_a"], d["legacy_points_b"]) == (0, 0)
    hist = client.get("/api/matches/m6/history", headers=admin).json()
    assert len(hist) == 1 and hist[0]["snapshot"]["points_a"] == 0


def test_22_idempotent_retry_after_duplicate_player(client, admin):
    body = {"eliminated_id": "b3", "client_token": "dup-token-1"}
    first = client.post("/api/matches/m4/eliminate", headers=admin, json=body)
    assert first.status_code == 200, first.text
    count = len(first.json()["eliminations"])
    retry = client.post("/api/matches/m4/eliminate", headers=admin, json=body)
    assert retry.status_code == 200, retry.text  # retry is idempotent, not 409
    assert len(retry.json()["eliminations"]) == count


def test_23_group_winner_cannot_be_overridden(client, admin):
    r = client.post("/api/matches/m1/set-winner", headers=admin,
                    json={"winner_team_id": "tb"})
    assert r.status_code == 400, r.text
    # The override was rejected: m1 stays a draw after the undo in test_09.
    assert get(client, "m1")["winner_team_id"] is None


def test_24_roster_snapshot_protects_historical_scoring(client, admin):
    async def _seed():
        await server.db.teams.insert_many([
            {"id": "tc", "name": "TEAM C", "order": 2, "group": "B",
             "players": ["c1", "c2", "c3"], "created_at": "2026-01-01T00:00:00+00:00"},
            {"id": "td", "name": "TEAM D", "order": 3, "group": "B",
             "players": ["d1", "d2", "d3"], "created_at": "2026-01-01T00:00:00+00:00"},
        ])
        await server.db.players.insert_many(
            [make_player(p, "tc") for p in ("c1", "c2", "c3")]
            + [make_player(p, "td") for p in ("d1", "d2", "d3")])
        m = make_match("m7", 7)
        m.update({"group": "B", "team_a": "tc", "team_b": "td",
                  "roster_a": ["c1", "c2", "c3"],
                  "roster_b": ["d1", "d2", "d3"]})
        await server.db.matches.insert_one(m)
    asyncio.run(_seed())

    # The live roster no longer has d3, but the match snapshot does.
    async def _mutate():
        await server.db.teams.update_one({"id": "td"}, {"$set": {"players": ["d1", "d2"]}})
        await server.db.players.delete_one({"id": "d3"})
    asyncio.run(_mutate())

    assert client.post("/api/matches/m7/start", headers=admin).status_code == 200
    r = client.post("/api/matches/m7/eliminate", headers=admin,
                    json={"eliminated_id": "d3"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["elims_a"] == 1 and d["points_a"] == 1
    assert d["alive_b"] == 2  # snapshot still has 3 opponents


def test_25_penalty_after_match_updates_standings(client, admin):
    before = next(r for r in client.get("/api/standings").json()["A"]
                  if r["team_id"] == "ta")["points"]
    r = client.post("/api/matches/m5/penalty", headers=admin, json={
        "team_id": "ta", "points": 1, "reason": "penalidade pós-partida"})
    assert r.status_code == 200, r.text
    after = next(r for r in client.get("/api/standings").json()["A"]
                 if r["team_id"] == "ta")["points"]
    assert after == before - 1


def test_26_concurrent_eliminations_keep_both_points(client, admin):
    async def _seed():
        m = make_match("m8", 8)
        m.update({"group": "B", "team_a": "tc", "team_b": "td",
                  "roster_a": ["c1", "c2", "c3"],
                  "roster_b": ["d1", "d2", "d3"]})
        await server.db.matches.insert_one(m)
    asyncio.run(_seed())
    assert client.post("/api/matches/m8/start", headers=admin).status_code == 200

    barrier = threading.Barrier(2)
    results = []

    def hit(pid):
        barrier.wait(timeout=10)
        results.append(client.post("/api/matches/m8/eliminate", headers=admin,
                                   json={"eliminated_id": pid}))

    threads = [threading.Thread(target=hit, args=(pid,)) for pid in ("d1", "d2")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert len(results) == 2, "one concurrent request did not finish"
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    d = get(client, "m8")
    assert len(d["eliminations"]) == 2
    # The derived value must include both eliminations, never a stale 1.
    assert d["elims_a"] == 2 and d["points_a"] == 2


def test_27_ranger_rbac_matrix(client, admin):
    email = "ranger2@example.com"
    assert client.post("/api/rangers", headers=admin, json={
        "name": "Ranger 2", "email": email, "password": "senha123"}).status_code == 200
    login = client.post("/api/auth/login", json={"email": email, "password": "senha123"})
    assert login.status_code == 200, login.text
    ranger = {"Authorization": f"Bearer {login.json()['access_token']}"}

    forbidden = [
        ("post", "/api/tournament/reset", None),
        ("patch", "/api/tournament", {"num_teams": 10}),
        ("post", "/api/draw", {}),
        ("patch", "/api/teams/ta", {"name": "X"}),
        ("patch", "/api/players/a1", {"name": "X"}),
        ("delete", "/api/players/a1", None),
        ("post", "/api/matches/m1/lock", None),
        ("post", "/api/matches/m1/set-winner", {"winner_team_id": "ta"}),
        ("post", "/api/matches/m1/redo", {"confirm": True}),
        ("post", "/api/matches/m1/wo", {"team_id": "ta"}),
        ("get", "/api/rangers", None),
        ("put", "/api/rules", {"content": "x"}),
        ("get", "/api/rules/history", None),
        ("post", "/api/banner", {"image": "x"}),
        ("delete", "/api/banner", None),
        ("post", "/api/admin/recalculate-scores", {"confirm": True}),
        ("get", "/api/matches/m1/history", None),
        ("post", "/api/matches/m1/history/fake/restore", {"confirm": True}),
    ]
    for method, path, body in forbidden:
        call = getattr(client, method)
        r = call(path, headers=ranger, json=body) if body is not None else call(path, headers=ranger)
        assert r.status_code in (401, 403), f"{method.upper()} {path} -> {r.status_code} {r.text}"

    # Live operations remain allowed for the Ranger.
    assert client.get("/api/matches/m8", headers=ranger).status_code == 200


def test_28_penalty_retry_is_idempotent(client, admin):
    body = {"team_id": "tb", "points": 1, "reason": "teste idempotente",
            "client_token": "pen-tok-1"}
    first = client.post("/api/matches/m6/penalty", headers=admin, json=body)
    assert first.status_code == 200, first.text
    count = len(first.json()["penalties"])
    retry = client.post("/api/matches/m6/penalty", headers=admin, json=body)
    assert retry.status_code == 200, retry.text
    assert len(retry.json()["penalties"]) == count


def test_29_redo_removes_only_that_match_points(client, admin):
    def points_ta():
        return next(r for r in client.get("/api/standings").json()["A"]
                    if r["team_id"] == "ta")["points"]
    before = points_ta()
    r = client.post("/api/matches/m6/redo", headers=admin, json={"confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "AGUARDANDO"
    assert r.json()["points_a"] == 0 and r.json()["points_b"] == 0
    assert points_ta() == before - 5  # m6 had given 5 points to ta


def test_30_redo_requires_a_finished_match(client, admin):
    assert client.post("/api/matches/m8/redo", headers=admin,
                       json={"confirm": True}).status_code == 400


def test_31_wo_does_not_invent_individual_stats(client, admin):
    def stats_c1():
        return next(p for p in client.get("/api/stats/players").json()
                    if p["player_id"] == "c1")
    before = stats_c1()

    async def _seed():
        m = make_match("m9", 9, status="ENCERRADA", wo=True, wo_team_id="tc")
        m.update({"group": "B", "team_a": "tc", "team_b": "td",
                  "roster_a": ["c1", "c2", "c3"],
                  "roster_b": ["d1", "d2", "d3"]})
        await server.db.matches.insert_one(m)
    asyncio.run(_seed())

    after = stats_c1()
    assert after["matches"] == before["matches"]
    assert after["times_eliminated"] == 0
    assert after["team_wins"] == before["team_wins"]


def test_32_rules_and_banner_are_public(client):
    assert client.get("/api/rules").status_code == 200
    assert client.get("/api/banner").status_code == 200


def test_33_admin_edit_finished_keeps_it_finished(client, admin):
    entry = next(e for e in get(client, "m5")["eliminations"]
                 if e["eliminated_id"] == "b3")
    r = client.delete(
        f"/api/matches/m5/eliminations/{entry['id']}?keep_finished=true",
        headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "ENCERRADA"
    assert d["base_points_a"] == 2
    assert d["points_a"] == 1  # 2 base - 1 penalty applied in test_25
    assert d["perfect_a"] is False


def test_34_wo_match_rejects_eliminations(client, admin):
    r = client.post("/api/matches/m9/eliminate", headers=admin,
                    json={"eliminated_id": "c1"})
    assert r.status_code == 400, r.text
    assert get(client, "m9")["elims_a"] == 0


def test_35_startup_migration_preserves_results():
    async def _run():
        await server.db.matches.insert_one(make_match(
            "mig1", 99, status="ENCERRADA",
            ended_at="2026-01-01T00:10:00+00:00",
            points_a=5, points_b=1, winner_team_id="ta",
            eliminations=[{"id": f"me{i}", "eliminated_id": pid, "at_ms": 1000}
                          for i, pid in enumerate(("b1", "b2", "b3", "a1"))]))
        await server.migrate_structural_defaults()
        after = await server.db.matches.find_one({"id": "mig1"})
        assert (after["points_a"], after["points_b"],
                after["winner_team_id"]) == (5, 1, "ta")
        snapshot = {k: v for k, v in after.items() if k != "_id"}
        await server.migrate_structural_defaults()
        again = await server.db.matches.find_one({"id": "mig1"})
        assert {k: v for k, v in again.items() if k != "_id"} == snapshot
    asyncio.run(_run())


def test_36_undeclared_elimination_adds_elim_and_minus_one(client, admin):
    r = client.post("/api/matches/m8/undeclared", headers=admin, json={
        "player_id": "d3", "reason": "jogador não se acusou"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "ENCERRADA"
    assert d["elims_a"] == 3 and d["base_points_a"] == 5
    pen = d["penalties"][-1]
    assert pen["type"] == "ELIMINACAO_NAO_DECLARADA" and pen["points"] == 1
    assert d["points_b"] == 0  # 0 base - 1, floored at zero
    audit = client.get("/api/matches/m8/audit", headers=admin).json()["audit_log"]
    assert any(a["action"] == "UNDECLARED_ELIMINATION" for a in audit)


def test_37_recalculation_fixes_perfect_even_when_points_match(client, admin):
    async def _seed():
        await server.db.matches.insert_one(make_match(
            "mrec", 98, status="ENCERRADA",
            ended_at="2026-01-01T00:10:00+00:00",
            points_a=5, points_b=1, winner_team_id="ta", perfect_a=True,
            scoring_version=2,
            eliminations=[{"id": f"re{i}", "eliminated_id": pid, "at_ms": 1000}
                          for i, pid in enumerate(("b1", "b2", "b3", "a1"))]))
    asyncio.run(_seed())
    r = client.post("/api/admin/recalculate-scores", headers=admin,
                    json={"dry_run": False, "confirm": True})
    assert r.status_code == 200, r.text
    d = client.get("/api/matches/mrec").json()
    assert d["perfect_a"] is False
    assert (d["points_a"], d["points_b"]) == (5, 1)
    assert d["legacy_points_a"] == 5


def test_38_public_match_hides_audit_and_actor_identity(client, admin):
    pub = client.get("/api/matches/m8").json()
    assert "audit_log" not in pub
    assert all("by" not in e for e in pub["eliminations"])
    assert all("by" not in p for p in pub["penalties"])
    full = client.get("/api/matches/m8/audit", headers=admin).json()
    assert full["audit_log"]


def _restore(client, admin, mid, history_id, confirm=True):
    return client.post(f"/api/matches/{mid}/history/{history_id}/restore",
                       headers=admin, json={"confirm": confirm})


def _history(client, admin, mid):
    r = client.get(f"/api/matches/{mid}/history", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def test_39_admin_rollback_restores_one_match_and_is_idempotent(client, admin):
    async def _seed():
        await server.db.matches.insert_one(make_match(
            "mrb", 97, status="ENCERRADA", winner_team_id="ta",
            points_a=3, points_b=0, perfect_a=False,
            ended_at="2026-01-01T00:10:00+00:00",
            eliminations=[{"id": f"rb{i}", "eliminated_id": pid, "at_ms": 1000}
                          for i, pid in enumerate(("b1", "b2", "b3"))]))
    asyncio.run(_seed())
    r = client.post("/api/admin/recalculate-scores", headers=admin,
                    json={"dry_run": False, "confirm": True})
    assert r.status_code == 200, r.text
    assert (get(client, "mrb")["points_a"], get(client, "mrb")["points_b"]) == (5, 0)
    assert get(client, "mrb")["perfect_a"] is True

    other_after = get(client, "m1")["points_a"]
    rec = next(h for h in _history(client, admin, "mrb")
               if h.get("kind") == "RECALCULATION")
    assert _restore(client, admin, "mrb", rec["id"], confirm=False).status_code == 400

    r = _restore(client, admin, "mrb", rec["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["already_restored"] is False
    assert "points_a" in body["restored_fields"]

    d = get(client, "mrb")
    assert (d["points_a"], d["points_b"]) == (3, 0)
    assert d["winner_team_id"] == "ta" and d["perfect_a"] is False
    assert get(client, "m1")["points_a"] == other_after

    hist = _history(client, admin, "mrb")
    assert any(h.get("kind") == "RESTORE" and h.get("restored_from") == rec["id"]
               for h in hist)
    count = len(hist)
    again = _restore(client, admin, "mrb", rec["id"])
    assert again.status_code == 200 and again.json()["already_restored"] is True
    assert len(_history(client, admin, "mrb")) == count


def test_40_second_recalculation_keeps_previous_snapshot(client, admin):
    rec1 = next(h for h in _history(client, admin, "mrb")
                if h.get("kind") == "RECALCULATION")
    r = client.post("/api/admin/recalculate-scores", headers=admin,
                    json={"dry_run": False, "confirm": True})
    assert r.status_code == 200, r.text
    assert get(client, "mrb")["points_a"] == 5
    hist = _history(client, admin, "mrb")
    assert any(h["id"] == rec1["id"] for h in hist)  # first snapshot preserved
    rec2 = next(h for h in hist if h.get("kind") == "RECALCULATION"
                and h["id"] != rec1["id"])
    assert _restore(client, admin, "mrb", rec2["id"]).status_code == 200
    assert get(client, "mrb")["points_a"] == 3


def test_41_bracket_status_flags_mismatch(client):
    async def _seed():
        await server.db.matches.insert_one(make_match(
            "po1", 200, phase="SEMI", group=None, status="ENCERRADA",
            team_a="ta", team_b="zz", points_a=5, points_b=0,
            winner_team_id="ta"))
    asyncio.run(_seed())
    r = client.get("/api/bracket/status")
    assert r.status_code == 200, r.text
    assert r.json()["stale"] is True
    assert "mata-mata" in r.json()["reason"].lower()


def test_42_public_payload_never_exposes_tokens_or_auth_data(client):
    async def _seed():
        await server.db.matches.insert_one(make_match(
            "msec", 96, status="ENCERRADA", points_a=5, points_b=0,
            winner_team_id="ta",
            audit_log=[{"action": "PENALTY", "user_email": "admin@example.com"}],
            eliminations=[{"eliminated_id": "b1", "by": "admin@example.com",
                           "client_token": "secret-token"}],
            penalties=[{"team_id": "tb", "points": 1, "by": "admin@example.com",
                        "client_token": "secret-token"}]))
    asyncio.run(_seed())
    pub = client.get("/api/matches/msec").json()
    assert "audit_log" not in pub
    assert all("by" not in e and "client_token" not in e for e in pub["eliminations"])
    assert all("by" not in p and "client_token" not in p for p in pub["penalties"])
    assert "secret-token" not in client.get("/api/matches/msec").text
    assert "admin@example.com" not in client.get("/api/matches/msec").text

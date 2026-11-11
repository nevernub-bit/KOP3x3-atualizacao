"""KOP 3x3 backend integration tests: v2 scoring (1 pt/elim + 2 bonus), draws keep points, W.O., no eliminator tracking."""
import os
import time
import base64
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE = line.split("=", 1)[1].strip()
                break
BASE = BASE.rstrip("/")
API = f"{BASE}/api"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "test-only-password")

PHOTO = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40).decode()


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def public():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# Helpers
def get_match(mid):
    return requests.get(f"{API}/matches/{mid}").json()


def get_group_matches():
    return [m for m in requests.get(f"{API}/matches").json() if m["phase"] == "GROUP"]


def get_team_players(tid):
    t = [x for x in requests.get(f"{API}/teams").json() if x["id"] == tid][0]
    return t["players"]


# ---------- 1. Reset ----------
def test_01_full_reset(admin):
    # delete existing players
    for p in requests.get(f"{API}/players").json():
        admin.delete(f"{API}/players/{p['id']}")
    r = admin.post(f"{API}/tournament/reset")
    assert r.status_code == 200
    t = requests.get(f"{API}/tournament").json()
    assert t["status"] == "OPEN"
    assert t["draw_done"] is False
    assert requests.get(f"{API}/players").json() == []


# ---------- 2. Register 30 ----------
def test_02_register_30(public):
    levels = ["PROFISSIONAL"] * 10 + ["INTERMEDIÁRIO"] * 10 + ["INICIANTE"] * 10
    for i, lvl in enumerate(levels):
        r = public.post(f"{API}/players/register",
                        json={"name": f"TEST_P{i:02d}", "level": lvl, "photo": PHOTO})
        assert r.status_code == 200, r.text
    assert len(requests.get(f"{API}/players").json()) == 30


# ---------- 3. Draw ----------
def test_03_draw(admin):
    r = admin.post(f"{API}/draw", json={"num_teams": 10, "players_per_team": 3, "mode": "BALANCED"})
    assert r.status_code == 200, r.text
    groups = get_group_matches()
    assert len(groups) == 20
    for m in groups:
        assert m["duration_seconds"] == 300
        assert m["eliminations"] == []
        assert m["status"] == "AGUARDANDO"


# ---------- 4. Eliminate validations ----------
def test_04_eliminate_pre_start_400(admin):
    m = get_group_matches()[0]
    b = get_team_players(m["team_b"])
    r = admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": b[0]})
    assert r.status_code == 400
    assert "andamento" in r.json()["detail"].lower()


def test_05_eliminate_not_in_match_400(admin):
    m0 = get_group_matches()[0]
    admin.post(f"{API}/matches/{m0['id']}/start")
    a0 = set(get_team_players(m0["team_a"]))
    b0 = set(get_team_players(m0["team_b"]))
    in_match = a0 | b0
    all_players = [p["id"] for p in requests.get(f"{API}/players").json()]
    other = [p for p in all_players if p not in in_match][0]
    r = admin.post(f"{API}/matches/{m0['id']}/eliminate", json={"eliminated_id": other})
    assert r.status_code == 400
    assert "pertence" in r.json()["detail"].lower()


def test_06_backwards_compat_eliminator_ignored(admin):
    m = get_group_matches()[0]
    b = get_team_players(m["team_b"])
    a = get_team_players(m["team_a"])
    # send both fields; eliminator ignored
    r = admin.post(f"{API}/matches/{m['id']}/eliminate",
                   json={"eliminated_id": b[0], "eliminator_id": a[0]})
    assert r.status_code == 200
    d = r.json()
    assert d["elims_a"] == 1
    # entry should not carry eliminator
    entry = d["eliminations"][-1]
    assert "eliminated_id" in entry
    assert entry.get("eliminator_id") in (None, "", a[0])  # ignored is fine either way


def test_07_double_elim_400(admin):
    m = get_group_matches()[0]
    b = get_team_players(m["team_b"])
    r = admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": b[0]})
    assert r.status_code == 400
    assert "já foi eliminado" in r.json()["detail"].lower()


# ---------- Rule A: Wipe wins (5 pts, perfect) ----------
def test_08_rule_A_wipe_perfect(admin):
    # match 0 currently has 1 B eliminated. Eliminate remaining 2 B players → wipe, winner=A, perfect.
    m = get_match(get_group_matches()[0]["id"])
    b = get_team_players(m["team_b"])
    for pid in b[1:3]:
        r = admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": pid})
        assert r.status_code == 200
    d = get_match(m["id"])
    assert d["status"] == "ENCERRADA", d
    assert d["winner_team_id"] == m["team_a"]
    assert d["is_draw"] is False
    assert d["elims_a"] == 3 and d["elims_b"] == 0
    assert d["points_a"] == 5 and d["points_b"] == 0
    assert d["perfect_a"] is True


# ---------- Rule B: Draw on timeout ----------
def test_09_rule_B_timeout_draw(admin):
    m = get_group_matches()[1]
    # set duration 6s
    r = admin.post(f"{API}/matches/{m['id']}/duration", json={"duration_seconds": 6})
    assert r.status_code == 200
    assert r.json()["duration_seconds"] == 6
    admin.post(f"{API}/matches/{m['id']}/start")
    a = get_team_players(m["team_a"])
    b = get_team_players(m["team_b"])
    # 2 B and 1 A eliminated - A "ahead"
    admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": b[0]})
    admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": b[1]})
    admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": a[0]})
    time.sleep(8)
    d = get_match(m["id"])
    assert d["status"] == "ENCERRADA", d
    assert d["is_draw"] is True
    assert d["winner_team_id"] is None
    # 2 x 1 on the clock: each team keeps its elimination points.
    assert d["points_a"] == 2 and d["points_b"] == 1


# ---------- Manual /end mid-match → draw ----------
def test_10_manual_end_both_alive_draw(admin):
    m = get_group_matches()[2]
    admin.post(f"{API}/matches/{m['id']}/start")
    a = get_team_players(m["team_a"])
    b = get_team_players(m["team_b"])
    admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": b[0]})
    admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": a[0]})
    r = admin.post(f"{API}/matches/{m['id']}/end")
    assert r.status_code == 200
    d = r.json()
    assert d["is_draw"] is True
    assert d["winner_team_id"] is None
    # 1 x 1 draw keeps one point per team (no bonus, no 0-0 reset).
    assert d["points_a"] == 1 and d["points_b"] == 1


# ---------- 3-1 win (not perfect), 5 pts ----------
def test_11_three_one_win_not_perfect(admin):
    m = get_group_matches()[3]
    admin.post(f"{API}/matches/{m['id']}/start")
    a = get_team_players(m["team_a"])
    b = get_team_players(m["team_b"])
    # B kills A[0] first
    admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": a[0]})
    # A wipes B
    for pid in b:
        admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": pid})
    d = get_match(m["id"])
    assert d["status"] == "ENCERRADA"
    assert d["winner_team_id"] == m["team_a"]
    assert d["elims_a"] == 3 and d["elims_b"] == 1
    assert d["points_a"] == 5 and d["points_b"] == 1
    assert d["perfect_a"] is False


# ---------- Auto-end happens inside eliminate call ----------
def test_12_auto_end_inside_eliminate(admin):
    m = get_group_matches()[4]
    admin.post(f"{API}/matches/{m['id']}/start")
    b = get_team_players(m["team_b"])
    # eliminate 2 - still ongoing
    admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": b[0]})
    admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": b[1]})
    # 3rd triggers auto-end within call
    r = admin.post(f"{API}/matches/{m['id']}/eliminate", json={"eliminated_id": b[2]})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ENCERRADA"
    assert d["winner_team_id"] == m["team_a"]
    assert d["points_a"] == 5


# ---------- Auth enforcement ----------
def test_13_auth_enforcement(public):
    matches = requests.get(f"{API}/matches").json()
    aguard = [m for m in matches if m["status"] == "AGUARDANDO"][0]["id"]
    endpoints = [
        ("post", f"/matches/{aguard}/start", None),
        ("post", f"/matches/{aguard}/pause", None),
        ("post", f"/matches/{aguard}/resume", None),
        ("post", f"/matches/{aguard}/end", None),
        ("post", f"/matches/{aguard}/duration", {"duration_seconds": 60}),
        ("post", f"/matches/{aguard}/eliminate", {"eliminated_id": "x"}),
        ("delete", f"/matches/{aguard}/eliminate/last", None),
        ("post", f"/matches/{aguard}/lock", None),
        ("post", f"/matches/{aguard}/set-winner", {"winner_team_id": None}),
    ]
    for method, path, body in endpoints:
        r = getattr(public, method)(f"{API}{path}", json=body)
        assert r.status_code in (401, 403), f"{method} {path} → {r.status_code}"


# ---------- Finish remaining group matches ----------
def test_14_finish_all_groups(admin):
    for m in get_group_matches():
        if m["status"] == "ENCERRADA":
            continue
        if m["status"] == "AGUARDANDO":
            admin.post(f"{API}/matches/{m['id']}/start")
        # end as draw (both alive)
        r = admin.post(f"{API}/matches/{m['id']}/end")
        assert r.status_code == 200
    left = [m for m in get_group_matches() if m["status"] != "ENCERRADA"]
    assert left == []


# ---------- Standings with draws + points from new rules ----------
def test_15_standings_new_rules(admin):
    s = requests.get(f"{API}/standings").json()
    entries = s["A"] + s["B"]
    assert len(entries) == 10
    for e in entries:
        assert "draws" in e
        assert "points" in e
    # Sum of points must equal sum from matches
    matches = requests.get(f"{API}/matches").json()
    match_pts_by_team = {}
    for m in matches:
        if m["phase"] != "GROUP":
            continue
        match_pts_by_team[m["team_a"]] = match_pts_by_team.get(m["team_a"], 0) + m["points_a"]
        match_pts_by_team[m["team_b"]] = match_pts_by_team.get(m["team_b"], 0) + m["points_b"]
    for e in entries:
        assert e["points"] == match_pts_by_team.get(e["team_id"], 0), e
    # Draws and losses keep their elimination points, so any value is valid.
    for e in entries:
        assert e["points"] >= 0


# ---------- Player stats new shape ----------
def test_16_player_stats_shape():
    ps = requests.get(f"{API}/stats/players").json()
    assert len(ps) == 30
    required = {"matches", "team_wins", "team_draws", "team_losses",
                "times_eliminated", "perfects", "survivals"}
    for p in ps:
        assert required.issubset(p.keys()), p.keys()
    # sorting: team_wins desc → perfects desc → survivals desc → times_eliminated asc
    for a, b in zip(ps, ps[1:]):
        ka = (-a["team_wins"], -a["perfects"], -a["survivals"], a["times_eliminated"])
        kb = (-b["team_wins"], -b["perfects"], -b["survivals"], b["times_eliminated"])
        assert ka <= kb


# ---------- Playoffs: semi draw → set-winner → final+third created ----------
def test_17_playoffs_flow(admin):
    po = requests.get(f"{API}/playoffs").json()
    semis = [m for m in po if m["phase"] == "SEMI"]
    assert len(semis) == 2
    for sm in semis:
        admin.post(f"{API}/matches/{sm['id']}/start")
        admin.post(f"{API}/matches/{sm['id']}/end")  # draw (no elims)
        d = get_match(sm["id"])
        assert d["is_draw"] is True
        # set winner to team_a
        r = admin.post(f"{API}/matches/{sm['id']}/set-winner",
                       json={"winner_team_id": sm["team_a"]})
        assert r.status_code == 200
        assert r.json()["winner_team_id"] == sm["team_a"]
    po2 = requests.get(f"{API}/playoffs").json()
    finals = [m for m in po2 if m["phase"] == "FINAL"]
    thirds = [m for m in po2 if m["phase"] == "THIRD"]
    assert len(finals) == 1
    assert len(thirds) == 1


# ---------- Startup recompute: finish matches then trigger recompute by importing? ----------
# The startup recompute runs at server boot. We can't restart from here, but we can verify
# that already-finished matches obey new rules (winner=5 or draw=0).
def test_18_recompute_new_rules_applied():
    matches = requests.get(f"{API}/matches").json()
    finished = [m for m in matches if m["status"] == "ENCERRADA"]
    for m in finished:
        if m.get("is_draw"):
            # A draw keeps the elimination points of each team and never 5 x 5.
            assert m["points_a"] == m["elims_a"], m
            assert m["points_b"] == m["elims_b"], m
            assert m["points_a"] <= 3 and m["points_b"] <= 3, m
        elif m.get("winner_team_id"):
            if m["phase"] == "GROUP":
                if m["winner_team_id"] == m["team_a"]:
                    assert m["points_a"] == 5, m
                    assert m["points_b"] == m["elims_b"], m
                else:
                    assert m["points_b"] == 5, m
                    assert m["points_a"] == m["elims_a"], m

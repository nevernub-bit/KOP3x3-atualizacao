"""Configurable tournament structure.

Scenarios:
  A) 10 teams x 3 players, 2 groups, 2 qualifiers/group  -> 20 group matches, semis
  B) 10 teams x 3 players, 1 group,  4 qualifiers       -> 45 group matches, semis
  C)  8 teams x 3 players, 1 group,  4 qualifiers       -> 28 group matches, semis
  D) 12 teams x 3 players, 2 groups, 2 qualifiers/group -> 30 group matches, semis
Extra: 8 qualifiers -> quarter-finals; 2 qualifiers -> final only.
Also covers admin profile editing (same id, same team, matches/stats untouched).
"""
import os
import base64
import uuid
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://127.0.0.1:8002").rstrip("/")
API = f"{BASE}/api"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "test-only-password")

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()
PHOTO = f"data:image/png;base64,{_PNG}"
GROUP_LETTERS = "ABCDEFGHIJKLMNOP"


def _ip():
    h = uuid.uuid4().int
    return f"10.9.{h % 250}.{(h >> 8) % 250}"


@pytest.fixture(scope="module")
def admin():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      headers={"X-Forwarded-For": _ip()})
    assert r.status_code == 200, r.text
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {r.json()['access_token']}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="module", autouse=True)
def restore_structure(admin):
    yield
    admin.post(f"{API}/tournament/reset")
    for p in requests.get(f"{API}/players", headers=admin.headers).json():
        admin.delete(f"{API}/players/{p['id']}")
    admin.patch(f"{API}/tournament", json={
        "num_teams": 10, "players_per_team": 3,
        "num_groups": 2, "qualifiers_per_group": 2,
    })


def _clear(admin):
    admin.post(f"{API}/tournament/reset")
    for p in requests.get(f"{API}/players", headers=admin.headers).json():
        admin.delete(f"{API}/players/{p['id']}")
    admin.patch(f"{API}/tournament", json={
        "num_teams": 10, "players_per_team": 3,
        "num_groups": 2, "qualifiers_per_group": 2,
    })


def _register(n, prefix="CFG"):
    for i in range(n):
        r = requests.post(f"{API}/players/register", json={
            "name": f"{prefix}_{i:03d}_{uuid.uuid4().hex[:4]}",
            "level": ["PROFISSIONAL", "INTERMEDIÁRIO", "INICIANTE"][i % 3],
            "photo": PHOTO,
        }, headers={"X-Forwarded-For": _ip()})
        assert r.status_code == 200, f"register {i}: {r.status_code} {r.text}"


def _config(admin, num_teams, ppt, groups, qpg):
    r = admin.patch(f"{API}/tournament", json={
        "num_teams": num_teams, "players_per_team": ppt,
        "num_groups": groups, "qualifiers_per_group": qpg,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["capacity"] == num_teams * ppt
    assert d["qualifiers_total"] == groups * qpg
    return d


def _draw(admin, num_teams, ppt, groups, qpg, mode="BALANCED"):
    r = admin.post(f"{API}/draw", json={
        "num_teams": num_teams, "players_per_team": ppt,
        "num_groups": groups, "qualifiers_per_group": qpg, "mode": mode,
    })
    assert r.status_code == 200, r.text


def _all_matches():
    return requests.get(f"{API}/matches").json()


def _finish_all_group(admin):
    for m in _all_matches():
        if m["phase"] != "GROUP" or m["status"] == "ENCERRADA":
            continue
        if m["status"] == "AGUARDANDO":
            assert admin.post(f"{API}/matches/{m['id']}/start").status_code == 200
        assert admin.post(f"{API}/matches/{m['id']}/end").status_code == 200


def _finish_round(admin, phase):
    ms = [m for m in _all_matches() if m["phase"] == phase]
    assert ms, f"no {phase} matches"
    for m in ms:
        if m["status"] != "ENCERRADA":
            admin.post(f"{API}/matches/{m['id']}/start")
            admin.post(f"{API}/matches/{m['id']}/end")
        d = requests.get(f"{API}/matches/{m['id']}").json()
        if not d.get("winner_team_id"):
            r = admin.post(f"{API}/matches/{m['id']}/set-winner",
                           json={"winner_team_id": d["team_a"]})
            assert r.status_code == 200, r.text


def _run_scenario(admin, num_teams, ppt, groups, qpg, expected_group_matches, first_phase):
    _clear(admin)
    total = num_teams * ppt
    _config(admin, num_teams, ppt, groups, qpg)
    _register(total, prefix=f"S{num_teams}x{ppt}G{groups}Q{qpg}")
    players = requests.get(f"{API}/players", headers=admin.headers).json()
    assert len(players) == total
    _draw(admin, num_teams, ppt, groups, qpg)

    teams = requests.get(f"{API}/teams").json()
    assert len(teams) == num_teams
    for t in teams:
        assert len(t["players"]) == ppt, f"{t['name']} has {len(t['players'])} players"
        assert t["group"] in GROUP_LETTERS[:groups], t

    group_ms = [m for m in _all_matches() if m["phase"] == "GROUP"]
    assert len(group_ms) == expected_group_matches
    seen = set()
    for m in group_ms:
        key = tuple(sorted([m["team_a"], m["team_b"]]))
        assert key not in seen, "same pair scheduled twice inside a group"
        seen.add(key)

    st = requests.get(f"{API}/standings").json()
    assert sorted(st.keys()) == list(GROUP_LETTERS[:groups])
    assert sum(len(v) for v in st.values()) == num_teams
    for rows in st.values():
        assert num_teams // groups <= len(rows) <= num_teams // groups + 1

    _finish_all_group(admin)
    po = requests.get(f"{API}/playoffs").json()
    first = [m for m in po if m["phase"] == first_phase]
    assert len(first) == (groups * qpg) // 2, po
    assert requests.get(f"{API}/tournament").json()["status"] == "PLAYOFFS"
    return st, po


# ---------------- Scenario A ----------------
def test_scenario_A_10x3_two_groups_two_qualifiers(admin):
    _st, po = _run_scenario(admin, 10, 3, 2, 2, 20, "SEMI")
    assert len([m for m in po if m["phase"] == "SEMI"]) == 2
    _finish_round(admin, "SEMI")
    po2 = requests.get(f"{API}/playoffs").json()
    assert len([m for m in po2 if m["phase"] == "FINAL"]) == 1
    assert len([m for m in po2 if m["phase"] == "THIRD"]) == 1
    _finish_round(admin, "FINAL")
    ch = requests.get(f"{API}/champion").json()
    assert ch["first"]
    assert requests.get(f"{API}/tournament").json()["status"] == "FINISHED"


# ---------------- Scenario B ----------------
def test_scenario_B_10x3_single_group_four_qualifiers(admin):
    _st, po = _run_scenario(admin, 10, 3, 1, 4, 45, "SEMI")
    assert len([m for m in po if m["phase"] == "SEMI"]) == 2


# ---------------- Scenario C ----------------
def test_scenario_C_8x3_single_group_four_qualifiers(admin):
    _st, po = _run_scenario(admin, 8, 3, 1, 4, 28, "SEMI")
    assert len([m for m in po if m["phase"] == "SEMI"]) == 2


# ---------------- Scenario D ----------------
def test_scenario_D_12x3_two_groups_two_qualifiers(admin):
    _st, po = _run_scenario(admin, 12, 3, 2, 2, 30, "SEMI")
    assert len([m for m in po if m["phase"] == "SEMI"]) == 2


# ---------------- 8 qualifiers -> quarter-finals ----------------
def test_scenario_E_8x3_single_group_eight_qualifiers(admin):
    _st, po = _run_scenario(admin, 8, 3, 1, 8, 28, "QF")
    assert len([m for m in po if m["phase"] == "QF"]) == 4
    _finish_round(admin, "QF")
    po2 = requests.get(f"{API}/playoffs").json()
    assert len([m for m in po2 if m["phase"] == "SEMI"]) == 2
    assert not [m for m in po2 if m["phase"] == "THIRD"], "third place only after semis"
    _finish_round(admin, "SEMI")
    po3 = requests.get(f"{API}/playoffs").json()
    assert len([m for m in po3 if m["phase"] == "FINAL"]) == 1
    assert len([m for m in po3 if m["phase"] == "THIRD"]) == 1
    _finish_round(admin, "FINAL")
    assert requests.get(f"{API}/champion").json()["first"]
    assert requests.get(f"{API}/tournament").json()["status"] == "FINISHED"


# ---------------- 2 qualifiers -> final only ----------------
def test_scenario_F_4x3_single_group_two_qualifiers(admin):
    _st, po = _run_scenario(admin, 4, 3, 1, 2, 6, "FINAL")
    assert len([m for m in po if m["phase"] == "FINAL"]) == 1
    assert not [m for m in po if m["phase"] in ("SEMI", "THIRD")]
    _finish_round(admin, "FINAL")
    assert requests.get(f"{API}/champion").json()["first"]
    assert requests.get(f"{API}/tournament").json()["status"] == "FINISHED"


# ---------------- Structure validation + excess players ----------------
def test_config_validation_and_excess_players(admin):
    _clear(admin)
    _register(30, prefix="VALID")

    r = admin.patch(f"{API}/tournament", json={"num_teams": 8, "players_per_team": 3})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "excedem" in detail and "24" in detail and "30" in detail
    t = requests.get(f"{API}/tournament").json()
    assert (t["num_teams"], t["players_per_team"]) == (10, 3)

    for payload in ({"num_groups": 3, "qualifiers_per_group": 4},
                    {"num_groups": 2, "qualifiers_per_group": 3},
                    {"num_teams": 67}):
        r = admin.patch(f"{API}/tournament", json=payload)
        assert r.status_code == 400, (payload, r.status_code, r.text)

    r = admin.patch(f"{API}/tournament", json={"num_groups": 1, "qualifiers_per_group": 4})
    assert r.status_code == 200, r.text
    assert r.json()["qualifiers_total"] == 4
    assert r.json()["player_limit"] == 30

    r = requests.post(f"{API}/players/register", json={
        "name": "EXTRA", "level": "INICIANTE", "photo": PHOTO,
    }, headers={"X-Forwarded-For": _ip()})
    assert r.status_code == 400 and "Limite" in r.json()["detail"]

    r = admin.patch(f"{API}/tournament", json={"num_groups": 2, "qualifiers_per_group": 2})
    assert r.status_code == 200
    _draw(admin, 10, 3, 2, 2)

    r = admin.patch(f"{API}/tournament", json={"num_teams": 12})
    assert r.status_code == 409, r.text
    assert "Reset" in r.json()["detail"]


# ---------------- Admin profile edit ----------------
def test_admin_edits_registration_preserving_links(admin):
    _clear(admin)
    _register(30, prefix="EDIT")
    _config(admin, 10, 3, 2, 2)
    _draw(admin, 10, 3, 2, 2)

    players = requests.get(f"{API}/players", headers=admin.headers).json()
    target = players[0]
    pid, team_id = target["id"], target["team_id"]
    assert team_id

    matches_before = _all_matches()
    refs_before = sum(1 for m in matches_before if team_id in (m["team_a"], m["team_b"]))
    stats_before = requests.get(f"{API}/stats/players").json()
    stat_before = next(s for s in stats_before if s["player_id"] == pid)

    new_photo = f"data:image/png;base64,{base64.b64encode(b'PNGDATA' + b'Z' * 40).decode()}"
    payload = {
        "name": "Nome Editado", "nickname": "NickEdit", "level": "PROFISSIONAL",
        "whatsapp": "+55 11 91234-5678", "notes": "observacao editada", "photo": new_photo,
    }
    r = admin.patch(f"{API}/players/{pid}", json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["id"] == pid
    assert d["team_id"] == team_id
    for k, v in payload.items():
        assert d[k] == v, f"{k}: {d.get(k)!r} != {v!r}"

    got = requests.get(f"{API}/players/{pid}", headers=admin.headers).json()
    assert got["name"] == "Nome Editado" and got["photo"] == new_photo

    team = next(t for t in requests.get(f"{API}/teams").json() if t["id"] == team_id)
    assert pid in team["players"], "edit removed the player from the team"
    assert team["players"].count(pid) == 1

    matches_after = _all_matches()
    assert len(matches_after) == len(matches_before)
    assert sum(1 for m in matches_after if team_id in (m["team_a"], m["team_b"])) == refs_before

    stats_after = requests.get(f"{API}/stats/players").json()
    assert len(stats_after) == len(stats_before) == 30
    stat_after = next(s for s in stats_after if s["player_id"] == pid)
    assert stat_after["team_id"] == stat_before["team_id"] == team_id

    # Optional fields can be cleared explicitly.
    r = admin.patch(f"{API}/players/{pid}", json={"nickname": None, "notes": None})
    assert r.status_code == 200
    assert r.json()["nickname"] is None and r.json()["notes"] is None

    # Photo validation mirrors registration.
    r = admin.patch(f"{API}/players/{pid}", json={"photo": "not-an-image"})
    assert r.status_code == 400

    # Anonymous users cannot edit.
    assert requests.patch(f"{API}/players/{pid}", json={"name": "x"}).status_code == 401


def test_zz_restore_defaults(admin):
    _clear(admin)
    t = requests.get(f"{API}/tournament").json()
    assert (t["num_teams"], t["players_per_team"],
            t["num_groups"], t["qualifiers_per_group"]) == (10, 3, 2, 2)

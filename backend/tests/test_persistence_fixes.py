"""Persistence / migration regression tests (P0 + P1 + P2 fixes).

Must run against a DISPOSABLE database only:
  - startup must never rewrite finished matches;
  - playoff winners set manually survive restarts;
  - roster changes do not rewrite history;
  - undo elimination keeps the match state consistent;
  - POST /matches/{id}/end rejects an AGUARDANDO match;
  - GET /players supports conditional revalidation (304) so the Telão does not
    resend base64 photos on every poll.
"""
import os
import json
import base64
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"

BASE = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE:
    for candidate in (REPO_ROOT / "frontend" / ".env", BACKEND_DIR / ".env"):
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE = line.split("=", 1)[1].strip().strip('"')
                    break
        if BASE:
            break
BASE = (BASE or "http://127.0.0.1:8001").rstrip("/")
API = f"{BASE}/api"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "test-only-password")

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"P" * 20).decode()
TINY_PHOTO = f"data:image/png;base64,{_PNG}"

_ip_counter = 0


def _uniq_ip():
    global _ip_counter
    _ip_counter += 1
    h = uuid.uuid4().int
    return f"10.30.{_ip_counter % 250}.{h % 250}"


@pytest.fixture(scope="session")
def admin_h():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      headers={"X-Forwarded-For": _uniq_ip()})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _reset(admin_h):
    assert requests.post(f"{API}/tournament/reset", headers=admin_h).status_code == 200
    for p in requests.get(f"{API}/players", headers=admin_h).json():
        requests.delete(f"{API}/players/{p['id']}", headers=admin_h)
    requests.patch(f"{API}/tournament", json={"player_limit": 60}, headers=admin_h)


def _register(admin_h, n=30):
    levels = ["PROFISSIONAL", "INTERMEDIÁRIO", "INICIANTE"]
    for i in range(n):
        body = {"name": f"TEST_PERS_{i:02d}_{uuid.uuid4().hex[:5]}",
                "level": levels[i % 3], "photo": TINY_PHOTO}
        r = requests.post(f"{API}/players/register", json=body,
                          headers={"X-Forwarded-For": _uniq_ip()})
        assert r.status_code == 200, f"register #{i}: {r.status_code} {r.text}"


def _matches():
    return requests.get(f"{API}/matches").json()


def _group_matches(status=None):
    ms = [m for m in _matches() if m["phase"] == "GROUP"]
    return [m for m in ms if m["status"] == status] if status else ms


def _teams():
    return {t["id"]: t for t in requests.get(f"{API}/teams").json()}


def _get_match(mid):
    r = requests.get(f"{API}/matches/{mid}")
    assert r.status_code == 200, r.text
    return r.json()


def _history_snapshot():
    """Match documents without the derived timing fields."""
    out = {}
    for m in _matches():
        d = dict(m)
        d.pop("elapsed_ms", None)
        d.pop("remaining_ms", None)
        out[m["id"]] = d
    return out


def _run_startup_once():
    """Simulate a real restart: fresh process importing server and running startup."""
    code = "import asyncio, server\nasyncio.run(server.startup())\nprint('startup-ok')\n"
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(BACKEND_DIR),
                          env=os.environ.copy(), capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, f"startup failed:\n{proc.stdout}\n{proc.stderr}"
    assert "startup-ok" in proc.stdout


# ---------------------------------------------------------------------------
def test_01_setup_tournament(admin_h):
    _reset(admin_h)
    _register(admin_h, 30)
    r = requests.post(f"{API}/draw",
                      json={"num_teams": 10, "players_per_team": 3, "mode": "BALANCED"},
                      headers=admin_h)
    assert r.status_code == 200, r.text
    groups = _group_matches()
    assert len(groups) == 20, f"expected 20 group matches, got {len(groups)}"


def test_02_end_rejects_waiting_match(admin_h):
    m = _group_matches("AGUARDANDO")[0]
    r = requests.post(f"{API}/matches/{m['id']}/end", headers=admin_h)
    assert r.status_code == 400, f"end of AGUARDANDO must be rejected: {r.status_code} {r.text}"
    after = _get_match(m["id"])
    assert after["status"] == "AGUARDANDO"
    assert after["points_a"] == 0 and after["points_b"] == 0
    assert after["is_draw"] is False
    assert after["winner_team_id"] is None


def test_03_undo_keeps_match_consistent(admin_h):
    m = _group_matches("AGUARDANDO")[0]
    teams = _teams()
    team_b_players = teams[m["team_b"]]["players"]

    assert requests.post(f"{API}/matches/{m['id']}/start", headers=admin_h).status_code == 200
    for pid in team_b_players:
        r = requests.post(f"{API}/matches/{m['id']}/eliminate",
                          json={"eliminated_id": pid}, headers=admin_h)
        assert r.status_code == 200, r.text

    done = _get_match(m["id"])
    assert done["status"] == "ENCERRADA", done
    assert done["winner_team_id"] == m["team_a"]
    assert done["points_a"] == 5 and done["points_b"] == 0
    assert done["perfect_a"] is True

    r = requests.delete(f"{API}/matches/{m['id']}/eliminate/last", headers=admin_h)
    assert r.status_code == 200, r.text
    undone = r.json()

    # Reopened, no stale winner/points/perfect left behind.
    assert undone["status"] == "EM_ANDAMENTO", f"stale status: {undone['status']}"
    assert undone["winner_team_id"] is None, "stale winner after undo"
    assert undone["is_draw"] is True, "draw flag not recomputed"
    assert undone["points_a"] == 0 and undone["points_b"] == 0, "stale points after undo"
    assert undone["perfect_a"] is False and undone["perfect_b"] is False
    assert undone["ended_at"] is None
    assert undone["elims_a"] == 2 and undone["elims_b"] == 0
    assert len(undone["eliminated_players_b"]) == 2

    r = requests.post(f"{API}/matches/{m['id']}/eliminate",
                      json={"eliminated_id": team_b_players[-1]}, headers=admin_h)
    assert r.status_code == 200, r.text
    redone = r.json()
    assert redone["status"] == "ENCERRADA"
    assert redone["winner_team_id"] == m["team_a"]
    assert redone["points_a"] == 5
    assert redone["perfect_a"] is True


def test_04_finish_remaining_groups(admin_h):
    for m in _group_matches():
        latest = _get_match(m["id"])
        if latest["status"] == "ENCERRADA":
            continue
        if latest["status"] == "AGUARDANDO":
            assert requests.post(f"{API}/matches/{latest['id']}/start",
                                 headers=admin_h).status_code == 200
        r = requests.post(f"{API}/matches/{latest['id']}/end", headers=admin_h)
        assert r.status_code == 200, r.text
    left = [m for m in _group_matches() if _get_match(m["id"])["status"] != "ENCERRADA"]
    assert left == []


def test_05_playoffs_set_winner(admin_h):
    playoffs = requests.get(f"{API}/playoffs").json()
    semis = [m for m in playoffs if m["phase"] == "SEMI"]
    assert len(semis) == 2, f"semis not generated: {playoffs}"
    for sm in semis:
        assert requests.post(f"{API}/matches/{sm['id']}/start", headers=admin_h).status_code == 200
        assert requests.post(f"{API}/matches/{sm['id']}/end", headers=admin_h).status_code == 200
        drawn = _get_match(sm["id"])
        assert drawn["is_draw"] is True
        r = requests.post(f"{API}/matches/{sm['id']}/set-winner",
                          json={"winner_team_id": sm["team_a"]}, headers=admin_h)
        assert r.status_code == 200, r.text
        assert r.json()["winner_team_id"] == sm["team_a"]

    playoffs = requests.get(f"{API}/playoffs").json()
    assert any(m["phase"] == "FINAL" for m in playoffs), "final not created"
    assert any(m["phase"] == "THIRD" for m in playoffs), "third place not created"


def test_06_startup_twice_preserves_history(admin_h):
    before = _history_snapshot()
    semis_before = {m["id"]: m.get("winner_team_id")
                    for m in _matches() if m["phase"] == "SEMI"}

    _run_startup_once()
    after_first = _history_snapshot()
    _run_startup_once()
    after_second = _history_snapshot()

    assert after_first == before, "startup #1 changed match documents"
    assert after_second == before, "startup #2 changed match documents"

    semis_after = {m["id"]: m.get("winner_team_id")
                   for m in _matches() if m["phase"] == "SEMI"}
    assert semis_after == semis_before
    assert all(v for v in semis_after.values()), "set-winner lost after restart"

    finished = [m for m in before.values() if m["status"] == "ENCERRADA"]
    assert finished, "expected finished matches in the snapshot"


def test_07_roster_change_does_not_rewrite_history(admin_h):
    finished_group = next(m for m in _group_matches() if _get_match(m["id"])["status"] == "ENCERRADA")
    before = _get_match(finished_group["id"])

    teams = _teams()
    roster_before = list(teams[finished_group["team_a"]]["players"])
    victim = roster_before[0]
    assert requests.delete(f"{API}/players/{victim}", headers=admin_h).status_code == 200

    teams_after_delete = _teams()
    assert victim not in teams_after_delete[finished_group["team_a"]]["players"], \
        "roster did not change; test would not prove anything"

    _run_startup_once()
    _run_startup_once()

    after = _get_match(finished_group["id"])
    for key in ("status", "winner_team_id", "is_draw", "points_a", "points_b",
                "elims_a", "elims_b", "perfect_a", "perfect_b", "ended_at",
                "eliminated_players_a", "eliminated_players_b"):
        assert after[key] == before[key], f"history rewritten: {key} {before[key]!r} -> {after[key]!r}"
    assert len(after["eliminations"]) == len(before["eliminations"])


def test_08_players_conditional_payload(admin_h):
    anon = requests.get(f"{API}/players")
    assert anon.status_code == 200
    etag = anon.headers.get("ETag")
    assert etag, "GET /players must expose an ETag"
    assert "must-revalidate" in anon.headers.get("Cache-Control", "")
    payload = anon.json()
    assert payload and any(str(p.get("photo", "")).startswith("data:image") for p in payload)

    revalidated = requests.get(f"{API}/players", headers={"If-None-Match": etag})
    assert revalidated.status_code == 304, f"expected 304, got {revalidated.status_code}"
    assert revalidated.content == b"", "304 must not carry a body"

    admin = requests.get(f"{API}/players", headers=admin_h)
    assert admin.status_code == 200
    assert admin.headers.get("ETag") != etag, "admin payload must not share the public ETag"

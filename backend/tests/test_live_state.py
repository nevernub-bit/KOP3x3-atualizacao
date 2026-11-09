"""Tests for KOP LIVE controller endpoints (iteration 5).

Covers:
- GET /api/live/state (public)
- POST /api/live/state (admin) with exclude_unset semantics
- POST /api/live/load-next (admin)
- POST /api/matches/{id}/start auto-pins the Telão
- Auth enforcement
- Light regression on read endpoints
"""
import os
import base64
import uuid
import pytest
import requests

# Load BASE_URL from the environment, falling back to frontend/.env
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"')
BASE_URL = BASE_URL.rstrip("/")

API = f"{BASE_URL}/api"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "test-only-password")

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"A" * 20).decode()
TINY_PHOTO = f"data:image/png;base64,{_PNG}"


def _uniq_ip():
    # use 10.5.x.y range to isolate from other test suites
    h = uuid.uuid4().int
    return f"10.5.{h % 250}.{(h >> 8) % 250}"


@pytest.fixture(scope="session")
def admin_h():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      headers={"X-Forwarded-For": _uniq_ip()})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="session", autouse=True)
def fresh_tournament(admin_h):
    """Reset tournament & clear players to get a deterministic state."""
    r = requests.post(f"{API}/tournament/reset", headers=admin_h)
    assert r.status_code == 200, r.text
    players = requests.get(f"{API}/players", headers=admin_h).json()
    for p in players:
        requests.delete(f"{API}/players/{p['id']}", headers=admin_h)
    yield


def _register_players(admin_h, n=30):
    for i in range(n):
        body = {
            "name": f"TEST_LIVE_{i:02d}_{uuid.uuid4().hex[:6]}",
            "level": ["INICIANTE", "INTERMEDIÁRIO", "PROFISSIONAL"][i % 3],
            "photo": TINY_PHOTO,
        }
        r = requests.post(f"{API}/players/register", json=body,
                          headers={"X-Forwarded-For": _uniq_ip()})
        assert r.status_code == 200, f"register #{i}: {r.status_code} {r.text}"


@pytest.fixture(scope="session")
def with_draw(admin_h):
    """Ensure 30 players + a draw has happened so matches exist."""
    _register_players(admin_h, 30)
    r = requests.post(f"{API}/draw",
                      json={"num_teams": 10, "players_per_team": 3, "mode": "BALANCED"},
                      headers=admin_h)
    assert r.status_code == 200, f"draw failed: {r.status_code} {r.text}"
    ms = requests.get(f"{API}/matches").json()
    assert len(ms) > 0, "draw produced no matches"
    return ms


# --------------------------------------------------------------------------
# 1) GET /live/state — public, defaults
# --------------------------------------------------------------------------
class TestLiveStateGet:
    def test_get_public_no_auth(self):
        r = requests.get(f"{API}/live/state")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "mode" in data and "match_id" in data
        assert data["mode"] in ("MATCH", "STANDINGS")

    def test_defaults_after_reset(self, admin_h):
        requests.post(f"{API}/tournament/reset", headers=admin_h)
        r = requests.get(f"{API}/live/state")
        data = r.json()
        assert data["mode"] == "MATCH"
        assert data["match_id"] is None


# --------------------------------------------------------------------------
# 2) POST /live/state — auth
# --------------------------------------------------------------------------
class TestLiveStateAuth:
    def test_post_state_requires_admin(self):
        r = requests.post(f"{API}/live/state", json={"mode": "STANDINGS"})
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_post_state_with_admin(self, admin_h):
        r = requests.post(f"{API}/live/state", json={"mode": "STANDINGS"},
                          headers=admin_h)
        assert r.status_code == 200, r.text
        assert r.json()["mode"] == "STANDINGS"

    def test_load_next_requires_admin(self):
        r = requests.post(f"{API}/live/load-next")
        assert r.status_code in (401, 403)


# --------------------------------------------------------------------------
# 3) POST /live/state — full behavior + exclude_unset preservation
# --------------------------------------------------------------------------
class TestLiveStateSet:
    def test_set_mode_and_match_id(self, admin_h, with_draw):
        first = with_draw[0]
        r = requests.post(f"{API}/live/state",
                          json={"mode": "MATCH", "match_id": first["id"]},
                          headers=admin_h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "MATCH"
        assert data["match_id"] == first["id"]
        # GET reflects
        g = requests.get(f"{API}/live/state").json()
        assert g["mode"] == "MATCH" and g["match_id"] == first["id"]

    def test_omit_match_id_preserves_it(self, admin_h, with_draw):
        # Pin match first
        first = with_draw[0]
        requests.post(f"{API}/live/state",
                      json={"mode": "MATCH", "match_id": first["id"]},
                      headers=admin_h)
        # Switch to STANDINGS without touching match_id
        r = requests.post(f"{API}/live/state", json={"mode": "STANDINGS"},
                          headers=admin_h)
        assert r.status_code == 200
        data = r.json()
        assert data["mode"] == "STANDINGS"
        assert data["match_id"] == first["id"], \
            f"match_id should be preserved when key omitted, got {data['match_id']}"

    def test_explicit_null_match_id_unpins(self, admin_h, with_draw):
        first = with_draw[0]
        requests.post(f"{API}/live/state",
                      json={"mode": "MATCH", "match_id": first["id"]},
                      headers=admin_h)
        # explicit null
        r = requests.post(f"{API}/live/state", json={"match_id": None},
                          headers=admin_h)
        assert r.status_code == 200
        data = r.json()
        assert data["match_id"] is None
        g = requests.get(f"{API}/live/state").json()
        assert g["match_id"] is None


# --------------------------------------------------------------------------
# 4) POST /live/load-next
# --------------------------------------------------------------------------
class TestLoadNext:
    def test_load_next_returns_first_aguardando(self, admin_h, with_draw):
        # Unpin first
        requests.post(f"{API}/live/state", json={"match_id": None, "mode": "STANDINGS"},
                      headers=admin_h)
        # Find first AGUARDANDO by number
        matches = requests.get(f"{API}/matches").json()
        aguard = [m for m in matches if m["status"] == "AGUARDANDO"]
        aguard.sort(key=lambda m: m["number"])
        assert aguard, "no AGUARDANDO match available"
        expected = aguard[0]["id"]

        r = requests.post(f"{API}/live/load-next", headers=admin_h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "MATCH"
        assert data["match_id"] == expected

        # And live/state reflects
        g = requests.get(f"{API}/live/state").json()
        assert g["mode"] == "MATCH" and g["match_id"] == expected

    def test_load_next_returns_null_when_none(self, admin_h):
        # Reset -> no matches at all
        requests.post(f"{API}/tournament/reset", headers=admin_h)
        r = requests.post(f"{API}/live/load-next", headers=admin_h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "MATCH"
        assert data["match_id"] is None


# --------------------------------------------------------------------------
# 5) POST /matches/{id}/start auto-pins telão
# --------------------------------------------------------------------------
class TestStartAutoPin:
    def test_start_match_pins_live_state(self, admin_h):
        # Ensure we have players (may have been reset in prior test) and re-draw
        players = requests.get(f"{API}/players", headers=admin_h).json()
        if len(players) < 30:
            # top up
            _register_players(admin_h, 30 - len(players))
        rd = requests.post(f"{API}/draw",
                           json={"num_teams": 10, "players_per_team": 3,
                                 "mode": "BALANCED"},
                           headers=admin_h)
        assert rd.status_code == 200, rd.text
        matches = requests.get(f"{API}/matches").json()
        aguard = [m for m in matches if m["status"] == "AGUARDANDO"]
        assert aguard, "need AGUARDANDO match"
        target = sorted(aguard, key=lambda m: m["number"])[0]

        # Force live state to STANDINGS + different pin so we can detect change
        requests.post(f"{API}/live/state",
                      json={"mode": "STANDINGS", "match_id": None},
                      headers=admin_h)

        r = requests.post(f"{API}/matches/{target['id']}/start", headers=admin_h)
        assert r.status_code == 200, r.text

        g = requests.get(f"{API}/live/state").json()
        assert g["mode"] == "MATCH"
        assert g["match_id"] == target["id"]


# --------------------------------------------------------------------------
# 6) Light regression on read endpoints
# --------------------------------------------------------------------------
class TestReadSchemasRegression:
    def test_public_players_projection(self):
        r = requests.get(f"{API}/players")
        assert r.status_code == 200
        for p in r.json():
            assert "whatsapp" not in p
            assert "notes" not in p
            assert "_id" not in p

    def test_admin_players_full(self, admin_h):
        r = requests.get(f"{API}/players", headers=admin_h)
        assert r.status_code == 200
        # not every player has whatsapp/notes but the field should be allowed to appear
        for p in r.json():
            assert "_id" not in p

    def test_matches_list(self):
        r = requests.get(f"{API}/matches")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_standings(self):
        r = requests.get(f"{API}/standings")
        assert r.status_code == 200

    def test_stats_players(self):
        r = requests.get(f"{API}/stats/players")
        assert r.status_code == 200

    def test_stats_teams(self):
        r = requests.get(f"{API}/stats/teams")
        assert r.status_code == 200

    def test_playoffs(self):
        r = requests.get(f"{API}/playoffs")
        assert r.status_code == 200

    def test_champion(self):
        r = requests.get(f"{API}/champion")
        assert r.status_code == 200

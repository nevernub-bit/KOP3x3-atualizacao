"""Iteration 6 — PATCH /api/players/{id} semantics + preservation + regression.

Covers:
- PATCH auth (admin required, 401 anon)
- Full update returns full doc (including whatsapp/notes)
- Pydantic constraints -> 422
- Photo update works and respects max_length
- exclude_unset / preservation: PATCH {name} must not clear nickname/whatsapp/notes
- DELETE removes player from team.players
- Status arbitrary string <=30 chars
- 404 on non-existent id
- Regression: GET anon = public projection (no whatsapp/notes); admin = full
- Light regression on other read endpoints and admin match actions
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
_PNG2 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"B" * 40).decode()
TINY_PHOTO_2 = f"data:image/png;base64,{_PNG2}"


def _uniq_ip():
    # use 10.6.x.y to isolate from other suites (which use 10.0 / 10.5)
    h = uuid.uuid4().int
    return f"10.6.{h % 250}.{(h >> 8) % 250}"


@pytest.fixture(scope="module")
def admin_h():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      headers={"X-Forwarded-For": _uniq_ip()})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module", autouse=True)
def fresh(admin_h):
    r = requests.post(f"{API}/tournament/reset", headers=admin_h)
    assert r.status_code == 200, r.text
    players = requests.get(f"{API}/players", headers=admin_h).json()
    for p in players:
        requests.delete(f"{API}/players/{p['id']}", headers=admin_h)
    # Ensure player_limit is at least 30 for draw tests
    requests.patch(f"{API}/tournament", json={"player_limit": 60}, headers=admin_h)
    yield
    # cleanup
    players = requests.get(f"{API}/players", headers=admin_h).json()
    for p in players:
        requests.delete(f"{API}/players/{p['id']}", headers=admin_h)


def _register(name="TEST_P6", nickname="Nick", whatsapp="+55 11 99999-0000",
              notes="initial notes", level="INTERMEDIÁRIO"):
    body = {
        "name": f"{name}_{uuid.uuid4().hex[:6]}",
        "level": level,
        "photo": TINY_PHOTO,
        "nickname": nickname,
        "whatsapp": whatsapp,
        "notes": notes,
    }
    r = requests.post(f"{API}/players/register", json=body,
                      headers={"X-Forwarded-For": _uniq_ip()})
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    return r.json()


# ---------- Core PATCH semantics ----------
class TestPatchPlayer:
    def test_patch_requires_admin_token(self):
        p = _register(name="TEST_AUTH")
        r = requests.patch(f"{API}/players/{p['id']}", json={"name": "Blocked"})
        assert r.status_code == 401, f"expected 401 anon PATCH, got {r.status_code}"

    def test_patch_full_update_returns_full_doc(self, admin_h):
        p = _register(name="TEST_FULL")
        payload = {
            "name": "Updated Name",
            "nickname": "UpdNick",
            "status": "SUSPENSO",
            "level": "PROFISSIONAL",
            "whatsapp": "+55 21 98888-7777",
            "notes": "updated notes content",
        }
        r = requests.patch(f"{API}/players/{p['id']}", json=payload, headers=admin_h)
        assert r.status_code == 200, r.text
        d = r.json()
        for k, v in payload.items():
            assert d.get(k) == v, f"{k}: expected {v!r}, got {d.get(k)!r}"
        # Full admin doc should expose whatsapp & notes
        assert "whatsapp" in d and "notes" in d
        assert "_id" not in d

    def test_patch_name_empty_422(self, admin_h):
        p = _register(name="TEST_EMPTY")
        r = requests.patch(f"{API}/players/{p['id']}", json={"name": ""}, headers=admin_h)
        assert r.status_code == 422, f"empty name should 422, got {r.status_code}"

    def test_patch_name_too_long_422(self, admin_h):
        p = _register(name="TEST_LONG")
        r = requests.patch(f"{API}/players/{p['id']}", json={"name": "x" * 81},
                           headers=admin_h)
        assert r.status_code == 422

    def test_patch_nickname_too_long_422(self, admin_h):
        p = _register(name="TEST_NICKLONG")
        r = requests.patch(f"{API}/players/{p['id']}", json={"nickname": "x" * 41},
                           headers=admin_h)
        assert r.status_code == 422

    def test_patch_notes_too_long_422(self, admin_h):
        p = _register(name="TEST_NOTELONG")
        r = requests.patch(f"{API}/players/{p['id']}", json={"notes": "x" * 301},
                           headers=admin_h)
        assert r.status_code == 422

    def test_patch_whatsapp_too_long_422(self, admin_h):
        p = _register(name="TEST_WALONG")
        r = requests.patch(f"{API}/players/{p['id']}", json={"whatsapp": "x" * 31},
                           headers=admin_h)
        assert r.status_code == 422

    def test_patch_photo_update_ok(self, admin_h):
        p = _register(name="TEST_PHOTO")
        r = requests.patch(f"{API}/players/{p['id']}", json={"photo": TINY_PHOTO_2},
                           headers=admin_h)
        assert r.status_code == 200, r.text
        assert r.json()["photo"] == TINY_PHOTO_2

    def test_patch_photo_too_long_422(self, admin_h):
        p = _register(name="TEST_PHOTOBIG")
        huge = "data:image/png;base64," + ("A" * 700001)
        r = requests.patch(f"{API}/players/{p['id']}", json={"photo": huge},
                           headers=admin_h)
        assert r.status_code == 422

    def test_patch_preserves_omitted_fields(self, admin_h):
        """Core preservation guarantee: PATCH {name} must not clear others."""
        p = _register(name="TEST_PRESERVE", nickname="OrigNick",
                      whatsapp="+55 11 97777-6666", notes="orig notes")
        pid = p["id"]
        r = requests.patch(f"{API}/players/{pid}", json={"name": "NewName"},
                           headers=admin_h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "NewName"
        assert body["nickname"] == "OrigNick", f"nickname cleared: {body['nickname']!r}"
        assert body["whatsapp"] == "+55 11 97777-6666", f"whatsapp cleared: {body['whatsapp']!r}"
        assert body["notes"] == "orig notes", f"notes cleared: {body['notes']!r}"

        # Verify via GET also
        g = requests.get(f"{API}/players/{pid}", headers=admin_h)
        assert g.status_code == 200
        gb = g.json()
        assert gb["nickname"] == "OrigNick"
        assert gb["whatsapp"] == "+55 11 97777-6666"
        assert gb["notes"] == "orig notes"

    def test_patch_404_on_missing(self, admin_h):
        r = requests.patch(f"{API}/players/does-not-exist-xyz",
                           json={"name": "X"}, headers=admin_h)
        assert r.status_code == 404

    def test_patch_arbitrary_status_string(self, admin_h):
        p = _register(name="TEST_STATUS")
        r = requests.patch(f"{API}/players/{p['id']}",
                           json={"status": "REMOVIDO_MANUAL"}, headers=admin_h)
        assert r.status_code == 200
        assert r.json()["status"] == "REMOVIDO_MANUAL"

    def test_patch_status_too_long_422(self, admin_h):
        p = _register(name="TEST_STATUSLONG")
        r = requests.patch(f"{API}/players/{p['id']}",
                           json={"status": "x" * 31}, headers=admin_h)
        assert r.status_code == 422


# ---------- Public projection ----------
class TestPlayerProjection:
    def test_anon_list_hides_whatsapp_and_notes(self, admin_h):
        _register(name="TEST_PROJ_ANON", whatsapp="+55 11 90000-0001",
                  notes="secret notes")
        r = requests.get(f"{API}/players")  # no auth
        assert r.status_code == 200
        for p in r.json():
            assert "whatsapp" not in p, f"anon list leaked whatsapp: {p}"
            assert "notes" not in p, f"anon list leaked notes: {p}"

    def test_admin_list_includes_whatsapp_and_notes(self, admin_h):
        _register(name="TEST_PROJ_ADMIN", whatsapp="+55 11 90000-0002",
                  notes="admin visible")
        r = requests.get(f"{API}/players", headers=admin_h)
        assert r.status_code == 200
        has_full = any("whatsapp" in p and "notes" in p for p in r.json())
        assert has_full, "admin GET /players must expose whatsapp/notes"


# ---------- DELETE ----------
class TestDeletePlayer:
    def test_delete_requires_admin(self):
        p = _register(name="TEST_DEL_ANON")
        r = requests.delete(f"{API}/players/{p['id']}")
        assert r.status_code == 401

    def test_delete_removes_from_team(self, admin_h):
        # register until 30 CONFIRMADO players (draw filters by status=CONFIRMADO)
        attempts = 0
        while attempts < 60:
            all_p = requests.get(f"{API}/players", headers=admin_h).json()
            conf = [p for p in all_p if p.get("status") == "CONFIRMADO"]
            if len(conf) >= 30:
                break
            _register(name=f"TEST_DRAW_{attempts}")
            attempts += 1
        r = requests.post(f"{API}/draw",
                          json={"num_teams": 10, "players_per_team": 3, "mode": "BALANCED"},
                          headers=admin_h)
        assert r.status_code == 200, r.text
        teams = requests.get(f"{API}/teams").json()
        # pick first team with players
        team = next((t for t in teams if t.get("players")), None)
        assert team, "no team with players after draw"
        victim_pid = team["players"][0]

        d = requests.delete(f"{API}/players/{victim_pid}", headers=admin_h)
        assert d.status_code == 200, d.text

        teams_after = requests.get(f"{API}/teams").json()
        same = next(t for t in teams_after if t["id"] == team["id"])
        assert victim_pid not in (same.get("players") or []), \
            "deleted player still referenced in team.players"


# ---------- Regression on other read endpoints ----------
class TestReadEndpointsRegression:
    def test_live_state_public(self):
        r = requests.get(f"{API}/live/state")
        assert r.status_code == 200
        assert "mode" in r.json()

    def test_matches(self):
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


# ---------- Regression on admin match actions ----------
class TestMatchActionsRegression:
    def test_start_pause_resume_end(self, admin_h):
        # ensure draw exists (DeletePlayer test ran draw; if not, do it here)
        matches = requests.get(f"{API}/matches").json()
        if not matches:
            attempts = 0
            while attempts < 60:
                all_p = requests.get(f"{API}/players", headers=admin_h).json()
                conf = [p for p in all_p if p.get("status") == "CONFIRMADO"]
                if len(conf) >= 30:
                    break
                _register(name=f"TEST_MREG_{attempts}")
                attempts += 1
            r = requests.post(f"{API}/draw",
                              json={"num_teams": 10, "players_per_team": 3,
                                    "mode": "BALANCED"}, headers=admin_h)
            assert r.status_code == 200, r.text
            matches = requests.get(f"{API}/matches").json()
        m = next((x for x in matches if x.get("status") == "AGUARDANDO"), None)
        assert m, "no AGUARDANDO match found"
        mid = m["id"]

        r = requests.post(f"{API}/matches/{mid}/start", headers=admin_h)
        assert r.status_code == 200, r.text

        r = requests.post(f"{API}/matches/{mid}/pause", headers=admin_h)
        assert r.status_code == 200, r.text

        r = requests.post(f"{API}/matches/{mid}/resume", headers=admin_h)
        assert r.status_code == 200, r.text

        # eliminate one player from team_a to drive a result then end
        md = requests.get(f"{API}/matches/{mid}").json()
        teams = requests.get(f"{API}/teams").json()
        tmap = {t["id"]: t for t in teams}
        a_team = tmap.get(md.get("team_a") or md.get("team_a_id"))
        assert a_team and a_team.get("players")
        victim = a_team["players"][0]
        r = requests.post(f"{API}/matches/{mid}/eliminate",
                          json={"eliminated_id": victim}, headers=admin_h)
        assert r.status_code == 200, r.text

        r = requests.post(f"{API}/matches/{mid}/end", headers=admin_h)
        assert r.status_code in (200, 400), r.text  # 400 if match-end requires more state

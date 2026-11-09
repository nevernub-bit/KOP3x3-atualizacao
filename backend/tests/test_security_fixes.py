"""SEC-001 + SEC-002 security fixes regression tests."""
import os
import base64
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    # read from frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

API = f"{BASE_URL}/api"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "test-only-password")

# tiny valid data URL (1x1 png)
_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"A" * 20).decode()
TINY_PHOTO = f"data:image/png;base64,{_PNG}"

PUBLIC_KEYS = {"id", "name", "nickname", "level", "photo", "status", "team_id", "created_at"}


@pytest.fixture(scope="session")
def admin_token():
    # use unique IP header so login rate limit tests don't interfere
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      headers={"X-Forwarded-For": "10.0.0.1"})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session", autouse=True)
def clean_slate(admin_h):
    """Reset tournament and delete all players so we start fresh."""
    requests.post(f"{API}/tournament/reset", headers=admin_h)
    players = requests.get(f"{API}/players", headers=admin_h).json()
    for p in players:
        requests.delete(f"{API}/players/{p['id']}", headers=admin_h)
    yield


def _register(ip="10.0.0.2", **overrides):
    body = {"name": overrides.pop("name", f"TEST_{uuid.uuid4().hex[:8]}"),
            "level": "INICIANTE", "photo": TINY_PHOTO}
    body.update(overrides)
    return requests.post(f"{API}/players/register", json=body,
                         headers={"X-Forwarded-For": ip})


# ---------- SEC-001 ----------
class TestSEC001PublicProjection:
    def test_seed_player(self, admin_h):
        r = _register(ip="10.0.1.1", name="TEST_seed_sec001",
                      nickname="nick", whatsapp="+5511999999999",
                      notes="secret notes visible to admin only")
        assert r.status_code == 200, r.text
        self.pid = r.json()["id"]
        TestSEC001PublicProjection.pid = self.pid

    def test_list_anonymous_no_pii(self):
        r = requests.get(f"{API}/players")
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        for p in data:
            assert "whatsapp" not in p, f"whatsapp leaked: {p}"
            assert "notes" not in p, f"notes leaked: {p}"
            assert "password_hash" not in p
            assert "_id" not in p
            extra = set(p.keys()) - PUBLIC_KEYS
            assert not extra, f"unexpected keys in public projection: {extra}"

    def test_detail_anonymous_no_pii(self):
        pid = TestSEC001PublicProjection.pid
        r = requests.get(f"{API}/players/{pid}")
        assert r.status_code == 200
        p = r.json()
        assert "whatsapp" not in p
        assert "notes" not in p
        assert set(p.keys()) <= PUBLIC_KEYS

    def test_list_admin_has_pii(self, admin_h):
        r = requests.get(f"{API}/players", headers=admin_h)
        assert r.status_code == 200
        data = r.json()
        target = next((p for p in data if p["id"] == TestSEC001PublicProjection.pid), None)
        assert target is not None
        assert target.get("whatsapp") == "+5511999999999"
        assert target.get("notes") == "secret notes visible to admin only"

    def test_detail_admin_has_pii(self, admin_h):
        pid = TestSEC001PublicProjection.pid
        r = requests.get(f"{API}/players/{pid}", headers=admin_h)
        assert r.status_code == 200
        p = r.json()
        assert p.get("whatsapp") == "+5511999999999"
        assert p.get("notes") == "secret notes visible to admin only"

    def test_patch_admin_returns_full_doc(self, admin_h):
        pid = TestSEC001PublicProjection.pid
        r = requests.patch(f"{API}/players/{pid}",
                           json={"notes": "updated notes"},
                           headers=admin_h)
        assert r.status_code == 200
        p = r.json()
        assert p.get("notes") == "updated notes"
        assert "whatsapp" in p  # full doc


# ---------- SEC-002 ----------
class TestSEC002Validation:
    def test_bad_photo_format(self):
        r = _register(ip="10.0.2.1", photo="notadatauri")
        assert r.status_code == 400
        assert "Formato de foto inválido" in r.text

    def test_photo_too_large_pydantic(self):
        big = "data:image/png;base64," + ("A" * 700_001)
        r = _register(ip="10.0.2.2", photo=big)
        # pydantic max_length or backend 400
        assert r.status_code in (400, 422), f"got {r.status_code}: {r.text[:200]}"

    def test_photo_720kb_rejected(self):
        big = "data:image/png;base64," + ("A" * 720_000)
        r = _register(ip="10.0.2.3", photo=big)
        assert r.status_code in (400, 422, 403), f"got {r.status_code}: {r.text[:200]}"

    def test_name_too_long(self):
        r = _register(ip="10.0.2.4", name="X" * 200)
        assert r.status_code == 422

    def test_notes_too_long(self):
        r = _register(ip="10.0.2.5", notes="n" * 301)
        assert r.status_code == 422

    def test_nickname_too_long(self):
        r = _register(ip="10.0.2.6", nickname="n" * 41)
        assert r.status_code == 422

    def test_whatsapp_too_long(self):
        r = _register(ip="10.0.2.7", whatsapp="9" * 31)
        assert r.status_code == 422


# ---------- Rate limits ----------
class TestRateLimits:
    def test_register_rate_limit(self, admin_h):
        # fresh reset + delete all players
        requests.post(f"{API}/tournament/reset", headers=admin_h)
        players = requests.get(f"{API}/players", headers=admin_h).json()
        for p in players:
            requests.delete(f"{API}/players/{p['id']}", headers=admin_h)

        ip = f"10.9.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"
        statuses = []
        for i in range(6):
            r = _register(ip=ip, name=f"TEST_rl_{i}_{uuid.uuid4().hex[:6]}")
            statuses.append(r.status_code)
        # First 5 must succeed (200), 6th must be 429
        assert statuses[:5] == [200] * 5, f"expected 5 successes, got {statuses}"
        assert statuses[5] == 429, f"expected 429 on 6th, got {statuses}"

    def test_login_rate_limit(self):
        ip = f"10.8.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"
        email = f"nobody_{uuid.uuid4().hex[:6]}@kop.com"
        statuses = []
        for i in range(11):
            r = requests.post(f"{API}/auth/login",
                              json={"email": email, "password": "wrong"},
                              headers={"X-Forwarded-For": ip})
            statuses.append(r.status_code)
        assert all(s == 401 for s in statuses[:10]), f"expected 10x401, got {statuses}"
        assert statuses[10] == 429, f"expected 429 on 11th, got {statuses}"
        r = requests.post(f"{API}/auth/login",
                          json={"email": email, "password": "wrong"},
                          headers={"X-Forwarded-For": ip})
        assert "Muitas tentativas" in r.text or r.status_code == 429

    def test_login_success_fresh(self):
        # use fresh IP so bucket clean
        r = requests.post(f"{API}/auth/login",
                         json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                         headers={"X-Forwarded-For": "10.7.7.77"})
        assert r.status_code == 200
        assert "access_token" in r.json()


# ---------- Regression: full v3 flow still works ----------
class TestRegressionFullFlow:
    def test_full_tournament_flow(self, admin_h):
        # reset + wipe players
        requests.post(f"{API}/tournament/reset", headers=admin_h)
        players = requests.get(f"{API}/players", headers=admin_h).json()
        for p in players:
            requests.delete(f"{API}/players/{p['id']}", headers=admin_h)

        # register 30 players using distinct IPs to bypass rate limit
        levels = ["PROFISSIONAL", "INTERMEDIÁRIO", "INICIANTE"]
        for i in range(30):
            ip = f"10.20.{i // 5}.{(i % 5) + 1}"  # cycle through many IPs
            r = _register(ip=ip, name=f"TEST_reg_{i}", level=levels[i % 3])
            assert r.status_code == 200, f"register {i} failed: {r.status_code} {r.text}"

        # draw
        r = requests.post(f"{API}/draw",
                          json={"num_teams": 10, "players_per_team": 3, "mode": "BALANCED"},
                          headers=admin_h)
        assert r.status_code == 200, r.text

        matches = requests.get(f"{API}/matches").json()
        group_matches = [m for m in matches if m["phase"] == "GROUP"]
        assert len(group_matches) == 20

        # play all group matches: start -> eliminate all of team_b -> auto ends
        teams = {t["id"]: t for t in requests.get(f"{API}/teams").json()}
        for m in group_matches:
            requests.post(f"{API}/matches/{m['id']}/start", headers=admin_h)
            for pid in teams[m["team_b"]]["players"]:
                requests.post(f"{API}/matches/{m['id']}/eliminate",
                              json={"eliminated_id": pid}, headers=admin_h)

        standings = requests.get(f"{API}/standings").json()
        assert len(standings["A"]) == 5 and len(standings["B"]) == 5

        playoffs = requests.get(f"{API}/playoffs").json()
        assert len(playoffs) >= 2  # semis generated

    def test_admin_responses_have_all_fields(self, admin_h):
        r = requests.get(f"{API}/players", headers=admin_h)
        assert r.status_code == 200
        data = r.json()
        assert len(data) > 0
        p = data[0]
        for k in ["id", "name", "level", "photo", "status", "team_id", "created_at"]:
            assert k in p, f"missing key {k}"
        # whatsapp and notes must exist as keys (may be None)
        assert "whatsapp" in p
        assert "notes" in p

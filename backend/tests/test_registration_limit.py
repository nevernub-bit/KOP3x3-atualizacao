"""Registration reception limit vs. official vacancies.

Official vacancies stay derived from teams × players per team (they still gate
the organizer's confirmation). The reception limit is an independent setting
that only bounds how many inscriptions the public form accepts. Runs against an
in-memory MongoDB, so no real data is touched.
"""
import base64
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mongomock_motor  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"A" * 20).decode()
PHOTO = f"data:image/png;base64,{_PNG}"


@pytest.fixture(scope="module", autouse=True)
def isolated_db():
    """Own database for this module, restored afterwards.

    The other suites assign `server.db` at import time; swapping it here (and
    restoring it on teardown) keeps the module isolated no matter which order
    pytest-xdist runs the files in.
    """
    previous = server.db
    server.db = mongomock_motor.AsyncMongoMockClient()["kop_registration_limit_test"]
    server._RATE_BUCKETS.clear()
    try:
        yield
    finally:
        server.db = previous


@pytest.fixture(scope="module")
def client(isolated_db):
    with TestClient(server.app) as c:
        yield c


@pytest.fixture(scope="module")
def admin(client):
    r = client.post("/api/auth/login", json={
        "email": server.ADMIN_EMAIL, "password": server.ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def register(client, name="TEST_LIMIT"):
    """Each call uses a distinct X-Forwarded-For to bypass the per-IP limit."""
    return client.post("/api/players/register", json={
        "name": f"{name}_{uuid.uuid4().hex[:6]}",
        "level": "INICIANTE",
        "photo": PHOTO,
    }, headers={"X-Forwarded-For": f"10.9.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"})


def test_01_small_structure_and_default_limit(client, admin):
    # 2 teams × 2 players = 4 official vacancies.
    r = client.patch("/api/tournament", headers=admin, json={
        "num_teams": 2, "players_per_team": 2,
        "num_groups": 1, "qualifiers_per_group": 2,
    })
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["capacity"] == 4
    # Documents without the new setting fall back to the official capacity.
    assert t["registration_limit"] == 4
    # No organizer contact configured yet: never invent a number.
    assert t["organizer_whatsapp"] is None


def test_02_reception_stops_at_the_default_limit(client):
    for i in range(4):
        assert register(client, f"TEST_FULL_{i}").status_code == 200
    blocked = register(client, "TEST_OVER")
    assert blocked.status_code == 400
    assert "Limite de inscrições recebidas" in blocked.json()["detail"]


def test_03_raising_the_limit_accepts_more_inscriptions(client, admin):
    r = client.patch("/api/tournament", headers=admin, json={"registration_limit": 6})
    assert r.status_code == 200, r.text
    assert r.json()["registration_limit"] == 6
    assert r.json()["capacity"] == 4  # official vacancies unchanged

    assert register(client, "TEST_EXTRA_1").status_code == 200
    assert register(client, "TEST_EXTRA_2").status_code == 200
    blocked = register(client, "TEST_EXTRA_3")
    assert blocked.status_code == 400
    assert "Limite de inscrições recebidas" in blocked.json()["detail"]


def test_04_limit_cannot_be_lower_than_official_vacancies(client, admin):
    r = client.patch("/api/tournament", headers=admin, json={"registration_limit": 3})
    assert r.status_code == 400
    assert "vagas oficiais" in r.json()["detail"]


def test_05_confirmation_still_respects_official_vacancies(client, admin):
    received = client.get("/api/players", headers=admin,
                          params={"all_statuses": "true"}).json()
    assert len(received) == 6 and all(p["status"] == "PENDENTE" for p in received)

    for p in received[:4]:
        r = client.patch(f"/api/players/{p['id']}/status", headers=admin,
                         json={"status": "CONFIRMADO"})
        assert r.status_code == 200, r.text

    overflow = client.patch(f"/api/players/{received[4]['id']}/status", headers=admin,
                            json={"status": "CONFIRMADO"})
    assert overflow.status_code == 400
    assert "vagas confirmadas" in overflow.json()["detail"]


def test_06_cancelled_inscription_frees_a_reception_slot(client, admin):
    players = client.get("/api/players", headers=admin,
                         params={"all_statuses": "true"}).json()
    target = next(p for p in players if p["status"] == "PENDENTE")
    r = client.patch(f"/api/players/{target['id']}/status", headers=admin,
                     json={"status": "CANCELADO"})
    assert r.status_code == 200, r.text

    # The record is preserved, the reception slot is free again.
    assert register(client, "TEST_AFTER_CANCEL").status_code == 200
    kept = client.get(f"/api/players/{target['id']}", headers=admin)
    assert kept.status_code == 200 and kept.json()["status"] == "CANCELADO"


def test_07_organizer_whatsapp_round_trip(client, admin):
    r = client.patch("/api/tournament", headers=admin,
                     json={"organizer_whatsapp": "+55 11 98888-7777"})
    assert r.status_code == 200, r.text
    assert r.json()["organizer_whatsapp"] == "+55 11 98888-7777"
    assert client.get("/api/tournament").json()["organizer_whatsapp"] == "+55 11 98888-7777"

    cleared = client.patch("/api/tournament", headers=admin, json={"organizer_whatsapp": ""})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["organizer_whatsapp"] is None

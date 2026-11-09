from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import uuid
import random
import logging
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Literal

import bcrypt
import jwt
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
JWT_ALG = "HS256"
DEFAULT_DURATION_S = 300  # 5 minutes

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="KINGS OF PAINTBALL — KOP 3x3")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("kop")


# ---------- Utils ----------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def create_token(user_id: str, email: str, role: str) -> str:
    return jwt.encode({
        "sub": user_id, "email": email, "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
    }, JWT_SECRET, algorithm=JWT_ALG)


bearer = HTTPBearer(auto_error=False)


async def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)):
    if not creds:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    user = await db.users.find_one({"id": payload["sub"]})
    if not user:
        raise HTTPException(401, "User not found")
    return user


async def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    return user


def clean(doc):
    if not doc: return doc
    doc.pop("_id", None)
    doc.pop("password_hash", None)
    return doc


# ---------- SEC-001: public projection for player docs ----------
PUBLIC_PLAYER_FIELDS = {
    "id", "name", "nickname", "level", "photo", "status", "team_id", "created_at",
}

def public_player(doc):
    """Anonymous-safe view of a player document (no whatsapp / notes)."""
    if not doc:
        return doc
    d = dict(doc)
    d.pop("_id", None); d.pop("password_hash", None)
    return {k: v for k, v in d.items() if k in PUBLIC_PLAYER_FIELDS}


async def optional_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)):
    """Same as get_current_user but returns None silently when unauthenticated / invalid."""
    if not creds:
        return None
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except Exception:
        return None
    return await db.users.find_one({"id": payload.get("sub")})


# ---------- SEC-002: naive in-memory rate limiter (per-process) ----------
from collections import deque as _deque
import time as _time

_RATE_BUCKETS: dict[str, _deque] = {}
MAX_PHOTO_B64_LEN = 700_000  # ~525KB decoded — plenty for 800px JPEG

def _rate_check(key: str, limit: int, window_s: int) -> bool:
    now = _time.time()
    q = _RATE_BUCKETS.setdefault(key, _deque())
    while q and q[0] < now - window_s:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True

def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------- Models ----------
Level = Literal["INICIANTE", "INTERMEDIÁRIO", "PROFISSIONAL"]


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class PlayerRegisterIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    level: Level
    photo: str = Field(..., min_length=1, max_length=MAX_PHOTO_B64_LEN)
    nickname: Optional[str] = Field(None, max_length=40)
    whatsapp: Optional[str] = Field(None, max_length=30)
    notes: Optional[str] = Field(None, max_length=300)


class PlayerUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    level: Optional[Level] = None
    photo: Optional[str] = Field(None, max_length=MAX_PHOTO_B64_LEN)
    nickname: Optional[str] = Field(None, max_length=40)
    whatsapp: Optional[str] = Field(None, max_length=30)
    notes: Optional[str] = Field(None, max_length=300)
    status: Optional[str] = Field(None, max_length=30)


class TeamRenameIn(BaseModel):
    name: str


class GroupAssignIn(BaseModel):
    groups: dict


class DrawIn(BaseModel):
    num_teams: Optional[int] = None
    players_per_team: Optional[int] = None
    num_groups: Optional[int] = None
    qualifiers_per_group: Optional[int] = None
    mode: Literal["NORMAL", "BALANCED"] = "BALANCED"


class EliminateIn(BaseModel):
    eliminated_id: str
    eliminator_id: Optional[str] = None  # deprecated, ignored (kept for backward compat)


class MvpIn(BaseModel):
    player_id: str


class TournamentUpdate(BaseModel):
    player_limit: Optional[int] = None
    num_teams: Optional[int] = None
    players_per_team: Optional[int] = None
    num_groups: Optional[int] = None
    qualifiers_per_group: Optional[int] = None
    status: Optional[str] = None
    default_duration_s: Optional[int] = None


class DurationIn(BaseModel):
    duration_seconds: int


class SetWinnerIn(BaseModel):
    winner_team_id: Optional[str] = None  # null to force draw


class LiveStateIn(BaseModel):
    mode: Optional[Literal["MATCH", "STANDINGS"]] = None
    match_id: Optional[str] = None  # explicit null unpins; omit to keep current


DEFAULT_TEAMS = [
    "TEAM JAPAN", "TEAM YAGAMI", "TEAM IKARI", "TEAM OROCHI", "TEAM NESTS",
    "TEAM FATAL FURY", "TEAM ART OF FIGHTING", "TEAM PSYCHO SOLDIER",
    "TEAM WOMEN FIGHTERS", "TEAM KOF HEROES", "TEAM KOREA", "TEAM BRAZIL",
    "TEAM MEXICO", "TEAM ITALY", "TEAM USA", "TEAM CHINA",
]


# ---------- Event structure (single source of truth) ----------
# Team count, squad size, group layout and bracket size all come from the
# tournament document. Nothing below assumes 10 teams / 3 players / 2 groups.
DEFAULT_NUM_TEAMS = 10
DEFAULT_PLAYERS_PER_TEAM = 3
DEFAULT_NUM_GROUPS = 2
DEFAULT_QUALIFIERS_PER_GROUP = 2
MIN_TEAMS, MAX_TEAMS = 2, 64
MIN_PLAYERS_PER_TEAM, MAX_PLAYERS_PER_TEAM = 1, 10
MAX_QUALIFIERS_TOTAL = 16
GROUP_LETTERS = "ABCDEFGHIJKLMNOP"
PLAYOFF_PHASES = ["R16", "QF", "SEMI", "FINAL", "THIRD"]


def is_power_of_two(n: int) -> bool:
    return n >= 1 and (n & (n - 1)) == 0


def tournament_config(t: dict) -> dict:
    """Resolve the event structure, tolerating legacy documents."""
    t = t or {}
    num_teams = int(t.get("num_teams") or DEFAULT_NUM_TEAMS)
    players_per_team = int(t.get("players_per_team") or DEFAULT_PLAYERS_PER_TEAM)
    num_groups = int(t.get("num_groups") or DEFAULT_NUM_GROUPS)
    qualifiers_per_group = int(t.get("qualifiers_per_group") or DEFAULT_QUALIFIERS_PER_GROUP)
    return {
        "num_teams": num_teams,
        "players_per_team": players_per_team,
        "num_groups": num_groups,
        "qualifiers_per_group": qualifiers_per_group,
        "capacity": num_teams * players_per_team,
        "qualifiers_total": num_groups * qualifiers_per_group,
    }


def validate_structure(num_teams: int, players_per_team: int,
                      num_groups: int, qualifiers_per_group: int) -> Optional[str]:
    """Returns an error message (pt-BR) or None when the structure is valid."""
    if not (MIN_TEAMS <= num_teams <= MAX_TEAMS):
        return f"O torneio deve ter entre {MIN_TEAMS} e {MAX_TEAMS} equipes."
    if not (MIN_PLAYERS_PER_TEAM <= players_per_team <= MAX_PLAYERS_PER_TEAM):
        return (f"Cada equipe deve ter entre {MIN_PLAYERS_PER_TEAM} e "
                f"{MAX_PLAYERS_PER_TEAM} jogadores.")
    if not (1 <= num_groups <= num_teams):
        return "A quantidade de grupos deve ficar entre 1 e o número de equipes."
    min_group_size = num_teams // num_groups
    if not (1 <= qualifiers_per_group <= min_group_size):
        return (f"Classificados por grupo deve ficar entre 1 e {min_group_size} "
                f"(o menor grupo tem {min_group_size} equipes).")
    total = num_groups * qualifiers_per_group
    if total < 2 or not is_power_of_two(total) or total > MAX_QUALIFIERS_TOTAL:
        return ("O total de classificados (grupos × classificados por grupo) deve ser "
                f"2, 4, 8 ou {MAX_QUALIFIERS_TOTAL} para formar um mata-mata válido.")
    return None


def first_playoff_phase(bracket_size: int) -> str:
    return {2: "FINAL", 4: "SEMI", 8: "QF", 16: "R16"}[bracket_size]


def next_playoff_phase(phase: str) -> Optional[str]:
    return {"R16": "QF", "QF": "SEMI", "SEMI": "FINAL"}.get(phase)


# ---------- Match helpers ----------
def default_match_fields(m):
    m.setdefault("duration_seconds", DEFAULT_DURATION_S)
    m.setdefault("eliminations", [])
    m.setdefault("started_at", None)
    m.setdefault("paused_at", None)
    m.setdefault("pause_accumulated_ms", 0)
    m.setdefault("ended_at", None)
    m.setdefault("is_draw", False)
    m.setdefault("locked", False)
    m.setdefault("perfect_a", False)
    m.setdefault("perfect_b", False)
    m.setdefault("points_a", 0)
    m.setdefault("points_b", 0)
    m.setdefault("elims_a", 0)
    m.setdefault("elims_b", 0)
    m.setdefault("eliminated_players_a", [])
    m.setdefault("eliminated_players_b", [])
    m.setdefault("winner_team_id", None)
    return m


def compute_elapsed_ms(m) -> int:
    if not m.get("started_at"):
        return 0
    started = parse_iso(m["started_at"])
    if m.get("ended_at"):
        end = parse_iso(m["ended_at"])
    elif m.get("paused_at"):
        end = parse_iso(m["paused_at"])
    else:
        end = datetime.now(timezone.utc)
    elapsed = int((end - started).total_seconds() * 1000) - int(m.get("pause_accumulated_ms", 0))
    return max(0, elapsed)


def compute_result(match, teams_by_id):
    """Official KOP 3x3 rules:
    - A team WINS only when ALL opponents (whole configured roster) are eliminated.
    - DRAW when time expires and both teams still have at least 1 alive player,
      regardless of the elimination count.
    - Winner points = 3 (win) + 2 (bonus for wiping 3 opponents) = 5.
    - Loser / Draw = 0 points.
    - PERFECT = winner + all 3 opponents eliminated + 0 own losses.
    - elims_a = opponents eliminated by A = len(eliminated_players_b).
    """
    ta = teams_by_id.get(match["team_a"], {"players": []})
    tb = teams_by_id.get(match["team_b"], {"players": []})
    a_ids = list(ta.get("players", []))
    b_ids = list(tb.get("players", []))
    eliminated: List[str] = [e["eliminated_id"] for e in match.get("eliminations", [])]
    eliminated_a = [pid for pid in eliminated if pid in a_ids]
    eliminated_b = [pid for pid in eliminated if pid in b_ids]
    alive_a = max(0, len(a_ids) - len(eliminated_a))
    alive_b = max(0, len(b_ids) - len(eliminated_b))
    # Eliminations realized BY each team = opponents they took out
    elims_by_a = len(eliminated_b)
    elims_by_b = len(eliminated_a)

    winner_id: Optional[str] = None
    is_draw = False
    if alive_a > 0 and alive_b == 0:
        winner_id = match["team_a"]
    elif alive_b > 0 and alive_a == 0:
        winner_id = match["team_b"]
    else:
        # Both still alive (or both zero) → DRAW
        is_draw = True

    # A wipe means every opponent on the roster was eliminated. The roster size
    # comes from the event configuration (3 in classic 3x3, N in other formats).
    wipe_a = len(b_ids) > 0 and elims_by_a >= len(b_ids)
    wipe_b = len(a_ids) > 0 and elims_by_b >= len(a_ids)

    points_a = points_b = 0
    perfect_a = perfect_b = False
    if winner_id == match["team_a"]:
        bonus = 2 if wipe_a else 0
        points_a = 3 + bonus
        perfect_a = wipe_a and (len(eliminated_a) == 0)
    elif winner_id == match["team_b"]:
        bonus = 2 if wipe_b else 0
        points_b = 3 + bonus
        perfect_b = wipe_b and (len(eliminated_b) == 0)

    return {
        "elims_a": elims_by_a, "elims_b": elims_by_b,
        "points_a": points_a, "points_b": points_b,
        "eliminated_players_a": eliminated_a,
        "eliminated_players_b": eliminated_b,
        "alive_a": alive_a, "alive_b": alive_b,
        "winner_team_id": winner_id,
        "is_draw": is_draw,
        "perfect_a": perfect_a, "perfect_b": perfect_b,
    }


async def migrate_structural_defaults():
    """Backfill ONLY missing structural fields on match documents.

    Historical results (status, winner, points, eliminations, PERFECT, draw)
    are immutable: they are never recalculated at startup, so roster changes or
    a new draw can never rewrite finished matches. Idempotent: a second run
    finds nothing missing and writes nothing.
    """
    async for m in db.matches.find({}):
        defaults = default_match_fields(dict(m))
        missing = {k: v for k, v in defaults.items() if k not in m}
        if missing:
            await db.matches.update_one({"id": m["id"]}, {"$set": missing})


# ---------- Startup ----------
@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.players.create_index("id", unique=True)
    await db.teams.create_index("id", unique=True)
    await db.matches.create_index("id", unique=True)

    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if not existing:
        await db.users.insert_one({
            "id": str(uuid.uuid4()), "email": ADMIN_EMAIL,
            "password_hash": hash_pw(ADMIN_PASSWORD),
            "role": "admin", "name": "KOP Organizer", "created_at": now_iso(),
        })
    elif not verify_pw(ADMIN_PASSWORD, existing.get("password_hash", "")):
        await db.users.update_one({"email": ADMIN_EMAIL}, {"$set": {"password_hash": hash_pw(ADMIN_PASSWORD)}})

    t = await db.tournament.find_one({"id": "main"})
    if not t:
        await db.tournament.insert_one({
            "id": "main", "name": "KINGS OF PAINTBALL — KOP 3x3",
            "num_teams": DEFAULT_NUM_TEAMS, "players_per_team": DEFAULT_PLAYERS_PER_TEAM,
            "num_groups": DEFAULT_NUM_GROUPS, "qualifiers_per_group": DEFAULT_QUALIFIERS_PER_GROUP,
            "player_limit": DEFAULT_NUM_TEAMS * DEFAULT_PLAYERS_PER_TEAM,
            "status": "OPEN", "draw_done": False, "mvp_player_id": None,
            "default_duration_s": DEFAULT_DURATION_S, "created_at": now_iso(),
        })
        for i in range(DEFAULT_NUM_TEAMS):
            name = DEFAULT_TEAMS[i] if i < len(DEFAULT_TEAMS) else f"TEAM {i + 1:02d}"
            await db.teams.insert_one({
                "id": str(uuid.uuid4()), "name": name, "order": i,
                "group": GROUP_LETTERS[i % DEFAULT_NUM_GROUPS], "players": [], "created_at": now_iso(),
            })
    else:
        # Backfill only missing structural fields; never recompute historical data.
        missing = {}
        if "default_duration_s" not in t:
            missing["default_duration_s"] = DEFAULT_DURATION_S
        if "num_groups" not in t:
            missing["num_groups"] = DEFAULT_NUM_GROUPS
        if "qualifiers_per_group" not in t:
            missing["qualifiers_per_group"] = DEFAULT_QUALIFIERS_PER_GROUP
        if "player_limit" not in t:
            cfg = tournament_config({**t, **missing})
            missing["player_limit"] = cfg["capacity"]
        if missing:
            await db.tournament.update_one({"id": "main"}, {"$set": missing})

    # Structural-only migration. Finished matches are historical records and
    # are never recomputed here (see migrate_structural_defaults).
    await migrate_structural_defaults()


@app.on_event("shutdown")
async def shutdown():
    client.close()


# ---------- Auth ----------
@api.post("/auth/login")
async def login(body: LoginIn, request: Request):
    ip = _client_ip(request)
    # Hardening: 10 attempts per 15min per (IP,email) before soft-throttle
    if not _rate_check(f"login:{ip}:{body.email.lower()}", limit=10, window_s=900):
        raise HTTPException(429, "Muitas tentativas. Tente novamente em 15 minutos.")
    user = await db.users.find_one({"email": body.email.lower()})
    if not user or not verify_pw(body.password, user["password_hash"]):
        raise HTTPException(401, "Credenciais inválidas")
    token = create_token(user["id"], user["email"], user["role"])
    return {"access_token": token, "token_type": "bearer", "user": clean(dict(user))}


@api.get("/auth/me")
async def me(user=Depends(get_current_user)):
    return clean(dict(user))


# ---------- Players ----------
@api.post("/players/register")
async def register_player(body: PlayerRegisterIn, request: Request):
    ip = _client_ip(request)
    # Hardening: max 5 registrations per IP per hour
    if not _rate_check(f"register:{ip}", limit=5, window_s=3600):
        raise HTTPException(429, "Muitas inscrições deste IP. Tente novamente mais tarde.")
    if not body.photo.startswith("data:image/"):
        raise HTTPException(400, "Formato de foto inválido")
    t = await db.tournament.find_one({"id": "main"}) or {}
    count = await db.players.count_documents({})
    capacity = tournament_config(t)["capacity"]
    if count >= capacity:
        raise HTTPException(400, "Limite de inscrições atingido")
    player = {
        "id": str(uuid.uuid4()), "name": body.name.strip(),
        "nickname": (body.nickname or "").strip() or None,
        "level": body.level, "photo": body.photo,
        "whatsapp": (body.whatsapp or "").strip() or None,
        "notes": (body.notes or "").strip() or None,
        "status": "CONFIRMADO", "team_id": None, "created_at": now_iso(),
    }
    await db.players.insert_one(player)
    # Owner receives their own full record; anonymous list/detail are projected below.
    return clean(dict(player))


@api.get("/players")
async def list_players(
    request: Request,
    photos: bool = True,
    ids: Optional[str] = None,
    user=Depends(optional_current_user),
):
    """Player list.

    The Telão polls this endpoint every few seconds, so it asks for a compact
    view (`photos=false`) and fetches the photos of the players actually on
    screen separately (`ids=<id,id,...>`). Both extras are opt-in: without them
    the response is exactly the previous full list.
    """
    query: dict = {}
    if ids:
        wanted = [i.strip() for i in ids.split(",") if i.strip()][:200]
        query["id"] = {"$in": wanted}
    docs = await db.players.find(query).sort("created_at", 1).to_list(1000)
    if user and user.get("role") == "admin":
        payload = [clean(d) for d in docs]
    else:
        payload = [public_player(d) for d in docs]
    if not photos:
        for p in payload:
            p.pop("photo", None)
    # The Telão polls this endpoint with base64 photos embedded, so allow
    # conditional revalidation: unchanged data answers 304 with no body.
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    etag = '"' + hashlib.sha256(body.encode("utf-8")).hexdigest() + '"'
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=0, must-revalidate",
        "Vary": "Authorization",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


@api.get("/players/{pid}")
async def get_player(pid: str, user=Depends(optional_current_user)):
    d = await db.players.find_one({"id": pid})
    if not d: raise HTTPException(404, "Jogador não encontrado")
    if user and user.get("role") == "admin":
        return clean(d)
    return public_player(d)


@api.patch("/players/{pid}")
async def update_player(pid: str, body: PlayerUpdateIn, _=Depends(require_admin)):
    """Admin edit of an existing registration. Keeps the same id and all links
    (team, matches, stats) — it never creates a second player document."""
    raw = body.model_dump(exclude_unset=True)
    updates = {}
    for key, value in raw.items():
        if key in ("name", "nickname", "whatsapp", "notes", "status") and isinstance(value, str):
            value = value.strip()
        if key == "name" and value is None:
            raise HTTPException(400, "Nome obrigatório")
        if key == "photo" and value is not None and not str(value).startswith("data:image/"):
            # Same processing/validation contract as the original registration.
            raise HTTPException(400, "Formato de foto inválido")
        updates[key] = value
    if updates:
        updates["updated_at"] = now_iso()
        r = await db.players.update_one({"id": pid}, {"$set": updates})
        if r.matched_count == 0: raise HTTPException(404, "Jogador não encontrado")
    d = await db.players.find_one({"id": pid})
    if not d: raise HTTPException(404, "Jogador não encontrado")
    return clean(d)


@api.delete("/players/{pid}")
async def delete_player(pid: str, _=Depends(require_admin)):
    await db.players.delete_one({"id": pid})
    await db.teams.update_many({}, {"$pull": {"players": pid}})
    return {"ok": True}


# ---------- Teams ----------
@api.get("/teams")
async def list_teams():
    docs = await db.teams.find({}).sort("order", 1).to_list(1000)
    return [clean(d) for d in docs]


@api.patch("/teams/{tid}")
async def rename_team(tid: str, body: TeamRenameIn, _=Depends(require_admin)):
    r = await db.teams.update_one({"id": tid}, {"$set": {"name": body.name.strip()}})
    if r.matched_count == 0: raise HTTPException(404, "Equipe não encontrada")
    return clean(await db.teams.find_one({"id": tid}))


@api.post("/teams/groups")
async def assign_groups(body: GroupAssignIn, _=Depends(require_admin)):
    for tid, grp in body.groups.items():
        await db.teams.update_one({"id": tid}, {"$set": {"group": grp}})
    return {"ok": True}


# ---------- Draw ----------
def balanced_split(players, num_teams, per_team):
    groups = {"PROFISSIONAL": [], "INTERMEDIÁRIO": [], "INICIANTE": []}
    for p in players:
        groups.get(p["level"], groups["INICIANTE"]).append(p)
    for k in groups: random.shuffle(groups[k])
    teams = [[] for _ in range(num_teams)]
    for lvl in ["PROFISSIONAL", "INTERMEDIÁRIO", "INICIANTE"]:
        for p in groups[lvl]:
            teams.sort(key=lambda t: len(t))
            for t in teams:
                if len(t) < per_team:
                    t.append(p); break
    return teams


def normal_split(players, num_teams, per_team):
    pool = players[:]; random.shuffle(pool)
    teams = [[] for _ in range(num_teams)]
    i = 0
    for p in pool:
        for _ in range(num_teams):
            if len(teams[i % num_teams]) < per_team:
                teams[i % num_teams].append(p); i += 1; break
            i += 1
    return teams


async def ensure_teams(num_teams: int):
    """Keep team slots in sync with the configured number of teams."""
    teams = await db.teams.find({}).sort("order", 1).to_list(1000)
    for i in range(len(teams), num_teams):
        name = DEFAULT_TEAMS[i] if i < len(DEFAULT_TEAMS) else f"TEAM {i + 1:02d}"
        doc = {
            "id": str(uuid.uuid4()), "name": name, "order": i,
            "group": None, "players": [], "created_at": now_iso(),
        }
        await db.teams.insert_one(doc)
        teams.append(doc)
    # Slots beyond the configured count are empty at this point (draw clears
    # rosters first), so removing them cannot delete player or match data.
    for extra in teams[num_teams:]:
        await db.teams.delete_one({"id": extra["id"]})
    return (await db.teams.find({}).sort("order", 1).to_list(1000))[:num_teams]


@api.post("/draw")
async def run_draw(body: DrawIn, _=Depends(require_admin)):
    t = await db.tournament.find_one({"id": "main"}) or {}
    cfg = tournament_config(t)
    num_teams = body.num_teams or cfg["num_teams"]
    players_per_team = body.players_per_team or cfg["players_per_team"]
    num_groups = body.num_groups or cfg["num_groups"]
    qualifiers_per_group = body.qualifiers_per_group or cfg["qualifiers_per_group"]
    err = validate_structure(num_teams, players_per_team, num_groups, qualifiers_per_group)
    if err:
        raise HTTPException(400, err)
    needed = num_teams * players_per_team
    players = await db.players.find({"status": "CONFIRMADO"}).to_list(2000)
    if len(players) < needed:
        raise HTTPException(400, f"Necessário {needed} jogadores confirmados, temos {len(players)}")

    selected = players[:needed]
    buckets = (balanced_split(selected, num_teams, players_per_team)
               if body.mode == "BALANCED" else normal_split(selected, num_teams, players_per_team))

    await db.players.update_many({}, {"$set": {"team_id": None}})
    await db.teams.update_many({}, {"$set": {"players": []}})
    teams = await ensure_teams(num_teams)

    for i, team in enumerate(teams):
        pids = [p["id"] for p in buckets[i]]
        group = GROUP_LETTERS[i % num_groups]
        await db.teams.update_one(
            {"id": team["id"]}, {"$set": {"players": pids, "group": group}})
        for pid in pids:
            await db.players.update_one({"id": pid}, {"$set": {"team_id": team["id"]}})

    await db.matches.delete_many({})
    await generate_group_matches()
    await db.tournament.update_one({"id": "main"}, {"$set": {
        "num_teams": num_teams, "players_per_team": players_per_team,
        "num_groups": num_groups, "qualifiers_per_group": qualifiers_per_group,
        "player_limit": needed,
        "draw_done": True, "status": "GROUPS",
        "live_mode": "MATCH", "live_match_id": None,
    }})
    return {
        "ok": True, "num_teams": num_teams, "players_per_team": players_per_team,
        "num_groups": num_groups, "qualifiers_per_group": qualifiers_per_group,
        "qualifiers_total": num_groups * qualifiers_per_group, "capacity": needed,
    }


async def generate_group_matches():
    teams = await db.teams.find({}).sort("order", 1).to_list(1000)
    tour = await db.tournament.find_one({"id": "main"}) or {}
    dur = tour.get("default_duration_s", DEFAULT_DURATION_S)

    by_group = {}
    for t in teams:
        if not t.get("players"):
            continue
        by_group.setdefault(t.get("group") or "A", []).append(t)

    match_no = 1
    all_pairs = []
    for gname in sorted(by_group):
        grp_teams = by_group[gname]
        pairs = []
        for i in range(len(grp_teams)):
            for j in range(i + 1, len(grp_teams)):
                pairs.append((grp_teams[i], grp_teams[j], gname))
        random.shuffle(pairs)
        ordered = []
        last = None
        remaining = pairs[:]
        while remaining:
            pick = 0
            for idx, p in enumerate(remaining):
                if last is None or (p[0]["id"] not in last and p[1]["id"] not in last):
                    pick = idx; break
            p = remaining.pop(pick)
            ordered.append(p); last = {p[0]["id"], p[1]["id"]}
        all_pairs.extend(ordered)
    for a, b, g in all_pairs:
        await db.matches.insert_one({
            "id": str(uuid.uuid4()), "number": match_no,
            "phase": "GROUP", "group": g,
            "team_a": a["id"], "team_b": b["id"],
            "status": "AGUARDANDO", "winner_team_id": None,
            "elims_a": 0, "elims_b": 0, "points_a": 0, "points_b": 0,
            "eliminated_players_a": [], "eliminated_players_b": [],
            "eliminations": [], "duration_seconds": dur,
            "started_at": None, "paused_at": None, "pause_accumulated_ms": 0,
            "ended_at": None, "is_draw": False, "locked": False,
            "perfect_a": False, "perfect_b": False,
            "created_at": now_iso(),
        })
        match_no += 1


# ---------- Tournament ----------
@api.get("/tournament")
async def get_tournament():
    t = await db.tournament.find_one({"id": "main"})
    if not t:
        raise HTTPException(404, "Torneio não configurado")
    t = clean(t)
    cfg = tournament_config(t)
    # Derived from the event configuration — never a separate source of truth.
    t["player_limit"] = cfg["capacity"]
    t["capacity"] = cfg["capacity"]
    t["qualifiers_total"] = cfg["qualifiers_total"]
    return t


@api.patch("/tournament")
async def update_tournament(body: TournamentUpdate, _=Depends(require_admin)):
    t = await db.tournament.find_one({"id": "main"})
    if not t:
        raise HTTPException(404, "Torneio não configurado")
    current = tournament_config(t)
    data = body.model_dump(exclude_unset=True)

    structural = ("num_teams", "players_per_team", "num_groups", "qualifiers_per_group")
    requested = {k: int(data[k]) for k in structural if data.get(k) is not None}
    changes = {k: v for k, v in requested.items() if v != current[k]}

    if changes:
        matches_exist = await db.matches.count_documents({}) > 0
        if t.get("draw_done") or matches_exist:
            raise HTTPException(409, (
                "A estrutura já foi sorteada. Reinicie o torneio (Reset) antes de alterar "
                "equipes, jogadores por equipe, grupos ou classificados."
            ))
        merged = {**current, **changes}
        err = validate_structure(merged["num_teams"], merged["players_per_team"],
                                 merged["num_groups"], merged["qualifiers_per_group"])
        if err:
            raise HTTPException(400, err)
        players_count = await db.players.count_documents({})
        capacity = merged["num_teams"] * merged["players_per_team"]
        if players_count > capacity:
            excess = players_count - capacity
            raise HTTPException(400, (
                f"{players_count} jogadores inscritos excedem as {capacity} vagas "
                f"({merged['num_teams']} equipes × {merged['players_per_team']} jogadores). "
                f"Remova {excess} inscrito(s) ou aumente as vagas antes de aplicar."
            ))
        data.update(changes)
        data["player_limit"] = capacity

    updates = {k: v for k, v in data.items() if v is not None}
    # player_limit is derived from the structure; keep the stored value in sync.
    updates["player_limit"] = (
        (data.get("num_teams") or current["num_teams"]) *
        (data.get("players_per_team") or current["players_per_team"])
    )
    await db.tournament.update_one({"id": "main"}, {"$set": updates})
    return await get_tournament()


@api.post("/tournament/reset")
async def reset_tournament(_=Depends(require_admin)):
    """Clears the whole competition structure but keeps every registered player.

    Idempotent: running it again on an already reset tournament is a no-op.
    Matches (group stage + playoffs), teams and standings (derived from matches)
    are removed; players keep all their data and only lose `team_id`.
    """
    matches = await db.matches.delete_many({})
    teams = await db.teams.delete_many({})
    players = await db.players.update_many({}, {"$set": {"team_id": None}})
    await db.tournament.update_one({"id": "main"}, {"$set": {
        "draw_done": False, "status": "OPEN", "mvp_player_id": None,
        "live_mode": "MATCH", "live_match_id": None,
    }})
    t = await db.tournament.find_one({"id": "main"})
    return {
        "ok": True,
        "deleted": {"matches": matches.deleted_count, "teams": teams.deleted_count},
        "players_kept": players.matched_count,
        "tournament": await get_tournament() if t else None,
    }


# ---------- LIVE state (Telão control) ----------
@api.get("/live/state")
async def live_state():
    """Public read: which view the Telão should show and which match is pinned."""
    t = await db.tournament.find_one({"id": "main"}) or {}
    return {
        "mode": t.get("live_mode") or "MATCH",
        "match_id": t.get("live_match_id"),
    }


@api.post("/live/state")
async def set_live_state(body: LiveStateIn, _=Depends(require_admin)):
    update = {}
    if body.mode is not None:
        update["live_mode"] = body.mode
    # match_id: only include when caller sent the key at all
    payload_keys = body.model_dump(exclude_unset=True).keys()
    if "match_id" in payload_keys:
        update["live_match_id"] = body.match_id
    if update:
        await db.tournament.update_one({"id": "main"}, {"$set": update})
    return await live_state()


@api.post("/live/load-next")
async def load_next_match(_=Depends(require_admin)):
    """Pins the next AGUARDANDO match onto the Telão and switches to MATCH mode."""
    docs = await db.matches.find({"status": "AGUARDANDO"}).sort("number", 1).to_list(1)
    match_id = docs[0]["id"] if docs else None
    await db.tournament.update_one({"id": "main"}, {"$set": {
        "live_mode": "MATCH", "live_match_id": match_id,
    }})
    return {"match_id": match_id, "mode": "MATCH"}


# ---------- Matches ----------
@api.get("/matches")
async def list_matches():
    docs = await db.matches.find({}).sort("number", 1).to_list(1000)
    out = []
    for d in docs:
        d = default_match_fields(d)
        if d["status"] == "EM_ANDAMENTO" and compute_elapsed_ms(d) >= d["duration_seconds"] * 1000:
            await _finalize_match_internal(d["id"])
            d = default_match_fields(await db.matches.find_one({"id": d["id"]}))
        d["elapsed_ms"] = compute_elapsed_ms(d)
        d["remaining_ms"] = max(0, d["duration_seconds"] * 1000 - d["elapsed_ms"])
        out.append(clean(d))
    return out


async def _get_match_doc(mid):
    d = await db.matches.find_one({"id": mid})
    if not d: raise HTTPException(404, "Partida não encontrada")
    return default_match_fields(d)


@api.get("/matches/{mid}")
async def get_match(mid: str):
    d = await _get_match_doc(mid)
    if d["status"] == "EM_ANDAMENTO" and compute_elapsed_ms(d) >= d["duration_seconds"] * 1000:
        await _finalize_match_internal(mid)
        d = await _get_match_doc(mid)
    d["elapsed_ms"] = compute_elapsed_ms(d)
    d["remaining_ms"] = max(0, d["duration_seconds"] * 1000 - d["elapsed_ms"])
    return clean(d)


@api.post("/matches/{mid}/duration")
async def set_duration(mid: str, body: DurationIn, _=Depends(require_admin)):
    m = await _get_match_doc(mid)
    if m["status"] not in ("AGUARDANDO",):
        raise HTTPException(400, "Só é possível alterar a duração antes de iniciar a partida")
    await db.matches.update_one({"id": mid}, {"$set": {"duration_seconds": max(5, int(body.duration_seconds))}})
    return await get_match(mid)


@api.post("/matches/{mid}/start")
async def start_match(mid: str, _=Depends(require_admin)):
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    if m["status"] == "ENCERRADA":
        raise HTTPException(400, "Partida já encerrada")
    if m.get("started_at"):
        return await get_match(mid)
    await db.matches.update_one({"id": mid}, {"$set": {
        "started_at": now_iso(), "status": "EM_ANDAMENTO",
        "paused_at": None, "pause_accumulated_ms": 0, "ended_at": None,
    }})
    # Auto-pin the Telão to this match & switch to MATCH mode
    await db.tournament.update_one({"id": "main"}, {"$set": {
        "live_mode": "MATCH", "live_match_id": mid,
    }})
    return await get_match(mid)


@api.post("/matches/{mid}/pause")
async def pause_match(mid: str, _=Depends(require_admin)):
    m = await _get_match_doc(mid)
    if m["status"] != "EM_ANDAMENTO":
        raise HTTPException(400, "Só é possível pausar uma partida em andamento")
    await db.matches.update_one({"id": mid}, {"$set": {"paused_at": now_iso(), "status": "PAUSADA"}})
    return await get_match(mid)


@api.post("/matches/{mid}/resume")
async def resume_match(mid: str, _=Depends(require_admin)):
    m = await _get_match_doc(mid)
    if m["status"] != "PAUSADA":
        raise HTTPException(400, "Partida não está pausada")
    paused = parse_iso(m["paused_at"])
    delta_ms = int((datetime.now(timezone.utc) - paused).total_seconds() * 1000)
    await db.matches.update_one({"id": mid}, {
        "$set": {"paused_at": None, "status": "EM_ANDAMENTO"},
        "$inc": {"pause_accumulated_ms": delta_ms},
    })
    return await get_match(mid)


@api.post("/matches/{mid}/end")
async def end_match(mid: str, _=Depends(require_admin)):
    m = await _get_match_doc(mid)
    if m["status"] == "AGUARDANDO":
        raise HTTPException(400, "A partida ainda não foi iniciada")
    await _finalize_match_internal(mid)
    return await get_match(mid)


async def _finalize_match_internal(mid: str):
    m = await db.matches.find_one({"id": mid})
    if not m or m.get("status") == "ENCERRADA":
        return
    m = default_match_fields(m)
    teams = await db.teams.find({}).to_list(50)
    teams_by_id = {t["id"]: t for t in teams}
    r = compute_result(m, teams_by_id)
    update_set = {**r, "status": "ENCERRADA", "ended_at": now_iso()}
    ops = {"$set": update_set}
    if m.get("paused_at"):
        paused = parse_iso(m["paused_at"])
        delta_ms = int((datetime.now(timezone.utc) - paused).total_seconds() * 1000)
        update_set["paused_at"] = None
        ops["$inc"] = {"pause_accumulated_ms": delta_ms}
    await db.matches.update_one({"id": mid}, ops)
    await maybe_advance_playoffs()


@api.post("/matches/{mid}/reopen")
async def reopen_match(mid: str, _=Depends(require_admin)):
    """Admin correction: reopen a finished match."""
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    await db.matches.update_one({"id": mid}, {"$set": {
        "status": "PAUSADA" if m.get("started_at") else "AGUARDANDO",
        "ended_at": None,
    }})
    return await get_match(mid)


@api.post("/matches/{mid}/lock")
async def toggle_lock(mid: str, _=Depends(require_admin)):
    m = await _get_match_doc(mid)
    await db.matches.update_one({"id": mid}, {"$set": {"locked": not m.get("locked", False)}})
    return await get_match(mid)


@api.post("/matches/{mid}/set-winner")
async def set_winner(mid: str, body: SetWinnerIn, _=Depends(require_admin)):
    """Manual override — used for playoff draws where a winner must be chosen."""
    m = await _get_match_doc(mid)
    if body.winner_team_id and body.winner_team_id not in (m["team_a"], m["team_b"]):
        raise HTTPException(400, "Vencedor inválido")
    is_draw = body.winner_team_id is None
    await db.matches.update_one({"id": mid}, {"$set": {
        "winner_team_id": body.winner_team_id, "is_draw": is_draw,
    }})
    await maybe_advance_playoffs()
    return await get_match(mid)


# ---------- Eliminations ----------
@api.post("/matches/{mid}/eliminate")
async def add_elimination(mid: str, body: EliminateIn, _=Depends(require_admin)):
    """Records that a player was eliminated in the match.
    The eliminator field is intentionally not tracked (per KOP 3x3 official rules)."""
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    if m["status"] not in ("EM_ANDAMENTO",):
        raise HTTPException(400, "A partida precisa estar em andamento")
    ta = await db.teams.find_one({"id": m["team_a"]})
    tb = await db.teams.find_one({"id": m["team_b"]})
    all_ids = set(ta["players"]) | set(tb["players"])
    if body.eliminated_id not in all_ids:
        raise HTTPException(400, "Jogador eliminado não pertence à partida")
    already_eliminated = {e["eliminated_id"] for e in m.get("eliminations", [])}
    if body.eliminated_id in already_eliminated:
        raise HTTPException(400, "Jogador já foi eliminado")
    entry = {
        "eliminated_id": body.eliminated_id,
        "at_ms": compute_elapsed_ms(m),
        "at": now_iso(),
    }
    await db.matches.update_one({"id": mid}, {"$push": {"eliminations": entry}})
    # Live aggregate recompute
    m = await _get_match_doc(mid)
    teams_by_id = {ta["id"]: ta, tb["id"]: tb}
    r = compute_result(m, teams_by_id)
    await db.matches.update_one({"id": mid}, {"$set": {
        "elims_a": r["elims_a"], "elims_b": r["elims_b"],
        "points_a": r["points_a"], "points_b": r["points_b"],
        "eliminated_players_a": r["eliminated_players_a"],
        "eliminated_players_b": r["eliminated_players_b"],
    }})
    # Auto-end when a full 3-0 wipe happens (winner determined by survivors)
    if r["alive_a"] == 0 or r["alive_b"] == 0:
        await _finalize_match_internal(mid)
    return await get_match(mid)


@api.delete("/matches/{mid}/eliminate/last")
async def undo_last_elim(mid: str, _=Depends(require_admin)):
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    if not m.get("eliminations"):
        raise HTTPException(400, "Sem eliminações para desfazer")
    await db.matches.update_one({"id": mid}, {"$pop": {"eliminations": 1}})
    # Recompute the full aggregate so the match never keeps a stale result.
    m = await _get_match_doc(mid)
    ta = await db.teams.find_one({"id": m["team_a"]})
    tb = await db.teams.find_one({"id": m["team_b"]})
    r = compute_result(m, {ta["id"]: ta, tb["id"]: tb})
    update = {
        "elims_a": r["elims_a"], "elims_b": r["elims_b"],
        "points_a": r["points_a"], "points_b": r["points_b"],
        "eliminated_players_a": r["eliminated_players_a"],
        "eliminated_players_b": r["eliminated_players_b"],
        "winner_team_id": r["winner_team_id"],
        "is_draw": r["is_draw"],
        "perfect_a": r["perfect_a"], "perfect_b": r["perfect_b"],
    }
    # If the match was closed by a wipe and the wipe no longer holds (and the
    # clock has not expired), reopen it instead of leaving it ENCERRADA.
    if m["status"] == "ENCERRADA":
        time_up = compute_elapsed_ms(m) >= m["duration_seconds"] * 1000
        if not time_up and r["winner_team_id"] is None:
            update["status"] = "EM_ANDAMENTO"
            update["ended_at"] = None
    await db.matches.update_one({"id": mid}, {"$set": update})
    await maybe_advance_playoffs()
    return await get_match(mid)


# ---------- Standings ----------
@api.get("/standings")
async def standings():
    teams = await db.teams.find({}).sort("order", 1).to_list(1000)
    matches = await db.matches.find({"phase": "GROUP", "status": "ENCERRADA"}).to_list(1000)

    def blank(t):
        return {
            "team_id": t["id"], "team_name": t["name"], "group": t.get("group") or "A",
            "played": 0, "wins": 0, "draws": 0, "losses": 0,
            "elims_for": 0, "elims_against": 0, "diff": 0, "points": 0,
        }

    stats = {t["id"]: blank(t) for t in teams}
    for m in matches:
        m = default_match_fields(m)
        a, b = m["team_a"], m["team_b"]
        if a not in stats or b not in stats: continue
        stats[a]["played"] += 1; stats[b]["played"] += 1
        stats[a]["elims_for"] += m["elims_a"]; stats[a]["elims_against"] += m["elims_b"]
        stats[b]["elims_for"] += m["elims_b"]; stats[b]["elims_against"] += m["elims_a"]
        stats[a]["points"] += m["points_a"]; stats[b]["points"] += m["points_b"]
        if m.get("is_draw"):
            stats[a]["draws"] += 1; stats[b]["draws"] += 1
        elif m["winner_team_id"] == a:
            stats[a]["wins"] += 1; stats[b]["losses"] += 1
        elif m["winner_team_id"] == b:
            stats[b]["wins"] += 1; stats[a]["losses"] += 1
    for s in stats.values():
        s["diff"] = s["elims_for"] - s["elims_against"]

    def sort_key(s):
        return (-s["points"], -s["wins"], -s["draws"], -s["diff"], -s["elims_for"])

    grouped = {}
    for s in stats.values():
        grouped.setdefault(s["group"], []).append(s)
    return {name: sorted(rows, key=sort_key) for name, rows in sorted(grouped.items())}


# ---------- Playoffs ----------
def seeded_qualifiers(standings_data, num_groups, qualifiers_per_group):
    """Seed order: rank 1 of every group, then rank 2, ... (cross-group bracket)."""
    seeds = []
    for rank in range(qualifiers_per_group):
        for g in sorted(standings_data.keys()):
            rows = standings_data.get(g) or []
            if rank < len(rows):
                seeds.append(rows[rank]["team_id"])
    return seeds


async def _create_playoff_matches(pairs, phase, start_number):
    tour = await db.tournament.find_one({"id": "main"}) or {}
    dur = tour.get("default_duration_s", DEFAULT_DURATION_S)
    for i, (ta, tb) in enumerate(pairs):
        await db.matches.insert_one({
            "id": str(uuid.uuid4()), "number": start_number + i,
            "phase": phase, "group": None,
            "team_a": ta, "team_b": tb, "status": "AGUARDANDO",
            "winner_team_id": None,
            "elims_a": 0, "elims_b": 0, "points_a": 0, "points_b": 0,
            "eliminated_players_a": [], "eliminated_players_b": [],
            "eliminations": [], "duration_seconds": dur,
            "started_at": None, "paused_at": None, "pause_accumulated_ms": 0,
            "ended_at": None, "is_draw": False, "locked": False,
            "perfect_a": False, "perfect_b": False,
            "created_at": now_iso(),
        })


async def maybe_advance_playoffs():
    total_group = await db.matches.count_documents({"phase": "GROUP"})
    done_group = await db.matches.count_documents({"phase": "GROUP", "status": "ENCERRADA"})
    if total_group == 0 or done_group < total_group:
        return

    t = await db.tournament.find_one({"id": "main"}) or {}
    cfg = tournament_config(t)
    bracket = cfg["qualifiers_total"]
    if bracket not in (2, 4, 8, 16):
        return

    playoff_count = await db.matches.count_documents({"phase": {"$in": PLAYOFF_PHASES}})
    if playoff_count == 0:
        s = await standings()
        seeds = seeded_qualifiers(s, cfg["num_groups"], cfg["qualifiers_per_group"])[:bracket]
        if len(seeds) < bracket:
            return
        pairs = [(seeds[i], seeds[bracket - 1 - i]) for i in range(bracket // 2)]
        start = (await db.matches.count_documents({})) + 1
        await _create_playoff_matches(pairs, first_playoff_phase(bracket), start)
        await db.tournament.update_one({"id": "main"}, {"$set": {"status": "PLAYOFFS"}})
        return

    present = [ph for ph in ("R16", "QF", "SEMI", "FINAL")
               if await db.matches.count_documents({"phase": ph})]
    if not present:
        return
    current = present[-1]
    current_matches = await db.matches.find({"phase": current}).sort("number", 1).to_list(50)

    if current == "FINAL":
        final = current_matches[0] if current_matches else None
        if final and final["status"] == "ENCERRADA" and final.get("winner_team_id"):
            await db.tournament.update_one({"id": "main"}, {"$set": {"status": "FINISHED"}})
        return

    if any(m["status"] != "ENCERRADA" for m in current_matches):
        return
    if any(not m.get("winner_team_id") for m in current_matches):
        return

    winners = [m["winner_team_id"] for m in current_matches]
    losers = [m["team_b"] if m["winner_team_id"] == m["team_a"] else m["team_a"]
              for m in current_matches]
    nxt = next_playoff_phase(current)
    if not nxt:
        return
    if await db.matches.count_documents({"phase": nxt}) > 0:
        return

    start = (await db.matches.count_documents({})) + 1
    pairs = [(winners[i], winners[i + 1]) for i in range(0, len(winners) - 1, 2)]
    await _create_playoff_matches(pairs, nxt, start)
    if nxt == "FINAL" and bracket >= 4 and await db.matches.count_documents({"phase": "THIRD"}) == 0:
        start_third = (await db.matches.count_documents({})) + 1
        await _create_playoff_matches([(losers[0], losers[1])], "THIRD", start_third)


@api.get("/playoffs")
async def get_playoffs():
    docs = await db.matches.find({"phase": {"$in": PLAYOFF_PHASES}}).sort("number", 1).to_list(100)
    return [clean(default_match_fields(d)) for d in docs]


@api.get("/champion")
async def champion():
    final = await db.matches.find_one({"phase": "FINAL", "status": "ENCERRADA"})
    third = await db.matches.find_one({"phase": "THIRD", "status": "ENCERRADA"})
    result = {"first": None, "second": None, "third": None}
    if final and final.get("winner_team_id"):
        winner = final["winner_team_id"]
        loser = final["team_b"] if winner == final["team_a"] else final["team_a"]
        result["first"] = winner; result["second"] = loser
    if third and third.get("winner_team_id"):
        result["third"] = third["winner_team_id"]
    t = await db.tournament.find_one({"id": "main"})
    result["mvp_player_id"] = t.get("mvp_player_id")
    return result


@api.post("/champion/mvp")
async def set_mvp(body: MvpIn, _=Depends(require_admin)):
    await db.tournament.update_one({"id": "main"}, {"$set": {"mvp_player_id": body.player_id}})
    return {"ok": True}


# ---------- Stats ----------
@api.get("/stats/players")
async def player_stats():
    players = await db.players.find({}).to_list(1000)
    teams = await db.teams.find({}).to_list(50)
    team_by_id = {t["id"]: t for t in teams}
    matches = await db.matches.find({"status": "ENCERRADA"}).to_list(1000)

    stats = {}
    for p in players:
        stats[p["id"]] = {
            "player_id": p["id"], "name": p["name"], "nickname": p.get("nickname"),
            "photo": p.get("photo"), "level": p["level"],
            "team_id": p.get("team_id"),
            "team_name": team_by_id.get(p.get("team_id") or "", {}).get("name"),
            "matches": 0, "team_wins": 0, "team_draws": 0, "team_losses": 0,
            "times_eliminated": 0, "perfects": 0, "survivals": 0,
        }

    for m in matches:
        m = default_match_fields(m)
        team_a = team_by_id.get(m["team_a"], {})
        team_b = team_by_id.get(m["team_b"], {})
        team_a_players = team_a.get("players", []); team_b_players = team_b.get("players", [])
        eliminated_ids = {e["eliminated_id"] for e in m.get("eliminations", [])}
        for pid in team_a_players:
            if pid in stats:
                stats[pid]["matches"] += 1
                if pid not in eliminated_ids: stats[pid]["survivals"] += 1
                if m.get("is_draw"): stats[pid]["team_draws"] += 1
                elif m["winner_team_id"] == m["team_a"]:
                    stats[pid]["team_wins"] += 1
                    if m.get("perfect_a"): stats[pid]["perfects"] += 1
                else: stats[pid]["team_losses"] += 1
        for pid in team_b_players:
            if pid in stats:
                stats[pid]["matches"] += 1
                if pid not in eliminated_ids: stats[pid]["survivals"] += 1
                if m.get("is_draw"): stats[pid]["team_draws"] += 1
                elif m["winner_team_id"] == m["team_b"]:
                    stats[pid]["team_wins"] += 1
                    if m.get("perfect_b"): stats[pid]["perfects"] += 1
                else: stats[pid]["team_losses"] += 1
        for e in m.get("eliminations", []):
            if e["eliminated_id"] in stats:
                stats[e["eliminated_id"]]["times_eliminated"] += 1

    return sorted(stats.values(), key=lambda s: (-s["team_wins"], -s["perfects"], -s["survivals"], s["times_eliminated"]))


@api.get("/stats/teams")
async def team_stats():
    teams = await db.teams.find({}).sort("order", 1).to_list(50)
    matches = await db.matches.find({"status": "ENCERRADA"}).to_list(1000)
    out = []
    for t in teams:
        played = wins = losses = draws = ef = ea = pts = perfects = 0
        streak = best = 0
        rel = sorted([m for m in matches if m["team_a"] == t["id"] or m["team_b"] == t["id"]],
                     key=lambda x: x["number"])
        for m in rel:
            m = default_match_fields(m)
            played += 1
            is_a = m["team_a"] == t["id"]
            if is_a:
                ef += m["elims_a"]; ea += m["elims_b"]; pts += m["points_a"]
            else:
                ef += m["elims_b"]; ea += m["elims_a"]; pts += m["points_b"]
            if m.get("is_draw"):
                draws += 1; streak = 0
            elif m["winner_team_id"] == t["id"]:
                wins += 1; streak += 1; best = max(best, streak)
                if (is_a and m.get("perfect_a")) or (not is_a and m.get("perfect_b")):
                    perfects += 1
            else:
                losses += 1; streak = 0
        out.append({
            "team_id": t["id"], "team_name": t["name"], "group": t["group"],
            "played": played, "wins": wins, "draws": draws, "losses": losses,
            "elims_for": ef, "elims_against": ea, "diff": ef - ea,
            "points": pts, "best_streak": best, "perfects": perfects,
        })
    return out


# ---------- Health ----------
@api.get("/")
async def root():
    return {"app": "KOP 3x3", "status": "running"}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"], allow_headers=["*"],
)

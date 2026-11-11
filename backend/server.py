from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import re
import uuid
import random
import logging
import hashlib
import json
import scoring
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
    if user.get("role") == "ranger" and not user.get("active", True):
        raise HTTPException(403, "Acesso desativado")
    return user


async def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin only")
    return user


async def require_staff(user=Depends(get_current_user)):
    """Admin or Ranger: live match operations (clock, eliminations, penalties)."""
    if user.get("role") not in ("admin", "ranger"):
        raise HTTPException(403, "Acesso restrito à arbitragem")
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


MATCH_PRIVATE_KEYS = {"audit_log"}
ACTOR_PRIVATE_KEYS = {"by", "by_role", "user_id", "user_email", "client_token"}


def public_match(doc):
    """Anonymous-safe view of a match.

    The audit trail and the identity of the staff member who applied an
    elimination/penalty are internal: the public Telão only needs the result.
    """
    d = clean(dict(doc))
    for key in MATCH_PRIVATE_KEYS:
        d.pop(key, None)
    for field in ("eliminations", "penalties"):
        d[field] = [{k: v for k, v in (item or {}).items()
                     if k not in ACTOR_PRIVATE_KEYS}
                    for item in d.get(field, [])]
    return d


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
    client_token: Optional[str] = Field(None, max_length=80)  # idempotency key
    expected_revision: Optional[int] = None  # optimistic concurrency


class UndeclaredIn(BaseModel):
    player_id: str
    reason: str = Field("Eliminação não declarada", min_length=3, max_length=300)
    client_token: Optional[str] = Field(None, max_length=80)


class PenaltyIn(BaseModel):
    team_id: str
    points: int = Field(1, ge=1, le=3)
    reason: str = Field(..., min_length=3, max_length=300)
    type: Literal["ELIMINACAO_NAO_DECLARADA", "CONDUTA", "OUTRA"] = "ELIMINACAO_NAO_DECLARADA"
    expected_revision: Optional[int] = None
    client_token: Optional[str] = Field(None, max_length=80)


class WoIn(BaseModel):
    team_id: str
    reason: Optional[str] = Field(None, max_length=300)


class DeclareDrawIn(BaseModel):
    reason: Optional[str] = Field(None, max_length=300)
    simultaneous: bool = True


class RedoMatchIn(BaseModel):
    confirm: bool = False
    reason: Optional[str] = Field(None, max_length=300)
    preserve_penalties: bool = False


class RecalculateIn(BaseModel):
    confirm: bool = False
    dry_run: bool = True


class RestoreHistoryIn(BaseModel):
    confirm: bool = False


class RangerIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=120)


class RangerUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    password: Optional[str] = Field(None, min_length=6, max_length=120)
    active: Optional[bool] = None


class RulesIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=60000)


class BannerIn(BaseModel):
    image: str = Field(..., min_length=1, max_length=MAX_PHOTO_B64_LEN * 2)
    filename: Optional[str] = Field(None, max_length=120)


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


DEFAULT_RULES = """# REGULAMENTO OFICIAL — KOP 3x3

## 1. Pontuação
- Cada jogador adversário eliminado vale 1 ponto para a equipe que realizou a eliminação.
- Ao eliminar os 3 jogadores adversários, a equipe recebe +2 pontos de bônus.
- A pontuação máxima de uma equipe em uma partida normal é 5 pontos.

## 2. Resultado da partida
- A equipe vence quando elimina todos os jogadores adversários antes do término do tempo.
- 3 x 0: vencedor 5 pontos, derrotado 0.
- 3 x 1: vencedor 5 pontos, derrotado 1.
- 3 x 2: vencedor 5 pontos, derrotado 2.
- A pontuação não é o placar: o vencedor recebe 5 pontos por eliminar os 3 adversários.

## 3. Empate
- Se o tempo terminar com pelo menos um jogador vivo em cada equipe, a partida é EMPATE, independentemente das eliminações.
- Cada equipe mantém os pontos das eliminações que realizou (ex.: 2 x 1 → 2 e 1 pontos).
- Empate não concede 1 ponto para cada equipe.

## 4. Eliminação simultânea
- Se os últimos jogadores forem eliminados simultaneamente e não houver como determinar a precedência, o resultado é EMPATE.
- Não há vencedor e não há bônus de +2.
- Nunca registrar 3 x 3 como 5 x 5.

## 5. PERFECT
- PERFECT ocorre quando uma equipe elimina os 3 adversários sem perder nenhum jogador.
- O PERFECT não adiciona pontos; é critério de desempate.

## 6. Classificação
1. Pontos totais
2. Número de vitórias
3. Saldo de eliminações (eliminações realizadas − sofridas)
4. Número de PERFECTs
5. Confronto direto
6. Critério complementar (a definir)
7. Critério final (a definir)

## 7. W.O.
- Equipe ausente: resultado administrativo 3 x 0, apresentado como 5 x 0 — W.O.
- Equipe presente: 5 pontos. Equipe ausente: 0 pontos.
- O W.O. não cria eliminações reais e não conta como PERFECT de campo para desempate.

## 8. Eliminação não declarada
- Jogador que não percebeu o impacto não sofre punição automática; o Ranger pode registrar a eliminação depois.
- Jogador que percebeu e deliberadamente continuou jogando: eliminação imediata, eliminação contabilizada ao adversário e −1 ponto na pontuação da equipe naquela partida.
- A pontuação da equipe nunca fica abaixo de zero.

## 9. Penalidades
- Podem ser aplicadas durante ou após a partida, com motivo obrigatório.
- Toda penalidade é registrada com equipe, partida, motivo, pontos, responsável, data/hora e situação da partida.

## 10. Conduta
- As decisões da arbitragem são soberanas.
- Reincidência ou comportamento sistemático pode gerar penalidades adicionais conforme o regulamento.
"""


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

# Fields written by `compute_result` plus the recalculation bookkeeping. A
# rollback restores exactly these fields; eliminations, penalties, rosters and
# audit trails are deliberately preserved as they are.
RESTORABLE_RESULT_KEYS = (
    "elims_a", "elims_b",
    "base_points_a", "base_points_b",
    "penalty_points_a", "penalty_points_b",
    "points_a", "points_b",
    "eliminated_players_a", "eliminated_players_b",
    "alive_a", "alive_b",
    "winner_team_id", "is_draw", "draw_reason",
    "perfect_a", "perfect_b", "admin_perfect_a", "admin_perfect_b",
    "wo", "wo_team_id", "wo_score",
    "legacy_points_a", "legacy_points_b", "scoring_version",
)


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
    # v2 scoring / administration (additive fields, legacy docs keep working)
    m.setdefault("penalties", [])
    m.setdefault("wo", False)
    m.setdefault("wo_team_id", None)
    m.setdefault("wo_reason", None)
    m.setdefault("declared_draw", False)
    m.setdefault("draw_reason", None)
    m.setdefault("base_points_a", 0)
    m.setdefault("base_points_b", 0)
    m.setdefault("penalty_points_a", 0)
    m.setdefault("penalty_points_b", 0)
    m.setdefault("admin_perfect_a", False)
    m.setdefault("admin_perfect_b", False)
    m.setdefault("revision", 0)
    m.setdefault("audit_log", [])
    m.setdefault("redo_count", 0)
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
    """Official KOP 3x3 rules (v2) — delegated to the pure `scoring` module.

    Kept as a thin wrapper so every existing caller keeps working while the
    rules themselves live in a single, unit-tested place.
    """
    return scoring.compute_result(match, teams_by_id)


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
    await db.match_history.create_index([("match_id", 1), ("archived_at", -1)])

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

    # Public regulation page — seeded with the official rules, then fully
    # editable by the administrator (versioned in rules_history).
    if not await db.rules.find_one({"id": "main"}):
        await db.rules.insert_one({
            "id": "main", "content": DEFAULT_RULES, "version": 1,
            "updated_at": now_iso(), "updated_by": "system",
        })

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
    if user.get("role") == "ranger" and not user.get("active", True):
        raise HTTPException(403, "Acesso desativado")
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
            "roster_a": list(a.get("players") or []),
            "roster_b": list(b.get("players") or []),
            "status": "AGUARDANDO", "winner_team_id": None,
            "elims_a": 0, "elims_b": 0, "points_a": 0, "points_b": 0,
            "eliminated_players_a": [], "eliminated_players_b": [],
            "eliminations": [], "duration_seconds": dur,
            "started_at": None, "paused_at": None, "pause_accumulated_ms": 0,
            "ended_at": None, "is_draw": False, "locked": False,
            "perfect_a": False, "perfect_b": False,
            "scoring_version": 2,
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
async def list_matches(user=Depends(optional_current_user)):
    docs = await db.matches.find({}).sort("number", 1).to_list(1000)
    out = []
    for d in docs:
        d = default_match_fields(d)
        if d["status"] == "EM_ANDAMENTO" and compute_elapsed_ms(d) >= d["duration_seconds"] * 1000:
            await _finalize_match_internal(d["id"])
            d = default_match_fields(await db.matches.find_one({"id": d["id"]}))
        d["elapsed_ms"] = compute_elapsed_ms(d)
        d["remaining_ms"] = max(0, d["duration_seconds"] * 1000 - d["elapsed_ms"])
        out.append(d)
    staff = bool(user) and user.get("role") in ("admin", "ranger")
    return [clean(d) if staff else public_match(d) for d in out]


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
    # Public endpoint: never exposes the audit trail or staff e-mails.
    return public_match(d)


@api.post("/matches/{mid}/duration")
async def set_duration(mid: str, body: DurationIn, _=Depends(require_admin)):
    m = await _get_match_doc(mid)
    if m["status"] not in ("AGUARDANDO",):
        raise HTTPException(400, "Só é possível alterar a duração antes de iniciar a partida")
    await db.matches.update_one({"id": mid}, {"$set": {"duration_seconds": max(5, int(body.duration_seconds))}})
    return await get_match(mid)


@api.post("/matches/{mid}/start")
async def start_match(mid: str, user=Depends(require_staff)):
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
async def pause_match(mid: str, user=Depends(require_staff)):
    m = await _get_match_doc(mid)
    if m["status"] != "EM_ANDAMENTO":
        raise HTTPException(400, "Só é possível pausar uma partida em andamento")
    await db.matches.update_one({"id": mid}, {"$set": {"paused_at": now_iso(), "status": "PAUSADA"}})
    return await get_match(mid)


@api.post("/matches/{mid}/resume")
async def resume_match(mid: str, user=Depends(require_staff)):
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
async def end_match(mid: str, user=Depends(require_staff)):
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
    # Snapshot rosters take precedence: a later roster change must never
    # rewrite the result of a match that was already played.
    ta, tb = await _teams_for_match(m)
    r = compute_result(m, {ta["id"]: ta, tb["id"]: tb})
    update_set = {**r, "status": "ENCERRADA", "ended_at": now_iso(),
                  "revision": int(m.get("revision") or 0) + 1}
    ops = {"$set": update_set}
    if m.get("paused_at"):
        paused = parse_iso(m["paused_at"])
        delta_ms = int((datetime.now(timezone.utc) - paused).total_seconds() * 1000)
        update_set["paused_at"] = None
        ops["$inc"] = {"pause_accumulated_ms": delta_ms}
    await db.matches.update_one({"id": mid}, ops)
    await maybe_advance_playoffs()


@api.post("/matches/{mid}/reopen")
async def reopen_match(mid: str, user=Depends(require_admin)):
    """Admin correction: reopen a finished match and recompute its derivations."""
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    before = {"status": m.get("status"), "winner_team_id": m.get("winner_team_id")}
    update = {
        "status": "PAUSADA" if m.get("started_at") else "AGUARDANDO",
        "ended_at": None,
    }
    fresh, r = await _recompute_match(mid, update)
    await _push_audit(mid, _audit_entry("REOPEN", user, before,
        {"status": fresh.get("status"), "points_a": r["points_a"],
         "points_b": r["points_b"]}))
    return await get_match(mid)


@api.post("/matches/{mid}/lock")
async def toggle_lock(mid: str, _=Depends(require_admin)):
    m = await _get_match_doc(mid)
    await db.matches.update_one({"id": mid}, {"$set": {"locked": not m.get("locked", False)}})
    return await get_match(mid)


@api.post("/matches/{mid}/set-winner")
async def set_winner(mid: str, body: SetWinnerIn, user=Depends(require_admin)):
    """Manual winner override for playoff ties (never changes points).

    Restricted to finished playoff matches: a group-stage winner must come
    from the recorded eliminations, so an override can never create a win the
    scoreboard does not support.
    """
    m = await _get_match_doc(mid)
    if m.get("phase") == "GROUP":
        raise HTTPException(400, "O vencedor de partida de grupo é definido pelas eliminações")
    if m.get("status") != "ENCERRADA":
        raise HTTPException(400, "A partida precisa estar encerrada")
    if m.get("wo"):
        raise HTTPException(400, "Partida W.O. já possui resultado administrativo")
    if body.winner_team_id and body.winner_team_id not in (m["team_a"], m["team_b"]):
        raise HTTPException(400, "Vencedor inválido")
    before = {"winner_team_id": m.get("winner_team_id"), "is_draw": m.get("is_draw")}
    is_draw = body.winner_team_id is None
    await db.matches.update_one({"id": mid}, {"$set": {
        "winner_team_id": body.winner_team_id, "is_draw": is_draw,
        "revision": int(m.get("revision") or 0) + 1,
    }})
    await _push_audit(mid, _audit_entry("SET_WINNER", user, before,
        {"winner_team_id": body.winner_team_id, "is_draw": is_draw},
        {"phase": m.get("phase")}))
    await maybe_advance_playoffs()
    return await get_match(mid)


# ---------- Eliminations ----------
async def _teams_for_match(m):
    ta = await db.teams.find_one({"id": m["team_a"]}) or {"id": m["team_a"], "players": []}
    tb = await db.teams.find_one({"id": m["team_b"]}) or {"id": m["team_b"], "players": []}
    # Matches store the roster used when they were created. That snapshot is
    # authoritative for scoring: a later player deletion/redraw can never
    # rewrite a historical result.
    if isinstance(m.get("roster_a"), list):
        ta = {**ta, "players": list(m["roster_a"])}
    if isinstance(m.get("roster_b"), list):
        tb = {**tb, "players": list(m["roster_b"])}
    return ta, tb


def _audit_entry(action, user, before=None, after=None, detail=None):
    return {
        "id": str(uuid.uuid4()), "action": action,
        "user_id": user.get("id"), "user_email": user.get("email"),
        "user_role": user.get("role"), "at": now_iso(),
        "before": before, "after": after, "detail": detail or {},
    }


async def _push_audit(mid: str, entry: dict):
    await db.matches.update_one({"id": mid}, {"$push": {"audit_log": entry}})


async def _recompute_match(mid: str, extra: Optional[dict] = None,
                          auto_end: bool = False):
    """Recompute every derived field with optimistic concurrency.

    Two Rangers may register eliminations at the same time. The elimination
    pushes are atomic; this loop guarantees the derived values (points, bonus,
    PERFECT, result) are written from the latest document, never from a stale
    read that would silently drop the other Ranger's elimination.
    """
    if extra:
        await db.matches.update_one({"id": mid}, {"$set": extra})
    for _ in range(6):
        m = await _get_match_doc(mid)
        revision = int(m.get("revision") or 0)
        ta, tb = await _teams_for_match(m)
        r = compute_result(m, {ta["id"]: ta, tb["id"]: tb})
        update = {**r, "revision": revision + 1}
        if extra:
            update.update(extra)
        if auto_end and m["status"] == "EM_ANDAMENTO" and (
                r["alive_a"] == 0 or r["alive_b"] == 0):
            update["status"] = "ENCERRADA"
            update["ended_at"] = now_iso()
        rev_query = {"revision": revision}
        if revision == 0:
            # Legacy documents may not carry the field yet.
            rev_query = {"$or": [{"revision": 0}, {"revision": {"$exists": False}}]}
        res = await db.matches.update_one(
            {"id": mid, **rev_query}, {"$set": update})
        if res.matched_count:
            return await _get_match_doc(mid), r
    raise HTTPException(
        409, "Partida em atualização concorrente. Recarregue e tente novamente.")


@api.post("/matches/{mid}/eliminate")
async def add_elimination(mid: str, body: EliminateIn, user=Depends(require_staff)):
    """Records that a player was eliminated in the match.

    - Duplicate eliminations are rejected atomically (never double counted).
    - `client_token` makes a retried request idempotent.
    - Rangers act on live matches; admins may also correct a finished match.
    """
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    if m.get("wo"):
        raise HTTPException(400, "Partida registrada como W.O. não aceita eliminações")
    if body.client_token:
        for e in m.get("eliminations", []):
            if e.get("client_token") == body.client_token:
                if e.get("eliminated_id") == body.eliminated_id:
                    return await get_match(mid)  # idempotent retry
                raise HTTPException(409, "client_token já utilizado por outra eliminação")
    is_admin = user.get("role") == "admin"
    if m["status"] == "ENCERRADA" and not is_admin:
        raise HTTPException(403, "Somente o administrador edita partida encerrada")
    if m["status"] not in ("EM_ANDAMENTO", "PAUSADA", "ENCERRADA"):
        raise HTTPException(400, "A partida precisa estar em andamento")
    ta, tb = await _teams_for_match(m)
    all_ids = set(ta.get("players") or []) | set(tb.get("players") or [])
    if body.eliminated_id not in all_ids:
        raise HTTPException(400, "Jogador eliminado não pertence à partida")

    before = {
        "points_a": m.get("points_a"), "points_b": m.get("points_b"),
        "elims_a": m.get("elims_a"), "elims_b": m.get("elims_b"),
        "status": m.get("status"),
    }
    entry = {
        "id": str(uuid.uuid4()), "eliminated_id": body.eliminated_id,
        "at_ms": compute_elapsed_ms(m), "at": now_iso(),
        "by": user.get("email"), "client_token": body.client_token,
    }
    # Atomic guard: one elimination per player and, when the client sends a
    # revision, no silent overwrite of another Ranger's concurrent change.
    query = {
        "id": mid, "locked": {"$ne": True},
        "eliminations.eliminated_id": {"$ne": body.eliminated_id},
    }
    if body.expected_revision is not None:
        query["revision"] = body.expected_revision
    res = await db.matches.update_one(query, {"$push": {"eliminations": entry}})
    if res.matched_count == 0:
        fresh = await db.matches.find_one({"id": mid}) or {}
        duplicate = next((e for e in fresh.get("eliminations", [])
                          if e.get("eliminated_id") == body.eliminated_id), None)
        # A retried request (same idempotency key) answers 200, not an error.
        if duplicate and body.client_token and \
                duplicate.get("client_token") == body.client_token:
            return await get_match(mid)
        if duplicate:
            raise HTTPException(409, "Jogador já foi eliminado")
        raise HTTPException(409, "Partida alterada por outro árbitro. Recarregue e tente novamente.")

    # A wipe ends the match automatically; editing a finished match never does.
    fresh, r = await _recompute_match(mid, auto_end=True)
    await _push_audit(mid, _audit_entry("ELIMINATE", user, before, {
        "points_a": r["points_a"], "points_b": r["points_b"],
        "elims_a": r["elims_a"], "elims_b": r["elims_b"],
        "status": fresh.get("status"),
    }, {"eliminated_id": body.eliminated_id}))
    if fresh.get("status") == "ENCERRADA" and m["status"] != "ENCERRADA":
        await maybe_advance_playoffs()
    return await get_match(mid)


async def _undo_elimination(mid: str, entry: dict, user, keep_finished: bool = False):
    m = await _get_match_doc(mid)
    before = {
        "points_a": m.get("points_a"), "points_b": m.get("points_b"),
        "elims_a": m.get("elims_a"), "elims_b": m.get("elims_b"),
        "status": m.get("status"),
    }
    query = {"id": mid, "locked": {"$ne": True}}
    if entry.get("id"):
        query["eliminations.id"] = entry["id"]
        pull = {"id": entry["id"]}
    else:
        pull = {"eliminated_id": entry.get("eliminated_id")}
    res = await db.matches.update_one(query, {"$pull": {"eliminations": pull}})
    if res.modified_count == 0:
        raise HTTPException(409, "Eliminação já foi removida. Recarregue a partida.")

    update = {}
    ta, tb = await _teams_for_match(m)
    r = compute_result(await _get_match_doc(mid), {ta["id"]: ta, tb["id"]: tb})
    time_up = compute_elapsed_ms(m) >= m["duration_seconds"] * 1000
    # If the match had been auto-closed by the wipe we just undid, let it
    # continue; a match ended by time/referee stays closed.
    if (m["status"] == "ENCERRADA" and m.get("winner_team_id") and not time_up
            and r["winner_team_id"] is None and not keep_finished
            and not m.get("wo") and not m.get("declared_draw")):
        update["status"] = "EM_ANDAMENTO"
        update["ended_at"] = None
    fresh, r = await _recompute_match(mid, update)
    await _push_audit(mid, _audit_entry("UNDO_ELIMINATION", user, before, {
        "points_a": r["points_a"], "points_b": r["points_b"],
        "elims_a": r["elims_a"], "elims_b": r["elims_b"],
        "status": fresh.get("status"),
    }, {"eliminated_id": entry.get("eliminated_id")}))
    await maybe_advance_playoffs()
    return await get_match(mid)


@api.delete("/matches/{mid}/eliminate/last")
async def undo_last_elim(mid: str, keep_finished: bool = False,
                         user=Depends(require_staff)):
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    if not m.get("eliminations"):
        raise HTTPException(400, "Sem eliminações para desfazer")
    if m["status"] == "ENCERRADA" and user.get("role") != "admin":
        raise HTTPException(403, "Somente o administrador edita partida encerrada")
    return await _undo_elimination(mid, m["eliminations"][-1], user, keep_finished)


@api.delete("/matches/{mid}/eliminations/{entry_id}")
async def undo_elimination(mid: str, entry_id: str, keep_finished: bool = False,
                           user=Depends(require_staff)):
    """Undo a specific elimination (correction during or after the match)."""
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    entry = next((e for e in m.get("eliminations", [])
                  if e.get("id") == entry_id or e.get("eliminated_id") == entry_id), None)
    if not entry:
        raise HTTPException(404, "Eliminação não encontrada")
    if m["status"] == "ENCERRADA" and user.get("role") != "admin":
        raise HTTPException(403, "Somente o administrador edita partida encerrada")
    return await _undo_elimination(mid, entry, user, keep_finished)


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
            "perfects": 0, "wo_wins": 0,
            "tiebreak_6": 0, "tiebreak_7": 0,  # reserved: to be defined by the organization
        }

    stats = {t["id"]: blank(t) for t in teams}
    clean_matches = []
    for m in matches:
        m = default_match_fields(m)
        clean_matches.append(m)
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
            if m.get("perfect_a"): stats[a]["perfects"] += 1
            if m.get("wo"): stats[a]["wo_wins"] += 1
        elif m["winner_team_id"] == b:
            stats[b]["wins"] += 1; stats[a]["losses"] += 1
            if m.get("perfect_b"): stats[b]["perfects"] += 1
            if m.get("wo"): stats[b]["wo_wins"] += 1
    for s in stats.values():
        s["diff"] = s["elims_for"] - s["elims_against"]

    grouped = {}
    for s in stats.values():
        grouped.setdefault(s["group"], []).append(s)
    return {name: scoring.sort_standings(rows, clean_matches)
            for name, rows in sorted(grouped.items())}


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
    roster_by_team = {t["id"]: list(t.get("players") or [])
                      for t in await db.teams.find({}).to_list(1000)}
    for i, (ta, tb) in enumerate(pairs):
        await db.matches.insert_one({
            "id": str(uuid.uuid4()), "number": start_number + i,
            "phase": phase, "group": None,
            "team_a": ta, "team_b": tb, "status": "AGUARDANDO",
            "roster_a": roster_by_team.get(ta, []),
            "roster_b": roster_by_team.get(tb, []),
            "winner_team_id": None,
            "elims_a": 0, "elims_b": 0, "points_a": 0, "points_b": 0,
            "eliminated_players_a": [], "eliminated_players_b": [],
            "eliminations": [], "duration_seconds": dur,
            "started_at": None, "paused_at": None, "pause_accumulated_ms": 0,
            "ended_at": None, "is_draw": False, "locked": False,
            "perfect_a": False, "perfect_b": False,
            "scoring_version": 2,
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
async def get_playoffs(user=Depends(optional_current_user)):
    docs = await db.matches.find({"phase": {"$in": PLAYOFF_PHASES}}).sort("number", 1).to_list(100)
    staff = bool(user) and user.get("role") in ("admin", "ranger")
    return [(clean(default_match_fields(d)) if staff
             else public_match(default_match_fields(d))) for d in docs]


@api.get("/bracket/status")
async def get_bracket_status():
    """Reports whether the generated bracket still matches the group results.

    This endpoint never regenerates anything. It only prevents the UI from
    presenting an outdated bracket as valid after a group match is redone or
    a previous playoff round is reopened.
    """
    playoff_docs = await db.matches.find(
        {"phase": {"$in": PLAYOFF_PHASES}}).sort("number", 1).to_list(200)
    if not playoff_docs:
        return {"stale": False, "reason": None}

    t = await db.tournament.find_one({"id": "main"}) or {}
    cfg = tournament_config(t)
    bracket = cfg["qualifiers_total"]
    if bracket not in (2, 4, 8, 16):
        return {"stale": True,
                "reason": "Configuração de classificados incompatível com um mata-mata válido."}

    s = await standings()
    expected = seeded_qualifiers(s, cfg["num_groups"], cfg["qualifiers_per_group"])[:bracket]
    first = first_playoff_phase(bracket)
    first_matches = [m for m in playoff_docs if m["phase"] == first]

    if not first_matches:
        return {"stale": True, "reason": "O mata-mata não possui a fase inicial esperada."}
    expected_pairs = sorted(tuple(sorted((expected[i], expected[bracket - 1 - i])))
                            for i in range(bracket // 2))
    actual_pairs = sorted(tuple(sorted((m["team_a"], m["team_b"])))
                          for m in first_matches)
    if expected_pairs != actual_pairs:
        return {"stale": True,
                "reason": ("A classificação atual não corresponde aos confrontos do mata-mata. "
                           "Um resultado de grupo pode ter sido alterado.")}
    if await db.matches.count_documents({"phase": "GROUP", "status": {"$ne": "ENCERRADA"}}):
        return {"stale": True,
                "reason": "Há partida de grupo não encerrada com mata-mata já gerado."}

    phase_index = {ph: i for i, ph in enumerate(PLAYOFF_PHASES)}
    for ph in ("R16", "QF", "SEMI"):
        phase_matches = [m for m in playoff_docs if m["phase"] == ph]
        if not phase_matches:
            continue
        has_later = any(phase_index[m["phase"]] > phase_index[ph] for m in playoff_docs)
        if has_later and any(m["status"] != "ENCERRADA" for m in phase_matches):
            return {"stale": True,
                    "reason": (f"A fase {ph} foi reaberta ou refeita depois de a fase seguinte "
                               "já ter sido gerada.")}
    return {"stale": False, "reason": None}


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
        # W.O. is administrative: it never invents individual eliminations,
        # survivals or matches played for the players.
        if m.get("wo"):
            continue
        team_a = team_by_id.get(m["team_a"], {})
        team_b = team_by_id.get(m["team_b"], {})
        # Prefer the roster snapshot recorded with the match, so a later roster
        # change cannot rewrite the individual history of that match.
        team_a_players = m.get("roster_a") or team_a.get("players", [])
        team_b_players = m.get("roster_b") or team_b.get("players", [])
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


# ---------- Match administration (official rules v2) ----------
@api.post("/matches/{mid}/wo")
async def set_wo(mid: str, body: WoIn, user=Depends(require_admin)):
    """Administrative W.O.: 3 x 0 on the scoreboard, 5 x 0 in points.

    No player elimination is invented. Only allowed before any real elimination
    was recorded, so individual statistics are never falsified.
    """
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    if body.team_id not in (m["team_a"], m["team_b"]):
        raise HTTPException(400, "Equipe inválida")
    if m.get("eliminations"):
        raise HTTPException(400, "W.O. não pode ser registrado depois de eliminações reais")
    before = {"status": m.get("status"), "points_a": m.get("points_a"),
              "points_b": m.get("points_b")}
    update = {
        "wo": True, "wo_team_id": body.team_id,
        "wo_reason": (body.reason or "").strip() or None,
        "declared_draw": False, "draw_reason": None,
        "status": "ENCERRADA", "ended_at": m.get("ended_at") or now_iso(),
    }
    # Atomic claim: a concurrent elimination cannot slip in between the check
    # above and this write, so a W.O. never carries invented eliminations.
    res = await db.matches.update_one(
        {"id": mid, "locked": {"$ne": True},
         "eliminations.0": {"$exists": False}},
        {"$set": {**update, "revision": int(m.get("revision") or 0) + 1}})
    if res.matched_count == 0:
        raise HTTPException(409, "Partida já possui eliminações registradas")
    fresh, r = await _recompute_match(mid)
    await _push_audit(mid, _audit_entry("WO", user, before, {
        "points_a": r["points_a"], "points_b": r["points_b"],
        "wo_team_id": body.team_id,
    }, {"reason": body.reason}))
    await maybe_advance_playoffs()
    return await get_match(mid)


@api.post("/matches/{mid}/declare-draw")
async def declare_draw(mid: str, body: DeclareDrawIn, user=Depends(require_staff)):
    """Referee-declared draw (e.g. simultaneous elimination without precedence).

    Keeps each team's elimination points and never applies the +2 bonus, so a
    3 x 3 can never become 5 x 5.
    """
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    if m.get("wo"):
        raise HTTPException(400, "Partida já registrada como W.O.")
    before = {"status": m.get("status"), "points_a": m.get("points_a"),
              "points_b": m.get("points_b")}
    update = {
        "declared_draw": True,
        "draw_reason": "SIMULTANEA" if body.simultaneous else "ARBITRAGEM",
    }
    if m["status"] in ("EM_ANDAMENTO", "PAUSADA"):
        update["status"] = "ENCERRADA"
        update["ended_at"] = now_iso()
    fresh, r = await _recompute_match(mid, update)
    await _push_audit(mid, _audit_entry("DECLARE_DRAW", user, before, {
        "points_a": r["points_a"], "points_b": r["points_b"], "is_draw": True,
    }, {"reason": body.reason, "simultaneous": body.simultaneous}))
    await maybe_advance_playoffs()
    return await get_match(mid)


@api.post("/matches/{mid}/penalty")
async def add_penalty(mid: str, body: PenaltyIn, user=Depends(require_staff)):
    """Apply a team penalty (-N points) during or after the match.

    The reason is mandatory and the audit trail stores the actor, the match
    status at the time and the points before/after the penalty.
    """
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    if body.team_id not in (m["team_a"], m["team_b"]):
        raise HTTPException(400, "Equipe inválida")
    if body.client_token and any(
            p.get("client_token") == body.client_token for p in m.get("penalties", [])):
        return await get_match(mid)  # retry of an already applied penalty
    entry = {
        "id": str(uuid.uuid4()), "team_id": body.team_id,
        "points": int(body.points), "reason": body.reason.strip(),
        "type": body.type, "at": now_iso(), "client_token": body.client_token,
        "by": user.get("email"), "by_role": user.get("role"),
        "match_status": m.get("status"),
    }
    query = {"id": mid, "locked": {"$ne": True}}
    if body.expected_revision is not None:
        query["revision"] = body.expected_revision
    if body.client_token:
        # Atomic idempotency: a retried request cannot insert a second penalty.
        query["penalties.client_token"] = {"$ne": body.client_token}
    res = await db.matches.update_one(query, {"$push": {"penalties": entry}})
    if res.matched_count == 0:
        fresh = await db.matches.find_one({"id": mid}) or {}
        if body.client_token and any(
                p.get("client_token") == body.client_token
                for p in fresh.get("penalties", [])):
            return await get_match(mid)
        raise HTTPException(409, "Partida alterada por outro árbitro. Recarregue e tente novamente.")
    is_a = body.team_id == m["team_a"]
    before_points = m.get("points_a") if is_a else m.get("points_b")
    fresh, r = await _recompute_match(mid)
    after_points = r["points_a"] if is_a else r["points_b"]
    await _push_audit(mid, _audit_entry("PENALTY", user,
        {"points": before_points}, {"points": after_points},
        {"team_id": body.team_id, "penalty_points": entry["points"],
         "reason": entry["reason"], "type": entry["type"],
         "match_status": m.get("status")}))
    return await get_match(mid)


@api.post("/matches/{mid}/undeclared")
async def undeclared_elimination(mid: str, body: UndeclaredIn,
                                 user=Depends(require_staff)):
    """Eliminação não declarada: elimination + −1 team penalty, atomically.

    The elimination is credited normally to the opponent and the offending
    team loses one point in that match (never below zero). There is no
    automatic match loss for a single occurrence.
    """
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    if m.get("wo"):
        raise HTTPException(400, "Partida registrada como W.O.")
    if m["status"] == "ENCERRADA" and user.get("role") != "admin":
        raise HTTPException(403, "Somente o administrador edita partida encerrada")
    if m["status"] not in ("EM_ANDAMENTO", "PAUSADA", "ENCERRADA"):
        raise HTTPException(400, "A partida precisa estar em andamento")
    ta, tb = await _teams_for_match(m)
    a_ids = set(ta.get("players") or [])
    b_ids = set(tb.get("players") or [])
    if body.player_id not in (a_ids | b_ids):
        raise HTTPException(400, "Jogador não pertence à partida")
    offending_team = m["team_a"] if body.player_id in a_ids else m["team_b"]
    if body.client_token:
        for e in m.get("eliminations", []):
            if e.get("client_token") == body.client_token:
                if e.get("eliminated_id") == body.player_id:
                    return await get_match(mid)
                raise HTTPException(409, "client_token já utilizado")

    before = {"points_a": m.get("points_a"), "points_b": m.get("points_b")}
    elim = {
        "id": str(uuid.uuid4()), "eliminated_id": body.player_id,
        "at_ms": compute_elapsed_ms(m), "at": now_iso(),
        "by": user.get("email"), "client_token": body.client_token,
        "undeclared": True,
    }
    pen = {
        "id": str(uuid.uuid4()), "team_id": offending_team, "points": 1,
        "reason": body.reason.strip(), "type": "ELIMINACAO_NAO_DECLARADA",
        "at": now_iso(), "client_token": body.client_token,
        "by": user.get("email"), "by_role": user.get("role"),
        "match_status": m.get("status"),
    }
    # One atomic write: the elimination and its penalty can never diverge.
    res = await db.matches.update_one(
        {"id": mid, "locked": {"$ne": True},
         "eliminations.eliminated_id": {"$ne": body.player_id}},
        {"$push": {"eliminations": elim, "penalties": pen}})
    if res.matched_count == 0:
        fresh = await db.matches.find_one({"id": mid}) or {}
        dup = next((e for e in fresh.get("eliminations", [])
                    if e.get("eliminated_id") == body.player_id), None)
        if dup and body.client_token and dup.get("client_token") == body.client_token:
            return await get_match(mid)
        raise HTTPException(409, "Jogador já foi eliminado")

    fresh, r = await _recompute_match(mid, auto_end=True)
    await _push_audit(mid, _audit_entry("UNDECLARED_ELIMINATION", user, before, {
        "points_a": r["points_a"], "points_b": r["points_b"],
        "elims_a": r["elims_a"], "elims_b": r["elims_b"],
        "status": fresh.get("status"),
    }, {"eliminated_id": body.player_id, "team_id": offending_team,
        "reason": body.reason, "penalty_points": 1}))
    if fresh.get("status") == "ENCERRADA" and m["status"] != "ENCERRADA":
        await maybe_advance_playoffs()
    return await get_match(mid)


@api.delete("/matches/{mid}/penalty/{penalty_id}")
async def remove_penalty(mid: str, penalty_id: str, user=Depends(require_admin)):
    m = await _get_match_doc(mid)
    if m.get("locked"):
        raise HTTPException(400, "Partida bloqueada")
    entry = next((p for p in m.get("penalties", []) if p.get("id") == penalty_id), None)
    if not entry:
        raise HTTPException(404, "Penalidade não encontrada")
    is_a = entry["team_id"] == m["team_a"]
    before_points = m.get("points_a") if is_a else m.get("points_b")
    await db.matches.update_one({"id": mid}, {"$pull": {"penalties": {"id": penalty_id}}})
    fresh, r = await _recompute_match(mid)
    after_points = r["points_a"] if is_a else r["points_b"]
    await _push_audit(mid, _audit_entry("REMOVE_PENALTY", user,
        {"points": before_points}, {"points": after_points},
        {"team_id": entry["team_id"], "reason": entry.get("reason")}))
    return await get_match(mid)


@api.post("/matches/{mid}/redo")
async def redo_match(mid: str, body: RedoMatchIn, user=Depends(require_admin)):
    """Replay one specific match, preserving the previous result as history.

    Only the selected match is reset: teams, players, other matches and the
    tournament structure are untouched.
    """
    m = await _get_match_doc(mid)
    if not body.confirm:
        raise HTTPException(400, "Confirmação explícita obrigatória")
    if m.get("status") != "ENCERRADA":
        raise HTTPException(400, "Só é possível refazer uma partida encerrada")
    snapshot = clean(dict(m))
    await db.match_history.insert_one({
        "id": str(uuid.uuid4()), "match_id": mid, "match_number": m.get("number"),
        "phase": m.get("phase"), "archived_at": now_iso(),
        "archived_by": user.get("email"),
        "reason": (body.reason or "").strip() or None,
        "snapshot": snapshot,
    })
    reset = {
        "status": "AGUARDANDO", "winner_team_id": None, "is_draw": False,
        "draw_reason": None, "declared_draw": False,
        "elims_a": 0, "elims_b": 0, "points_a": 0, "points_b": 0,
        "base_points_a": 0, "base_points_b": 0,
        "penalty_points_a": 0, "penalty_points_b": 0,
        "eliminated_players_a": [], "eliminated_players_b": [],
        "eliminations": [], "perfect_a": False, "perfect_b": False,
        "admin_perfect_a": False, "admin_perfect_b": False,
        "wo": False, "wo_team_id": None, "wo_reason": None,
        "started_at": None, "paused_at": None, "pause_accumulated_ms": 0,
        "ended_at": None,
        "redo_count": int(m.get("redo_count") or 0) + 1,
        "revision": int(m.get("revision") or 0) + 1,
    }
    if not body.preserve_penalties:
        reset["penalties"] = []
    await db.matches.update_one({"id": mid}, {"$set": reset})
    await _push_audit(mid, _audit_entry("REDO_MATCH", user,
        {"status": m.get("status"), "points_a": m.get("points_a"),
         "points_b": m.get("points_b")},
        {"status": "AGUARDANDO"},
        {"reason": body.reason, "preserve_penalties": body.preserve_penalties}))
    t = await db.tournament.find_one({"id": "main"}) or {}
    if t.get("status") == "FINISHED":
        await db.tournament.update_one({"id": "main"}, {"$set": {"status": "PLAYOFFS"}})
    return await get_match(mid)


@api.get("/matches/{mid}/history")
async def get_match_history(mid: str, _=Depends(require_admin)):
    docs = await db.match_history.find({"match_id": mid}).sort("archived_at", -1).to_list(50)
    return [clean(d) for d in docs]


@api.post("/matches/{mid}/history/{history_id}/restore")
async def restore_match_history(mid: str, history_id: str,
                                body: RestoreHistoryIn,
                                user=Depends(require_admin)):
    """Restore the result of one match from a recalculation snapshot.

    Safety properties:
    - admin only and explicit `confirm`;
    - only snapshots produced by the v2 recalculation are accepted;
    - only the selected match is touched;
    - the state immediately before the restore is archived as a new history
      entry, so the restore itself can be audited/reverted;
    - repeated calls are idempotent (the snapshot is marked as restored).
    """
    if not body.confirm:
        raise HTTPException(400, "Confirmação explícita obrigatória")
    h = await db.match_history.find_one({"id": history_id, "match_id": mid})
    if not h:
        raise HTTPException(404, "Snapshot não encontrado para esta partida")
    reason = (h.get("reason") or "").lower()
    if h.get("kind") != "RECALCULATION" and "recálculo" not in reason:
        raise HTTPException(400, "Este snapshot não é de recálculo histórico")

    m = await _get_match_doc(mid)
    if h.get("restored_at"):
        return {"ok": True, "already_restored": True, "match_id": mid,
                "history_id": history_id, "restored_fields": [],
                "match": public_match(m)}

    expected_revision = h.get("revision_after")
    if expected_revision is not None and int(m.get("revision") or 0) != int(expected_revision):
        raise HTTPException(
            409, "A partida foi alterada depois do recálculo; revise o snapshot antes de restaurar")

    snapshot = h.get("snapshot") or {}
    set_fields = {k: snapshot[k] for k in RESTORABLE_RESULT_KEYS if k in snapshot}
    unset_fields = {k: "" for k in RESTORABLE_RESULT_KEYS if k not in snapshot and k in m}
    before = {k: m.get(k) for k in ("points_a", "points_b", "winner_team_id",
                                    "perfect_a", "perfect_b")}

    restore_entry_id = str(uuid.uuid4())
    await db.match_history.insert_one({
        "id": restore_entry_id, "match_id": mid,
        "match_number": m.get("number"), "phase": m.get("phase"),
        "kind": "RESTORE",
        "archived_at": now_iso(), "archived_by": user.get("email"),
        "reason": f"estado anterior à restauração do snapshot {history_id}",
        "restored_from": history_id,
        "snapshot": clean(dict(m)),
    })

    update = {
        "$set": {**set_fields, "restored_from": history_id,
                 "restored_at": now_iso(),
                 "revision": int(m.get("revision") or 0) + 1},
    }
    if unset_fields:
        update["$unset"] = unset_fields
    res = await db.matches.update_one({"id": mid}, update)
    if not res.matched_count:
        raise HTTPException(404, "Partida não encontrada")

    await db.match_history.update_one({"id": history_id}, {"$set": {
        "restored_at": now_iso(), "restored_by": user.get("email"),
        "restore_history_id": restore_entry_id,
    }})
    await _push_audit(mid, _audit_entry("RESTORE_RESULT", user, before, {
        "points_a": set_fields.get("points_a"),
        "points_b": set_fields.get("points_b"),
        "winner_team_id": set_fields.get("winner_team_id"),
        "perfect_a": set_fields.get("perfect_a"),
        "perfect_b": set_fields.get("perfect_b"),
    }, {"history_id": history_id, "restored_fields": sorted(set_fields),
        "unset_fields": sorted(unset_fields)}))
    fresh = await _get_match_doc(mid)
    return {"ok": True, "already_restored": False, "match_id": mid,
            "history_id": history_id,
            "restored_fields": sorted(set_fields),
            "unset_fields": sorted(unset_fields),
            "history_entry_id": restore_entry_id,
            "match": public_match(fresh)}


@api.get("/matches/{mid}/audit")
async def get_match_audit(mid: str, _=Depends(require_admin)):
    """Admin-only audit trail (actor identities included)."""
    d = await _get_match_doc(mid)
    return {
        "match_id": mid,
        "audit_log": d.get("audit_log", []),
        "penalties": d.get("penalties", []),
        "eliminations": d.get("eliminations", []),
    }


# ---------- Rangers (arbitragem) ----------
@api.get("/rangers")
async def list_rangers(_=Depends(require_admin)):
    docs = await db.users.find({"role": "ranger"}).sort("created_at", 1).to_list(200)
    return [clean(d) for d in docs]


@api.post("/rangers")
async def create_ranger(body: RangerIn, _=Depends(require_admin)):
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "E-mail já cadastrado")
    doc = {
        "id": str(uuid.uuid4()), "email": email, "name": body.name.strip(),
        "password_hash": hash_pw(body.password), "role": "ranger",
        "active": True, "created_at": now_iso(),
    }
    await db.users.insert_one(doc)
    return clean(dict(doc))


@api.patch("/rangers/{uid}")
async def update_ranger(uid: str, body: RangerUpdateIn, _=Depends(require_admin)):
    doc = await db.users.find_one({"id": uid, "role": "ranger"})
    if not doc:
        raise HTTPException(404, "Ranger não encontrado")
    data = body.model_dump(exclude_unset=True)
    updates = {}
    if data.get("name") is not None:
        updates["name"] = data["name"].strip()
    if data.get("password"):
        updates["password_hash"] = hash_pw(data["password"])
    if data.get("active") is not None:
        updates["active"] = bool(data["active"])
    if updates:
        updates["updated_at"] = now_iso()
        await db.users.update_one({"id": uid}, {"$set": updates})
    return clean(await db.users.find_one({"id": uid}))


@api.delete("/rangers/{uid}")
async def deactivate_ranger(uid: str, _=Depends(require_admin)):
    r = await db.users.update_one(
        {"id": uid, "role": "ranger"},
        {"$set": {"active": False, "updated_at": now_iso()}})
    if r.matched_count == 0:
        raise HTTPException(404, "Ranger não encontrado")
    return {"ok": True, "active": False}


# ---------- Public rules (versioned) ----------
@api.get("/rules")
async def get_rules():
    doc = await db.rules.find_one({"id": "main"}) or {}
    return {
        "content": doc.get("content") or DEFAULT_RULES,
        "version": int(doc.get("version") or 1),
        "updated_at": doc.get("updated_at"),
        "updated_by": doc.get("updated_by"),
    }


@api.put("/rules")
async def update_rules(body: RulesIn, user=Depends(require_admin)):
    doc = await db.rules.find_one({"id": "main"})
    version = int((doc or {}).get("version") or 0) + 1
    if doc:
        await db.rules_history.insert_one({
            **clean(dict(doc)), "archived_at": now_iso(),
            "archived_by": user.get("email"),
        })
    payload = {
        "id": "main", "content": body.content, "version": version,
        "updated_at": now_iso(), "updated_by": user.get("email"),
    }
    await db.rules.update_one({"id": "main"}, {"$set": payload}, upsert=True)
    return payload


@api.get("/rules/history")
async def get_rules_history(_=Depends(require_admin)):
    docs = await db.rules_history.find({}).sort("archived_at", -1).to_list(50)
    return [clean(d) for d in docs]


# ---------- Event banner ----------
BANNER_MAX_LEN = 1_200_000  # ~900 KB decoded


@api.get("/banner")
async def get_banner():
    doc = await db.settings.find_one({"id": "banner"}) or {}
    return {
        "image": doc.get("image"),
        "updated_at": doc.get("updated_at"),
        "filename": doc.get("filename"),
    }


@api.post("/banner")
async def set_banner(body: BannerIn, user=Depends(require_admin)):
    image = body.image.strip()
    if not re.match(r"^data:image/(png|jpe?g|webp);base64,[A-Za-z0-9+/=\s]+$", image):
        raise HTTPException(400, "Formato de imagem inválido (use PNG, JPEG ou WEBP)")
    if len(image) > BANNER_MAX_LEN:
        raise HTTPException(400, "Imagem muito grande (máx. ~900 KB)")
    payload = {
        "id": "banner", "image": image, "filename": body.filename,
        "updated_at": now_iso(), "updated_by": user.get("email"),
    }
    await db.settings.update_one({"id": "banner"}, {"$set": payload}, upsert=True)
    return {"ok": True, "updated_at": payload["updated_at"], "filename": payload["filename"]}


@api.delete("/banner")
async def delete_banner(_=Depends(require_admin)):
    await db.settings.delete_one({"id": "banner"})
    return {"ok": True}


# ---------- Safe migration: recompute finished matches (v2 rules) ----------
@api.post("/admin/recalculate-scores")
async def recalculate_scores(body: RecalculateIn, user=Depends(require_admin)):
    """Recompute finished matches with the official v2 scoring rules.

    `dry_run` (default) only reports differences. Applying archives every
    previous result in `match_history` and keeps `legacy_points_a/b`, so the
    change is reversible. No other collection is touched.
    """
    if not body.dry_run and not body.confirm:
        raise HTTPException(400, "Confirmação explícita obrigatória")
    docs = await db.matches.find({"status": "ENCERRADA"}).to_list(2000)

    async def _result_for(doc):
        doc = default_match_fields(doc)
        ta, tb = await _teams_for_match(doc)
        return doc, compute_result(doc, {ta["id"]: ta, tb["id"]: tb})

    changes = []
    for m in docs:
        m, r = await _result_for(m)
        if ((r["points_a"], r["points_b"]) != (m.get("points_a"), m.get("points_b"))
                or (r["perfect_a"], r["perfect_b"]) != (m.get("perfect_a"), m.get("perfect_b"))):
            changes.append({
                "match_id": m["id"], "number": m.get("number"),
                "before": {"points_a": m.get("points_a"), "points_b": m.get("points_b")},
                "after": {"points_a": r["points_a"], "points_b": r["points_b"]},
            })
    if body.dry_run:
        return {"dry_run": True, "count": len(changes), "changes": changes}

    applied = 0
    for m in docs:
        m, r = await _result_for(m)
        if ((r["points_a"], r["points_b"]) == (m.get("points_a"), m.get("points_b"))
                and (r["perfect_a"], r["perfect_b"]) == (m.get("perfect_a"), m.get("perfect_b"))
                and m.get("scoring_version") == 2):
            continue
        revision_before = int(m.get("revision") or 0)
        revision_after = revision_before + 1
        await db.match_history.insert_one({
            "id": str(uuid.uuid4()), "match_id": m["id"],
            "match_number": m.get("number"), "phase": m.get("phase"),
            "kind": "RECALCULATION", "archived_at": now_iso(),
            "archived_by": user.get("email"), "reason": "recálculo regra v2",
            "revision_before": revision_before,
            "revision_after": revision_after,
            "snapshot": clean(dict(m)),
        })
        await db.matches.update_one({"id": m["id"]}, {"$set": {
            **r,
            # Keep the first legacy value even if the admin recalculates twice.
            "legacy_points_a": m.get("legacy_points_a", m.get("points_a")),
            "legacy_points_b": m.get("legacy_points_b", m.get("points_b")),
            "scoring_version": 2,
            "revision": revision_after,
        }})
        applied += 1
    return {"dry_run": False, "applied": applied, "changes": changes}


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

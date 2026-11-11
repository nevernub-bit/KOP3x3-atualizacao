"""Non-destructive JSON backup of the KOP 3x3 MongoDB database.

Reads MONGO_URL / DB_NAME from backend/.env and writes one JSON file per
collection plus a manifest. It only reads from the database — never writes,
drops or migrates anything.

Usage (from backend/):
    python scripts/backup_db.py [output-dir]

The default output directory (backend/backups/) is git-ignored because it may
contain personal data (names, WhatsApp, photos).
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _json_default(value):
    return str(value)


async def main() -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "backups" / stamp
    out.mkdir(parents=True, exist_ok=True)

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    names = sorted(await db.list_collection_names())
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": os.environ["DB_NAME"],
        "collections": {},
    }
    for name in names:
        docs = await db[name].find({}).to_list(1_000_000)
        payload = [dict(d) for d in docs]
        (out / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        manifest["collections"][name] = len(payload)
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    client.close()
    print(f"Backup written to {out} "
          f"({sum(manifest['collections'].values())} documents)")


if __name__ == "__main__":
    asyncio.run(main())

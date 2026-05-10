# memory.py
import motor.motor_asyncio
from config import MONGO_URL
import json

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client.game_db                # ← ganti nama database di URL kalau diperlukan
users = db.user_states

# ----------------------------------------------------------------------
# Helper: parse file .txt → list[dict]
# ----------------------------------------------------------------------
import re
SCENE_RE = re.compile(
    r"TURN\s*[:\-]?\s*(?P<turn>\d+)\s*[\r\n]+"
    r"USER\s*[:\-]?\s*(?P<user>.+?)\s*[\r\n]+"
    r"AI\s*[:\-]?\s*(?P<ai>.+?)(?=\nTURN|\Z)",        # sampai next TURN atau EOF
    re.DOTALL | re.IGNORECASE
)

async def import_story(user_id: int, file_content: str) -> dict:
    """
    Parse `file_content` (txt) menjadi list scene.
    Simpan ke DB dan kembalikan scene terakhir.
    """
    scenes = []
    for m in SCENE_RE.finditer(file_content):
        turn = int(m.group("turn"))
        user = m.group("user").strip()
        ai   = m.group("ai").strip()
        scenes.append({"turn": turn, "user": user, "ai": ai})

    if not scenes:
        raise ValueError("File tidak berisi scene yang valid (format TURN, USER, AI).")

    # Simpan *semua* scene ke koleksi `stories` (bisa pakai koleksi lain)
    await db.stories.update_one(
        {"_id": user_id},
        {"$set": {"scenes": scenes}},
        upsert=True
    )

    # Simpan pointer ke scene terakhir – ini yang akan dipakai saat
    # user melanjutkan cerita.
    await users.update_one(
        {"_id": user_id},
        {"$set": {
            "selected_model": "gemini-2.5-flash",   # default, bisa diganti
            "state": "STORY",
            "last_scene": scenes[-1]               # ← penting!
        }},
        upsert=True
    )
    return scenes[-1]      # return scene terakhir untuk ditampilkan

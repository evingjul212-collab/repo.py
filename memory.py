# -------------------------------------------------
# File: memory.py
# -------------------------------------------------
import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL
client = AsyncIOMotorClient(MONGO_URL)
db = client.game_db
# users = db.user_states

logger = logging.getLogger(__name__)

MONGO_URL = os.getenv("MONGO_URL")
client = AsyncIOMotorClient(MONGO_URL)
# db = client.get_default_database()
users = db.users          # koleksi user state
stories = db.stories      # optional, bila Anda menyimpan terpisah

# -----------------------------------------------------------------
# INIT USER (buat dokumen bila belum ada)
# -----------------------------------------------------------------
async def init_user(user_id: int) -> None:
    await users.update_one(
        {"_id": user_id},
        {
            "$setOnInsert": {
                "state": "START",
                "selected_model": "gemini-2.5-flash",
                "story": [],          # list of dicts {turn, user, ai}
                "genre": None,
                "prompt_template": "",
            }
        },
        upsert=True,
    )

# -----------------------------------------------------------------
# GET USER (seluruh dokumen)
# -----------------------------------------------------------------
async def get_user(user_id: int) -> dict | None:
    return await users.find_one({"_id": user_id})

# -----------------------------------------------------------------
# UPDATE STORY (menambahkan scene baru)
# -----------------------------------------------------------------
async def update_story(
    user_id: int,
    old_story: list,
    ai_text: str,
    user_msg: str,
) -> None:
    """
    `old_story` adalah list yang di‑ambil sebelumnya (biasanya
    `data["story"]`). Kami men‑push scene baru dengan turn = len(old_story).
    """
    turn = len(old_story)
    await users.update_one(
        {"_id": user_id},
        {
            "$push": {
                "story": {
                    "turn": turn,
                    "user": user_msg,
                    "ai": ai_text,
                }
            }
        },
    )

# -----------------------------------------------------------------
# GET FULL STORY (list semua scene)
# -----------------------------------------------------------------
async def get_full_story(user_id: int) -> list | None:
    doc = await get_user(user_id)
    return doc.get("story") if doc else None

# -----------------------------------------------------------------
# GET LAST SCENE (scene terakhir, pasti ada key `turn`)
# -----------------------------------------------------------------
async def get_last_scene(user_id: int) -> dict | None:
    """
    Mengembalikan scene terakhir dalam format:
    {
        "turn": int,
        "user": str,
        "ai":   str,
    }
    Jika story masih kosong, mengembalikan None.
    """
    doc = await get_user(user_id)
    if not doc:
        return None

    story = doc.get("story", [])
    if not story:
        return None

    # Pastikan setiap item memiliki `turn`. Jika tidak, hitung.
    last = story[-1]
    if "turn" not in last:
        # Rekalkulasi semua turn – ini jarang terjadi, hanya untuk legacy data.
        for idx, item in enumerate(story):
            await users.update_one(
                {"_id": user_id, "story.turn": {"$exists": False}},
                {"$set": {f"story.{idx}.turn": idx}},
            )
        last["turn"] = len(story) - 1

    return last

# -----------------------------------------------------------------
# SIMPAN / AMBIL PROMPT TERAKHIR (untuk /retry_last)
# -----------------------------------------------------------------
async def save_last_prompt(user_id: int, prompt: str) -> None:
    await users.update_one(
        {"_id": user_id},
        {"$set": {"last_prompt": prompt}},
    )

async def get_last_prompt(user_id: int) -> str | None:
    doc = await get_user(user_id)
    return doc.get("last_prompt") if doc else None

# -----------------------------------------------------------------
# SET / GET GENRE (opsional)
# -----------------------------------------------------------------
async def set_genre(user_id: int, genre: str, prompt_template: str) -> None:
    await users.update_one(
        {"_id": user_id},
        {"$set": {"genre": genre, "prompt_template": prompt_template, "state": "STORY"}},
    )

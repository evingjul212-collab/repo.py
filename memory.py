# --------------------------------------------------------------
# memory.py
# --------------------------------------------------------------
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL

log = logging.getLogger(__name__)

client = AsyncIOMotorClient(MONGO_URL)
db = client.game_db                # pastikan DB bernama game_db
users   = db.user_states           # state per‑user (genre, system_prompt, dll.)
stories = db.stories               # koleksi story (list of scene)

# ------------------------------------------------------------------
# Inisialiasi user (dipanggil di /start)
# ------------------------------------------------------------------
async def init_user(user_id: int):
    await users.update_one(
        {"_id": user_id},
        {"$setOnInsert": {"state": "IDLE"}},
        upsert=True,
    )

# ------------------------------------------------------------------
# Simpan genre + system prompt (setelah pilih genre)
# ------------------------------------------------------------------
async def set_genre(user_id: int, genre_key: str, system_prompt: str):
    await users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "genre": genre_key,
                "system_prompt": system_prompt,
                "state": "STORY",      # otomatis masuk ke mode cerita
                "selected_model": "gemini-2.5-flash",   # default
            }
        },
        upsert=True,
    )

# ------------------------------------------------------------------
# Simpan / perbarui story (list of scene) + last scene
# ------------------------------------------------------------------
async def update_story(user_id: int, story: list, ai_text: str, user_msg: str):
    """
    story      : list of scene dicts yang sudah ada
    ai_text    : output AI untuk scene baru
    user_msg   : pesan user yang diproses
    """
    new_turn = len(story) + 1
    new_scene = {
        "turn": new_turn,
        "user": user_msg,
        "ai": ai_text,
    }
    story.append(new_scene)

    # simpan semua scene
    await stories.update_one(
        {"_id": user_id},
        {"$set": {"scenes": story}},
        upsert=True,
    )
    # simpan scene terakhir untuk /regen dan /retry
    await users.update_one(
        {"_id": user_id},
        {"$set": {"last_scene": new_scene}},
        upsert=True,
    )
    return story

# ------------------------------------------------------------------
# Simpan prompt terakhir (untuk /retry)
# ------------------------------------------------------------------
async def save_last_prompt(user_id: int, prompt: str):
    await users.update_one(
        {"_id": user_id},
        {"$set": {"last_prompt": prompt}},
        upsert=True,
    )

async def get_last_prompt(user_id: int):
    doc = await users.find_one({"_id": user_id})
    return doc.get("last_prompt") if doc else None

# ------------------------------------------------------------------
# Dapatkan seluruh state (metadata + story) untuk satu user
# ------------------------------------------------------------------
async def get_full_state(user_id: int):
    """
    Return:
        {
            "metadata": {"genre": "...", "system_prompt": "...", "selected_model": "..."},
            "story":    [{turn:1, user:"…", ai:"…"}, …]
        }
    """
    user_doc = await users.find_one({"_id": user_id}) or {}
    story_doc = await stories.find_one({"_id": user_id}) or {}

    metadata = {
        "genre":          user_doc.get("genre", ""),
        "system_prompt":  user_doc.get("system_prompt", ""),
        "selected_model": user_doc.get("selected_model", "gemini-2.5-flash"),
    }
    story = story_doc.get("scenes", [])
    return {"metadata": metadata, "story": story}

# ------------------------------------------------------------------
# Rekam / ambil scene terakhir (digunakan di /regen)
# ------------------------------------------------------------------
async def get_last_scene(user_id: int):
    doc = await users.find_one({"_id": user_id})
    return doc.get("last_scene") if doc else None

async def set_last_scene(user_id: int, scene: dict):
    await users.update_one(
        {"_id": user_id},
        {"$set": {"last_scene": scene}},
        upsert=True,
    )

# ------------------------------------------------------------------
# Replay story (mengembalikan list scene lengkap)
# ------------------------------------------------------------------
async def get_full_story(user_id: int):
    story_doc = await stories.find_one({"_id": user_id})
    return story_doc.get("scenes") if story_doc else None

import motor.motor_asyncio
import re
from config import MONGO_URL

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client.game_db                # sesuaikan nama DB
users = db.user_states
stories = db.stories                # koleksi untuk menyimpan seluruh story

SCENE_RE = re.compile(
    r"TURN\s*[:\-]?\s*(?P<turn>\d+)\s*[\r\n]+"
    r"USER\s*[:\-]?\s*(?P<user>.+?)\s*[\r\n]+"
    r"AI\s*[:\-]?\s*(?P<ai>.+?)(?=\nTURN|\Z)",
    re.DOTALL | re.IGNORECASE,
)

async def init_user(user_id: int):
    await users.update_one(
        {"_id": user_id},
        {"$setOnInsert": {"state": "IDLE", "selected_model": "gemini-2.5-flash"}},
        upsert=True,
    )

async def get_user(user_id: int):
    return await users.find_one({"_id": user_id})

async def set_genre(user_id: int, genre: str, prompt: str):
    await users.update_one(
        {"_id": user_id},
        {"$set": {"genre": genre, "genre_prompt": prompt, "state": "STORY"}},
        upsert=True,
    )

async def update_story(user_id: int, story: str, ai_text: str, user_msg: str):
    # Simpan tiap turn ke koleksi stories
    user_doc = await stories.find_one({"_id": user_id})
    turn = (user_doc["scenes"][-1]["turn"] + 1) if user_doc else 1
    scene = {"turn": turn, "user": user_msg, "ai": ai_text}
    await stories.update_one(
        {"_id": user_id},
        {"$push": {"scenes": scene}},
        upsert=True,
    )

async def get_full_story(user_id: int):
    doc = await stories.find_one({"_id": user_id})
    return doc["scenes"] if doc else []

async def set_last_scene(user_id: int, prompt: str, ai_text: str, story: str):
    await users.update_one(
        {"_id": user_id},
        {"$set": {"last_scene": {"prompt": prompt, "ai_text": ai_text, "story": story}}},
    )

async def get_last_scene(user_id: int):
    doc = await users.find_one({"_id": user_id})
    return doc.get("last_scene") if doc else None

async def save_last_prompt(user_id: int, prompt: str):
    await users.update_one({"_id": user_id}, {"$set": {"last_prompt": prompt}})

async def get_last_prompt(user_id: int):
    doc = await users.find_one({"_id": user_id})
    return doc.get("last_prompt") if doc else None

# ---------- IMPORT ----------
async def import_story(user_id: int, file_content: str) -> dict:
    scenes = []
    for m in SCENE_RE.finditer(file_content):
        turn = int(m.group("turn"))
        user = m.group("user").strip()
        ai   = m.group("ai").strip()
        scenes.append({"turn": turn, "user": user, "ai": ai})

    if not scenes:
        raise ValueError("File tidak berisi scene yang valid (TURN, USER, AI).")

    await stories.update_one(
        {"_id": user_id},
        {"$set": {"scenes": scenes}},
        upsert=True,
    )
    await users.update_one(
        {"_id": user_id},
        {"$set": {
            "state": "STORY",
            "last_scene": scenes[-1],
            "selected_model": "gemini-2.5-flash"
        }},
        upsert=True,
    )
    return scenes[-1]

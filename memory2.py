from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URL
client = AsyncIOMotorClient(MONGO_URL)
db = client.game_db
users = db.user_states


async def init_user(user_id):
    await users.update_one(
        {"_id": user_id},
        {"$set": {"state": "START"}},
        upsert=True
    )


async def set_genre(user_id, genre, sys_prompt):
    await users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "state": "STORY",
                "story": {
                    "genre": genre,
                    "sys_prompt": sys_prompt,
                    "summary": "Cerita baru dimulai.",
                    "turn": 0
                }
            }
        }
    )


async def get_user(user_id):
    return await users.find_one({"_id": user_id})


async def update_story(user_id, story, ai_text, user_msg, prompt=None):

    # turn
    story["turn"] = story.get("turn", 0) + 1

    # =========================
    # INIT ARCHIVE
    # =========================
    if "archive" not in story:
        story["archive"] = []

    # =========================
    # SAVE FULL STORY
    # =========================
    story["archive"].append({
        "turn": story["turn"],
        "user": user_msg,
        "ai": ai_text,
        "prompt": prompt
    })

    # limit archive
    story["archive"] = story["archive"][-50:]

    # =========================
    # SUMMARY
    # =========================
    story["summary"] = (
        story.get("summary", "") +
        f"\nUser: {user_msg}\nAI: {ai_text}"
    )[-3000:]

    # =========================
    # SAVE DATABASE
    # =========================
    await users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "story": story
            }
        }
    )
async def get_full_story(user_id):

    data = await users.find_one({"_id": user_id})

    if not data:
        return []

    return data.get("story", {}).get("archive", [])

async def set_last_scene(user_id, prompt, ai_text, story):
    await users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "last_scene": {
                    "prompt": prompt,
                    "ai_text": ai_text,
                    "story": story
                }
            }
        }
    )

async def save_last_prompt(user_id, prompt):

    await users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "last_prompt": prompt
            }
        }
    )


async def get_last_prompt(user_id):

    data = await users.find_one({"_id": user_id})

    if not data:
        return None

    return data.get("last_prompt")
async def get_last_scene(user_id):
    data = await users.find_one({"_id": user_id})
    return data.get("last_scene")

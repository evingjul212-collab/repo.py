from motor.motor_asyncio import AsyncIOMotorClient
import os

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states


# =========================================================
# INIT USER STATE
# =========================================================

async def init_user(user_id):
    await users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "state": "CHOOSING_GENRE"
            }
        },
        upsert=True
    )


# =========================================================
# SET GENRE + INIT STORY STATE STRUCTURED
# =========================================================

async def set_genre(user_id, genre, prompt):
    await users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "state": "STORY_ONGOING",
                "story": {
                    "genre": genre,

                    # ===== CORE MEMORY (NEW SYSTEM) =====
                    "world_state": "",
                    "characters": [],
                    "current_scene": "Cerita dimulai.",
                    "recent_events": [],
                    "turn": 0
                },
                "sys_prompt": prompt
            }
        }
    )


# =========================================================
# GET STORY
# =========================================================

async def get_story(user_id):
    data = await users.find_one({"_id": user_id})
    return data


# =========================================================
# UPDATE AFTER AI RESPONSE
# =========================================================

async def update_story(user_id, story, ai_text, user_msg):

    story["turn"] += 1

    story["recent_events"].append({
        "user": user_msg,
        "ai": ai_text
    })

    # limit memory biar gak bengkak
    story["recent_events"] = story["recent_events"][-10:]

    await users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "story": story
            }
        }
    )
# =========================================================
# 🔁 NEW FEATURE: LAST SCENE CACHE
# =========================================================

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


async def get_last_scene(user_id):
    data = await users.find_one({"_id": user_id})
    return data.get("last_scene", None)

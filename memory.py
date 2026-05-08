from motor.motor_asyncio import AsyncIOMotorClient
import os

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states


async def init_user(user_id):
    await users.update_one(
        {"_id": user_id},
        {"$set": {"state": "CHOOSING_GENRE"}},
        upsert=True
    )


async def set_genre(user_id, genre, prompt):
    await users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "state": "STORY",
                "story": {
                    "genre": genre,
                    "world_state": "",
                    "current_scene": "",
                    "recent_events": [],
                    "turn": 0
                },
                "sys_prompt": prompt
            }
        }
    )


async def get_user(user_id):
    return await users.find_one({"_id": user_id})


async def update_story(user_id, story, ai_text, user_msg):

    story["turn"] += 1

    story["recent_events"].append({
        "user": user_msg,
        "ai": ai_text
    })

    story["recent_events"] = story["recent_events"][-10:]

    await users.update_one(
        {"_id": user_id},
        {"$set": {"story": story}}
    )


# 🔁 LAST SCENE (UNTUK REGENERATE)
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
    return data.get("last_scene")

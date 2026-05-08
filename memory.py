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


async def update_story(user_id, story, ai_text, user_msg):
    story["turn"] += 1

    story["summary"] = (story["summary"] + "\nUser: " + user_msg + "\nAI: " + ai_text)[-2000:]

    await users.update_one(
        {"_id": user_id},
        {"$set": {"story": story}}
    )


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

import os 
import asyncio
import re 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from bson import ObjectId 

# =================================================================
# CONFIG
# =================================================================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.datsa

# =================================================================
# STATE
# =================================================================
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name", "User"),
        "desc_utama": s.get("desc_utama", "Tokoh Utama"),
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "world_state": s.get("world_state", {"time": "Pagi", "location": "Rumah", "turn": 0}),
        "summary": s.get("summary", ""),
        "memory": s.get("memory", []),
        "temp_val": s.get("temp_val")
    }

async def get_state(uid):
    return fix_state(await users.find_one({"_id": uid}))

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# =================================================================
# WORLD + MOOD + MEMORY
# =================================================================
def update_world(s):
    ws = s["world_state"]
    ws["turn"] += 1

    if ws["turn"] % 6 == 0:
        ws["time"] = "Malam"
    elif ws["turn"] % 3 == 0:
        ws["time"] = "Sore"
    else:
        ws["time"] = "Pagi"

    return ws

def update_mood(s, text):
    idx = s.get("selected", -1)
    if idx == -1 or idx >= len(s["chars"]):
        return s

    npc = s["chars"][idx]
    mood = npc.get("mood", 50)

    if any(w in text.lower() for w in ["baik","tolong","ramah"]):
        mood += 5
    if any(w in text.lower() for w in ["kasar","marah","hina"]):
        mood -= 5

    npc["mood"] = max(0, min(100, mood))
    return s

def update_memory(s, text):
    if any(k in text.lower() for k in ["jatuh","hilang","janji","cinta","temukan"]):
        s["memory"].append(text[:120])
    return s

async def update_summary(uid, s):
    if len(s["history"]) > 8:
        p = "Ringkas cerita:\n" + "\n".join(s["history"])
        summary = await generate_response(p, [], s, False)
        if summary:
            s["summary"] = summary
            s["history"] = s["history"][-4:]

# =================================================================
# AI
# =================================================================
async def generate_response(prompt, history, s, force_options=False):
    waktu = s["world_state"]["time"]
    lokasi = s["world_state"]["location"]

    idx = s.get("selected", -1)
    npc_info = ""
    npc_desc = ""

    if idx != -1 and s["chars"]:
        npc = s["chars"][idx]
        npc_info = f"{npc['name']} mood {npc.get('mood',50)}"
        npc_desc = npc.get("desc","")

    all_chars = "\n".join([f"- {c['name']}: {c.get('desc','')}" for c in s["chars"]])
    memory = "\n".join(s["memory"][-5:])

    system = f"""
Penulis novel interaktif.

Ringkasan: {s["summary"]}
Memory: {memory}
Dunia: {waktu} di {lokasi}

Karakter aktif: {npc_info}
Deskripsi: {npc_desc}

Daftar karakter:
{all_chars}

ATURAN:
- WAJIB ikuti deskripsi karakter
- Jika nama disebut, sifat harus sesuai
- Dilarang ubah kepribadian
- Narasi + dialog
- Panjang 800-1000 karakter
"""

    if force_options:
        system += "\nAkhiri dengan pilihan A B C D"

    context = "\n".join(history[-5:])
    full_prompt = f"{system}\n\n{context}\n\n{prompt}"

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_prompt))
            return resp.text.strip()
        except:
            continue
    return None

# =================================================================
# APPLY UPDATE (AUTO)
# =================================================================
async def apply_updates(uid, s, text=""):
    s = update_mood(s, text)
    s = update_memory(s, s["history"][-1])
    s["world_state"] = update_world(s)
    await update_summary(uid, s)
    await save(uid, s)
    return s

# =================================================================
# UI
# =================================================================
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("🎭 Narator", callback_data="narator")],
        [InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")]
    ]
    return InlineKeyboardMarkup(kb)

# =================================================================
# MESSAGE
# =================================================================
async def msg(update, context):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    out = await generate_response(text, s["history"], s, True)
    if out:
        s["history"].append(out)
        s = await apply_updates(uid, s, text)
        await update.message.reply_text(out, reply_markup=await menu_utama(uid))

# =================================================================
# CALLBACK
# =================================================================
async def callback(update, context):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "lanjut":
        out = await generate_response("lanjutkan cerita", s["history"], s, True)
        if out:
            s["history"].append(out)
            s = await apply_updates(uid, s)
            await q.message.reply_text(out, reply_markup=await menu_utama(uid))

# =================================================================
# START
# =================================================================
async def start(update: Update, context):
    uid = update.effective_user.id
    await save(uid, {"history": [], "chars": []})
    await update.message.reply_text("Mulai cerita!", reply_markup=await menu_utama(uid))

# =================================================================
# RUN
# =================================================================
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

    async def main():
        await app.bot.delete_webhook(drop_pending_updates=True)
        async with app:
            await app.initialize()
            await app.start()
            await app.updater.start_polling()
            while True:
                await asyncio.sleep(1000)

    asyncio.run(main())

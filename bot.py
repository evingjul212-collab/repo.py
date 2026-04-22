import os
import asyncio
import io
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai

print("BOT STARTING...")

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash", "gemini-2.5-pro"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states

# ========= DATABASE =========
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name") or "User",
        "desc_utama": s.get("desc_utama") or "Tokoh Utama",
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "last_prompt": s.get("last_prompt"),
        "last_system": s.get("last_system"),
        "scene_state": s.get("scene_state", {
            "location": "Kamar",
            "emotion": "Netral",
            "condition": "Normal"
        })
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    s = fix_state(s)
    await users.update_one({"_id": uid}, {"$set": s}, upsert=True)
    return s

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= MEMORY =========
def extract_scene_state(text, old):
    state = old.copy()
    low = text.lower()

    loc = re.findall(r"\*\*\((.*?)\)\*\*", text)
    if loc:
        state["location"] = loc[-1]

    if any(x in low for x in ["panik","gemetar","takut"]):
        state["emotion"] = "Panik"
    elif any(x in low for x in ["marah","geram"]):
        state["emotion"] = "Marah"
    elif any(x in low for x in ["tenang","lega"]):
        state["emotion"] = "Tenang"

    if "handuk" in low:
        state["condition"] = "Memakai handuk"

    return state

# ========= AI =========
async def generate(prompt, system, history, state):
    context = "\n---\n".join(history[-15:]) if history else "Start."

    state_block = f"""
[STATE]
Lokasi: {state['location']}
Emosi: {state['emotion']}
Kondisi: {state['condition']}
"""

    full = f"{system}\n{state_block}\n[MEMORI]\n{context}\n\n[AKSI]\n{prompt}"

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: client_ai.models.generate_content(model=m, contents=full)
            )
            return resp.text.strip()
        except:
            continue

    return None

# ========= PROMPT =========
def build_system(tag, desc, state):
    return f"""
Kamu narator cerita sinematik.

PERAN: {tag}
DESKRIPSI: {desc}

STATE:
Lokasi: {state['location']}
Emosi: {state['emotion']}
Kondisi: {state['condition']}

ATURAN:
- Dialog "..."
- Aksi *(...)*
- Lokasi pakai format:
***
**(Lokasi)**
***
- WAJIB konsisten kondisi
- Jangan kontradiksi
- Jangan pilihan angka
"""

# ========= MENU =========
async def menu_utama(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎭 Aksi", callback_data="action")],
        [InlineKeyboardButton("🎬 Narator", callback_data="narator")],
        [InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("📖 Riwayat", callback_data="log")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo"),
         InlineKeyboardButton("🔄 Regen", callback_data="regen")],
        [InlineKeyboardButton("🧹 Reset", callback_data="reset")]
    ])

# ========= SAFE SEND =========
async def safe_send(obj, text, tag, markup):
    target = None

    if hasattr(obj, "effective_message") and obj.effective_message:
        target = obj.effective_message
    elif hasattr(obj, "message") and obj.message:
        target = obj.message

    if not target:
        return

    try:
        await target.reply_text(f"✨ *{tag}*\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except:
        await target.reply_text(f"✨ {tag}\n\n{text}", reply_markup=markup)

# ========= START =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"step": "set_name", "history": []})
    await update.message.reply_text("Nama karakter?")

# ========= MESSAGE =========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Mulai {text}", reply_markup=await menu_utama(uid))
        return

    if s["step"] in ["action", "narator"]:
        system = build_system(s["name"], s["desc_utama"], s["scene_state"])
        out = await generate(text, system, s["history"], s["scene_state"])

        if out:
            new_state = extract_scene_state(out, s["scene_state"])
            s["history"].append(out)

            await save(uid, {"history": s["history"], "scene_state": new_state, "step": None})
            await safe_send(update, out, s["name"], await menu_utama(uid))

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "action":
        await save(uid, {"step": "action"})
        await q.message.reply_text("Aksi kamu?")

    elif q.data == "narator":
        await save(uid, {"step": "narator"})
        await q.message.reply_text("Kejadian?")

    elif q.data == "lanjut":
        out = await generate("Lanjutkan cerita.", "Narator", s["history"], s["scene_state"])
        if out:
            s["history"].append(out)
            await save(uid, {"history": s["history"]})
            await safe_send(q, out, "NARASI", await menu_utama(uid))

    elif q.data == "undo":
        if s["history"]:
            s["history"].pop()
            await save(uid, {"history": s["history"]})
        await q.message.reply_text("Undo")

    elif q.data == "regen":
        if not s["history"]:
            return
        last = s["history"][-1]
        out = await generate(last, "Narator", s["history"], s["scene_state"])
        if out:
            s["history"].append(out)
            await save(uid, {"history": s["history"]})
            await safe_send(q, out, "REGEN", await menu_utama(uid))

    elif q.data == "log":
        text = "\n\n".join(s["history"])
        file = io.BytesIO(text.encode())
        file.name = "story.txt"
        await q.message.reply_document(file)

    elif q.data == "reset":
        await save(uid, {"history": [], "step": None})
        await q.message.reply_text("Reset selesai")

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

    print("BOT READY")
    app.run_polling()

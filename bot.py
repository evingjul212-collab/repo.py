import os
import asyncio
import io
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai

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
        "temp_char": s.get("temp_char"),
        "state": s.get("state", {
            "location": "Tidak diketahui",
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

# ========= MEMORY PARSER =========
def extract_state(text, old_state):
    state = old_state.copy()

    # lokasi
    loc = re.findall(r"\*\*\*\s*\n\*\*\((.*?)\)\*\*", text)
    if loc:
        state["location"] = loc[-1]

    # emosi simple detect
    if any(x in text.lower() for x in ["panik", "gemetar", "takut"]):
        state["emotion"] = "Panik"
    elif any(x in text.lower() for x in ["marah", "geram"]):
        state["emotion"] = "Marah"
    elif any(x in text.lower() for x in ["tenang", "lega"]):
        state["emotion"] = "Tenang"

    # kondisi pakaian
    if "handuk" in text.lower():
        state["condition"] = "Memakai handuk"

    return state

# ========= AI =========
async def generate(prompt, system, history, state):
    context = "\n---\n".join(history[-12:]) if history else "Start."

    state_block = f"""
[STATE]
Lokasi: {state['location']}
Emosi: {state['emotion']}
Kondisi: {state['condition']}
"""

    full_input = f"{system}\n\n{state_block}\n\n[MEMORI]\n{context}\n\n[AKSI]\n{prompt}"

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: client_ai.models.generate_content(model=m, contents=full_input)
            )
            print(f"[AI] {m}")
            return resp.text.strip()
        except:
            continue

    return None

# ========= PROMPT =========
def build_system(tag, desc):
    return f"""
Kamu adalah narator cerita RPG sinematik.

PERAN: {tag}
DESKRIPSI: {desc}

ATURAN:
- Gunakan gaya novel
- Dialog "..."
- Aksi *(...)*
- Tampilkan lokasi jika berubah:
***
**(Lokasi)**
***
- WAJIB konsisten dengan STATE
- Jangan ubah pakaian/posisi tanpa alasan
- Jangan buat detail yang bertentangan
- Jangan buat pilihan angka
- Fokus imersi
"""

# ========= UI =========
async def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎭 Aksi", callback_data="action")],
        [InlineKeyboardButton("📖 Riwayat", callback_data="log")],
        [InlineKeyboardButton("🔄 Regen", callback_data="regen")]
    ])

# ========= SAFE SEND =========
async def send(update, text, state):
    footer = f"\n\n━━━━━━━━━━━━━━\n📍 {state['location']}\n😈 {state['emotion']}\n👕 {state['condition']}\n━━━━━━━━━━━━━━"

    try:
        await update.effective_message.reply_text(text + footer)
    except:
        await update.effective_message.reply_text(text)

# ========= START =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {
        "step": "set_name",
        "history": [],
        "state": {
            "location": "Kamar",
            "emotion": "Netral",
            "condition": "Normal"
        }
    })
    await update.message.reply_text("Nama karakter?")

# ========= MESSAGE =========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Mulai cerita, {text}.", reply_markup=await menu())
        return

    if s["step"] == "action":
        system = build_system(s["name"], s["desc_utama"])
        out = await generate(text, system, s["history"], s["state"])

        if out:
            new_state = extract_state(out, s["state"])
            s["history"].append(out)

            await save(uid, {
                "history": s["history"],
                "state": new_state,
                "step": None
            })

            await send(update, out, new_state)

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "action":
        await save(uid, {"step": "action"})
        await q.message.reply_text("Aksi kamu?")

    elif q.data == "log":
        text = "\n\n".join(s["history"])
        file = io.BytesIO(text.encode())
        file.name = "story.txt"
        await q.message.reply_document(file)

    elif q.data == "regen":
        if not s["history"]:
            return

        s["history"].pop()
        out = await generate(s["last_prompt"], s["last_system"], s["history"], s["state"])

        if out:
            new_state = extract_state(out, s["state"])
            s["history"].append(out)

            await save(uid, {"history": s["history"], "state": new_state})
            await send(q, out, new_state)

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

    print("🔥 MEMORY RPG READY")
    app.run_polling()

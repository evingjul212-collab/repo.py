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
        "scene_state": s.get("scene_state", {
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

# ========= MEMORY =========
def extract_scene_state(text, old):
    state = old.copy()
    low = text.lower()

    # lokasi
    loc = re.findall(r"\*\*\((.*?)\)\*\*", text)
    if loc:
        state["location"] = loc[-1]

    # emosi
    if any(x in low for x in ["panik","gemetar","takut","terburu"]):
        state["emotion"] = "Panik"
    elif any(x in low for x in ["marah","geram"]):
        state["emotion"] = "Marah"
    elif any(x in low for x in ["tenang","lega"]):
        state["emotion"] = "Tenang"

    # kondisi
    if "handuk" in low:
        state["condition"] = "Memakai handuk"

    return state

# ========= AI =========
async def generate(prompt, system, history, scene_state):
    context = "\n---\n".join(history[-15:]) if history else "Start."

    state_block = f"""
[STATE]
Lokasi: {scene_state['location']}
Emosi: {scene_state['emotion']}
Kondisi: {scene_state['condition']}
"""

    full_input = f"{system}\n{state_block}\n[MEMORI]\n{context}\n\n[AKSI]\n{prompt}"

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: client_ai.models.generate_content(model=m, contents=full_input)
            )
            return resp.text.strip(), m
        except:
            continue

    return None, None

# ========= PROMPT =========
def build_system(tag, desc, scene_state):
    return f"""
Kamu adalah narator cerita RPG sinematik.

PERAN: {tag}
DESKRIPSI: {desc}

STATE:
Lokasi: {scene_state['location']}
Emosi: {scene_state['emotion']}
Kondisi: {scene_state['condition']}

ATURAN:
- Format novel
- Dialog "..."
- Aksi *(...)*
- Jika pindah lokasi:
***
**(Nama Lokasi)**
***
- WAJIB konsisten dengan kondisi
- Jika pakai handuk → jangan muncul pakaian lain
- Jangan kontradiksi
- Jangan pilihan angka
"""

# ========= UI =========
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"),
         InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("📖 Riwayat", callback_data="export_logs")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo"),
         InlineKeyboardButton("🔄 Regen", callback_data="regen")],
        [InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")]
    ]
    return InlineKeyboardMarkup(kb)

# ========= SAFE SEND =========
async def safe_send(obj, text, tag, markup):
    target = obj.message if hasattr(obj, "message") else obj.effective_message
    try:
        await target.reply_text(f"✨ *{tag}*\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except:
        await target.reply_text(f"✨ {tag}\n\n{text}", reply_markup=markup)

# ========= START =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {
        "name": None,
        "step": "set_name",
        "history": [],
        "chars": [],
        "scene_state": {
            "location": "Kamar",
            "emotion": "Netral",
            "condition": "Normal"
        }
    })
    await update.message.reply_text("🎮 RPG Engine\nNama Tokoh?")

# ========= MESSAGE =========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, text = update.effective_user.id, update.message.text
    s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Halo {text}!", reply_markup=await menu_utama(uid))
        return

    if s["step"] in ["action","narator_input"]:
        is_nar = s["step"] == "narator_input"
        idx = s.get("selected", -1)

        tag = "NARASI" if is_nar else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]

        system = build_system(tag, desc, s["scene_state"])
        prompt = f"KEJADIAN: {text}" if is_nar else f"AKSI: {text}"

        await save(uid, {"last_prompt": prompt, "last_system": system})

        out, _ = await generate(prompt, system, s["history"], s["scene_state"])

        if out:
            new_state = extract_scene_state(out, s["scene_state"])
            s["history"].append(f"[{tag}]: {out}")

            await save(uid, {
                "history": s["history"],
                "scene_state": new_state,
                "step": None
            })

            await safe_send(update, out, tag, await menu_utama(uid))

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid, s = q.from_user.id, await get_state(q.from_user.id)
    await q.answer()

    if q.data == "step_narator":
        await save(uid, {"step": "narator_input"})
        await q.message.reply_text("🎭 Kejadian apa?")

    elif q.data == "lanjut":
        out, _ = await generate("Lanjutkan cerita.", "Narator RPG.", s["history"], s["scene_state"])
        if out:
            new_state = extract_scene_state(out, s["scene_state"])
            s["history"].append(f"[NARASI]: {out}")
            await save(uid, {"history": s["history"], "scene_state": new_state})
            await safe_send(q, out, "NARASI", await menu_utama(uid))

    elif q.data == "undo":
        if s["history"]:
            s["history"].pop()
            await save(uid, {"history": s["history"]})
        await q.message.reply_text("↩️ Undo.", reply_markup=await menu_utama(uid))

    elif q.data == "regen":
        if not s.get("last_prompt") or not s["history"]:
            await q.message.reply_text("⚠️ Tidak bisa regen.")
            return
        s["history"].pop()
        out, _ = await generate(s["last_prompt"], s["last_system"], s["history"], s["scene_state"])
        if out:
            new_state = extract_scene_state(out, s["scene_state"])
            s["history"].append(out)
            await save(uid, {"history": s["history"], "scene_state": new_state})
            await safe_send(q, out, "REGEN", await menu_utama(uid))

    elif q.data == "export_logs":
        text = "\n\n".join(s["history"])
        file = io.BytesIO(text.encode())
        file.name = "story.txt"
        await q.message.reply_document(file)

    elif q.data == "reset_confirm":
        await save(uid, {"history": [], "chars": [], "step": None})
        await q.message.reply_text("🧹 Reset.")

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("🔥 FINAL STABLE READY")
    app.run_polling()

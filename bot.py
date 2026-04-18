import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
# MENGGUNAKAN SDK BARU UNTUK TAHUN 2026
from google import genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
# Inisialisasi Client Baru sesuai standar terbaru
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Daftar model resmi yang pasti ada di server Google
MODELS = [
    "gemini-2.0-flash", 
    "gemini-1.5-flash",
    "gemini-1.5-pro"
]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states

# ========= STATE LOGIC =========
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name"),
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected"),
        "temp_char": s.get("temp_char"),
        "last_prompt": s.get("last_prompt"),
        "story": s.get("story", {
            "setting": "Rumah",
            "time": "Sore",
            "rules": "Romcom natural, realistis"
        })
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    s = fix_state(s)
    await users.update_one({"_id": uid}, {"$set": s}, upsert=True)
    return s

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= SYSTEM ENGINE =========
def build_system(s):
    st = s["story"]
    char_list = ", ".join([c['name'] for c in s['chars']])
    return f"""
KONTROL ENGINE RPG:
- Setting: {st['setting']} | Waktu: {st['time']}
- Karakter: {s['name']} (User), {char_list}
PROTOKOL: Wajib konsisten posisi fisik, POV terkunci pada karakter terpilih, 1-2 paragraf saja.
"""

# ========= AI GENERATOR (LOGIKA 2026) =========
async def generate(prompt, system, history):
    context = "\n---\n".join(history[-12:]) if history else "Cerita dimulai."
    full_input = f"{system}\n\n--- MEMORI ---\n{context}\n\n--- INSTRUKSI ---\n{prompt}"
    
    for m in MODELS:
        try:
            # Cara panggil baru: client_ai.models.generate_content
            response = client_ai.models.generate_content(
                model=m,
                contents=full_input
            )
            return response.text.strip(), m
        except Exception as e:
            print(f"DEBUG: Model {m} gagal di Railway. Error: {e}")
            continue
    return None, None

# ========= INTERFACE & HANDLERS =========
async def menu(uid):
    s = await get_state(uid)
    kb = []
    if s["name"]: kb.append([InlineKeyboardButton(f"👤 POV: {s['name']}", callback_data="main")])
    kb.append([InlineKeyboardButton("🎭 Narator", callback_data="narator"), InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")])
    for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"💬 POV: {c['name']}", callback_data=f"char_{i}")])
    kb.append([InlineKeyboardButton("➕ Tambah Karakter", callback_data="add_char")])
    kb.append([InlineKeyboardButton("↩️ Undo", callback_data="undo"), InlineKeyboardButton("🔄 Regen", callback_data="regen")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine Railway Ready.\nMasukkan nama Tokoh Utama:")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)
    
    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Tokoh utama '{text}' siap.", reply_markup=await menu(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Deskripsi singkat {text}?")
        return

    if s["step"] == "char_desc":
        chars = s["chars"]
        chars.append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": chars, "step": None})
        await update.message.reply_text(f"{s['temp_char']} ditambahkan.", reply_markup=await menu(uid))
        return

    if s["step"] == "main_action":
        prompt = f"POV {s['name']}: {text}."
    elif s["step"] == "char_action":
        c = s["chars"][s["selected"]]
        prompt = f"POV {c['name']}: Reaksi terhadap {s['name']} -> {text}."
    elif s["step"] == "narator":
        prompt = f"NARASI: {text}."
    else: return

    await save(uid, {"last_prompt": prompt})
    out, model_name = await generate(prompt, build_system(s), s["history"])

    if out:
        s["history"].append(out)
        await save(uid, {"history": s["history"], "step": None})
        await update.message.reply_text(f"{out}\n\n[🤖 Model: {model_name}]", reply_markup=await menu(uid))
    else:
        await update.message.reply_text("Gagal memanggil AI. Cek Variable Environment di Railway kamu.")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    try: await q.answer()
    except: pass

    if q.data == "main": await save(uid, {"step": "main_action"}); await q.message.reply_text(f"Aksi {s['name']}?")
    elif q.data.startswith("char_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"step": "char_action", "selected": idx})
        await q.message.reply_text(f"Reaksi {s['chars'][idx]['name']}?")
    elif q.data == "add_char": await save(uid, {"step": "char_name"}); await q.message.reply_text("Nama karakter?")
    elif q.data == "narator": await save(uid, {"step": "narator"}); await q.message.reply_text("Apa yang terjadi?")
    elif q.data == "lanjut":
        out, model_name = await generate("Lanjutkan alur cerita.", build_system(s), s["history"])
        if out: s["history"].append(out); await save(uid, {"history": s["history"]}); await q.message.reply_text(f"{out}\n\n[🤖 Model: {model_name}]", reply_markup=await menu(uid))
    elif q.data == "undo":
        if len(s["history"]) > 1: s["history"].pop(); await save(uid, {"history": s["history"]}); await q.message.reply_text(f"--- Undo ---\n{s['history'][-1]}", reply_markup=await menu(uid))
    elif q.data == "regen":
        out, model_name = await generate(s.get("last_prompt") + " (Variasikan)", build_system(s), s["history"][:-1])
        if out: s["history"][-1] = out; await save(uid, {"history": s["history"]}); await q.message.reply_text(f"{out}\n\n[🤖 Model: {model_name}]", reply_markup=await menu(uid))

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("BOT DEPLOYED ON RAILWAY (GENAI SDK 2026)...")
    app.run_polling(drop_pending_updates=True)

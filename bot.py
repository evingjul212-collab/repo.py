import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
# Gunakan Client SDK 2026
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Daftar Model Prioritas (3.1 Lite paling atas karena paling stabil kuotanya)
MODELS = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash"
]

# Database MongoDB
client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states

# ========= DATABASE LOGIC =========
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name") or "Tanpa Nama",
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "temp_char": s.get("temp_char"),
        "last_prompt": s.get("last_prompt"),
        "last_system": s.get("last_system")
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    s = fix_state(s)
    await users.update_one({"_id": uid}, {"$set": s}, upsert=True)
    return s

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI ENGINE =========
async def generate(prompt, system, history):
    # Mengirim 10 baris terakhir sebagai konteks ingatan AI
    context = "\n---\n".join(history[-10:]) if history else "Mulai cerita baru."
    full_input = f"{system}\n\n[MEMORI CERITA]\n{context}\n\n[AKSI SEKARANG]\n{prompt}"
    
    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: client_ai.models.generate_content(model=m, contents=full_input)
            )
            return response.text.strip(), m
        except Exception as e:
            print(f"DEBUG: Model {m} gagal: {str(e)}")
            continue
    return None, None

# ========= MENU BUILDERS =========
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Daftar Karakter", callback_data="list_all")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), InlineKeyboardButton("⏩ Lanjut Alur", callback_data="lanjut")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo"), InlineKeyboardButton("🔄 Regenerate", callback_data="regen")],
        [InlineKeyboardButton("🧹 Reset Total", callback_data="reset_confirm")]
    ]
    return InlineKeyboardMarkup(kb)

async def menu_karakter(idx, name):
    kb = [
        [InlineKeyboardButton(f"💬 Lanjut POV: {name}", callback_data=f"act_{idx}")],
        [InlineKeyboardButton(f"📝 Edit Identitas", callback_data=f"edit_{idx}")],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]
    ]
    return InlineKeyboardMarkup(kb)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await save(uid, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine V1.6 Ready!\n\nSiapa nama Tokoh Utama kamu?")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)
    
    # Setup Tokoh Utama
    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Halo {text}! Karakter utama disetel.", reply_markup=await menu_utama(uid))
        return

    # Tambah NPC Baru
    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Apa deskripsi dari {text}?")
        return

    if s["step"] == "char_desc":
        chars = s["chars"]
        chars.append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": chars, "step": None})
        await update.message.reply_text(f"Karakter {s['temp_char']} disimpan.", reply_markup=await menu_utama(uid))
        return

    # Edit Deskripsi
    if s["step"] and s["step"].startswith("updating_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: await save(uid, {"name": text, "step": None})
        else:
            s["chars"][idx]["desc"] = text
            await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text("✅ Deskripsi diperbarui.", reply_markup=await menu_utama(uid))
        return

    # LOGIKA GENERATE
    if s["step"] in ["action", "narator_input"]:
        is_nar = s["step"] == "narator_input"
        idx = s.get("selected", -1)
        
        if is_nar:
            tag = "NARASI"
            prompt = f"KEJADIAN: {text}"
            system = "Kamu Narator RPG. Deskripsikan kejadian dengan imersif."
        else:
            tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
            desc = "Tokoh Utama" if idx == -1 else s["chars"][idx]["desc"]
            prompt = f"POV {tag}: {text}"
            system = f"Kamu asisten RPG. Fokus pada aksi {tag} ({desc})."

        await save(uid, {"last_prompt": prompt, "last_system": system})
        out, model_name = await generate(prompt, system, s["history"])
        
        if out:
            s["history"].append(f"**{tag}**: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(f"✨ {s['history'][-1]}", parse_mode="Markdown", reply_markup=await menu_utama(uid))
        else:
            # Tetap tampilkan menu meski error biar user bisa Regenerate
            await update.message.reply_text("⚠️ Semua AI sedang sibuk. Tunggu 10 detik lalu klik '🔄 Regenerate'.", reply_markup=await menu_utama(uid))

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "step_narator":
        await save(uid, {"step": "narator_input"})
        await q.message.reply_text("🎭 [MODE NARATOR]\nApa yang terjadi di duniamu?")

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]):
            kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah Karakter Baru", callback_data="add_new")])
        kb.append([InlineKeyboardButton("⬅️ Menu Utama", callback_data="main_menu")])
        await q.edit_message_text("Daftar Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await q.edit_message_text(f"Karakter: {name}", reply_markup=await menu_karakter(idx, name))

    elif q.data.startswith("act_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"Aksi untuk {name}:")

    elif q.data.startswith("edit_"):
        idx = int(q.data.split("_")[1])
        await save(uid, {"step": f"updating_{idx}"})
        await q.message.reply_text("Tulis deskripsi baru:")

    elif q.data == "add_new":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Nama karakter?")

    elif q.data == "main_menu":
        await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))

    elif q.data == "undo":
        if s["history"]:
            s["history"].pop()
            await save(uid, {"history": s["history"]})
            await q.message.reply_text("↩️ Aksi terakhir dihapus.", reply_markup=await menu_utama(uid))

    elif q.data == "regen":
        if not s.get("last_prompt"):
            await q.message.reply_text("Gak ada yang bisa diulang, Bos.")
            return
        if s["history"]: s["history"].pop()
        await q.message.reply_text("🔄 Memproses ulang...")
        out, model = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            tag = s["last_prompt"].split(":")[0].replace("POV ", "").replace("KEJADIAN", "NARASI")
            s["history"].append(f"**{tag}**: {out}")
            await save(uid, {"history": s["history"]})
            await q.message.reply_text(f"✨ {s['history'][-1]}", parse_mode="Markdown", reply_markup=await menu_utama(uid))

    elif q.data == "lanjut":
        await q.message.reply_text("🎬 Melanjutkan...")
        out, model = await generate("Lanjutkan ceritanya.", "Kamu Narator RPG.", s["history"])
        if out:
            s["history"].append(f"**NARASI**: {out}")
            await save(uid, {"history": s["history"]})
            await q.message.reply_text(f"🎬 {s['history'][-1]}", parse_mode="Markdown", reply_markup=await menu_utama(uid))

    elif q.data == "reset_confirm":
        await save(uid, {"history": [], "step": None, "chars": []})
        await q.message.reply_text("🧹 Data game di-reset. Klik /start lagi.")

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("V1.6 DEPLOYED. SIAP DIUJI, BOS!")
    app.run_polling()

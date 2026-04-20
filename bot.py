import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODELS = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash"
]

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
        "last_system": s.get("last_system") # Untuk kebutuhan Regenerate
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
    # Kirim 10 history terakhir untuk konteks yang kuat
    context = "\n---\n".join(history[-10:]) if history else "Mulai cerita baru."
    full_input = f"{system}\n\n[MEMORI CERITA]\n{context}\n\n[INSTRUKSI AKSI]\n{prompt}"
    
    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: client_ai.models.generate_content(model=m, contents=full_input)
            )
            return response.text.strip(), m
        except: continue
    return None, None

# ========= MENU BUILDERS =========
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Daftar Karakter", callback_data="list_all")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), InlineKeyboardButton("⏩ Lanjut Alur", callback_data="lanjut")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo"), InlineKeyboardButton("🔄 Regenerate", callback_data="regen")],
        [InlineKeyboardButton("🆕 Reset Game", callback_data="reset_confirm")]
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
    await save(update.effective_user.id, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine V1.5 [Full Features]\n\nMasukkan nama Tokoh Utama kamu:")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)
    
    # Setup Awal
    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Halo {text}! Karakter utama telah disetel.", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Apa deskripsi/sifat dari {text}?")
        return

    if s["step"] == "char_desc":
        chars = s["chars"]
        chars.append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": chars, "step": None})
        await update.message.reply_text(f"Karakter {s['temp_char']} berhasil ditambah.", reply_markup=await menu_utama(uid))
        return

    # Update Deskripsi
    if s["step"] and s["step"].startswith("updating_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: await save(uid, {"name": text, "step": None})
        else:
            s["chars"][idx]["desc"] = text
            await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text("✅ Identitas diperbarui.", reply_markup=await menu_utama(uid))
        return

    # Proses Aksi (Karakter atau Narator)
    if s["step"] in ["action", "narator_input"]:
        is_nar = s["step"] == "narator_input"
        idx = s.get("selected", -1)
        
        if is_nar:
            char_tag = "NARASI"
            prompt = f"KEJADIAN: {text}"
            system = "Kamu adalah Narator RPG. Deskripsikan suasana dan kejadian dengan sangat imersif."
        else:
            char_tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
            c_desc = "Tokoh Utama" if idx == -1 else s["chars"][idx]["desc"]
            prompt = f"POV {char_tag}: {text}"
            system = f"Kamu asisten RPG. Fokus pada aksi {char_tag} ({c_desc}). Berikan respon yang sesuai."

        await save(uid, {"last_prompt": prompt, "last_system": system})
        out, model = await generate(prompt, system, s["history"])
        
        if out:
            s["history"].append(f"**{char_tag}**: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(f"✨ {s['history'][-1]}", parse_mode="Markdown", reply_markup=await menu_utama(uid))
        else:
            await update.message.reply_text("⚠️ Koneksi AI sibuk. Coba lagi.")

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "step_narator":
        await save(uid, {"step": "narator_input"})
        await q.message.reply_text("🎭 [MODE NARATOR]\nApa yang terjadi selanjutnya?")

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]):
            kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC Baru", callback_data="add_new")])
        kb.append([InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")])
        await q.edit_message_text("Manajemen Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await q.edit_message_text(f"Karakter: {name}", reply_markup=await menu_karakter(idx, name))

    elif q.data.startswith("act_"):
        idx = int(q.data.split("_")[1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"Tulis aksi untuk {name}:")

    elif q.data.startswith("edit_"):
        idx = int(q.data.split("_")[1])
        await save(uid, {"step": f"updating_{idx}"})
        await q.message.reply_text("Masukkan deskripsi baru:")

    elif q.data == "add_new":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Nama NPC baru?")

    elif q.data == "main_menu":
        await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))

    elif q.data == "undo":
        if s["history"]:
            s["history"].pop() # Hapus chat terakhir
            await save(uid, {"history": s["history"]})
            await q.message.reply_text("↩️ Aksi terakhir telah dihapus dari memori.")
        else:
            await q.message.reply_text("Memori sudah kosong.")

    elif q.data == "regen":
        if not s.get("last_prompt"):
            await q.message.reply_text("Tidak ada aksi untuk di-regenerate.")
            return
        
        # Hapus yang lama, buat yang baru
        if s["history"]: s["history"].pop()
        await q.message.reply_text("🔄 Memutar ulang waktu... (Regenerating)")
        out, model = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            # Ambil tag dari prompt (POV/KEJADIAN)
            tag = s["last_prompt"].split(":")[0]
            s["history"].append(f"**{tag}**: {out}")
            await save(uid, {"history": s["history"]})
            await q.message.reply_text(f"✨ {s['history'][-1]}", parse_mode="Markdown", reply_markup=await menu_utama(uid))

    elif q.data == "lanjut":
        await q.message.reply_text("🎬 Melanjutkan alur cerita...")
        out, model = await generate("Lanjutkan alur cerita secara otomatis.", "Kamu Narator RPG.", s["history"])
        if out:
            s["history"].append(f"**NARASI**: {out}")
            await save(uid, {"history": s["history"]})
            await q.message.reply_text(f"🎬 {s['history'][-1]}", parse_mode="Markdown", reply_markup=await menu_utama(uid))

    elif q.data == "reset_confirm":
        await save(uid, {"history": [], "step": None, "chars": []})
        await q.message.reply_text("🧹 Database dibersihkan. Ketik /start untuk mulai baru.")

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("RPG BOT V1.5 READY - ALL SYSTEMS GO")
    app.run_polling()

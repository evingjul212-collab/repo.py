import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClientimport os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
# MENGGUNAKAN SDK TERBARU (2026)
from google import genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Inisialisasi Client sesuai daftar yang Bos kasih tadi
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# DAFTAR MODEL VALID (Sesuai hasil JSON Bos tadi)
# Saya taruh 3.1 Flash Lite di atas karena biasanya kuotanya paling lega
MODELS = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash"
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
RPG ENGINE 2.5/3.1:
- User: {s['name']} | Partner: {char_list}
- Lokasi: {st['setting']} | Waktu: {st['time']}
- Aturan: POV konsisten, narasi natural, max 2 paragraf.
"""

# ========= AI GENERATOR (RETRY LOGIC) =========
async def generate(prompt, system, history):
    context = "\n---\n".join(history[-8:]) if history else "Start."
    full_input = f"{system}\n\n[MEMORI]\n{context}\n\n[INPUT]\n{prompt}"
    
    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            # Panggil model tanpa paksa versi, biar auto-detect
            response = await loop.run_in_executor(
                None,
                lambda: client_ai.models.generate_content(model=m, contents=full_input)
            )
            return response.text.strip(), m
        except Exception as e:
            err = str(e)
            print(f"DEBUG: Model {m} gagal. Info: {err}")
            # Jika kena kuota (429), kita skip ke model berikutnya
            if "429" in err or "QUOTA" in err:
                continue
            # Jika 404, lanjut cari yang ada
            continue
    return None, None

# ========= TELEGRAM HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await save(uid, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine 2026 Aktif.\nMasukkan nama Karakter Utama:")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    if not text: return
    s = await get_state(uid)
    
    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Nama '{text}' oke. Mulai?", reply_markup=await menu(uid))
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
        prompt = f"POV {c['name']}: {text}."
    elif s["step"] == "narator":
        prompt = f"NARATOR: {text}."
    else: return

    await save(uid, {"last_prompt": prompt})
    out, model_name = await generate(prompt, build_system(s), s["history"])

    if out:
        s["history"].append(out)
        await save(uid, {"history": s["history"], "step": None})
        await update.message.reply_text(f"{out}\n\n[🤖 {model_name}]", reply_markup=await menu(uid))
    else:
        await update.message.reply_text("Semua model (2.5/3.1) sedang limit. Tunggu sebentar ya Bos.")

async def menu(uid):
    s = await get_state(uid)
    kb = []
    if s["name"]: kb.append([InlineKeyboardButton(f"👤 {s['name']}", callback_data="main")])
    for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"💬 {c['name']}", callback_data=f"char_{i}")])
    kb.append([InlineKeyboardButton("🎭 Narasi", callback_data="narator"), InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")])
    kb.append([InlineKeyboardButton("➕ Tambah Karakter", callback_data="add_char")])
    kb.append([InlineKeyboardButton("🔄 Regen", callback_data="regen")])
    return InlineKeyboardMarkup(kb)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    try: await q.answer()
    except: pass

    if q.data == "main": await save(uid, {"step": "main_action"}); await q.message.reply_text(f"Aksi {s['name']}?")
    elif q.data.startswith("char_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"step": "char_action", "selected": idx})
        await q.message.reply_text(f"Aksi {s['chars'][idx]['name']}?")
    elif q.data == "add_char": await save(uid, {"step": "char_name"}); await q.message.reply_text("Nama karakter?")
    elif q.data == "narator": await save(uid, {"step": "narator"}); await q.message.reply_text("Kejadian apa?")
    elif q.data == "lanjut":
        out, model_name = await generate("Lanjutkan ceritanya.", build_system(s), s["history"])
        if out: s["history"].append(out); await save(uid, {"history": s["history"]}); await q.message.reply_text(f"{out}\n\n[🤖 {model_name}]", reply_markup=await menu(uid))
    elif q.data == "regen":
        out, model_name = await generate(s.get("last_prompt", "Lanjutkan"), build_system(s), s["history"][:-1])
        if out: s["history"][-1] = out; await save(uid, {"history": s["history"]}); await q.message.reply_text(f"{out}\n\n[🤖 {model_name}]", reply_markup=await menu(uid))

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("RPG BOT DEPLOYED ON RAILWAY (MODERN MODELS 2.5/3.1)...")
    app.run_polling(drop_pending_updates=True)
# MENGGUNAKAN SDK TERBARU GOOGLE GENAI
from google import genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

# JURUS PAMUNGKAS: Memaksa API menggunakan versi 'v1' (bukan v1beta) agar tidak 404
# dan menaikkan stabilitas koneksi dari server Railway
client_ai = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options={'api_version': 'v1'}
)

# Daftar model dengan urutan cerdas: 
# 1.5 Flash (paling stabil), 1.5 Flash-8b (cadangan kuota), 2.0 Flash (terakhir karena kuota kamu kritis)
MODELS = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-2.0-flash"
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

# ========= SYSTEM ENGINE (POV & KONSISTENSI) =========
def build_system(s):
    st = s["story"]
    char_list = ", ".join([c['name'] for c in s['chars']])
    return f"""
KONTROL ENGINE RPG:
- Setting: {st['setting']} | Waktu: {st['time']}
- Karakter Aktif: {s['name']} (User), {char_list}
PROTOKOL:
1. POV TERKUNCI: Hasilkan narasi & dialog HANYA untuk satu karakter yang dipilih.
2. LOGIKA FISIK: Wajib ingat posisi (berdiri/duduk/lokasi) sesuai memori.
3. BATASAN: 1-2 paragraf saja. DILARANG menulis aksi karakter lain.
"""

# ========= AI GENERATOR (DENGAN AUTO-RETRY) =========
async def generate(prompt, system, history):
    context = "\n---\n".join(history[-12:]) if history else "Cerita dimulai."
    full_input = f"{system}\n\n--- MEMORI ALUR ---\n{context}\n\n--- INSTRUKSI ---\n{prompt}"
    
    for m in MODELS:
        try:
            # Menggunakan loop.run_in_executor agar tidak blocking di Railway
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client_ai.models.generate_content(model=m, contents=full_input)
            )
            return response.text.strip(), m
        except Exception as e:
            err_msg = str(e)
            print(f"DEBUG: Model {m} gagal. Error: {err_msg}")
            # Jika kuota habis (429), langsung coba model berikutnya
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                continue
            # Jika 404, lanjut cari model lain
            continue
    return None, None

# ========= HANDLERS (TELEGRAM) =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine 2026 (v1 Stable) Ready.\nMasukkan nama Tokoh Utama:")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    if not text: return
    s = await get_state(uid)
    
    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Karakter utama '{text}' terdaftar.", reply_markup=await menu(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Apa deskripsi singkat untuk {text}?")
        return

    if s["step"] == "char_desc":
        chars = s["chars"]
        chars.append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": chars, "step": None})
        await update.message.reply_text(f"{s['temp_char']} bergabung.", reply_markup=await menu(uid))
        return

    if s["step"] == "main_action":
        prompt = f"POV {s['name']}: {text}. Jangan tulis dialog orang lain."
    elif s["step"] == "char_action":
        c = s["chars"][s["selected"]]
        prompt = f"POV {c['name']}: Bereaksi terhadap {s['name']}. Aksi: {text}. Jangan tulis dialog {s['name']}."
    elif s["step"] == "narator":
        prompt = f"NARASI: {text}. Tanpa dialog."
    else: return

    await save(uid, {"last_prompt": prompt})
    out, model_name = await generate(prompt, build_system(s), s["history"])

    if out:
        s["history"].append(out)
        await save(uid, {"history": s["history"], "step": None})
        await update.message.reply_text(f"{out}\n\n[🤖 Aktif: {model_name}]", reply_markup=await menu(uid))
    else:
        await update.message.reply_text("Semua model sedang limit/error. Tunggu 15-30 detik lalu klik 'Regen' atau 'Lanjut', Bos.")

async def menu(uid):
    s = await get_state(uid)
    kb = []
    if s["name"]: kb.append([InlineKeyboardButton(f"👤 POV: {s['name']}", callback_data="main")])
    kb.append([InlineKeyboardButton("🎭 Narator", callback_data="narator"), InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")])
    for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"💬 POV: {c['name']}", callback_data=f"char_{i}")])
    kb.append([InlineKeyboardButton("➕ Karakter", callback_data="add_char")])
    kb.append([InlineKeyboardButton("↩️ Undo", callback_data="undo"), InlineKeyboardButton("🔄 Regen", callback_data="regen")])
    return InlineKeyboardMarkup(kb)

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
    elif q.data == "narator": await save(uid, {"step": "narator"}); await q.message.reply_text("Peristiwa alam/sekitar?")
    elif q.data == "lanjut":
        out, model_name = await generate("Lanjutkan alur secara natural.", build_system(s), s["history"])
        if out: s["history"].append(out); await save(uid, {"history": s["history"]}); await q.message.reply_text(f"{out}\n\n[🤖 Aktif: {model_name}]", reply_markup=await menu(uid))
    elif q.data == "undo":
        if len(s["history"]) > 1: s["history"].pop(); await save(uid, {"history": s["history"]}); await q.message.reply_text(f"--- Mundur 1 Langkah ---\n{s['history'][-1]}", reply_markup=await menu(uid))
    elif q.data == "regen":
        out, model_name = await generate(s.get("last_prompt") + " (Berikan variasi narasi)", build_system(s), s["history"][:-1])
        if out: s["history"][-1] = out; await save(uid, {"history": s["history"]}); await q.message.reply_text(f"{out}\n\n[🤖 Aktif: {model_name}]", reply_markup=await menu(uid))

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("RPG BOT DEPLOYED (V1 STABLE ENGINE)...")
    app.run_polling(drop_pending_updates=True)

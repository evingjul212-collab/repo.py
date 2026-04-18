import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
import google.generativeai as genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Menggunakan model versi 2.5 dan 3 sesuai permintaan
MODELS = [
    "gemini-3-flash",
    "gemini-2.5-flash",
    "gemini-1.5-flash" # Sebagai fallback terakhir
]

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

# ========= STATE =========
def fix_state(s):
    if not s:
        s = {}
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
            "main_desc": "",
            "plot": "",
            "relationships": "",
            "rules": "Romcom natural"
        })
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    s = fix_state(s)
    await users.update_one({"_id": uid}, {"$set": s}, upsert=True)
    return s

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= SYSTEM (RPG LOGIC) =========
def build_system(s):
    st = s["story"]
    char_list = ", ".join([c['name'] for c in s['chars']])
    
    return f"""
Kamu adalah engine RPG Romcom interaktif. 
Setting: {st['setting']} | Waktu: {st['time']} | Rules: {st['rules']}
Daftar Karakter: {s['name']} (User), {char_list}

TUGAS UTAMA:
- Fokus HANYA pada satu karakter yang ditentukan di prompt.
- Hasilkan narasi aksi dan dialog HANYA untuk karakter tersebut.
- DILARANG Keras menulis dialog, pikiran, atau aksi untuk karakter lain.
- Gunakan sudut pandang orang ketiga (Third Person POV).
- Output: 1 paragraf pendek, padat, fokus pada interaksi saat ini.
"""

# ========= AI =========
async def generate(prompt, system, history):
    # Mengambil sedikit konteks sejarah agar nyambung
    context = "\n".join(history[-3:]) if history else ""
    full_input = f"{system}\n\nKonteks sebelumnya:\n{context}\n\nInstruksi sekarang:\n{prompt}"
    
    for m in MODELS:
        try:
            model = genai.GenerativeModel(m)
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None,
                lambda: model.generate_content(full_input)
            )
            return res.text.strip()
        except Exception as e:
            print(f"MODEL ERROR {m}:", e)
            continue
    return None

# ========= MENU =========
async def menu(uid):
    s = await get_state(uid)
    kb = []

    if s["name"]:
        kb.append([InlineKeyboardButton(f"👤 {s['name']} (UTAMA)", callback_data="main")])

    kb.append([
        InlineKeyboardButton("📖 Narator", callback_data="narator"),
        InlineKeyboardButton("➡️ Lanjut", callback_data="lanjut")
    ])

    kb.append([
        InlineKeyboardButton("➕ Tambah Karakter", callback_data="add_char")
    ])

    for i, c in enumerate(s["chars"]):
        kb.append([InlineKeyboardButton(f"💬 {c['name']}", callback_data=f"char_{i}")])

    kb.append([
        InlineKeyboardButton("↩️ Undo", callback_data="undo"),
        InlineKeyboardButton("🔄 Regen", callback_data="regen")
    ])

    return InlineKeyboardMarkup(kb)

# ========= START =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {
        "name": None,
        "step": "set_name",
        "history": [],
        "chars": []
    })
    await update.message.reply_text("Selamat datang di RPG Romcom!\nMasukkan nama Tokoh Utama kamu:")

# ========= MESSAGE =========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)
    step = s["step"]

    if step == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Halo {text}! Siap memulai cerita?", reply_markup=await menu(uid))
        return

    if step == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Apa deskripsi/sifat untuk {text}?")
        return

    if step == "char_desc":
        chars = s["chars"]
        chars.append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": chars, "step": None})
        await update.message.reply_text(f"Karakter {s['temp_char']} berhasil masuk ke dalam cerita!", reply_markup=await menu(uid))
        return

    system = build_system(s)

    # PEMISAHAN LOGIKA SUDUT PANDANG (POV)
    if step == "main_action":
        prompt = f"Tulis narasi & dialog untuk {s['name']} saja. Dia sedang: {text}. Jangan tulis respon karakter lain."
    
    elif step == "char_action":
        c = s["chars"][s["selected"]]
        prompt = f"Tulis narasi & dialog untuk {c['name']} saja sebagai respon. User ({s['name']}) sedang: {text}. Jangan tulis dialog {s['name']}."

    elif step == "narator":
        prompt = f"Tulis narasi lingkungan atau transisi tanpa dialog: {text}"
    else:
        return

    await save(uid, {"last_prompt": prompt})
    out = await generate(prompt, system, s["history"])

    if not out:
        await update.message.reply_text("AI sedang lelah, coba lagi, Bos.")
        return

    hist = s["history"]
    hist.append(out)
    await save(uid, {"history": hist, "step": None})
    await update.message.reply_text(out, reply_markup=await menu(uid))

# ========= BUTTON =========
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data
    try: await q.answer()
    except: pass

    s = await get_state(uid)

    if data == "main":
        await save(uid, {"step": "main_action"})
        await q.message.reply_text(f"Apa yang dilakukan {s['name']}?")

    elif data.startswith("char_"):
        idx = int(data.split("_")[1])
        await save(uid, {"step": "char_action", "selected": idx})
        await q.message.reply_text(f"Apa yang dilakukan {s['chars'][idx]['name']}?")

    elif data == "add_char":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Nama karakter baru:")

    elif data == "narator":
        await save(uid, {"step": "narator"})
        await q.message.reply_text("Apa yang terjadi secara naratif?")

    elif data == "lanjut":
        system = build_system(s)
        prompt = "Lanjutkan narasi secara natural tanpa dialog baru, fokus pada suasana."
        out = await generate(prompt, system, s["history"])
        if out:
            hist = s["history"]
            hist.append(out)
            await save(uid, {"history": hist})
            await q.message.reply_text(out, reply_markup=await menu(uid))

    elif data == "undo":
        hist = s["history"]
        if len(hist) > 1:
            hist.pop()
            await save(uid, {"history": hist})
            await q.message.reply_text("--- Langkah Terakhir Dibatalkan ---\n\n" + hist[-1], reply_markup=await menu(uid))

    elif data == "regen":
        prompt = s.get("last_prompt")
        if not prompt: return
        system = build_system(s)
        out = await generate(prompt + " (Variasikan sedikit)", system, s["history"][:-1])
        if out:
            hist = s["history"]
            hist[-1] = out
            await save(uid, {"history": hist})
            await q.message.reply_text(out, reply_markup=await menu(uid))

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("RPG BOT READY (MODELS: 3 & 2.5)...")
    app.run_polling(drop_pending_updates=True)

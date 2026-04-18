import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
import google.generativeai as genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Prioritas Model 3 dan 2.5 untuk kecerdasan logika terbaik
MODELS = [
    "gemini-3-flash",
    "gemini-2.5-flash",
    "gemini-1.5-flash"
]

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

# ========= STATE =========
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
- Setting Utama: {st['setting']} | Waktu: {st['time']}
- Daftar Karakter Aktif: {s['name']} (User), {char_list}

PROTOKOL KONSISTENSI (WAJIB):
1. LOGIKA FISIK: Perhatikan posisi karakter di pesan terakhir (duduk, berdiri, lokasi). Jangan mengubah posisi tanpa aksi yang masuk akal.
2. POV TERKUNCI: Hasilkan narasi & dialog HANYA untuk karakter yang diminta.
3. ANTI-AMNESIA: Gunakan konteks sebelumnya untuk menjaga alur. Jika karakter sedang di kamar mandi, jangan tiba-tiba di dapur.
4. GAYA BAHASA: Romcom natural, deskripsi hidup, 1-2 paragraf saja.
5. DILARANG keras mengontrol atau menulis dialog karakter lain.
"""

# ========= AI GENERATOR =========
async def generate(prompt, system, history):
    # Mengambil hingga 12 pesan terakhir untuk stabilitas memori jangka panjang
    context = "\n---\n".join(history[-12:]) if history else "Cerita dimulai."
    
    full_input = f"""
{system}

--- MEMORI ALUR TERAKHIR ---
{context}

--- INSTRUKSI PERAN SEKARANG ---
{prompt}

Tanggapi dengan menjaga kesinambungan posisi fisik dan situasi dari memori di atas:
"""
    
    for m in MODELS:
        try:
            model = genai.GenerativeModel(m)
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None, 
                lambda: model.generate_content(full_input)
            )
            return res.text.strip().replace("```", "")
        except Exception as e:
            print(f"DEBUG: {m} bermasalah, mencoba model lain... Error: {e}")
            continue
    return None

# ========= INTERFACE =========
async def menu(uid):
    s = await get_state(uid)
    kb = []
    if s["name"]:
        kb.append([InlineKeyboardButton(f"👤 POV: {s['name']}", callback_data="main")])

    kb.append([
        InlineKeyboardButton("🎭 Narator", callback_data="narator"),
        InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")
    ])

    for i, c in enumerate(s["chars"]):
        kb.append([InlineKeyboardButton(f"💬 POV: {c['name']}", callback_data=f"char_{i}")])

    kb.append([InlineKeyboardButton("➕ Karakter Baru", callback_data="add_char")])
    kb.append([
        InlineKeyboardButton("↩️ Undo", callback_data="undo"),
        InlineKeyboardButton("🔄 Regen", callback_data="regen")
    ])

    return InlineKeyboardMarkup(kb)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine Ready.\nMasukkan nama Tokoh Utama:")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)
    
    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"Karakter utama '{text}' terdaftar.", reply_markup=await menu(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Deskripsi singkat untuk {text}?")
        return

    if s["step"] == "char_desc":
        chars = s["chars"]
        chars.append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": chars, "step": None})
        await update.message.reply_text(f"{s['temp_char']} masuk ke dunia.", reply_markup=await menu(uid))
        return

    # PROMPT LOGIC
    if s["step"] == "main_action":
        prompt = f"POV {s['name']}: Lakukan aksi ini -> {text}. Fokus pada respon {s['name']} saja."
    elif s["step"] == "char_action":
        c = s["chars"][s["selected"]]
        prompt = f"POV {c['name']}: Berikan reaksi terhadap {s['name']}. Aksi spesifik: {text}. Fokus pada {c['name']} saja."
    elif s["step"] == "narator":
        prompt = f"NARASI: Deskripsikan perubahan situasi atau lingkungan: {text}. Tanpa dialog."
    else: return

    await save(uid, {"last_prompt": prompt})
    out = await generate(prompt, build_system(s), s["history"])

    if out:
        hist = s["history"]
        hist.append(out)
        await save(uid, {"history": hist, "step": None})
        await update.message.reply_text(out, reply_markup=await menu(uid))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    try: await q.answer()
    except: pass

    if q.data == "main":
        await save(uid, {"step": "main_action"})
        await q.message.reply_text(f"Tindakan apa yang diambil {s['name']}?")
    elif q.data.startswith("char_"):
        idx = int(q.data.split("_")[1])
        await save(uid, {"step": "char_action", "selected": idx})
        await q.message.reply_text(f"Apa reaksi dari {s['chars'][idx]['name']}?")
    elif q.data == "add_char":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Siapa nama karakternya?")
    elif q.data == "narator":
        await save(uid, {"step": "narator"})
        await q.message.reply_text("Tuliskan peristiwa lingkungan:")
    elif q.data == "lanjut":
        out = await generate("Lanjutkan alur cerita secara natural sesuai posisi terakhir.", build_system(s), s["history"])
        if out:
            s["history"].append(out)
            await save(uid, {"history": s["history"]})
            await q.message.reply_text(out, reply_markup=await menu(uid))
    elif q.data == "undo":
        if len(s["history"]) > 1:
            s["history"].pop()
            await save(uid, {"history": s["history"]})
            await q.message.reply_text("--- Langkah Dibatalkan ---\n\n" + s["history"][-1], reply_markup=await menu(uid))
    elif q.data == "regen":
        out = await generate(s.get("last_prompt") + " (Berikan variasi narasi berbeda)", build_system(s), s["history"][:-1])
        if out:
            s["history"][-1] = out
            await save(uid, {"history": s["history"]})
            await q.message.reply_text(out, reply_markup=await menu(uid))

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("RPG ENGINE DEPLOYED. WAITING FOR ACTIONS...")
    app.run_polling(drop_pending_updates=True)

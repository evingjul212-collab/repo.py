import os
import warnings
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, Defaults
)
from motor.motor_asyncio import AsyncIOMotorClient
from openai import OpenAI
import google.generativeai as genai

warnings.filterwarnings("ignore")

# ================= CONFIG =================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_main = genai.GenerativeModel("gemini-2.5-flash")
gemini_lite = genai.GenerativeModel("gemini-3-flash")

# OpenRouter fallback (Qwen)
client_ai = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

QWEN_MODEL = "qwen/qwen2.5-7b-instruct"

# Mongo
client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

# ================= MEMORY =================

def ensure_memory(state):
    defaults = {
        "time": "sore",
        "location": "rumah",
        "scene": "awal",
        "outfit": "pakaian santai",
        "history": [],
        "chars": []
    }
    for k, v in defaults.items():
        if k not in state:
            state[k] = v
    return state

def build_memory(state):
    return f"""
Waktu: {state['time']}
Lokasi: {state['location']}
Scene: {state['scene']}
Outfit: {state['outfit']}
"""

def get_context(state):
    return "\n".join(state.get("history", [])[-3:])

# ================= PROMPT =================

SYSTEM_PROMPT = """
Kamu penulis romcom realistis.

WAJIB:
- Bahasa Indonesia natural
- Maksimal 2 paragraf
- Minimal 60% dialog
- Jangan langsung konflik ekstrem
- Jangan absurd
- Reaksi manusiawi
- Mulai dari narasi jika scene baru
"""

def prompt_narator(memory, text):
    return f"{memory}\n\nBuat adegan dari input ini:\n{text}"

def prompt_lanjut(memory, hist):
    return f"{memory}\n\nLanjutkan cerita:\n{hist}"

def prompt_interaksi(memory, hist, char_name, text):
    return f"{memory}\n\nKonteks:\n{hist}\n\nTampilkan reaksi {char_name} terhadap:\n{text}"

# ================= VALIDASI =================

def validate(text):
    if not text or len(text.split()) < 20:
        return False
    if any(w in text.lower() for w in [" i ", " you ", " the "]):
        return False
    return True

# ================= AI =================

async def generate_gemini(prompt, model):
    try:
        res = model.generate_content(SYSTEM_PROMPT + "\n" + prompt)
        return res.text if res.text else None
    except:
        return None

async def generate_qwen(prompt):
    try:
        res = client_ai.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=700
        )
        return res.choices[0].message.content.strip()
    except:
        return None

async def smart_generate(prompt):
    # 1. Gemini utama
    out = await generate_gemini(prompt, gemini_main)
    if validate(out):
        return out, "gemini-main"

    # 2. Gemini lite
    out = await generate_gemini(prompt, gemini_lite)
    if validate(out):
        return out, "gemini-lite"

    # 3. Qwen fallback
    out = await generate_qwen(prompt)
    if validate(out):
        return out, "qwen"

    return None, None

# ================= MENU =================

async def get_menu(uid):
    state = ensure_memory(await users.find_one({"_id": uid}) or {})

    keyboard = [
        [InlineKeyboardButton("📖 Narator", callback_data="narator"),
         InlineKeyboardButton("➡️ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("➕ Karakter", callback_data="tambah"),
         InlineKeyboardButton("🔄 Reset", callback_data="reset")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo")]
    ]

    for i, c in enumerate(state.get("chars", [])):
        keyboard.append([
            InlineKeyboardButton(f"💬 {c['name']}", callback_data=f"char_{i}")
        ])

    return InlineKeyboardMarkup(keyboard)

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await users.update_one(
        {"_id": update.effective_user.id},
        {"$set": {"step": "input_name"}},
        upsert=True
    )
    await update.message.reply_text("Nama tokoh utama?")

# ================= MESSAGE =================

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    state = ensure_memory(await users.find_one({"_id": uid}) or {})
    step = state.get("step")

    if step == "input_name":
        await users.update_one({"_id": uid}, {"$set": {"name": text, "step": None}})
        await update.message.reply_text("Nama disimpan!", reply_markup=await get_menu(uid))
        return

    if step == "wait_char":
        await users.update_one({"_id": uid}, {"$set": {"temp_char": text, "step": "wait_desc"}})
        await update.message.reply_text("Deskripsi karakter:")
        return

    if step == "wait_desc":
        await users.update_one({"_id": uid}, {
            "$push": {"chars": {"name": state["temp_char"], "desc": text}},
            "$set": {"step": None}
        })
        await update.message.reply_text("Karakter ditambah!", reply_markup=await get_menu(uid))
        return

    memory = build_memory(state)
    hist = get_context(state)

    if step == "narator":
        prompt = prompt_narator(memory, text)

    elif step == "char_react":
        char = state["chars"][state["selected_char"]]
        prompt = prompt_interaksi(memory, hist, char["name"], text)

    else:
        return

    out, model = await smart_generate(prompt)

    if not out:
        await update.message.reply_text("❌ AI gagal semua")
        return

    history = state.get("history", [])
    history.append(out)

    await users.update_one({"_id": uid}, {"$set": {"history": history, "step": None}})

    await update.message.reply_text(f"🔹 {model}\n\n{out}", reply_markup=await get_menu(uid))

# ================= BUTTON =================

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data

    try:
        await q.answer()
    except:
        pass

    if data == "narator":
        await users.update_one({"_id": uid}, {"$set": {"step": "narator"}})
        await q.message.reply_text("Masukkan cerita:")

    elif data == "lanjut":
        state = ensure_memory(await users.find_one({"_id": uid}) or {})
        memory = build_memory(state)
        hist = get_context(state)

        out, model = await smart_generate(prompt_lanjut(memory, hist))

        if out:
            history = state.get("history", [])
            history.append(out)
            await users.update_one({"_id": uid}, {"$set": {"history": history}})
            await q.message.reply_text(f"🔹 {model}\n\n{out}", reply_markup=await get_menu(uid))

    elif data.startswith("char_"):
        idx = int(data.split("_")[1])
        await users.update_one({"_id": uid}, {"$set": {"step": "char_react", "selected_char": idx}})
        state = await users.find_one({"_id": uid})
        char = state["chars"][idx]
        await q.message.reply_text(f"Reaksi {char['name']}:")

    elif data == "tambah":
        await users.update_one({"_id": uid}, {"$set": {"step": "wait_char"}})
        await q.message.reply_text("Nama karakter:")

    elif data == "undo":
        state = await users.find_one({"_id": uid})
        history = state.get("history", [])

        if len(history) > 1:
            history.pop()
            await users.update_one({"_id": uid}, {"$set": {"history": history}})
            await q.message.reply_text(history[-1], reply_markup=await get_menu(uid))
        else:
            await q.message.reply_text("Tidak bisa undo.")

    elif data == "reset":
        await users.delete_one({"_id": uid})
        await q.message.reply_text("Reset. /start lagi")

# ================= RUN =================

defaults = Defaults(parse_mode=None)

app = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

print("🚀 BOT RUNNING...")
app.run_polling()

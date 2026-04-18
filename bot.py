import os
import warnings
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from motor.motor_asyncio import AsyncIOMotorClient
from openai import OpenAI
import google.generativeai as genai

warnings.filterwarnings("ignore")

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_main = genai.GenerativeModel("gemini-2.5-flash")
gemini_lite = genai.GenerativeModel("gemini-3-flash-preview")

client_ai = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)
QWEN_MODEL = "qwen/qwen2.5-7b-instruct"

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

# ========= MEMORY =========
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
    return f"Waktu: {state['time']}\nLokasi: {state['location']}\nScene: {state['scene']}\nOutfit: {state['outfit']}"

def get_context(state):
    return "\n".join(state.get("history", [])[-3:])

# ========= PROMPT =========
SYSTEM_PROMPT = """
Kamu penulis romcom realistis.
- Bahasa Indonesia natural
- Maksimal 2 paragraf
- Fokus dialog
- Reaksi manusia normal
- Jangan absurd
"""

def prompt_narator(memory, text):
    return f"{memory}\n\nBuat adegan dari input ini (mulai dari narasi dulu):\n{text}"

def prompt_lanjut(memory, hist):
    return f"{memory}\n\nLanjutkan cerita ini:\n{hist}"

def prompt_main(memory, hist, name, action):
    return f"{memory}\n\nKonteks:\n{hist}\n\n{name} melakukan:\n{action}\n\nLanjutkan secara natural."

def prompt_interaksi(memory, hist, char, text):
    return f"{memory}\n\nKonteks:\n{hist}\n\nTampilkan reaksi {char} terhadap:\n{text}"

# ========= VALIDASI =========
def validate(text):
    return text and len(text.split()) > 8

# ========= AI =========
async def gen_gemini(prompt, model):
    try:
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None,
            lambda: model.generate_content(SYSTEM_PROMPT + "\n" + prompt)
        )
        return res.text.strip() if res and hasattr(res, "text") else None
    except:
        return None

async def gen_qwen(prompt):
    try:
        res = client_ai.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ]
        )
        return res.choices[0].message.content.strip()
    except:
        return None

async def smart_generate(prompt, force=None):
    if force == "qwen":
        out = await gen_qwen(prompt)
        if validate(out): return out, "qwen"

    out = await gen_gemini(prompt, gemini_main)
    if validate(out): return out, "gemini"

    out = await gen_gemini(prompt, gemini_lite)
    if validate(out): return out, "gemini-lite"

    out = await gen_qwen(prompt)
    if validate(out): return out, "qwen"

    return None, None

# ========= UI =========
def error_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Coba Lagi", callback_data="retry")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo")],
        [InlineKeyboardButton("🔄 Ganti Model", callback_data="switch_model")]
    ])

async def get_menu(uid):
    state = ensure_memory(await users.find_one({"_id": uid}) or {})

    kb = []
    if state.get("name"):
        kb.append([InlineKeyboardButton(f"👤 {state['name']}", callback_data="main_char")])

    kb += [
        [InlineKeyboardButton("📖 Narator", callback_data="narator"),
         InlineKeyboardButton("➡️ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("➕ Karakter", callback_data="tambah"),
         InlineKeyboardButton("🔄 Reset", callback_data="reset")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo")]
    ]

    for i, c in enumerate(state.get("chars", [])):
        kb.append([InlineKeyboardButton(f"💬 {c['name']}", callback_data=f"char_{i}")])

    return InlineKeyboardMarkup(kb)

# ========= HANDLER =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await users.update_one({"_id": update.effective_user.id},
                           {"$set": {"step": "input_name"}}, upsert=True)
    await update.message.reply_text("Nama tokoh utama?")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    state = ensure_memory(await users.find_one({"_id": uid}) or {})
    step = state.get("step")

    if step == "input_name":
        await users.update_one({"_id": uid}, {"$set": {"name": text, "step": None}})
        await update.message.reply_text("Nama disimpan!", reply_markup=await get_menu(uid))
        return

    memory = build_memory(state)
    hist = get_context(state)

    if step == "narator":
        prompt = prompt_narator(memory, text)
    elif step == "main_action":
        prompt = prompt_main(memory, hist, state["name"], text)
    elif step == "char_react":
        char = state["chars"][state["selected_char"]]["name"]
        prompt = prompt_interaksi(memory, hist, char, text)
    else:
        return

    await users.update_one({"_id": uid}, {"$set": {"last_prompt": prompt}})

    out, model = await smart_generate(prompt, state.get("force_model"))

    if not out:
        await update.message.reply_text("⚠️ AI gagal / limit.", reply_markup=error_menu())
        return

    history = state.get("history", [])
    history.append(out)
    await users.update_one({"_id": uid}, {"$set": {"history": history, "step": None}})

    await update.message.reply_text(f"🔹 {model}\n\n{out}", reply_markup=await get_menu(uid))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data

    try:
        await q.answer()
    except:
        pass

    state = ensure_memory(await users.find_one({"_id": uid}) or {})

    if data == "main_char":
        await users.update_one({"_id": uid}, {"$set": {"step": "main_action"}})
        await q.message.reply_text("Apa yang dilakukan tokoh utama?")
    
    elif data == "retry":
        prompt = state.get("last_prompt")
        out, model = await smart_generate(prompt, state.get("force_model"))
        if not out:
            await q.message.reply_text("❌ Masih gagal", reply_markup=error_menu())
            return

        history = state.get("history", [])
        history.append(out)
        await users.update_one({"_id": uid}, {"$set": {"history": history}})
        await q.message.reply_text(f"🔹 {model}\n\n{out}", reply_markup=await get_menu(uid))

    elif data == "undo":
        history = state.get("history", [])
        if len(history) > 1:
            history = history[:-1]
            await users.update_one({"_id": uid}, {"$set": {"history": history}})
            await q.message.reply_text(history[-1], reply_markup=await get_menu(uid))
        else:
            await q.message.reply_text("Tidak bisa undo.")

    elif data == "switch_model":
        new_model = "qwen" if state.get("force_model") != "qwen" else None
        await users.update_one({"_id": uid}, {"$set": {"force_model": new_model}})
        await q.message.reply_text("Model diganti. Tekan Coba Lagi.")

    elif data == "narator":
        await users.update_one({"_id": uid}, {"$set": {"step": "narator"}})
        await q.message.reply_text("Masukkan cerita:")

    elif data == "lanjut":
        memory = build_memory(state)
        hist = get_context(state)
        prompt = prompt_lanjut(memory, hist)

        out, model = await smart_generate(prompt)
        if out:
            history = state.get("history", [])
            history.append(out)
            await users.update_one({"_id": uid}, {"$set": {"history": history}})
            await q.message.reply_text(f"🔹 {model}\n\n{out}", reply_markup=await get_menu(uid))

    elif data.startswith("char_"):
        idx = int(data.split("_")[1])
        await users.update_one({"_id": uid}, {"$set": {"step": "char_react", "selected_char": idx}})
        await q.message.reply_text(f"Reaksi {state['chars'][idx]['name']}:")

    elif data == "tambah":
        await users.update_one({"_id": uid}, {"$set": {"step": "wait_char"}})
        await q.message.reply_text("Nama karakter:")

    elif data == "reset":
        await users.delete_one({"_id": uid})
        await q.message.reply_text("Reset. /start lagi")

# ========= RUN =========
app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

print("🚀 BOT RUNNING...")
app.run_polling()

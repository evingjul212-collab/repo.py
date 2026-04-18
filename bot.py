import os
import asyncio
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

# OpenRouter (Qwen & Llama)
client_ai = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

MODELS = {
    "qwen": "qwen/qwen2.5-7b-instruct",
    "qwen_big": "qwen/qwen2.5-14b-instruct",
    "llama": "meta-llama/llama-3-8b-instruct"
}

MODEL_ORDER = ["qwen_big", "qwen", "gemini", "llama"]

# Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# Mongo
client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

# ================= MEMORY =================

def ensure_memory(state):
    defaults = {
        "time": "pagi",
        "location": "rumah",
        "scene": "awal cerita",
        "outfit": "pakaian santai",
        "history": ["Cerita dimulai."],
        "chars": [],
        "model": "qwen"
    }
    for k, v in defaults.items():
        if k not in state:
            state[k] = v
    return state

def build_memory(state):
    return (
        f"Waktu: {state['time']}\n"
        f"Lokasi: {state['location']}\n"
        f"Scene: {state['scene']}\n"
        f"Outfit: {state['outfit']}\n"
    )

def get_context(state):
    return "\n".join(state.get("history", [])[-3:])

# ================= PROMPT =================

SYSTEM_PROMPT = """
Kamu penulis romcom realistis.

WAJIB:
- 100% Bahasa Indonesia
- Maksimal 2 paragraf
- Minimal 60% dialog
- Jangan asumsi tanpa konteks
- Jangan absurd / random
- Lanjutkan cerita secara logis
"""

def build_prompt(memory, hist, action):
    return f"""
{memory}

KONTEKS:
{hist}

AKSI:
{action}
"""

# ================= VALIDATION =================

def validate_output(text):
    t = text.lower()

    if len(text.split()) < 20:
        return False

    if any(w in t for w in [" i ", " you ", " the "]):
        return False

    if "mengandung" in t and "hamil" in t:
        return False

    return True

# ================= AI =================

async def generate_qwen(prompt, model):
    res = client_ai.chat.completions.create(
        model=MODELS[model],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=700
    )
    return res.choices[0].message.content.strip()

async def generate_gemini(prompt):
    res = gemini_model.generate_content(SYSTEM_PROMPT + "\n" + prompt)
    return res.text if res.text else None

async def smart_generate(prompt, state):
    for model_key in MODEL_ORDER:
        for _ in range(2):
            try:
                if model_key == "gemini":
                    out = await generate_gemini(prompt)
                else:
                    out = await generate_qwen(prompt, model_key)

                if out and validate_output(out):
                    return out, f"🔹 {model_key}"

            except:
                continue

    return None, "❌ Semua model gagal"

# ================= MENU =================

async def get_menu(uid):
    state = ensure_memory(await users.find_one({"_id": uid}) or {})

    keyboard = [
        [InlineKeyboardButton(f"🧠 Model: {state['model']}", callback_data="ganti_model")],
        [InlineKeyboardButton("📖 Narator", callback_data='narator'),
         InlineKeyboardButton("➡️ Lanjut", callback_data='lanjut')],
        [InlineKeyboardButton("➕ Karakter", callback_data='tambah_karakter'),
         InlineKeyboardButton("🔄 Reset", callback_data='reset')],
        [InlineKeyboardButton("↩️ Undo", callback_data='undo')]
    ]

    if state.get("name"):
        keyboard.insert(1, [
            InlineKeyboardButton(f"👤 {state['name']}", callback_data='aksi_user')
        ])

    for i, c in enumerate(state.get("chars", [])):
        keyboard.append([
            InlineKeyboardButton(f"💬 {c['name']}", callback_data=f"c_{i}")
        ])

    return InlineKeyboardMarkup(keyboard)

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await users.update_one(
        {"_id": update.effective_user.id},
        {"$set": {"step": "input_name"}},
        upsert=True
    )
    await update.message.reply_text("Masukkan nama tokoh:")

# ================= MESSAGE =================

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    state = ensure_memory(await users.find_one({"_id": uid}) or {})
    step = state.get("step")

    if step == "input_name":
        await users.update_one({"_id": uid}, {"$set": {
            "name": text,
            "step": None
        }})
        await update.message.reply_text("Nama disimpan!", reply_markup=await get_menu(uid))
        return

    if step == "wait_char_name":
        await users.update_one({"_id": uid}, {"$set": {"temp_char": text, "step": "wait_char_desc"}})
        await update.message.reply_text("Deskripsi karakter:")
        return

    if step == "wait_char_desc":
        name = state.get("temp_char")
        await users.update_one({"_id": uid}, {
            "$push": {"chars": {"name": name, "desc": text}},
            "$set": {"step": None}
        })
        await update.message.reply_text("Karakter ditambah!", reply_markup=await get_menu(uid))
        return

    if step in ["input_aksi_user", "input_narator", "input_char_action"]:
        memory = build_memory(state)
        hist = get_context(state)

        if step == "input_char_action":
            char = state["chars"][state["selected_char"]]
            action = f"{state['name']} ke {char['name']}: {text}"
        else:
            action = text

        prompt = build_prompt(memory, hist, action)
        out, model_used = await smart_generate(prompt, state)

        if not out:
            keyboard = [[InlineKeyboardButton("🔄 Ganti Model", callback_data="ganti_model")]]
            await update.message.reply_text(model_used, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        history = state.get("history", [])
        history.append(out)

        await users.update_one({"_id": uid}, {"$set": {
            "history": history,
            "step": None,
            "selected_char": None
        }})

        await update.message.reply_text(f"{model_used}\n\n{out}", reply_markup=await get_menu(uid))

# ================= BUTTON =================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    await query.answer()

    state = ensure_memory(await users.find_one({"_id": uid}) or {})

    if data == "ganti_model":
        keyboard = [
            [InlineKeyboardButton("Qwen Cepat", callback_data="set_qwen")],
            [InlineKeyboardButton("Qwen Pintar", callback_data="set_qwen_big")],
            [InlineKeyboardButton("Gemini", callback_data="set_gemini")],
            [InlineKeyboardButton("Llama", callback_data="set_llama")]
        ]
        await query.message.reply_text("Pilih model:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("set_"):
        model = data.replace("set_", "")
        await users.update_one({"_id": uid}, {"$set": {"model": model}})
        await query.message.reply_text(f"✅ Model: {model}")

    elif data == "narator":
        await users.update_one({"_id": uid}, {"$set": {"step": "input_narator"}})
        await query.message.reply_text("Input cerita:")

    elif data == "aksi_user":
        await users.update_one({"_id": uid}, {"$set": {"step": "input_aksi_user"}})
        await query.message.reply_text("Aksi:")

    elif data.startswith("c_"):
        idx = int(data.split("_")[1])
        await users.update_one({"_id": uid}, {"$set": {"step": "input_char_action", "selected_char": idx}})
        await query.message.reply_text("Aksi ke karakter:")

    elif data == "lanjut":
        memory = build_memory(state)
        hist = get_context(state)

        out, model_used = await smart_generate(build_prompt(memory, hist, "lanjutkan"), state)

        if not out:
            keyboard = [[InlineKeyboardButton("🔄 Ganti Model", callback_data="ganti_model")]]
            await query.message.reply_text(model_used, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        history = state.get("history", [])
        history.append(out)

        await users.update_one({"_id": uid}, {"$set": {"history": history}})

        await query.message.reply_text(f"{model_used}\n\n{out}", reply_markup=await get_menu(uid))

    elif data == "undo":
        history = state.get("history", [])
        if len(history) > 1:
            history = history[:-1]
            await users.update_one({"_id": uid}, {"$set": {"history": history}})
            await query.message.reply_text(history[-1], reply_markup=await get_menu(uid))
        else:
            await query.message.reply_text("Tidak bisa undo.")

    elif data == "tambah_karakter":
        await users.update_one({"_id": uid}, {"$set": {"step": "wait_char_name"}})
        await query.message.reply_text("Nama karakter:")

    elif data == "reset":
        await users.delete_one({"_id": uid})
        await query.message.reply_text("Reset. /start lagi")

# ================= RUN =================

defaults = Defaults(parse_mode=None)

app = Application.builder().token(BOT_TOKEN).defaults(defaults).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

print("🚀 BOT RUNNING...")
app.run_polling()

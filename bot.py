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

warnings.filterwarnings("ignore")

# ================= CONFIG =================
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")

client_ai = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

MODELS = {
    "qwen": "qwen/qwen2.5-7b-instruct",
    "qwen_big": "qwen/qwen2.5-14b-instruct",
    "llama": "meta-llama/llama-3-8b-instruct"
}

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

# ================= UTIL =================

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

def build_prompt(memory, hist, action):
    return f"""
{memory}

LANJUTKAN CERITA ROMCOM.

RULE:
- Maksimal 2 paragraf
- Minimal 60% dialog
- Gunakan tanda kutip
- Jangan ubah waktu/lokasi/outfit
- Lanjutkan natural

KONTEKS:
{hist}

AKSI:
{action}
"""

# ================= AI =================

async def generate_ai(prompt, state):
    model_key = state.get("model", "qwen")

    try:
        res = client_ai.chat.completions.create(
            model=MODELS[model_key],
            messages=[
                {"role": "system", "content": "Penulis romcom dialog natural."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=700,
            temperature=0.9
        )
        return res.choices[0].message.content.strip(), None

    except Exception:
        fallback = "llama" if model_key != "llama" else "qwen"

        try:
            res = client_ai.chat.completions.create(
                model=MODELS[fallback],
                messages=[
                    {"role": "system", "content": "Penulis romcom dialog natural."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=700,
                temperature=0.9
            )
            return res.choices[0].message.content.strip(), f"⚠️ Model diganti ke {fallback}"

        except Exception:
            return None, "❌ Semua model error"

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
        out, err = await generate_ai(prompt, state)

        if not out:
            keyboard = [[InlineKeyboardButton("🔄 Ganti Model", callback_data="ganti_model")]]
            await update.message.reply_text(err, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        history = state.get("history", [])
        history.append(out)

        await users.update_one({"_id": uid}, {"$set": {
            "history": history,
            "step": None,
            "selected_char": None
        }})

        msg_text = (err + "\n\n" if err else "") + out

        await update.message.reply_text(msg_text, reply_markup=await get_menu(uid))

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

        out, err = await generate_ai(build_prompt(memory, hist, "lanjutkan"), state)

        if not out:
            keyboard = [[InlineKeyboardButton("🔄 Ganti Model", callback_data="ganti_model")]]
            await query.message.reply_text(err, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        history = state.get("history", [])
        history.append(out)

        await users.update_one({"_id": uid}, {"$set": {"history": history}})

        await query.message.reply_text((err + "\n\n" if err else "") + out, reply_markup=await get_menu(uid))

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

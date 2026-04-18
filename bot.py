import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
import google.generativeai as genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# MODEL PALING AMAN (NO DRAMA)
MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash"
]

client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.game_db
users = db.user_states

# ========= STATE SAFE =========
def fix_state(s):
    if not s:
        s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name"),
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "last_prompt": s.get("last_prompt"),
        "temp_char": s.get("temp_char"),
        "selected": s.get("selected"),
        "force_model": s.get("force_model"),
        "model": s.get("model")
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    s = fix_state(s)
    await users.update_one({"_id": uid}, {"$set": s}, upsert=True)
    return s

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI =========
async def generate(prompt, uid):
    state = await get_state(uid)

    model_list = MODELS.copy()
    if state.get("force_model"):
        model_list.insert(0, state["force_model"])

    for m in model_list:
        try:
            model = genai.GenerativeModel(m)

            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None,
                lambda: model.generate_content(prompt)
            )

            await save(uid, {"model": m})
            return res.text.strip()

        except Exception as e:
            print(f"MODEL ERROR {m}: {e}")
            continue

    return None

# ========= MENU =========
async def menu(uid):
    s = await get_state(uid)

    kb = []

    if s["name"]:
        kb.append([InlineKeyboardButton(f"👤 {s['name']}", callback_data="main")])

    kb.append([
        InlineKeyboardButton("📖 Narator", callback_data="narator"),
        InlineKeyboardButton("➡️ Lanjut", callback_data="lanjut")
    ])

    kb.append([
        InlineKeyboardButton("➕ Karakter", callback_data="add_char"),
        InlineKeyboardButton("↩️ Undo", callback_data="undo")
    ])

    for i, c in enumerate(s["chars"]):
        kb.append([
            InlineKeyboardButton(f"💬 {c['name']}", callback_data=f"char_{i}")
        ])

    return InlineKeyboardMarkup(kb)

def err_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Retry", callback_data="retry")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo")]
    ])

# ========= START =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {
        "name": None,
        "step": "set_name",
        "history": [],
        "chars": []
    })
    await update.message.reply_text("Masukkan nama tokoh utama:")

# ========= MESSAGE =========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    s = await get_state(uid)
    step = s["step"]

    if step == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text("Nama disimpan!", reply_markup=await menu(uid))
        return

    if step == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text("Deskripsi karakter:")
        return

    if step == "char_desc":
        chars = s["chars"]
        chars.append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": chars, "step": None, "temp_char": None})
        await update.message.reply_text("Karakter ditambahkan!", reply_markup=await menu(uid))
        return

    if step == "main_action":
        prompt = f"""
Lanjutkan adegan romcom.
Aksi:
{text}

JANGAN jelaskan ulang.
Langsung adegan.
2 paragraf, banyak dialog.
"""

    elif step == "narator":
        prompt = f"""
Ubah ini jadi adegan romcom:

{text}

Langsung adegan.
2 paragraf, dialog natural.
"""

    elif step == "char_action":
        if s["selected"] is None or s["selected"] >= len(s["chars"]):
            await update.message.reply_text("Karakter error.")
            return

        c = s["chars"][s["selected"]]

        prompt = f"""
Adegan antara {s['name']} dan {c['name']}.

Aksi:
{text}

JANGAN jelaskan.
Langsung dialog.
2 paragraf.
"""
    else:
        return

    await save(uid, {"last_prompt": prompt})

    out = await generate(prompt, uid)

    if not out:
        await update.message.reply_text("AI error.", reply_markup=err_menu())
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

    try:
        await q.answer()
    except:
        pass

    s = await get_state(uid)

    if data == "main":
        await save(uid, {"step": "main_action"})
        await q.message.reply_text(f"{s['name']} melakukan apa?")

    elif data == "narator":
        await save(uid, {"step": "narator"})
        await q.message.reply_text("Ceritanya mau dibawa kemana?")

    elif data == "lanjut":
        if not s["history"]:
            await q.message.reply_text("Belum ada cerita.")
            return

        prompt = f"Lanjutkan adegan ini:\n{s['history'][-1]}"
        out = await generate(prompt, uid)

        if out:
            hist = s["history"]
            hist.append(out)
            await save(uid, {"history": hist})
            await q.message.reply_text(out, reply_markup=await menu(uid))
        else:
            await q.message.reply_text("AI error.", reply_markup=err_menu())

    elif data == "add_char":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Nama karakter baru?")

    elif data.startswith("char_"):
        idx = int(data.split("_")[1])

        if idx >= len(s["chars"]):
            await q.message.reply_text("Karakter tidak ada.")
            return

        c = s["chars"][idx]
        await save(uid, {"step": "char_action", "selected": idx})
        await q.message.reply_text(f"{c['name']} bereaksi bagaimana?")

    elif data == "undo":
        hist = s["history"]

        if len(hist) > 1:
            hist.pop()
            await save(uid, {"history": hist})
            await q.message.reply_text(hist[-1], reply_markup=await menu(uid))
        else:
            await q.message.reply_text("Tidak bisa undo.")

    elif data == "retry":
        prompt = s.get("last_prompt")

        if not prompt:
            await q.message.reply_text("Tidak ada data.")
            return

        out = await generate(prompt, uid)

        if out:
            hist = s["history"]
            hist.append(out)
            await save(uid, {"history": hist})
            await q.message.reply_text(out, reply_markup=await menu(uid))
        else:
            await q.message.reply_text("Masih error.")

# ========= RUN =========
app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

print("BOT RUNNING...")
app.run_polling(drop_pending_updates=True)

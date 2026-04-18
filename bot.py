import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
import google.generativeai as genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash"
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

# ========= SYSTEM CONTEXT (HIDDEN) =========
def build_system(s):
    st = s["story"]
    return f"""
Kamu adalah penulis cerita romcom natural.

ATURAN KERAS:
- Jangan tampilkan setting, waktu, atau konteks ini
- Jangan menulis ulang instruksi
- Jangan menambahkan elemen baru di luar aksi user
- Jangan mengubah waktu (tetap {st['time']})
- Fokus pada aksi karakter, bukan menjelaskan ulang
- Gunakan dialog natural, ringan, tidak kaku
- Maksimal 2 paragraf

KONTEKS:
Setting: {st['setting']}
Waktu: {st['time']}
Tokoh utama: {s['name']}
Deskripsi: {st['main_desc']}
Plot: {st['plot']}
Hubungan: {st['relationships']}
Gaya: {st['rules']}
"""

# ========= AI =========
async def generate(prompt, uid, system):
    for m in MODELS:
        try:
            model = genai.GenerativeModel(m)
            loop = asyncio.get_event_loop()

            res = await loop.run_in_executor(
                None,
                lambda: model.generate_content(system + "\n\n" + prompt)
            )

            return res.text.strip()

        except Exception as e:
            print("MODEL ERROR:", m, e)
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
        InlineKeyboardButton("⚙️ Edit Dunia", callback_data="edit_story")
    ])

    kb.append([
        InlineKeyboardButton("↩️ Undo", callback_data="undo"),
        InlineKeyboardButton("🔄 Regenerate", callback_data="regen")
    ])

    for i, c in enumerate(s["chars"]):
        kb.append([InlineKeyboardButton(f"💬 {c['name']}", callback_data=f"char_{i}")])

    return InlineKeyboardMarkup(kb)

# ========= START =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {
        "name": None,
        "step": "set_name",
        "history": [],
        "chars": [],
        "story": {
            "setting": "Rumah",
            "time": "Sore",
            "main_desc": "",
            "plot": "",
            "relationships": "",
            "rules": "Romcom natural"
        }
    })
    await update.message.reply_text("Masukkan nama tokoh utama:")

# ========= MESSAGE =========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)
    step = s["step"]

    # ===== SET NAME =====
    if step == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text("Nama disimpan!", reply_markup=await menu(uid))
        return

    # ===== ADD CHAR =====
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

    # ===== EDIT STORY =====
    if step and step.startswith("edit_"):
        key = step.replace("edit_", "")
        s["story"][key] = text
        await save(uid, {"story": s["story"], "step": None})
        await update.message.reply_text("Story diperbarui!", reply_markup=await menu(uid))
        return

    # ===== GENERATE =====
    system = build_system(s)

    if step == "main_action":
        prompt = f"""
Fokus: {s['name']}

Aksi:
{text}

{s['name']} adalah pusat aksi
Karakter lain hanya merespon
"""

    elif step == "char_action":
        c = s["chars"][s["selected"]]
        prompt = f"""
Fokus: {c['name']}

Aksi:
{text}

{c['name']} yang memulai aksi
{s['name']} hanya bereaksi
"""

    elif step == "narator":
        prompt = f"""
Ubah menjadi adegan dari:
{text}
"""

    else:
        return

    await save(uid, {"last_prompt": prompt})

    out = await generate(prompt, uid, system)

    if not out:
        await update.message.reply_text("AI error.")
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
        await q.message.reply_text("Masukkan ide cerita:")

    elif data == "lanjut":
        if not s["history"]:
            await q.message.reply_text("Belum ada cerita.")
            return

        system = build_system(s)
        prompt = f"Lanjutkan cerita:\n{s['history'][-1]}"
        await save(uid, {"last_prompt": prompt})

        out = await generate(prompt, uid, system)

        if out:
            hist = s["history"]
            hist.append(out)
            await save(uid, {"history": hist})
            await q.message.reply_text(out, reply_markup=await menu(uid))

    elif data == "regen":
        system = build_system(s)
        prompt = s.get("last_prompt")

        if not prompt:
            await q.message.reply_text("Tidak ada yang bisa diulang.")
            return

        prompt = prompt + "\nTulis ulang dengan variasi berbeda."

        out = await generate(prompt, uid, system)

        if not out:
            await q.message.reply_text("AI error.")
            return

        hist = s["history"]

        if hist:
            hist[-1] = out
        else:
            hist.append(out)

        await save(uid, {"history": hist})
        await q.message.reply_text(out, reply_markup=await menu(uid))

    elif data == "undo":
        hist = s["history"]
        if len(hist) > 1:
            hist.pop()
            await save(uid, {"history": hist})
            await q.message.reply_text(hist[-1], reply_markup=await menu(uid))
        else:
            await q.message.reply_text("Tidak bisa undo.")

    elif data == "add_char":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Nama karakter:")

    elif data.startswith("char_"):
        idx = int(data.split("_")[1])
        await save(uid, {"step": "char_action", "selected": idx})
        await q.message.reply_text(f"{s['chars'][idx]['name']} bereaksi bagaimana?")

    elif data == "edit_story":
        kb = [
            [InlineKeyboardButton("Setting", callback_data="edit_setting")],
            [InlineKeyboardButton("Waktu", callback_data="edit_time")],
            [InlineKeyboardButton("Deskripsi", callback_data="edit_main_desc")],
            [InlineKeyboardButton("Plot", callback_data="edit_plot")],
            [InlineKeyboardButton("Hubungan", callback_data="edit_relationships")]
        ]
        await q.message.reply_text("Edit bagian:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("edit_"):
        await save(uid, {"step": data})
        await q.message.reply_text("Masukkan nilai baru:")

# ========= RUN =========
app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

print("BOT RUNNING...")
app.run_polling(drop_pending_updates=True)

import os
import asyncio
import random
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from bson import ObjectId

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

MODELS = {
    "FAST": "gemini-2.5-flash",
    "CREATIVE": "gemini-3.1-flash-lite-preview"
}

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.archives

# ========= STATE =========
async def get_state(uid):
    s = await users.find_one({"_id": uid}) or {}
    return {
        "_id": uid,
        "name": s.get("name", "Bayu"),
        "desc_utama": s.get("desc_utama", "Tokoh utama"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "step": s.get("step"),
        "edit_target": s.get("edit_target")
    }

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI =========
async def generate(prompt, system, history, mode="FAST"):
    context = "\n---\n".join(history[-10:]) if history else "Mulai."
    full = f"{system}\n\n{context}\n\n{prompt}"
    model = MODELS.get(mode, MODELS["FAST"])

    try:
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(
            None,
            lambda: client_ai.models.generate_content(
                model=model,
                contents=full
            )
        )
        return r.text.strip()
    except:
        return None

# ========= MENU =========
async def menu_utama():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Karakter", callback_data="menu_char")],
        [InlineKeyboardButton("📂 Muat", callback_data="load_list")],
        [InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut_menu")],
        [InlineKeyboardButton("💾 Simpan", callback_data="save_manual")]
    ])

# ========= START =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await save(uid, {"history": [], "chars": [], "step": None})
    await update.message.reply_text("🎮 Mulai RPG v.1.1", reply_markup=await menu_utama())

# ========= MESSAGE =========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    # ===== EDIT =====
    if s["step"] == "edit_name":
        if s["edit_target"] == "main":
            await save(uid, {"name": text, "step": "edit_desc"})
            await update.message.reply_text("Deskripsi tokoh utama?")
        else:
            idx = s["edit_target"]
            chars = s["chars"]
            chars[idx]["name"] = text
            await save(uid, {"chars": chars, "step": "edit_desc"})
            await update.message.reply_text("Deskripsi NPC?")
        return

    if s["step"] == "edit_desc":
        if s["edit_target"] == "main":
            await save(uid, {"desc_utama": text, "step": None})
        else:
            idx = s["edit_target"]
            chars = s["chars"]
            chars[idx]["desc"] = text
            await save(uid, {"chars": chars, "step": None})

        await update.message.reply_text("✅ Update selesai", reply_markup=await menu_utama())
        return

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    # ===== MENU KARAKTER =====
    if q.data == "menu_char":
        kb = [
            [InlineKeyboardButton("🧍 Tokoh Utama", callback_data="main_char")],
            [InlineKeyboardButton("👥 NPC", callback_data="npc_list")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")]
        ]
        await q.edit_message_text("Menu Karakter", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "main_char":
        kb = [
            [InlineKeyboardButton("✏️ Edit", callback_data="edit_main")],
            [InlineKeyboardButton("🎮 Gunakan", callback_data="use_main")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_char")]
        ]
        await q.edit_message_text("Tokoh Utama", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "edit_main":
        await save(uid, {"step": "edit_name", "edit_target": "main"})
        await q.message.reply_text("Nama baru tokoh utama?")

    elif q.data == "npc_list":
        kb = [[InlineKeyboardButton(c["name"], callback_data=f"npc_{i}")] for i,c in enumerate(s["chars"])]
        await q.edit_message_text("NPC", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("npc_"):
        idx = int(q.data.split("_")[1])
        kb = [
            [InlineKeyboardButton("✏️ Edit", callback_data=f"edit_npc_{idx}")],
            [InlineKeyboardButton("🎮 Gunakan", callback_data=f"use_npc_{idx}")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="npc_list")]
        ]
        await q.edit_message_text(s["chars"][idx]["name"], reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("edit_npc_"):
        idx = int(q.data.split("_")[2])
        await save(uid, {"step": "edit_name", "edit_target": idx})
        await q.message.reply_text("Nama baru NPC?")

    # ===== LANJUT MENU (UPGRADE) =====
    elif q.data == "lanjut_menu":
        kb = [
            [InlineKeyboardButton("🎬 Lanjut Normal", callback_data="lanjut")],
            [InlineKeyboardButton("🔥 Tambah Konflik", callback_data="lanjut_konflik")],
            [InlineKeyboardButton("💬 Fokus Dialog", callback_data="lanjut_dialog")],
            [InlineKeyboardButton("⚡ Twist Tak Terduga", callback_data="lanjut_twist")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")]
        ]
        await q.edit_message_text("Pilih gaya lanjut:", reply_markup=InlineKeyboardMarkup(kb))

    # ===== LANJUT ENGINE =====
    elif q.data.startswith("lanjut"):
        if not s["history"]:
            await q.message.reply_text("Belum ada cerita.")
            return

        mode_map = {
            "lanjut": "lanjut normal",
            "lanjut_konflik": "buat konflik besar",
            "lanjut_dialog": "fokus dialog antar karakter",
            "lanjut_twist": "beri twist tak terduga"
        }

        style = mode_map.get(q.data, "lanjut")

        names = [s["name"]] + [c["name"] for c in s["chars"]]

        prompt = f"""
Lanjutkan cerita.

Gaya: {style}

Karakter:
{', '.join(names)}

Gunakan konteks sebelumnya.
"""

        out = await generate(prompt, "Narator", s["history"], mode=random.choice(["FAST","CREATIVE"]))

        if out:
            s["history"].append(out)
            await save(uid, {"history": s["history"]})
            await q.message.reply_text(out, reply_markup=await menu_utama())

    elif q.data == "main_menu":
        await q.edit_message_text("Menu", reply_markup=await menu_utama())

# ========= RUN =========
if __name__ == "__main__":
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=5)
    except:
        pass

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

    app.run_polling()

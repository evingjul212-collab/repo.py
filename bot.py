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
    "FAST": "gemini-2.0-flash", # Sesuaikan dengan versi model yang tersedia
    "CREATIVE": "gemini-2.0-pro-exp-02-05" 
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
        "name": s.get("name", "Pemain"),
        "desc_utama": s.get("desc_utama", "Tokoh utama biasa"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "step": s.get("step"),
        "temp_char": s.get("temp_char")
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
        return r.text.strip(), model
    except Exception as e:
        print(f"AI Error: {e}")
        return None, None

def build_system(name, desc, role="CHAR"):
    base = f"""
Kamu adalah {name}.
Deskripsi: {desc}

Aturan:
- Dialog dominan
- Karakter hidup & emosional
- Jangan kaku
- Maks 3 paragraf
"""
    if role == "NARATOR":
        base += "\nFokus narasi & konflik."
    return base

# ========= MENU =========
async def menu_utama(uid=None): # Ditambah default parameter agar tidak error
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Karakter", callback_data="menu_char")],
        [InlineKeyboardButton("📂 Muat", callback_data="load_list")],
        [InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("💾 Simpan", callback_data="save_manual")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator")]
    ])

# ========= START =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await save(uid, {"history": [], "chars": [], "step": None, "name": update.effective_user.first_name})
    await update.message.reply_text("🎮 RPG AI Siap v1.2!", reply_markup=await menu_utama())

# ========= MESSAGE =========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    # ===== TAMBAH NPC =====
    if s["step"] == "char_name":
        await save(uid, {"temp_char": {"name": text}, "step": "char_desc"})
        await update.message.reply_text("Deskripsi NPC?")
        return

    if s["step"] == "char_desc":
        temp = s["temp_char"]
        temp["desc"] = text
        await save(uid, {"temp_char": temp, "step": "char_intro"})
        await update.message.reply_text("Dialog awal NPC?")
        return

    if s["step"] == "char_intro":
        temp = s["temp_char"]
        temp["intro"] = text
        chars = s["chars"]
        chars.append(temp)
        await save(uid, {"chars": chars, "temp_char": None, "step": None})
        await update.message.reply_text("✅ NPC ditambahkan!", reply_markup=await menu_utama())
        return

    # ===== SAVE =====
    if s["step"] == "save_name":
        await archives.insert_one({
            "user_id": uid,
            "save_name": text,
            "history": s["history"],
            "chars": s["chars"],
            "date": datetime.now()
        })
        await save(uid, {"step": None})
        await update.message.reply_text("💾 Tersimpan!", reply_markup=await menu_utama())
        return

    # ===== AKSI KARAKTER / NARATOR =====
    if s["step"] in ["action", "narator_input"]:
        is_nar = s["step"] == "narator_input"
        idx = s.get("selected", -1)

        tag = "NARASI" if is_nar else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        desc = "Dunia RPG" if is_nar else (s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"])
        role = "NARATOR" if is_nar else "CHAR"

        sys = build_system(tag, desc, role)
        prompt = f"KEJADIAN: {text}" if is_nar else f"AKSI: {text}"

        out, _ = await generate(prompt, sys, s["history"], mode="FAST")

        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(out, reply_markup=await menu_utama())
        else:
            await update.message.reply_text("⚠️ AI sibuk.", reply_markup=await menu_utama())
        return

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "menu_char":
        kb = [
            [InlineKeyboardButton("🧍 Tokoh Utama", callback_data="use_main")],
            [InlineKeyboardButton("👥 NPC", callback_data="npc_list")],
            [InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")]
        ]
        await q.edit_message_text("Menu Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "use_main":
        await save(uid, {"selected": -1, "step": "action"})
        await q.message.reply_text("Ketik aksi kamu:")

    elif q.data == "add_npc":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Nama NPC baru?")

    elif q.data == "npc_list":
        if not s["chars"]:
            await q.edit_message_text("Belum ada NPC.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="menu_char")]]))
            return
        kb = []
        for i, c in enumerate(s["chars"]):
            kb.append([InlineKeyboardButton(c["name"], callback_data=f"npc_{i}")])
        kb.append([InlineKeyboardButton("⬅️ Kembali", callback_data="menu_char")])
        await q.edit_message_text("Daftar NPC:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("npc_"):
        idx = int(q.data.split("_")[1])
        npc = s["chars"][idx]
        kb = [
            [InlineKeyboardButton("🎮 Gunakan", callback_data=f"use_npc_{idx}")],
            [InlineKeyboardButton("📖 Cerita Baru", callback_data=f"story_npc_{idx}")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="npc_list")]
        ]
        await q.edit_message_text(f"NPC: {npc['name']}\n{npc['desc']}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("use_npc_"):
        idx = int(q.data.split("_")[2])
        await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"Ketik aksi sebagai {s['chars'][idx]['name']}:")

    elif q.data.startswith("story_npc_"):
        idx = int(q.data.split("_")[2])
        npc = s["chars"][idx]
        sys = build_system("Narator", npc["desc"], "NARATOR")
        prompt = f"Mulai cerita. Dialog awal: {npc.get('intro', 'Halo.')}"
        
        out, _ = await generate(prompt, sys, [], mode="CREATIVE")
        if out:
            await save(uid, {"history": [out], "selected": idx})
            await q.message.reply_text(out, reply_markup=await menu_utama())

    elif q.data == "lanjut":
        if not s["history"]:
            await q.message.reply_text("Mulai cerita dulu!")
            return
        sys = build_system("Narator", "Dunia", "NARATOR")
        prompt = "Lanjutkan cerita dengan kejadian tak terduga."
        out, _ = await generate(prompt, sys, s["history"], mode="CREATIVE")
        if out:
            s["history"].append(f"[NARASI]: {out}")
            await save(uid, {"history": s["history"]})
            await q.message.reply_text(out, reply_markup=await menu_utama())

    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("date", -1).to_list(10)
        if not items:
            await q.message.reply_text("Belum ada simpanan.")
            return
        kb = [[InlineKeyboardButton(f"{i['save_name']}", callback_data=f"load:{i['_id']}")] for i in items]
        kb.append([InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")])
        await q.edit_message_text("Pilih Save Slot:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load:"):
        sid = q.data.split(":")[1]
        data = await archives.find_one({"_id": ObjectId(sid)})
        if data:
            await save(uid, {"history": data["history"], "chars": data["chars"], "selected": -1, "step": None})
            await q.message.reply_text("✅ Data dimuat!", reply_markup=await menu_utama())

    elif q.data == "save_manual":
        await save(uid, {"step": "save_name"})
        await q.message.reply_text("Beri nama untuk save ini:")

    elif q.data == "main_menu":
        await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama())

    elif q.data == "step_narator":
        await save(uid, {"step": "narator_input"})
        await q.message.reply_text("🎭 Kejadian apa yang ingin kamu masukkan ke dalam cerita?")

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    
    print("Bot Berjalan...")
    app.run_polling()

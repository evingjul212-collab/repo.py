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

# ========= [1] CONFIG =========
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

# ========= [2] STATE =========
async def get_state(uid):
    s = await users.find_one({"_id": uid}) or {}
    return {
        "_id": uid,
        "name": s.get("name", ""), # Kosongkan jika tidak ada
        "desc_utama": s.get("desc_utama", ""), # Kosongkan jika tidak ada
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "step": s.get("step"),
        "temp_char": s.get("temp_char")
    }

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= [3] AI & SYSTEM =========
async def generate(prompt, system, history, mode="FAST"):
    context = "\n---\n".join(history[-10:]) if history else "Mulai."
    full = f"{system}\n\n{context}\n\n{prompt}"
    model = MODELS.get(mode, MODELS["FAST"])
    try:
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=model, contents=full))
        return r.text.strip(), model
    except:
        return None, None

def build_system(name, desc, role):
    name_tag = name if name else "Karakter"
    base = f"Kamu adalah {name_tag}.\nDeskripsi: {desc}\n\nAturan: Dialog dominan, emosional, maks 3 paragraf."
    if role == "NARATOR":
        base += "\nFokus narasi & konflik dunia."
    return base

# ========= [4] MENU =========
async def menu_utama(uid=None): 
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Karakter", callback_data="menu_char")],
        [InlineKeyboardButton("📂 Muat", callback_data="load_list")],
        [InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("💾 Simpan", callback_data="save_manual")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator")]
    ])

# ========= [5] MESSAGE HANDLER =========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    # -- EDIT NAMA TOKOH UTAMA --
    if s["step"] == "edit_main_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"✅ Nama Tokoh Utama diubah jadi: {text}", reply_markup=await menu_utama())
        return

    # -- EDIT DESKRIPSI TOKOH UTAMA --
    if s["step"] == "edit_main_desc":
        await save(uid, {"desc_utama": text, "step": None})
        await update.message.reply_text("✅ Deskripsi Tokoh Utama diperbarui!", reply_markup=await menu_utama())
        return

    # -- EDIT DESKRIPSI NPC --
    if s["step"] == "edit_char_desc":
        idx = s["selected"]
        chars = s["chars"]
        chars[idx]["desc"] = text
        await save(uid, {"chars": chars, "step": None})
        await update.message.reply_text(f"✅ Deskripsi {chars[idx]['name']} diperbarui!", reply_markup=await menu_utama())
        return

    # -- TAMBAH NPC BARU --
    if s["step"] == "char_name":
        await save(uid, {"temp_char": {"name": text}, "step": "char_desc"})
        await update.message.reply_text("Deskripsi NPC?")
        return
    if s["step"] == "char_desc":
        temp = s["temp_char"]; temp["desc"] = text
        await save(uid, {"temp_char": temp, "step": "char_intro"})
        await update.message.reply_text("Dialog awal NPC?")
        return
    if s["step"] == "char_intro":
        temp = s["temp_char"]; temp["intro"] = text
        chars = s["chars"]; chars.append(temp)
        await save(uid, {"chars": chars, "temp_char": None, "step": None})
        await update.message.reply_text("✅ NPC ditambahkan!", reply_markup=await menu_utama())
        return

    # -- SIMPAN GAME --
    if s["step"] == "save_name":
        await archives.insert_one({"user_id": uid, "save_name": text, "history": s["history"], "chars": s["chars"], "name": s["name"], "desc_utama": s["desc_utama"], "date": datetime.now()})
        await save(uid, {"step": None})
        await update.message.reply_text("💾 Tersimpan!", reply_markup=await menu_utama())
        return

    # -- LOGIKA AKSI & LANJUT --
    if s["step"] in ["action", "narator_input"]:
        is_nar = s["step"] == "narator_input"
        idx = s.get("selected", -1)
        
        if is_nar:
            tag, desc = "NARASI", "Dunia"
        elif idx == -1:
            tag, desc = s["name"] or "Tokoh Utama", s["desc_utama"] or "Karakter utama"
        else:
            tag, desc = s["chars"][idx]["name"], s["chars"][idx]["desc"]

        system = build_system(tag, desc, "NARATOR" if is_nar else "CHAR")
        prompt = f"KEJADIAN: {text}" if is_nar else f"AKSI: {text}"
        out, _ = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(out, reply_markup=await menu_utama())
        else:
            await update.message.reply_text("⚠️ AI sibuk. Coba lagi.")
        return

# ========= [6] CALLBACK HANDLER =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "menu_char":
        kb = [[InlineKeyboardButton("🧍 Tokoh Utama", callback_data="use_main")],
              [InlineKeyboardButton("👥 Daftar NPC", callback_data="npc_list")],
              [InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc")],
              [InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")]]
        await q.edit_message_text("Menu Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "use_main":
        kb = [[InlineKeyboardButton("🎮 Aksi", callback_data="main_action"), InlineKeyboardButton("📖 New Story", callback_data="main_new_story")],
              [InlineKeyboardButton("📛 Edit Nama", callback_data="main_edit_name"), InlineKeyboardButton("📝 Edit Deskripsi", callback_data="main_edit_desc")],
              [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_char")]]
        name = s["name"] if s["name"] else "(Belum ada nama)"
        desc = s["desc_utama"] if s["desc_utama"] else "(Belum ada deskripsi)"
        await q.edit_message_text(f"Tokoh Utama: {name}\nInfo: {desc}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "main_edit_name":
        await save(uid, {"step": "edit_main_name"})
        await q.message.reply_text("Masukkan nama Tokoh Utama baru:")

    elif q.data == "main_edit_desc":
        await save(uid, {"step": "edit_main_desc"})
        await q.message.reply_text("Masukkan deskripsi Tokoh Utama baru:")

    elif q.data == "main_action":
        await save(uid, {"selected": -1, "step": "action"})
        await q.message.reply_text(f"Gunakan {s['name'] or 'Tokoh Utama'}. Ketik aksi:")

    elif q.data == "main_new_story":
        if not s["desc_utama"]: await q.message.reply_text("Isi deskripsi dulu!"); return
        sys = build_system("Narator", s["desc_utama"], "NARATOR")
        await q.message.reply_text("🪄 Membuat cerita baru...")
        out, _ = await generate(f"Mulai cerita baru untuk {s['name']}: {s['desc_utama']}", sys, [], mode="CREATIVE")
        if out:
            await save(uid, {"history": [out], "selected": -1, "step": "action"})
            await q.message.reply_text(out, reply_markup=await menu_utama())

    elif q.data == "npc_list":
        if not s["chars"]: await q.answer("Kosong!", show_alert=True); return
        kb = [[InlineKeyboardButton(c["name"], callback_data=f"npc_{i}")] for i, c in enumerate(s["chars"])]
        kb.append([InlineKeyboardButton("⬅️ Kembali", callback_data="menu_char")])
        await q.edit_message_text("Pilih NPC:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("npc_"):
        idx = int(q.data.split("_")[1]); npc = s["chars"][idx]
        kb = [[InlineKeyboardButton("🎮 Aksi", callback_data=f"use_npc_{idx}"), InlineKeyboardButton("📖 New Story", callback_data=f"story_npc_{idx}")],
              [InlineKeyboardButton("📝 Edit Deskripsi", callback_data=f"edit_npc_{idx}")],
              [InlineKeyboardButton("⬅️ Kembali", callback_data="npc_list")]]
        await q.edit_message_text(f"NPC: {npc['name']}\nInfo: {npc['desc']}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("use_npc_"):
        idx = int(q.data.split("_")[2]); await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"Gunakan {s['chars'][idx]['name']}. Ketik aksi:")

    elif q.data.startswith("edit_npc_"):
        idx = int(q.data.split("_")[2]); await save(uid, {"selected": idx, "step": "edit_char_desc"})
        await q.message.reply_text(f"Deskripsi baru untuk {s['chars'][idx]['name']}:")

    elif q.data.startswith("story_npc_"):
        idx = int(q.data.split("_")[2]); npc = s["chars"][idx]
        sys = build_system("Narator", npc["desc"], "NARATOR")
        await q.message.reply_text(f"🪄 Cerita baru {npc['name']}...")
        out, _ = await generate(f"Mulai cerita: {npc['desc']}", sys, [], mode="CREATIVE")
        if out:
            await save(uid, {"history": [out], "selected": idx, "step": "action"})
            await q.message.reply_text(out, reply_markup=await menu_utama())

    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("date", -1).to_list(10)
        if not items: await q.message.reply_text("Kosong."); return
        kb = [[InlineKeyboardButton(f"{i['save_name']}", callback_data=f"load:{i['_id']}")] for i in items]
        await q.edit_message_text("Pilih Slot:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load:"):
        sid = q.data.split(":")[1]; data = await archives.find_one({"_id": ObjectId(sid)})
        if data:
            await save(uid, {"history": data["history"], "chars": data["chars"], "name": data.get("name", ""), "desc_utama": data.get("desc_utama", ""), "step": "action", "selected": -1})
            await q.message.reply_text(f"✅ Dimuat: {data.get('name', 'Tanpa Nama')}\n\n{data['history'][-1] if data['history'] else 'Kosong'}", reply_markup=await menu_utama())

    elif q.data == "save_manual": await save(uid, {"step": "save_name"}); await q.message.reply_text("Nama save?")
    elif q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama())
    elif q.data == "step_narator": await save(uid, {"step": "narator_input"}); await q.message.reply_text("🎭 Kejadian apa?")

# ========= [7] RUN =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await save(uid, {"history": [], "chars": [], "name": "", "desc_utama": "", "step": None})
    await update.message.reply_text("🎮 RPG AI Siap!", reply_markup=await menu_utama())

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    app.run_polling()

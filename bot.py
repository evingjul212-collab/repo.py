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
        "name": s.get("name"),
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
    except:
        return None, None

def build_system(name, desc, role):
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
async def menu_utama(uid=None): 
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
    await save(uid, {"history": [], "chars": [], "step": None})
    await update.message.reply_text("🎮 RPG AI Siap v1.2!", reply_markup=await menu_utama())

# ========= MESSAGE =========
async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)
    if s["step"] == "edit_char_desc":
        idx = s["selected"]
        chars = s["chars"]
        chars[idx]["desc"] = text # Timpa deskripsi lama
        await save(uid, {"chars": chars, "step": None})
        await update.message.reply_text(f"✅ Deskripsi {chars[idx]['name']} berhasil diupdate!", reply_markup=await menu_utama())
        return
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

    if s["step"] == "action":
        idx = s["selected"]
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
        style = random.choice(["dramatis", "tegang", "ringan"])
        sys = build_system(name, desc, "CHAR")
        prompt = f"Gaya: {style}\n\nAKSI: {text}\n\nLanjutkan cerita."
        out, _ = await generate(prompt, sys, s["history"], mode="FAST")
        if out:
            s["history"].append(f"[{name}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(out, reply_markup=await menu_utama())

    if s["step"] in ["action", "narator_input"]:
        is_nar = s["step"] == "narator_input"
        idx = s.get("selected", -1)
        tag = "NARASI" if is_nar else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
        system = build_system(tag, desc, "NARATOR" if is_nar else "CHAR")
        prompt = f"KEJADIAN: {text}" if is_nar else f"AKSI: {text}"
        await save(uid, {"last_prompt": prompt, "last_system": system})
        out, _ = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await update.message.reply_text(out, reply_markup=await menu_utama(uid))
        else:
            await update.message.reply_text("⚠️ AI sibuk.", reply_markup=await menu_utama(uid))

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    # === BLOK MENU KARAKTER KOMPLIT (GANTI DI SINI) ===
    if q.data == "menu_char":
        kb = [
            [InlineKeyboardButton("🧍 Tokoh Utama", callback_data="use_main")],
            [InlineKeyboardButton("👥 Daftar NPC", callback_data="npc_list")],
            [InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="main_menu")]
        ]
        await q.edit_message_text("Menu Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "add_npc":
        await save(uid, {"step": "char_name"})
        await q.message.reply_text("Nama NPC baru?")

    elif q.data == "npc_list":
        if not s["chars"]:
            await q.answer("NPC masih kosong!", show_alert=True)
            return
        kb = [[InlineKeyboardButton(c["name"], callback_data=f"npc_{i}")] for i, c in enumerate(s["chars"])]
        kb.append([InlineKeyboardButton("⬅️ Kembali", callback_data="menu_char")])
        await q.edit_message_text("Pilih NPC:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("npc_"):
        idx = int(q.data.split("_")[1])
        npc = s["chars"][idx]
        kb = [
            [InlineKeyboardButton("🎮 Aksi (Lanjut)", callback_data=f"use_npc_{idx}")],
            [InlineKeyboardButton("📖 New Story", callback_data=f"story_npc_{idx}")],
            [InlineKeyboardButton("📝 Edit Deskripsi", callback_data=f"edit_npc_{idx}")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="npc_list")]
        ]
        # Di sini AI nampilin deskripsi biar user bisa baca dulu sebelum milih opsi
        await q.edit_message_text(f"Karakter: {npc['name']}\n\nInfo: {npc['desc']}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "use_main":
        # Langsung set ke mode aksi untuk Tokoh Utama
        await save(uid, {"selected": -1, "step": "action"})
        await q.message.reply_text(f"Gunakan {s.get('name', 'Tokoh Utama')}. Ketik aksi kamu:")

    elif q.data.startswith("use_npc_"):
        idx = int(q.data.split("_")[2])
        await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"Gunakan {s['chars'][idx]['name']}. Ketik aksi:")

    elif q.data.startswith("edit_npc_"):
        idx = int(q.data.split("_")[2])
        await save(uid, {"selected": idx, "step": "edit_char_desc"})
        await q.message.reply_text(f"Ketik deskripsi baru untuk {s['chars'][idx]['name']}:")

    elif q.data.startswith("story_npc_"):
        idx = int(q.data.split("_")[2])
        npc = s["chars"][idx]
        # New Story: Hapus history lama, buat awal baru berdasarkan deskripsi
        sys = build_system("Narator", npc["desc"], "NARATOR")
        prompt = f"Buatkan awal cerita yang menarik untuk karakter ini: {npc['name']}. Deskripsi: {npc['desc']}"
        
        await q.message.reply_text(f"🪄 Membuat cerita baru untuk {npc['name']}...")
        out, _ = await generate(prompt, sys, [], mode="CREATIVE")
        if out:
            await save(uid, {"history": [out], "selected": idx, "step": "action"})
            await q.message.reply_text(out, reply_markup=await menu_utama())
    # === SELESAI BLOK MENU KARAKTER ===
    elif q.data == "lanjut":
        if not s["history"]:
            await q.message.reply_text("Mulai cerita dulu dari NPC.")
            return
        sys = build_system("Narator", "Dunia", "NARATOR")
        mode = random.choice(["FAST", "CREATIVE"])
        prompt = "Lanjutkan cerita dengan konflik atau kejadian baru."
        out, _ = await generate(prompt, sys, s["history"], mode=mode)
        if out:
            s["history"].append(out)
            await save(uid, {"history": s["history"]})
            await q.message.reply_text(out, reply_markup=await menu_utama())

    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("date", -1).to_list(10)
        if not items:
            await q.message.reply_text("Kosong.")
            return
        kb = [[InlineKeyboardButton(f"{i['save_name']}", callback_data=f"load:{i['_id']}")] for i in items]
        await q.edit_message_text("Pilih Save Slot:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load:"):
        sid = q.data.split(":")[1]
        data = await archives.find_one({"_id": ObjectId(sid)})
        if data:
            history = data.get("history", [])
            chars = data.get("chars", [])
            await save(uid, {"history": history, "chars": chars, "step": "action", "selected": -1})
            
            # Balik ke logika asli: Tampilkan isi cerita terakhir + menu
            last_text = history[-1] if history else "Data kosong."
            await q.message.reply_text(f"✅ Load Berhasil!\n\n{last_text}", reply_markup=await menu_utama())

    elif q.data == "save_manual":
        await save(uid, {"step": "save_name"})
        await q.message.reply_text("Nama save?")

    elif q.data == "main_menu":
        await q.edit_message_text("Menu:", reply_markup=await menu_utama())

    elif q.data == "step_narator":
        await save(uid, {"step": "narator_input"})
        await q.message.reply_text("🎭 Kejadian apa?")

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

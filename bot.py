import os
import asyncio
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from datetime import datetime

# ========= CONFIG (MODEL TETAP SESUAI PERMINTAAN) =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash", "gemini-2.5-pro"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.archives 

# ========= DATABASE =========
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name"),
        "desc_utama": s.get("desc_utama") or "Tokoh Utama",
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "last_prompt": s.get("last_prompt"),
        "last_system": s.get("last_system"),
        "temp_char": s.get("temp_char")
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    s = fix_state(s)
    await users.update_one({"_id": uid}, {"$set": s}, upsert=True)
    return s

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI =========
async def generate(prompt, system, history):
    context = "\n---\n".join(history[-15:]) if history else "Start."
    full_input = f"{system}\n\n[MEMORI]\n{context}\n\n[AKSI]\n{prompt}"

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: client_ai.models.generate_content(model=m, contents=full_input)
            )
            return resp.text.strip(), m
        except:
            continue
    return None, None

def build_system(tag, desc):
    return f"""
Kamu adalah RPG Engine dengan gaya penulisan Novel Visual yang ekspresif.
PERAN SAAT INI: {tag}
DESKRIPSI KARAKTER: {desc}
FORMAT OUTPUT WAJIB:
1. Dialog: Tulis langsung dengan tanda kutip "..."
2. Aksi/Narasi: Tulis di dalam kurung dan cetak miring: *(...)*
"""

# ========= UI =========
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"),
         InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("💾 Save Slot", callback_data="save_manual"),
         InlineKeyboardButton("📂 Load Slot", callback_data="load_list")],
        [InlineKeyboardButton("📖 Riwayat", callback_data="export_logs"),
         InlineKeyboardButton("↩️ Undo", callback_data="undo")],
        [InlineKeyboardButton("🔄 Regen", callback_data="regen"),
         InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")]
    ]
    return InlineKeyboardMarkup(kb)

async def safe_send(obj, text, tag, markup):
    target = obj.message if hasattr(obj, "message") else obj.effective_message
    try:
        await target.reply_text(f"✨ *{tag}*\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except:
        await target.reply_text(f"✨ {tag}\n\n{text}", reply_markup=markup)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine\n\nMasukkan nama karakter utama:")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text, "step": None})
        await update.message.reply_text(f"🔥 Selamat datang, {text}!", reply_markup=await menu_utama(uid))
        return

    # LOGIKA EDIT (AKURAT: NAMA -> DESKRIPSI)
    if s["step"] and s["step"].startswith("editname_"):
        idx = int(s["step"].split("_")[1])
        await save(uid, {"temp_char": text, "step": f"editdesc_final_{idx}"})
        await update.message.reply_text(f"✅ Nama disimpan: **{text}**\n\nSekarang, masukkan **DESKRIPSI** barunya:")
        return

    if s["step"] and s["step"].startswith("editdesc_final_"):
        idx = int(s["step"].split("_")[2])
        new_name = s.get("temp_char")
        if idx == -1: 
            await save(uid, {"name": new_name, "desc_utama": text, "step": None, "temp_char": None})
        else:
            s["chars"][idx]["name"], s["chars"][idx]["desc"] = new_name, text
            await save(uid, {"chars": s["chars"], "step": None, "temp_char": None})
        await update.message.reply_text(f"✨ Karakter {new_name} diperbarui!", reply_markup=await menu_utama(uid))
        return

    # SAVE & IMPORT
    if s["step"] == "save_name_input":
        await archives.insert_one({"user_id": uid, "save_name": text, "name": s["name"], "history": s["history"], "chars": s["chars"], "desc_utama": s["desc_utama"]})
        await save(uid, {"step": None})
        await update.message.reply_text(f"✅ Tersimpan: {text}", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "import_chars":
        for line in text.split("\n"):
            if ":" in line:
                n, d = line.split(":", 1)
                s["chars"].append({"name": n.strip(), "desc": d.strip()})
        await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text("✅ Karakter diimport!", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Deskripsi {text}?")
        return

    if s["step"] == "char_desc":
        s["chars"].append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text("✅ NPC ditambahkan.", reply_markup=await menu_utama(uid))
        return

    # ACTION / NARATOR
    if s["step"] in ["action", "narator_input"]:
        is_nar = s["step"] == "narator_input"
        idx = s.get("selected", -1)
        tag = "NARASI" if is_nar else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
        system = build_system(tag, desc)
        prompt = f"KEJADIAN: {text}" if is_nar else f"AKSI: {text}"
        await save(uid, {"last_prompt": prompt, "last_system": system})
        out, _ = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await safe_send(update, out, tag, await menu_utama(uid))
        else:
            await update.message.reply_text("⚠️ AI sibuk.", reply_markup=await menu_utama(uid))

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    elif q.data == "save_manual": await save(uid, {"step": "save_name_input"}); await q.message.reply_text("Nama slot?")
    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("_id", -1).to_list(10)
        if not items: await q.message.reply_text("📂 Kosong."); return
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load_{i['_id']}")] for i in items]
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Pilih Slot:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif q.data.startswith("load_"):
        from bson import ObjectId
        data = await archives.find_one({"_id": ObjectId(q.data.split("_")[1])})
        if data:
            # Sinkronisasi Database (Penting!)
            await save(uid, {"history": data["history"], "chars": data["chars"], "name": data["name"], "desc_utama": data["desc_utama"], "step": None})
            raw_text = data["history"][-1].split("]: ", 1)[1] if data["history"] else "Slot dimuat."
            await q.message.reply_text(f"📂 **Dimuat:**\n\n{raw_text[:3500]}", reply_markup=await menu_utama(uid))

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah", callback_data="add_new"), InlineKeyboardButton("📥 Import", callback_data="import_menu")])
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("📜 Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"selected": idx})
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        info = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
        kb = [[InlineKeyboardButton("🎮 Aksi", callback_data=f"act_{idx}")],[InlineKeyboardButton("🎬 New Story", callback_data=f"new_story_{idx}")],[InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")],[InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        await q.edit_message_text(f"Karakter: {name}\n\nInfo: {info}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("edit_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"step": f"editname_{idx}"})
        await q.message.reply_text("📝 Masukkan NAMA baru:")

    elif q.data.startswith("new_story_"):
        idx = int(q.data.split("_")[-1]); s = await get_state(uid)
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
        await q.message.reply_text(f"🎬 Memulai cerita {name}...")
        sys = build_system(name, desc); pr = f"Mulai adegan pembuka novel visual untuk {name}. Latar: {desc}"
        out, _ = await generate(pr, sys, [])
        if out:
            # Cukup 1x Generate (Fixed)
            await save(uid, {"history": [f"[{name}]: {out}"], "selected": idx, "last_prompt": pr, "last_system": sys, "step": None})
            await safe_send(q, out, name, await menu_utama(uid))

    elif q.data == "reset_confirm":
        await save(uid, {"name": None, "desc_utama": "Tokoh Utama", "history": [], "chars": [], "step": "set_name", "selected": -1})
        await q.message.reply_text("🧹 Reset Berhasil! Masukkan nama baru:")

    elif q.data.startswith("act_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"selected": idx, "step": "action"}); await q.message.reply_text("Aksi?")
    elif q.data == "step_narator": await save(uid, {"step": "narator_input"}); await q.message.reply_text("Kejadian?")
    elif q.data == "undo" and s["history"]: 
        s["history"].pop(); await save(uid, {"history": s["history"]})
        await q.message.reply_text("↩️ Undo.", reply_markup=await menu_utama(uid))
    
    elif q.data == "regen":
        if not s.get("last_prompt") or not s["history"]: return
        s["history"].pop(); await save(uid, {"history": s["history"]}) # Sinkronkan ke DB
        out, _ = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out: 
            tag = s["last_prompt"].split(":")[0].replace("AKSI", "").replace("KEJADIAN", "").strip(" :[]")
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, tag, await menu_utama(uid))
    
    elif q.data == "lanjut":
        out, _ = await generate("Lanjutkan cerita.", "Kamu narator RPG.", s["history"])
        if out: s["history"].append(f"[NARASI]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, "NARASI", await menu_utama(uid))
    elif q.data == "add_new": await save(uid, {"step": "char_name"}); await q.message.reply_text("Nama NPC?")
    elif q.data == "import_menu": await save(uid, {"step": "import_chars"}); await q.message.reply_text("Format\nNama: Deskripsi")

# ========= RUNNER (ANTI-CONFLICT) =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

    async def cleanup():
        await app.initialize()
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.shutdown()
    
    asyncio.get_event_loop().run_until_complete(cleanup())
    print("🔥 RPG BOT READY - TANCAP GAS!")
    app.run_polling(drop_pending_updates=True)

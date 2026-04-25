import os 
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash", "gemini-2.5-pro"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.archives 

# ========= DATABASE & STATE =========
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

# ========= AI ENGINE =========
def build_romcom_system(tag, desc, rel="Awkward"):
    return f"""
Kamu penulis Novel Visual RomCom. PERAN: {tag} ({desc}). Status Hubungan: {rel}.
ATURAN:
1. Romantis/Lucu/Awkward. DILARANG HOROR/Misteri/Suara Gaib.
2. Maksimal 2 paragraf (1000 karakter).
3. Wajib berikan 4 pilihan aksi (A, B, C, D) di akhir teks.
"""

async def generate(prompt, system, history):
    context = ""
    if len(history) >= 2:
        context = "[KONTEKS]\n" + "\n---\n".join(history[-2:]) + "\n---\n"
    elif history:
        context = "[KONTEKS]\n" + history[-1] + "\n---\n"
    
    full_input = f"{system}\n\n{context}\n[AKSI SEKARANG]\n{prompt}"
    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_input))
            return resp.text.strip(), m
        except: continue
    return None, None

# ========= UI & SEND =========
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("💾 Save Slot", callback_data="save_manual"), InlineKeyboardButton("📂 Load Slot", callback_data="load_list")],
        [InlineKeyboardButton("📖 Riwayat", callback_data="show_history"), InlineKeyboardButton("↩️ Undo", callback_data="undo")],
        [InlineKeyboardButton("🔄 Regen", callback_data="regen"), InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")]
    ]
    return InlineKeyboardMarkup(kb)

async def safe_send(obj, current_text, prev_text, tag, markup):
    target = obj.message if hasattr(obj, "message") else obj.effective_message
    header = f"✨ *{tag}*\n\n"
    context_msg = f"_[Cerita Sebelumnya]_\n{prev_text[:500]}...\n\n━━━━━━━━━━━━━━━━━━━━\n\n" if prev_text else ""
    final_text = (context_msg + header + current_text)[:4000]
    try: await target.reply_text(final_text, parse_mode="Markdown", reply_markup=markup)
    except: await target.reply_text(final_text, reply_markup=markup)

# ========= HANDLERS =========
async def start(update, context):
    await save(update.effective_user.id, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine RomCom\n\nMasukkan nama karakter utama:")

async def msg(update, context):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text.capitalize(), "step": None})
        await update.message.reply_text(f"🔥 Selamat datang, {text.capitalize()}!", reply_markup=await menu_utama(uid)); return

    # LOGIKA PILIHAN A-B-C-D (GAMBAR 2)
    if s["history"] and re.match(r'^[a-dA-D]$', text.strip()):
        idx = s.get("selected", -1); tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
        sys = build_romcom_system(tag, s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"])
        prompt = f"User memilih opsi {text.upper()}. Lanjutkan cerita."
        out, _ = await generate(prompt, sys, s["history"])
        if out:
            prev = s["history"][-1]; s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "last_prompt": prompt, "last_system": sys})
            await safe_send(update, out, prev, tag, await menu_utama(uid)); return

    # LOGIKA EDIT NAMA & DESKRIPSI (GAMBAR 1)
    if s["step"] and s["step"].startswith("editname_"):
        idx = int(s["step"].split("_")[1])
        await save(uid, {"temp_char": text, "step": f"editdesc_{idx}"})
        await update.message.reply_text(f"Nama baru: {text}. Sekarang masukkan DESKRIPSI karakter:"); return
    
    if s["step"] and s["step"].startswith("editdesc_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: s["name"], s["desc_utama"] = s["temp_char"], text
        else: s["chars"][idx]["name"], s["chars"][idx]["desc"] = s["temp_char"], text
        await save(uid, {"name": s["name"], "desc_utama": s["desc_utama"], "chars": s["chars"], "step": None, "temp_char": None})
        await update.message.reply_text("✨ Karakter diperbarui!", reply_markup=await menu_utama(uid)); return

    if s["step"] in ["action", "narator_input"]:
        idx = s.get("selected", -1); tag = "NARASI" if s["step"] == "narator_input" else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        sys = build_romcom_system(tag, s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"])
        out, _ = await generate(f"AKSI: {text}", sys, s["history"])
        if out:
            prev = s["history"][-1] if s["history"] else ""; s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None}); await safe_send(update, out, prev, tag, await menu_utama(uid)); return

    if s["step"] == "save_name":
        await archives.insert_one({"user_id": uid, "save_name": text, "history": s["history"], "chars": s["chars"], "name": s["name"], "desc_utama": s["desc_utama"]})
        await save(uid, {"step": None}); await update.message.reply_text(f"✅ Tersimpan: {text}", reply_markup=await menu_utama(uid))

# ========= CALLBACKS =========
async def callback(update, context):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    
    elif q.data == "show_history":
        if not s["history"]: await q.message.reply_text("📖 Kosong."); return
        full_h = "\n\n".join(s["history"])
        for i in range(0, len(full_h), 4000): await q.message.reply_text(f"📖 **RIWAYAT**:\n\n{full_h[i:i+4000]}")

    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("_id", -1).to_list(10)
        if not items: await q.message.reply_text("📂 Kosong."); return
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load_{i['_id']}")] for i in items]
        await q.edit_message_text("Pilih slot:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load_"):
        from bson import ObjectId
        data = await archives.find_one({"_id": ObjectId(q.data.split("_")[1])})
        if data:
            await save(uid, {"history": data["history"], "chars": data.get("chars", []), "name": data["name"], "desc_utama": data.get("desc_utama", "Tokoh Utama"), "step": None})
            txt = data["history"][-1] if data["history"] else "Data dimuat."
            await q.message.reply_text(f"✅ **LOAD SUCCESS**\n\n{txt}", reply_markup=await menu_utama(uid))

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']} [{c.get('rel', 'Awkward')}]", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc"), InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("📜 Karakter & Relationship:", reply_markup=InlineKeyboardMarkup(kb))

    # MENU KARAKTER TERPILIH (GAMBAR 1 & 3)
    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"selected": idx})
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        kb = [
            [InlineKeyboardButton("🎮 Aksi (Lanjut)", callback_data=f"act_{idx}")],
            [InlineKeyboardButton("🎬 New Story", callback_data=f"new_{idx}")],
            [InlineKeyboardButton("📝 Edit Deskripsi", callback_data=f"edit_{idx}")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]
        ]
        await q.edit_message_text(f"Karakter: {name}\nInfo: {'Tokoh Utama' if idx == -1 else 'NPC'}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("new_"):
        idx = int(q.data.split("_")[1]); name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        sys = build_romcom_system(name, s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"])
        out, _ = await generate("Mulai cerita baru romcom.", sys, [])
        if out:
            await save(uid, {"history": [f"[{name}]: {out}"], "selected": idx}); await safe_send(q, out, "", name, await menu_utama(uid))

    elif q.data == "lanjut":
        idx = s.get("selected", -1); tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
        sys = build_romcom_system(tag, s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"])
        out, _ = await generate("Lanjutkan adegan.", sys, s["history"])
        if out:
            prev = s["history"][-1] if s["history"] else ""; s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "last_prompt": "Lanjut", "last_system": sys})
            await safe_send(q, out, prev, tag, await menu_utama(uid))

    elif q.data == "undo" and s["history"]:
        s["history"].pop(); await save(uid, {"history": s["history"]}); await q.message.reply_text("↩️ Undone.")
    elif q.data == "save_manual":
        await save(uid, {"step": "save_name"}); await q.message.reply_text("Nama Save Slot?")
    elif q.data == "reset_confirm":
        await save(uid, {"name": None, "history": [], "chars": [], "step": "set_name"}); await q.message.reply_text("🧹 Reset! Nama baru?")
    elif q.data.startswith("act_"): await save(uid, {"step": "action"}); await q.message.reply_text("Apa aksimu?")
    elif q.data.startswith("edit_"): await save(uid, {"step": f"editname_{q.data.split('_')[1]}"}); await q.message.reply_text("Masukkan NAMA baru untuk karakter ini:")
    elif q.data == "step_narator": await save(uid, {"step": "narator_input"}); await q.message.reply_text("Narasi?")

# ========= BOOT & CLEANUP =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

    async def run_bot():
        await app.initialize()
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.start()
        print("🔥 RPG BOT READY - ALL MENUS FIXED!")
        await app.updater.start_polling(drop_pending_updates=True)
    
    loop = asyncio.get_event_loop()
    loop.create_task(run_bot())
    loop.run_forever()

import os
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from bson import ObjectId

# ========= CONFIG =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]

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
        "last_system_type": s.get("last_system_type"),
        "temp_val": s.get("temp_val")
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    s = fix_state(s)
    await users.update_one({"_id": uid}, {"$set": s}, upsert=True)
    return s

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI ENGINE =========
async def generate_response(prompt, history, force_options=False):
    system = "Penulis RomCom RPG. Fokus interaksi manis/lucu."
    if force_options:
        system += " [PENTING]: Di akhir narasi, WAJIB berikan 4 pilihan aksi: A, B, C, D."
    
    context = "[KONTEKS]\n" + "\n".join(history[-3:]) if history else ""
    full_prompt = f"{system}\n\n{context}\n\n[INPUT]\n{prompt}"

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_prompt))
            return resp.text.strip()
        except: continue
    return None

# ========= UI COMPONENTS =========
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("💾 Save Slot", callback_data="save_manual"), InlineKeyboardButton("📂 Load Slot", callback_data="load_list")],
        [InlineKeyboardButton("📖 Riwayat", callback_data="show_history"), InlineKeyboardButton("↩️ Back", callback_data="undo")],
        [InlineKeyboardButton("🔄 Regen", callback_data="regen"), InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")]
    ]
    return InlineKeyboardMarkup(kb)

async def safe_send(obj, current_text, prev_text, tag, markup):
    target = obj.message if hasattr(obj, "message") else obj.effective_message
    header = f"✨ *{tag}*\n\n"
    context_msg = f"_[Sebelumnya]_\n{prev_text[:200]}...\n\n━━━━━━━━━━\n\n" if prev_text else ""
    await target.reply_text((context_msg + header + current_text)[:4000], parse_mode="Markdown", reply_markup=markup)

# ========= MESSAGE HANDLERS =========
async def msg(update, context):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    # 1. SETUP NAMA AWAL
    if s["step"] == "set_name":
        await save(uid, {"name": text.capitalize(), "step": None})
        await update.message.reply_text(f"Selamat datang {text.capitalize()}!", reply_markup=await menu_utama(uid)); return

    # 2. PROSES EDIT (NAMA -> DESKRIPSI)
    if s["step"] and s["step"].startswith("editname_"):
        idx = int(s["step"].split("_")[1])
        await save(uid, {"temp_val": text, "step": f"editdesc_{idx}"})
        await update.message.reply_text(f"Nama baru: {text}. Sekarang masukkan DESKRIPSI karakter:"); return
    
    if s["step"] and s["step"].startswith("editdesc_"):
        idx = int(s["step"].split("_")[1])
        if idx == -1: s["name"], s["desc_utama"] = s["temp_val"], text
        else: s["chars"][idx]["name"], s["chars"][idx]["desc"] = s["temp_val"], text
        await save(uid, {"name": s["name"], "desc_utama": s["desc_utama"], "chars": s["chars"], "step": None, "temp_val": None})
        await update.message.reply_text("✨ Karakter diperbarui!", reply_markup=await menu_utama(uid)); return

    # 3. RESPON PILIHAN ABCD
    if re.match(r'^[a-dA-D]$', text.strip()) and s["history"]:
        out = await generate_response(f"User pilih {text.upper()}", s["history"], force_options=True)
        if out:
            prev = s["history"][-1]; s["history"].append(f"[STORY]: {out}")
            await save(uid, {"history": s["history"], "last_prompt": f"Pilih {text.upper()}", "last_system_type": True})
            await safe_send(update, out, prev, "STORY", await menu_utama(uid)); return

    # 4. AKSI KARAKTER (INTERAKTIF)
    if s["step"] == "action":
        idx = s.get("selected", -1); tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
        out = await generate_response(f"Aksi {tag}: {text}", s["history"], force_options=False)
        if out:
            prev = s["history"][-1] if s["history"] else ""; s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None, "last_prompt": text, "last_system_type": False})
            await safe_send(update, out, prev, tag, await menu_utama(uid)); return

    # 5. SAVE SLOT NAME
    if s["step"] == "save_name":
        await archives.insert_one({"user_id": uid, "save_name": text, "history": s["history"], "chars": s["chars"], "name": s["name"], "desc_utama": s["desc_utama"]})
        await save(uid, {"step": None}); await update.message.reply_text(f"✅ Slot '{text}' Tersimpan!", reply_markup=await menu_utama(uid)); return

# ========= CALLBACK HANDLERS =========
async def callback(update, context):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "lanjut":
        out = await generate_response("Lanjutkan alur cerita.", s["history"], force_options=True)
        if out:
            prev = s["history"][-1] if s["history"] else ""; s["history"].append(f"[STORY]: {out}")
            await save(uid, {"history": s["history"], "last_prompt": "Lanjut", "last_system_type": True})
            await safe_send(q, out, prev, "STORY", await menu_utama(uid))

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']}", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc"), InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("📜 Daftar Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"selected": idx})
        kb = [[InlineKeyboardButton("🎮 Aksi Karakter", callback_data=f"act_{idx}")],
              [InlineKeyboardButton("🎬 New Story", callback_data=f"new_{idx}")],
              [InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")],
              [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        await q.edit_message_text(f"Menu Karakter.", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("_id", -1).to_list(10)
        if not items: await q.message.reply_text("📂 Belum ada save-an."); return
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load_{i['_id']}")] for i in items]
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Pilih slot yang akan di-load:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load_"):
        data = await archives.find_one({"_id": ObjectId(q.data.split("_")[1])})
        if data:
            await save(uid, {"history": data["history"], "chars": data.get("chars", []), "name": data["name"], "desc_utama": data.get("desc_utama", "Tokoh Utama"), "step": None})
            txt = data["history"][-1] if data["history"] else "Data dimuat."
            await q.message.reply_text(f"✅ **LOAD SUCCESS**\n\n{txt}", reply_markup=await menu_utama(uid))

    elif q.data.startswith("edit_"):
        idx = q.data.split("_")[1]
        await save(uid, {"step": f"editname_{idx}"})
        await q.message.reply_text("Masukkan NAMA baru untuk karakter ini:")

    elif q.data == "undo" and s["history"]:
        s["history"].pop(); await save(uid, {"history": s["history"]})
        await q.message.reply_text("↩️ Back Berhasil (History Mundur).", reply_markup=await menu_utama(uid))

    elif q.data == "save_manual":
        await save(uid, {"step": "save_name"}); await q.message.reply_text("Ketik nama save slot:")
    elif q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    elif q.data.startswith("act_"): await save(uid, {"step": "action"}); await q.message.reply_text("Ketik aksi/dialog:")
    elif q.data == "reset_confirm":
        await save(uid, {"name": None, "history": [], "chars": [], "step": "set_name"})
        await q.message.reply_text("🧹 Reset Berhasil! Masukkan nama baru:")

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", lambda u, c: save(u.effective_user.id, {"step": "set_name"}) or u.message.reply_text("Masukkan nama karakter utama:")))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    
    async def clean_start():
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Polling dimulai. Jalur fungsi sudah diaudit!")

    asyncio.get_event_loop().run_until_complete(clean_start())
    app.run_polling(drop_pending_updates=True)

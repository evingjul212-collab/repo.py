import os
import asyncio
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from datetime import datetime

# ========= CONFIG (AMAN) =========
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
        "name": s.get("name") or "User",
        "referensi": s.get("referensi") or "Belum ada referensi cerita.",
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
            print(f"[AI] Model: {m}")
            return resp.text.strip(), m
        except:
            continue
    return None, None

# PROMPT DENGAN REFERENSI PLOT
def build_system(tag, desc, referensi):
    return f"""
Kamu adalah RPG Engine berbasis teks.

REFERENSI DUNIA & PLOT:
{referensi}

PERAN SAAT INI: {tag}
DESKRIPSI: {desc}

FORMAT OUTPUT:
1. Dialog: "..."
2. Narasi/Aksi: *(Deskripsi detail, dramatis, sensorik)*
3. Transisi Lokasi: *** / **(Di [Lokasi])**

ATURAN:
- Tetap dalam karakter & patuhi referensi plot di atas.
- Gaya narasi natural, 2-4 paragraf.
- Jangan buat pilihan (1,2,3).
"""

# ========= UI =========
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all")],
        [InlineKeyboardButton("📝 Edit Referensi", callback_data="edit_ref")],
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
    text = text.replace("\n\n\n", "\n\n")
    try:
        await target.reply_text(f"✨ *{tag}*\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except:
        await target.reply_text(f"✨ {tag}\n\n{text}", reply_markup=markup)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"step": "set_referensi", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine\n\nSilakan masukkan **Alur Cerita / Referensi** (Plot, Tokoh Utama, Karakter lain, Dunia):")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    # SET REFERENSI AWAL
    if s["step"] == "set_referensi":
        await save(uid, {"referensi": text, "step": None})
        await update.message.reply_text("✅ Referensi disimpan! Cerita siap dimulai.", reply_markup=await menu_utama(uid))
        return

    # EDIT REFERENSI DI TENGAH JALAN
    if s["step"] == "updating_referensi":
        await save(uid, {"referensi": text, "step": None})
        await update.message.reply_text("✅ Referensi diperbarui.", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "save_name_input":
        save_data = {"user_id": uid, "save_name": text, "referensi": s["referensi"], "history": s["history"], "chars": s["chars"]}
        await archives.insert_one(save_data)
        await save(uid, {"step": None})
        await update.message.reply_text(f"✅ Tersimpan: {text}", reply_markup=await menu_utama(uid))
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

    if s["step"] in ["action", "narator_input"]:
        is_nar = s["step"] == "narator_input"
        idx = s.get("selected", -1)
        tag = "NARASI" if is_nar else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
        
        system = build_system(tag, desc, s["referensi"])
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
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "edit_ref":
        await save(uid, {"step": "updating_referensi"})
        await q.message.reply_text(f"📝 **Referensi Saat Ini:**\n\n{s['referensi']}\n\nSilakan masukkan referensi baru:")

    elif q.data == "save_manual":
        await save(uid, {"step": "save_name_input"})
        await q.message.reply_text("📝 Nama slot simpanan:")

    elif q.data == "load_list":
        cursor = archives.find({"user_id": uid}).sort("_id", -1)
        items = await cursor.to_list(length=10)
        if not items:
            await q.message.reply_text("📂 Tidak ada arsip.")
            return
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load_{i['_id']}")] for i in items]
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("📂 Muat Slot:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load_"):
        from bson import ObjectId
        data = await archives.find_one({"_id": ObjectId(q.data.split("_")[1])})
        if data:
            await save(uid, {"history": data["history"], "chars": data["chars"], "referensi": data.get("referensi", "")})
            await q.message.reply_text(f"✅ Memuat: {data['save_name']}", reply_markup=await menu_utama(uid))

    elif q.data == "reset_confirm":
        await save(uid, {"history": [], "chars": [], "step": None, "referensi": "Belum ada referensi."})
        await q.message.reply_text("🧹 Reset selesai. Gunakan /start untuk alur baru.")

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah", callback_data="add_new")])
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("📜 Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        kb = [[InlineKeyboardButton("💬 Aksi", callback_data=f"act_{idx}")],[InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")],[InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        await q.edit_message_text(f"Karakter: {name}", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("act_"):
        idx = int(q.data.split("_")[1]); name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await save(uid, {"selected": idx, "step": "action"}); await q.message.reply_text(f"Aksi {name}?")

    elif q.data == "lanjut":
        out, _ = await generate("Lanjutkan alur.", build_system("NARASI", "Narator", s["referensi"]), s["history"])
        if out:
            s["history"].append(f"[NARASI]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, "NARASI", await menu_utama(uid))

    elif q.data == "main_menu": await q.edit_message_text("Menu:", reply_markup=await menu_utama(uid))

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    print("🔥 RPG REFERENSI ENGINE READY")
    app.run_polling()

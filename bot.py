import os
import asyncio
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from datetime import datetime

# ========= CONFIG (TETAP) =========
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

# ========= AI ENGINE =========
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

def build_system(tag, desc, referensi):
    return f"""Kamu adalah RPG Engine. 
REFERENSI PLOT: {referensi}
KARAKTER SAAT INI: {tag} ({desc})
FORMAT: Dialog "...", Narasi *(Aksi/Ekspresi)*.
Patuhi alur referensi."""

# ========= UI MENU =========
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
    try:
        await target.reply_text(f"✨ *{tag}*\n\n{text}", parse_mode="Markdown", reply_markup=markup)
    except:
        await target.reply_text(f"✨ {tag}\n\n{text}", reply_markup=markup)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"step": "set_referensi", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine Aktif.\n\nSilakan masukkan **Alur Cerita / Referensi** (Plot, Tokoh Utama, Karakter lain, Dunia):")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    if s["step"] == "set_referensi":
        await save(uid, {"referensi": text, "step": None})
        # LANGSUNG GENERATE AWAL CERITA
        system = build_system("NARASI", "Narator", text)
        out, _ = await generate("Mulai cerita berdasarkan referensi.", system, [])
        if out:
            s["history"].append(f"[NARASI]: {out}")
            await save(uid, {"history": s["history"]})
            await safe_send(update, out, "NARASI", await menu_utama(uid))
        return

    if s["step"] == "updating_referensi":
        await save(uid, {"referensi": text, "step": None})
        await update.message.reply_text("✅ Referensi diperbarui.", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "save_name_input":
        await archives.insert_one({"user_id": uid, "save_name": text, "history": s["history"], "referensi": s["referensi"], "chars": s["chars"]})
        await save(uid, {"step": None})
        await update.message.reply_text(f"✅ Tersimpan: {text}", reply_markup=await menu_utama(uid))
        return

    if s["step"] in ["action", "narator_input"]:
        idx = s.get("selected", -1)
        tag = "NARASI" if s["step"] == "narator_input" else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
        system = build_system(tag, desc, s["referensi"])
        prompt = f"AKSI: {text}"
        await save(uid, {"last_prompt": prompt, "last_system": system})
        out, _ = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await safe_send(update, out, tag, await menu_utama(uid))

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "load_list":
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
            # TAMPILKAN 3 PARAGRAF TERAKHIR
            last_three = "\n\n".join(data["history"][-3:]) if data["history"] else "Cerita baru dimulai."
            await q.message.reply_text(f"✅ Memuat: {data['save_name']}\n\n--- POSISI TERAKHIR ---\n\n{last_three}", reply_markup=await menu_utama(uid))

    elif q.data == "export_logs":
        if not s["history"]: return
        output = f"RIWAYAT - {s['referensi'][:50]}...\n\n" + "\n\n".join(s["history"])
        file_bytes = io.BytesIO(output.encode('utf-8'))
        file_bytes.name = "Riwayat_Cerita.txt"
        await context.bot.send_document(chat_id=uid, document=file_bytes, caption="📜 Riwayat petualangan.")

    elif q.data == "edit_ref":
        await save(uid, {"step": "updating_referensi"})
        await q.message.reply_text(f"📝 **Referensi Saat Ini:**\n{s['referensi']}\n\nMasukkan referensi baru:")

    elif q.data == "save_manual":
        await save(uid, {"step": "save_name_input"})
        await q.message.reply_text("📝 Nama slot simpanan:")

    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]})
        await q.message.reply_text("↩️ Undo.", reply_markup=await menu_utama(uid))

    elif q.data == "regen":
        if not s.get("last_prompt") or not s["history"]: return
        s["history"].pop()
        out, _ = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            tag = s["last_prompt"].split(":")[0]
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"]}); await safe_send(q, out, tag, await menu_utama(uid))

    elif q.data == "reset_confirm":
        await save(uid, {"history": [], "chars": [], "step": None, "referensi": "Belum ada."})
        await q.message.reply_text("🧹 Reset selesai. Gunakan /start.")

    elif q.data == "main_menu":
        await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    app.run_polling()

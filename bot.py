import os
import asyncio 
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai

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
    }

async def get_state(uid):
    s = await users.find_one({"_id": uid})
    s = fix_state(s)
    await users.update_one({"_id": uid}, {"$set": s}, upsert=True)
    return s

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI ENGINE (LOGIKA TERPISAH) =========
async def generate_response(prompt, history, force_options=False):
    """
    Jika force_options=True (untuk tombol Lanjut), AI wajib beri pilihan ABCD.
    Jika False (untuk Aksi Karakter), AI merespons secara interaktif alami.
    """
    system_instruction = (
        "Kamu penulis Novel Visual RomCom. Fokus pada interaksi manis/lucu.\n"
        "Jika ada instruksi [OPSI], berikan 4 pilihan aksi (A, B, C, D).\n"
        "Jika TIDAK ADA, balaslah sebagai interaksi karakter yang natural."
    )
    
    context = "[HISTORY SEBELUMNYA]\n" + "\n".join(history[-3:]) if history else ""
    full_prompt = f"{system_instruction}\n\n{context}\n\n[INPUT USER]\n{prompt}"
    if force_options:
        full_prompt += "\n\n[OPSI]: Berikan narasi cerita dan akhiri dengan 4 pilihan A, B, C, D."

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_prompt))
            return resp.text.strip()
        except: continue
    return None

# ========= UI =========
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
    context_msg = f"_[Sebelumnya]_\n{prev_text[:200]}...\n\n━━━━━━━━━━\n\n" if prev_text else ""
    await target.reply_text((context_msg + header + current_text)[:4000], parse_mode="Markdown", reply_markup=markup)

# ========= HANDLERS =========
async def start(update, context):
    await save(update.effective_user.id, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG RomCom\nMasukkan nama karakter utama:")

async def msg(update, context):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text.capitalize(), "step": None})
        await update.message.reply_text(f"Selamat datang, {text.capitalize()}!", reply_markup=await menu_utama(uid)); return

    # PROSES AKSI KARAKTER (INTERAKTIF - TETAP SAMA)
    if s["step"] == "action":
        idx = s.get("selected", -1); tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
        out = await generate_response(f"Aksi {tag}: {text}", s["history"], force_options=False)
        if out:
            prev = s["history"][-1] if s["history"] else ""
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await safe_send(update, out, prev, tag, await menu_utama(uid)); return

    # RESPON PILIHAN A-B-C-D
    if re.match(r'^[a-dA-D]$', text.strip()):
        out = await generate_response(f"User memilih opsi {text.upper()}", s["history"], force_options=True)
        if out:
            prev = s["history"][-1]; s["history"].append(f"[STORY]: {out}")
            await save(uid, {"history": s["history"]})
            await safe_send(update, out, prev, "CERITA", await menu_utama(uid)); return

# ========= CALLBACKS =========
async def callback(update, context):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "lanjut": # HANYA DISINI YANG ADA PILIHAN ABCD
        out = await generate_response("Lanjutkan cerita.", s["history"], force_options=True)
        if out:
            prev = s["history"][-1] if s["history"] else ""
            s["history"].append(f"[STORY]: {out}")
            await save(uid, {"history": s["history"]})
            await safe_send(q, out, prev, "ALUR CERITA", await menu_utama(uid))

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']}", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("📜 Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"selected": idx})
        kb = [[InlineKeyboardButton("🎮 Aksi Karakter", callback_data=f"act_{idx}")],
              [InlineKeyboardButton("🎬 New Story", callback_data=f"new_{idx}")],
              [InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")], # MENU EDIT KEMBALI
              [InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        await q.edit_message_text(f"Karakter Terpilih.", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("act_"): await save(uid, {"step": "action"}); await q.message.reply_text("Ketik apa yang dilakukan karakter ini:")
    elif q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    elif q.data == "show_history":
        full_h = "\n\n".join(s["history"])
        for i in range(0, len(full_h), 4000): await q.message.reply_text(f"📖 **RIWAYAT**:\n\n{full_h[i:i+4000]}")

# ========= RUN =========
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    
    # Anti-Conflict Solusi Final
    async def boot():
        await app.initialize()
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.updater.start_polling(drop_pending_updates=True)
    
    asyncio.get_event_loop().run_until_complete(boot())
    print("🔥 RPG BOT READY - STRUKTUR DIKUNCI!")
    asyncio.get_event_loop().run_forever()

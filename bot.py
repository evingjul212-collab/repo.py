import os
import asyncio
import io
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from datetime import datetime

# ========= CONFIG (MODEL TETAP) =========
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
    context = ""
    if len(history) >= 2:
        prev_blocks = history[-2:]
        context = "[KONTEKS CERITA SEBELUMNYA]\n" + "\n---\n".join(prev_blocks) + "\n---\n"
    elif len(history) == 1:
        context = "[KONTEKS CERITA SEBELUMNYA]\n" + history[-1] + "\n---\n"
    else:
        context = "Start."

    full_input = f"{system}\n\n{context}\n[AKSI SEKARANG]\n{prompt}"

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
PERAN: {tag} ({desc})
FORMAT: Dialog "..." dan Narasi *(...)*.
"""

# KHUSUS UNTUK LANJUT (ROMCOM MODE)
def build_romcom_system(tag, desc):
    return f"""
Kamu adalah penulis Novel Visual genre Romantic Comedy (RomCom).
PERAN: {tag} ({desc})
ATURAN WAJIB:
1. Genre RomCom: Fokus pada interaksi manis, lucu, awkward, dan masuk akal.
2. DILARANG HOROR: Jangan ada suara misterius, hantu, atau elemen supernatural.
3. KONFLIK: Konflik harus seputar hubungan, kecemburuan, salah paham lucu, atau situasi sosial yang canggung.
4. PANJANG: Maksimal 2 paragraf (total sekitar 1000 karakter).
5. FORMAT: Dialog "..." dan Narasi *(...)*.
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

async def safe_send(obj, current_text, prev_text, tag, markup):
    target = obj.message if hasattr(obj, "message") else obj.effective_message
    clean_prev = prev_text[:1000] + "..." if len(prev_text) > 1000 else prev_text
    header = f"✨ *{tag}*\n\n"
    context_msg = f"_[Cerita Sebelumnya]_\n{clean_prev}\n\n━━━━━━━━━━━━━━━━━━━━\n\n" if clean_prev else ""
    full_content = header + current_text
    
    if len(context_msg + full_content) > 4000:
        final_text = full_content
    else:
        final_text = context_msg + full_content

    try:
        await target.reply_text(final_text, parse_mode="Markdown", reply_markup=markup)
    except:
        await target.reply_text(final_text[:4090], reply_markup=markup)

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save(update.effective_user.id, {"name": None, "step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("🎮 RPG Engine\n\nMasukkan nama karakter utama:")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.lower()
    s = await get_state(uid)

    if s["step"] == "set_name":
        await save(uid, {"name": text.capitalize(), "step": None})
        await update.message.reply_text(f"🔥 Selamat datang, {text.capitalize()}!", reply_markup=await menu_utama(uid))
        return

    # EDIT PROSES (TETAP)
    if s["step"] and s["step"].startswith("editname_"):
        idx = int(s["step"].split("_")[1])
        await save(uid, {"temp_char": text.capitalize(), "step": f"editdesc_final_{idx}"})
        await update.message.reply_text(f"✅ Nama disimpan: **{text.capitalize()}**\n\nMasukkan deskripsi baru:")
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

    # PILIHAN A B C D (TETAP)
    if s["history"] and "apa yang akan kamu lakukan?" in s["history"][-1].lower():
        if re.match(r'^[a-d]$', text):
            pilihan = text.upper()
            idx = s.get("selected", -1)
            tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
            system = build_system(tag, s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"])
            prompt = f"User memilih opsi {pilihan}. Lanjutkan adegan."
            prev_block = s["history"][-1]
            out, _ = await generate(prompt, system, s["history"])
            if out:
                s["history"].append(f"[{tag}]: {out}")
                await save(uid, {"history": s["history"], "step": None})
                await safe_send(update, out, prev_block, tag, await menu_utama(uid))
            return

    if s["step"] in ["action", "narator_input"]:
        is_nar = s["step"] == "narator_input"
        idx = s.get("selected", -1)
        tag = "NARASI" if is_nar else (s["name"] if idx == -1 else s["chars"][idx]["name"])
        system = build_system(tag, s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"])
        prompt = f"AKSI: {text}"
        prev_block = s["history"][-1] if s["history"] else ""
        out, _ = await generate(prompt, system, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None})
            await safe_send(update, out, prev_block, tag, await menu_utama(uid))
        return

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "main_menu": await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))
    elif q.data == "load_list":
        items = await archives.find({"user_id": uid}).sort("_id", -1).to_list(10)
        if not items: await q.message.reply_text("📂 Kosong."); return
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load_{i['_id']}")] for i in items]
        await q.edit_message_text("Pilih Slot:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif q.data.startswith("load_"):
        from bson import ObjectId
        data = await archives.find_one({"_id": ObjectId(q.data.split("_")[1])})
        if data:
            await save(uid, {"history": data["history"], "chars": data["chars"], "name": data["name"], "desc_utama": data["desc_utama"], "step": None})
            await q.message.reply_text("📂 Slot dimuat.", reply_markup=await menu_utama(uid))

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"👤 {s['name']}", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("📜 Karakter:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); await save(uid, {"selected": idx})
        kb = [[InlineKeyboardButton("🎮 Aksi", callback_data=f"act_{idx}")],[InlineKeyboardButton("🎬 New Story", callback_data=f"new_story_{idx}")],[InlineKeyboardButton("📝 Edit", callback_data=f"edit_{idx}")],[InlineKeyboardButton("⬅️ Kembali", callback_data="list_all")]]
        await q.edit_message_text(f"Karakter terpilih.", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("new_story_"):
        idx = int(q.data.split("_")[-1])
        name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        sys = build_system(name, s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"])
        out, _ = await generate("Mulai adegan pembuka novel visual romcom.", sys, [])
        if out:
            await save(uid, {"history": [f"[{name}]: {out}"], "selected": idx, "last_prompt": "Start", "last_system": sys, "step": None})
            await safe_send(q, out, "", name, await menu_utama(uid))

    elif q.data == "regen":
        if not s.get("last_prompt") or not s["history"]: return
        prev_block_regen = s["history"][-2] if len(s["history"]) > 1 else ""
        tag_regen = s["history"][-1].split("]: ", 1)[0].replace("[", "")
        s["history"].pop(); await save(uid, {"history": s["history"]})
        out, _ = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out: 
            s["history"].append(f"[{tag_regen}]: {out}"); await save(uid, {"history": s["history"]})
            await safe_send(q, out, prev_block_regen, tag_regen, await menu_utama(uid))
    
    # ========= PERBAIKAN KHUSUS OPSI LANJUT =========
    elif q.data == "lanjut":
        if s["history"] and "apa yang akan kamu lakukan?" in s["history"][-1].lower():
            await q.message.reply_text("⚠️ Pilih opsi (A, B, C, D) dulu Boss!")
            return
            
        idx = s.get("selected", -1)
        tag = s["name"] if idx == -1 else s["chars"][idx]["name"]
        desc = s["desc_utama"] if idx == -1 else s["chars"][idx]["desc"]
        
        # System khusus RomCom & Hemat Paragraf
        system_lanjut = build_romcom_system(tag, desc)
        prompt_lanjut = "Lanjutkan cerita romcom ini. Fokus pada perkembangan situasi yang lucu atau manis. Maksimal 2 paragraf."
        
        prev_block_lanjut = s["history"][-1] if s["history"] else ""
        
        out, _ = await generate(prompt_lanjut, system_lanjut, s["history"])
        if out: 
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "last_prompt": prompt_lanjut, "last_system": system_lanjut})
            await safe_send(q, out, prev_block_lanjut, tag, await menu_utama(uid))

    elif q.data == "reset_confirm":
        await save(uid, {"name": None, "history": [], "chars": [], "step": "set_name"})
        await q.message.reply_text("🧹 Reset Berhasil! Nama baru?")

    elif q.data.startswith("act_"): await save(uid, {"step": "action"}); await q.message.reply_text("Aksi?")
    elif q.data == "step_narator": await save(uid, {"step": "narator_input"}); await q.message.reply_text("Kejadian?")

# ========= RUNNER =========
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
    print("🔥 RPG BOT READY - LANJUT ROMCOM ONLY!")
    app.run_polling(drop_pending_updates=True)

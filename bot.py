import os
import asyncio
import io
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from bson import ObjectId

# ========= CONFIG & DATABASE =========
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.archives 

# ========= DATABASE UTILITY =========
async def get_state(uid):
    s = await users.find_one({"_id": uid})
    if not s: s = {}
    state = {
        "_id": uid,
        "name": s.get("name") or "Bayu",
        "referensi": s.get("referensi") or "",
        "desc_utama": s.get("desc_utama") or "Tokoh Utama",
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "last_prompt": s.get("last_prompt"),
        "last_system": s.get("last_system"),
        "msg_stack": s.get("msg_stack", []) # Menyimpan ID pesan untuk dihapus bertahap
    }
    return state

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ========= AI ENGINE (DUAL STYLE) =========
async def generate(prompt, system, history):
    context = "\n---\n".join(history[-12:]) if history else "Mulai."
    full_input = f"{system}\n\n[MEMORI CERITA]\n{context}\n\n[AKSI SEKARANG]\n{prompt}"
    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_input))
            return resp.text.strip(), m
        except: continue
    return None, None

def build_system(target_name, desc, referensi, role_type="NPC"):
    # Gaya bahasa Narator (Deskriptif) vs Karakter (Dialog)
    if role_type == "NARATOR":
        style_instruction = "GAYA PENULISAN: Utamakan NARASI deskriptif yang mendalam untuk membangun suasana dunia. Dialog secukupnya saja."
        pov = "Kamu adalah Narator/Dunia Cerita."
    else:
        style_instruction = "GAYA PENULISAN: Fokuskan pada DIALOG (Percakapan). Narasi hanya singkat saja untuk menjelaskan aksi atau ekspresi. Buat karakter banyak bicara."
        if role_type == "UTAMA":
            pov = f"Kamu adalah {target_name} (Tokoh Utama). Pakai kata ganti 'Aku'."
        else:
            pov = f"Kamu adalah {target_name} (NPC). JANGAN pakai 'Aku', sebut dirimu '{target_name}'."

    return f"""Kamu RPG Engine. Plot: {referensi}.
Role: {pov}. Deskripsi: {desc}.

{style_instruction}

ATURAN:
1. Dialog: "...".
2. Narasi/Aksi: *(...)*.
3. Max 3 paragraf.
4. Jangan mengambil alih tindakan karakter lain."""

# ========= UI MENU =========
async def menu_utama(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all"), InlineKeyboardButton("📝 Edit Plot", callback_data="edit_ref")],
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")],
        [InlineKeyboardButton("💾 Simpan", callback_data="save_manual"), InlineKeyboardButton("📂 Muat", callback_data="load_list")],
        [InlineKeyboardButton("📖 Riwayat", callback_data="export_logs"), InlineKeyboardButton("🔄 Regen", callback_data="regen")],
        [InlineKeyboardButton("↩️ Undo", callback_data="undo"), InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")]
    ])

# ========= DISPLAY LOGIC (STRICT) =========
async def send_story_and_menu(update, s, text, tag):
    """
    Mengirim cerita dan menu sebagai pesan TERPISAH agar cerita tidak hilang saat menu diklik.
    Juga mengelola penghapusan pesan lama setelah generate ke-3.
    """
    uid = s["_id"]
    # 1. Kirim teks cerita sebagai pesan baru
    story_msg = await update.effective_message.reply_text(
        f"✨ **{tag}**\n\n{text}", 
        parse_mode="Markdown"
    )
    
    # 2. Kirim menu sebagai pesan baru (atau update menu lama jika ingin, tapi di sini kita kirim baru agar tetap nempel di bawah cerita)
    menu_msg = await update.effective_message.reply_text(
        "--- Kontrol Cerita ---", 
        reply_markup=await menu_utama(uid)
    )

    # 3. Kelola Stack Pesan (Hapus setelah generate ke-3)
    # Kita simpan ID pesan cerita dan pesan menu
    current_stack = s.get("msg_stack", [])
    current_stack.append(story_msg.message_id)
    current_stack.append(menu_msg.message_id)

    # Jika stack sudah lebih dari 6 pesan (3x cerita + 3x menu), hapus yang paling tua
    if len(current_stack) > 6:
        to_delete = current_stack[:2] # Hapus cerita & menu tertua
        for mid in to_delete:
            try: await update.get_bot().delete_message(chat_id=uid, message_id=mid)
            except: pass
        current_stack = current_stack[2:]

    await save(uid, {"msg_stack": current_stack})

# ========= HANDLERS =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await save(uid, {"step": "set_referensi", "history": [], "chars": [], "referensi": "", "msg_stack": []})
    await update.message.reply_text("🎮 RPG Engine Aktif.\n\nMasukkan Referensi Plot & Nama Tokoh Utama (Contoh: Kerajaan, Tokoh: Bayu):")

async def msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; text = update.message.text; s = await get_state(uid)

    if s["step"] == "set_referensi":
        name = "Bayu"
        if "Tokoh:" in text: name = text.split("Tokoh:")[1].strip().split()[0]
        await save(uid, {"referensi": text, "name": name, "step": None})
        
        # AWAL CERITA (Gaya Narasi)
        sys = build_system("NARASI", "Dunia Cerita", text, "NARATOR")
        out, _ = await generate("Mulai cerita awal dengan narasi yang kuat.", sys, [])
        if out:
            s["history"].append(f"[NARASI]: {out}")
            await save(uid, {"history": s["history"], "last_system": sys, "last_prompt": "Mulai cerita."})
            await send_story_and_menu(update, s, out, "NARASI")
        return

    if s["step"] == "save_name_input":
        await archives.insert_one({"user_id": uid, "save_name": text, "history": s["history"], "referensi": s["referensi"], "chars": s["chars"], "date": datetime.now()})
        await save(uid, {"step": None})
        await update.message.reply_text(f"💾 Tersimpan di slot: {text}", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "updating_referensi":
        await save(uid, {"referensi": text, "step": None})
        await update.message.reply_text("✅ Plot Diperbarui.", reply_markup=await menu_utama(uid))
        return

    if s["step"] == "char_name":
        await save(uid, {"temp_char": text, "step": "char_desc"})
        await update.message.reply_text(f"Deskripsi untuk {text}?"); return

    if s["step"] == "char_desc":
        s["chars"].append({"name": s["temp_char"], "desc": text})
        await save(uid, {"chars": s["chars"], "step": None})
        await update.message.reply_text(f"✅ NPC {s['temp_char']} ditambahkan.", reply_markup=await menu_utama(uid)); return

    if s["step"] in ["action", "narator_input"]:
        idx = s["selected"]; is_u = (idx == -1)
        tag = s["name"] if is_u else s["chars"][idx]["name"]
        desc = s["desc_utama"] if is_u else s["chars"][idx]["desc"]
        # Tentukan Gaya: Karakter (Dialog) atau Narator (Narasi)
        r_type = "UTAMA" if is_u else "NPC"
        if s["step"] == "narator_input": tag, desc, r_type = "NARASI", "Dunia", "NARATOR"

        sys = build_system(tag, desc, s["referensi"], r_type)
        prompt = f"{tag} melakukan: {text}"
        out, _ = await generate(prompt, sys, s["history"])
        if out:
            s["history"].append(f"[{tag}]: {out}")
            await save(uid, {"history": s["history"], "step": None, "last_prompt": prompt, "last_system": sys})
            await send_story_and_menu(update, s, out, tag)

# ========= CALLBACK =========
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; s = await get_state(uid); await q.answer()

    if q.data == "export_logs":
        if not s["history"]: await q.message.reply_text("Kosong."); return
        txt = "RIWAYAT CERITA\n\n" + "\n\n".join(s["history"])
        f = io.BytesIO(txt.encode()); f.name = "riwayat.txt"
        await context.bot.send_document(chat_id=uid, document=f, caption="📜 Seluruh riwayat cerita.")

    elif q.data == "edit_ref":
        await save(uid, {"step": "updating_referensi"})
        # Menampilkan plot lama agar user tau apa yang mau diperbaiki sesuai permintaan
        await q.message.reply_text(f"📝 **Plot Saat Ini:**\n\n`{s['referensi']}`\n\nSilakan masukkan update plot:", parse_mode="Markdown")

    elif q.data == "list_all":
        kb = [[InlineKeyboardButton(f"🌟 {s['name']} (Utama)", callback_data="sel_-1")]]
        for i, c in enumerate(s["chars"]): kb.append([InlineKeyboardButton(f"👥 {c['name']}", callback_data=f"sel_{i}")])
        kb.append([InlineKeyboardButton("➕ Tambah NPC", callback_data="add_npc"), InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        # Gunakan edit_message_text HANYA untuk menu, pesan cerita di atasnya tidak akan hilang
        await q.edit_message_text("Pilih Karakter untuk dikontrol:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("sel_"):
        idx = int(q.data.split("_")[1]); name = s["name"] if idx == -1 else s["chars"][idx]["name"]
        await save(uid, {"selected": idx, "step": "action"})
        await q.message.reply_text(f"🕹️ Kontrol: **{name}**. Masukkan aksi:")

    elif q.data == "add_npc":
        await save(uid, {"step": "char_name"}); await q.message.reply_text("Nama NPC?")

    elif q.data == "save_manual":
        await save(uid, {"step": "save_name_input"}); await q.message.reply_text("Nama Slot?")

    elif q.data == "load_list":
        cursor = archives.find({"user_id": uid}).sort("date", -1); items = await cursor.to_list(10)
        if not items: await q.message.reply_text("Kosong."); return
        kb = [[InlineKeyboardButton(f"📖 {i['save_name']}", callback_data=f"load:{str(i['_id'])}")] for i in items]
        kb.append([InlineKeyboardButton("⬅️ Menu", callback_data="main_menu")])
        await q.edit_message_text("Pilih Slot Simpanan:", reply_markup=InlineKeyboardMarkup(kb))

    elif q.data.startswith("load:"):
        sid = q.data.split(":")[1]; data = await archives.find_one({"_id": ObjectId(sid)})
        if data:
            h = data.get("history", [])
            await save(uid, {"history": h, "chars": data.get("chars", []), "referensi": data.get("referensi", ""), "step": None})
            await q.message.reply_text(f"✅ Muat Slot: {data['save_name']}", reply_markup=await menu_utama(uid))

    elif q.data == "regen":
        if not s["history"]: return
        s["history"].pop(); await q.message.reply_text("🔄 Menghasilkan ulang..."); out, _ = await generate(s["last_prompt"], s["last_system"], s["history"])
        if out:
            tag = s["last_prompt"].split(" melakukan")[0]
            s["history"].append(f"[{tag}]: {out}"); await save(uid, {"history": s["history"]})
            await send_story_and_menu(update, s, out, tag)

    elif q.data == "undo":
        if s["history"]: s["history"].pop(); await save(uid, {"history": s["history"]}); await q.message.reply_text("↩️ Pesan terakhir dihapus.")

    elif q.data == "main_menu": 
        await q.edit_message_text("Menu Utama:", reply_markup=await menu_utama(uid))

    elif q.data == "step_narator":
        await save(uid, {"step": "narator_input"}); await q.message.reply_text("Narasi kejadian apa?")

    elif q.data == "lanjut":
        sys = build_system("NARASI", "Dunia", s["referensi"], "NARATOR")
        out, _ = await generate("Lanjutkan alur ceritanya.", sys, s["history"])
        if out:
            s["history"].append(f"[NARASI]: {out}"); await save(uid, {"history": s["history"]})
            await send_story_and_menu(update, s, out, "NARASI")

    elif q.data == "reset_confirm":
        await save(uid, {"history": [], "chars": [], "step": "set_referensi", "referensi": "", "msg_stack": []})
        await q.message.reply_text("🧹 Reset Berhasil. Masukkan Plot & Tokoh Baru:")

if __name__ == "__main__":
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=5)
    except: pass
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start)); app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))
    app.run_polling(drop_pending_updates=True)

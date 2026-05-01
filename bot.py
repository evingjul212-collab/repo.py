import os 
import asyncio
import re 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from bson import ObjectId 

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
client_ai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODELS = ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash"]

client_db = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client_db.game_db
users = db.user_states
archives = db.datsa

# ================= STATE =================
def fix_state(s):
    if not s: s = {}
    return {
        "_id": s.get("_id"),
        "name": s.get("name", "User"),
        "desc_utama": s.get("desc_utama", "Tokoh Utama"),
        "step": s.get("step"),
        "history": s.get("history", []),
        "chars": s.get("chars", []),
        "selected": s.get("selected", -1),
        "world_state": s.get("world_state", {"time": "Pagi", "location": "Rumah", "turn": 0}), 
        "summary": s.get("summary", ""), 
        "memory": s.get("memory", []),
        "temp_val": s.get("temp_val")
    }

async def get_state(uid):
    return fix_state(await users.find_one({"_id": uid}))

async def save(uid, data):
    await users.update_one({"_id": uid}, {"$set": data}, upsert=True)

# ================= SYSTEM =================
def update_mood(s, text):
    idx = s.get("selected", -1)
    if idx != -1 and idx < len(s["chars"]):
        npc = s["chars"][idx]
        mood = npc.get("mood", 50)
        if any(w in text.lower() for w in ["baik","tolong","ramah"]):
            mood += 5
        if any(w in text.lower() for w in ["kasar","marah","hina"]):
            mood -= 5
        npc["mood"] = max(0, min(100, mood))
    return s

def update_world(s):
    ws = s["world_state"]
    ws["turn"] += 1
    ws["time"] = "Malam" if ws["turn"] % 6 == 0 else ("Sore" if ws["turn"] % 3 == 0 else "Pagi")
    return ws

def update_memory(s, text):
    if any(k in text.lower() for k in ["jatuh","hilang","janji","cinta","temukan"]):
        s["memory"].append(text[:120])
    return s

async def update_summary(uid, s):
    if len(s["history"]) > 10:
        p = "Ringkas cerita:\n" + "\n".join(s["history"])
        summary = await generate_response(p, [], s, False)
        if summary:
            s["summary"] = summary
            s["history"] = s["history"][-3:]

async def apply_updates(uid, s, text=""):
    s = update_mood(s, text)
    s = update_memory(s, s["history"][-1])
    s["world_state"] = update_world(s)
    await update_summary(uid, s)
    await save(uid, s)
    return s

# ================= AI =================
async def generate_response(prompt, history, s, force_options=False):
    waktu = s["world_state"]["time"]
    lokasi = s["world_state"]["location"]
    all_chars = "\n".join([f"- {c['name']}: {c.get('desc','')}" for c in s["chars"]])
    memory = "\n".join(s["memory"][-5:])

    system = f"""
Penulis novel interaktif.
Ringkasan: {s['summary']}
Memory: {memory}
Dunia: {waktu} di {lokasi}
Karakter:
{all_chars}

WAJIB konsisten dengan deskripsi karakter.
"""

    if force_options:
        system += "\nAkhiri dengan pilihan A B C D"

    full_prompt = f"{system}\n\n{prompt}"

    for m in MODELS:
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: client_ai.models.generate_content(model=m, contents=full_prompt))
            return resp.text.strip()
        except:
            continue
    return None

# ================= MENU =================
async def menu_utama(uid):
    kb = [
        [InlineKeyboardButton("📜 Karakter", callback_data="list_all")], 
        [InlineKeyboardButton("🎭 Narator", callback_data="step_narator"), 
         InlineKeyboardButton("⏩ Lanjut", callback_data="lanjut")], 
        [InlineKeyboardButton("💾 Save Slot", callback_data="save_manual"), 
         InlineKeyboardButton("📂 Load Slot", callback_data="load_list")], 
        [InlineKeyboardButton("📖 Riwayat", callback_data="show_history"), 
         InlineKeyboardButton("↩️ Back", callback_data="undo")], 
        [InlineKeyboardButton("🔄 Regen", callback_data="regen"), 
         InlineKeyboardButton("🧹 Reset", callback_data="reset_confirm")] 
    ]
    return InlineKeyboardMarkup(kb)

# ================= MESSAGE =================
async def msg(update, context):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    # FIX FLOW START
    if s["step"] == "set_name":
        s["name"] = text.capitalize()
        s["step"] = None
        await save(uid, s)
        await update.message.reply_text(f"Halo {s['name']}!", reply_markup=await menu_utama(uid))
        return
async def msg(update, context):
    uid = update.effective_user.id
    text = update.message.text
    s = await get_state(uid)

    # ================= SET NAME =================
    if s["step"] == "set_name":
        s["name"] = text.capitalize()
        s["step"] = None
        await save(uid, s)
        await update.message.reply_text(f"Halo {s['name']}!", reply_markup=await menu_utama(uid))
        return

    # ================= NARATOR =================
    if s["step"] == "narator_input":
        loading_msg = await update.message.reply_text("✍️ Narator sedang menyusun cerita...")

        is_new = len(s["history"]) == 0
        prompt_narator = f"Bertindak sebagai Narator. Arahan: '{text}', {'buat pembukaan cerita' if is_new else 'lanjutkan cerita'}."

        out = await generate_response(prompt_narator, s["history"], s, True)

        if out:
            try:
                await context.bot.delete_message(chat_id=uid, message_id=loading_msg.message_id)
            except:
                pass

            s["history"].append(f"[NARRATOR]:\n{out}")
            s["step"] = None
            s = await apply_updates(uid, s, text)

            await update.message.reply_text(out, reply_markup=await menu_utama(uid))
        return

 if re.match(r'^[a-dA-D]$', text.strip()) and s["history"]:
        out = await generate_response(f"Pilih {text.upper()}", s["history"], s, True)
        if out:
            s["history"].append(f"[STORY]:\n{out}")
            s = await apply_updates(uid, s, text)
            await update.message.reply_text(out, reply_markup=await menu_utama(uid))
        return

    # ================= DEFAULT =================
    await update.message.reply_text("Pilih menu dulu.", reply_markup=await menu_utama(uid))
    # HANDLE PILIHAN A/B/C/D
    if re.match(r'^[a-dA-D]$', text.strip()) and s["history"]:
        out = await generate_response(f"Pilih {text.upper()}", s["history"], s, True)
        if out:
            s["history"].append(f"[STORY]:\n{out}")
            s = await apply_updates(uid, s, text)
            await update.message.reply_text(out, reply_markup=await menu_utama(uid))
        return

    # fallback
    await update.message.reply_text("Pilih menu dulu.", reply_markup=await menu_utama(uid))

# ================= CALLBACK =================
async def callback(update, context):
    q = update.callback_query
    uid = q.from_user.id
    s = await get_state(uid)
    await q.answer()

    if q.data == "lanjut":
        out = await generate_response("Lanjutkan cerita", s["history"], s, True)
        if out:
            s["history"].append(f"[STORY]:\n{out}")
            s = await apply_updates(uid, s)
            await q.message.reply_text(out, reply_markup=await menu_utama(uid))

    elif q.data == "regen":
        if not s["history"]:
            return
        s["history"].pop()
        out = await generate_response("Ulangi adegan terakhir", s["history"], s, True)
        if out:
            s["history"].append(f"[STORY]:\n{out}")
            s = await apply_updates(uid, s)
            await q.message.reply_text(out, reply_markup=await menu_utama(uid))

    elif q.data == "undo":
        if s["history"]:
            s["history"].pop()
            await save(uid, s)
            await q.message.reply_text("↩️ Undo", reply_markup=await menu_utama(uid))
            #================================
   elif q.data == "step_narator":
    await save(uid, {"step": "narator_input"})
    await q.message.reply_text("🎭 Ketik alur cerita (awal / lanjutan):")


# ================= START =================
async def start(update: Update, context):
    uid = update.effective_user.id
    await save(uid, {"step": "set_name", "history": [], "chars": []})
    await update.message.reply_text("Siapa namamu?")

# ================= RUN =================
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg))

    asyncio.run(app.run_polling())

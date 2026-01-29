import os
import logging
import time
import json
import asyncio
import urllib.request
from datetime import datetime
from collections import deque
from dataclasses import dataclass, asdict, field
from typing import Dict, Any, Optional, Tuple, List

import uvicorn
from fastapi import FastAPI
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# --- CONFIGURACIÓN ---
load_dotenv()

class Config:
    TOKEN = os.getenv("BOT_TOKEN")
    MODERATION_GROUP_ID = int(os.getenv("MODERATION_GROUP_ID", 0))
    PUBLIC_CHANNEL = os.getenv("PUBLIC_CHANNEL")
    BACKUP_FILE = "bot_backup.json"
    QUEUE_INTERVAL = 1800  # 30 minutos
    RATE_LIMIT = 60        # 1 minuto

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- MODELOS DE DATOS ---
@dataclass
class BotState:
    pending_items: Dict[str, Dict] = field(default_factory=dict)
    pending_questions: Dict[str, Dict] = field(default_factory=dict)
    user_last_confession: Dict[int, float] = field(default_factory=dict)
    banned_users: Dict[int, float] = field(default_factory=dict)
    publication_queue: deque = field(default_factory=deque)
    auto_publishing_active: bool = True

    def to_dict(self):
        return {
            'pending_items': self.pending_items,
            'pending_questions': self.pending_questions,
            'user_last_confession': self.user_last_confession,
            'banned_users': self.banned_users,
            'publication_queue': list(self.publication_queue),
            'timestamp': datetime.now().isoformat()
        }

    def load_dict(self, data):
        self.pending_items = data.get('pending_items', {})
        self.pending_questions = data.get('pending_questions', {})
        self.user_last_confession = {int(k): v for k, v in data.get('user_last_confession', {}).items()}
        self.banned_users = {int(k): v for k, v in data.get('banned_users', {}).items()}
        self.publication_queue = deque(data.get('publication_queue', []))

state = BotState()

# --- UTILIDADES Y PERSISTENCIA ---
class PersistenceManager:
    @staticmethod
    async def save():
        try:
            with open(Config.BACKUP_FILE, 'w', encoding='utf-8') as f:
                json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
            logging.info("💾 Backup guardado.")
        except Exception as e:
            logging.error(f"❌ Error backup: {e}")

    @staticmethod
    def load():
        if os.path.exists(Config.BACKUP_FILE):
            try:
                with open(Config.BACKUP_FILE, 'r', encoding='utf-8') as f:
                    state.load_dict(json.load(f))
                logging.info("📂 Backup cargado exitosamente.")
            except Exception as e:
                logging.error(f"❌ Error cargando backup: {e}")

def get_item_id(user_id: int, content: str) -> str:
    """Genera un ID único más robusto."""
    return str(abs(hash(f"{user_id}{content}{time.time()}")) % (10**8))

def check_user_status(user_id: int) -> Tuple[bool, str]:
    """Centraliza baneo y rate limit."""
    now = time.time()
    # Check Ban
    if user_id in state.banned_users:
        if now < state.banned_users[user_id]:
            rem = int(state.banned_users[user_id] - now)
            return False, f"🚫 Baneado. Restan: {rem // 3600}h {(rem % 3600) // 60}m"
        else:
            del state.banned_users[user_id]
    
    # Check Rate Limit
    if user_id in state.user_last_confession:
        elapsed = now - state.user_last_confession[user_id]
        if elapsed < Config.RATE_LIMIT:
            return False, f"⏰ Espera {int(Config.RATE_LIMIT - elapsed)}s."
    
    return True, ""

# --- LÓGICA DE TELEGRAM (HANDLERS) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola 👋\n\nEnvíame texto, voz o encuesta y la publicaré anónimamente.\n"
        "Usa /preguntas para contactar a moderación."
    )

async def cmd_confesion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Normas: No política, no ofensas personales, no datos privados."
    )

async def cmd_preguntas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok, msg = check_user_status(update.effective_user.id)
    if not ok: return await update.message.reply_text(msg)
    
    context.user_data['waiting_for_question'] = True
    await update.message.reply_text("📝 Escribe tu pregunta para los moderadores:")

async def handle_incoming_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejador unificado para texto, voz y encuestas."""
    if update.effective_chat.type != "private": return
    
    user_id = update.effective_user.id
    # Si es una respuesta a /preguntas
    if context.user_data.get('waiting_for_question'):
        return await process_question(update, context)

    ok, msg = check_user_status(user_id)
    if not ok: return await update.message.reply_text(msg)

    item_id = get_item_id(user_id, str(update.message.message_id))
    item_data = {"user_id": user_id, "timestamp": time.time()}

    # Categorizar contenido
    if update.message.poll:
        p = update.message.poll
        item_data.update({"type": "poll", "q": p.question, "opt": [o.text for o in p.options], "anon": p.is_anonymous, "multi": p.allows_multiple_answers, "p_type": p.type})
        kb_prefix = "poll"
        mod_text = f"📊 Encuesta: {p.question}"
    elif update.message.voice:
        v = update.message.voice
        item_data.update({"type": "voice", "file_id": v.file_id, "duration": v.duration})
        kb_prefix = "voice"
        mod_text = f"🎤 Voz ({v.duration}s)"
    elif update.message.text:
        item_data.update({"type": "text", "text": update.message.text})
        kb_prefix = "text"
        mod_text = f"📝 Confesión:\n\n{update.message.text}"
    else:
        return await update.message.reply_text("⚠️ Formato no soportado.")

    state.pending_items[item_id] = item_data
    state.user_last_confession[user_id] = time.time()
    
    # Enviar a moderación
    kb = [
        [InlineKeyboardButton("✅ Aprobar", callback_data=f"mod:ok:{kb_prefix}:{item_id}"),
         InlineKeyboardButton("🕒 Cola", callback_data=f"mod:cola:{kb_prefix}:{item_id}")],
        [InlineKeyboardButton("❌ Rechazar", callback_data=f"mod:no:{kb_prefix}:{item_id}"),
         InlineKeyboardButton("⚖️ Sancionar", callback_data=f"mod:ban:{kb_prefix}:{item_id}")]
    ]
    
    if update.message.voice:
        await context.bot.send_voice(Config.MODERATION_GROUP_ID, v.file_id, caption=mod_text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await context.bot.send_message(Config.MODERATION_GROUP_ID, mod_text, reply_markup=InlineKeyboardMarkup(kb))
    
    await update.message.reply_text("✋ Enviado a moderación.")

async def process_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['waiting_for_question'] = False
    user_id = update.effective_user.id
    q_id = get_item_id(user_id, update.message.text[:10])
    
    state.pending_questions[q_id] = {"user_id": user_id, "text": update.message.text}
    state.user_last_confession[user_id] = time.time()

    kb = [[InlineKeyboardButton("📝 Responder", callback_data=f"q:res:{q_id}"),
           InlineKeyboardButton("⚖️ Sancionar", callback_data=f"q:ban:{q_id}")]]
    
    await context.bot.send_message(Config.MODERATION_GROUP_ID, f"❓ Pregunta:\n\n{update.message.text}", reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("✅ Pregunta enviada.")

# --- MODERACIÓN Y CALLBACKS ---
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split(":")
    action_type = data[0] # 'mod' o 'q'

    await query.answer()

    if action_type == "mod":
        await handle_content_moderation(query, data[1:], context)
    elif action_type == "q":
        await handle_question_moderation(query, data[1:], context)

async def handle_content_moderation(query, parts, context):
    cmd, c_type, item_id = parts
    item = state.pending_items.get(item_id)
    if not item: return await query.message.delete()

    user_id = item['user_id']

    if cmd == "ok":
        await publish_item(item, context)
        await notify_user(user_id, "🎉 Tu contenido ha sido aprobado.", context)
        state.pending_items.pop(item_id, None)
        await query.message.delete()
    
    elif cmd == "cola":
        state.publication_queue.append(item)
        await notify_user(user_id, "🕒 Añadido a la cola de publicación.", context)
        state.pending_items.pop(item_id, None)
        await query.message.delete()

    elif cmd == "no":
        await notify_user(user_id, "❌ Tu contenido fue rechazado.", context)
        state.pending_items.pop(item_id, None)
        await query.message.delete()

    elif cmd == "ban":
        kb = [[InlineKeyboardButton(f"{h}h", callback_data=f"ban_do:{h}:{user_id}:{item_id}") for h in [1, 2, 4, 24]],
              [InlineKeyboardButton("↩️ Cancelar", callback_data=f"mod:cancel:{c_type}:{item_id}")]]
        await query.edit_message_reply_markup(InlineKeyboardMarkup(kb))

async def handle_question_moderation(query, parts, context):
    cmd, q_id = parts
    q_data = state.pending_questions.get(q_id)
    if not q_data: return await query.message.delete()

    if cmd == "res":
        context.user_data.update({'res_q_id': q_id, 'res_msg_id': query.message.message_id, 'res_u_id': q_data['user_id']})
        prompt = await query.message.reply_text("✍️ Escribe la respuesta:")
        context.user_data['res_prompt_id'] = prompt.message_id
    elif cmd == "ban":
        # Lógica similar a ban de contenido
        pass

async def publish_item(item: Dict, context: ContextTypes.DEFAULT_TYPE):
    try:
        if item['type'] == "text":
            await context.bot.send_message(Config.PUBLIC_CHANNEL, f"📢 Confesión:\n\n{item['text']}")
        elif item['type'] == "voice":
            await context.bot.send_voice(Config.PUBLIC_CHANNEL, item['file_id'], caption="🎤 Voz anónima")
        elif item['type'] == "poll":
            await context.bot.send_poll(Config.PUBLIC_CHANNEL, item['q'], item['opt'], is_anonymous=item['anon'], allows_multiple_answers=item['multi'], type=item['p_type'])
    except Exception as e:
        logging.error(f"Error publicando: {e}")

async def notify_user(user_id: int, text: str, context: ContextTypes.DEFAULT_TYPE):
    try: await context.bot.send_message(user_id, text)
    except: pass

# --- TAREAS EN SEGUNDO PLANO ---
async def auto_publisher(context: ContextTypes.DEFAULT_TYPE):
    while True:
        await asyncio.sleep(Config.QUEUE_INTERVAL)
        if state.auto_publishing_active and state.publication_queue:
            item = state.publication_queue.popleft()
            await publish_item(item, context)
            logging.info("Auto-publicado desde cola.")

async def backup_loop():
    while True:
        await asyncio.sleep(60)
        await PersistenceManager.save()

# --- SERVIDOR Y MAIN ---
app = FastAPI()
@app.get("/health")
def health(): return {"status": "ok", "queue": len(state.publication_queue)}

async def main():
    PersistenceManager.load()
    bot_app = ApplicationBuilder().token(Config.TOKEN).build()

    # Handlers
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("confesion", cmd_confesion))
    bot_app.add_handler(CommandHandler("preguntas", cmd_preguntas))
    bot_app.add_handler(CallbackQueryHandler(handle_callbacks))
    bot_app.add_handler(MessageHandler((filters.TEXT | filters.VOICE | filters.POLL) & ~filters.COMMAND, handle_incoming_content))

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()

    # Tareas concurrentes
    asyncio.create_task(auto_publisher(bot_app))
    asyncio.create_task(backup_loop())
    
    # Servidor API
    config = uvicorn.Config(app, host="0.0.0.0", port=10000)
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
import os
import logging
import time
import json
from fastapi import FastAPI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from dotenv import load_dotenv
import uvicorn
import asyncio
import urllib.request
from datetime import datetime

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
MODERATION_GROUP_ID = os.getenv("MODERATION_GROUP_ID")
PUBLIC_CHANNEL = os.getenv("PUBLIC_CHANNEL")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Variables globales
pending_confessions = {}
pending_polls = {}
pending_voices = {}  # Cambiado de pending_audios a pending_voices
user_last_confession = {}
banned_users = {}

class BackupManager:
    def __init__(self, backup_file="bot_backup.json"):
        self.backup_file = backup_file
        self.backup_interval = 300
    
    async def save_backup(self):
        try:
            backup_data = {
                'pending_confessions': pending_confessions,
                'pending_polls': pending_polls,
                'pending_voices': pending_voices,  # Cambiado aquí
                'banned_users': banned_users,
                'user_last_confession': user_last_confession,
                'backup_timestamp': datetime.now().isoformat()
            }
            
            with open(self.backup_file, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
            
            logging.info(f"💾 Backup guardado: {self.backup_file}")
            
        except Exception as e:
            logging.error(f"❌ Error guardando backup: {e}")
    
    async def load_backup(self):
        try:
            if os.path.exists(self.backup_file):
                with open(self.backup_file, 'r', encoding='utf-8') as f:
                    backup_data = json.load(f)
                
                pending_confessions.update(backup_data.get('pending_confessions', {}))
                pending_polls.update(backup_data.get('pending_polls', {}))
                pending_voices.update(backup_data.get('pending_voices', {}))  # Cambiado aquí
                banned_users.update(backup_data.get('banned_users', {}))
                user_last_confession.update(backup_data.get('user_last_confession', {}))
                
                logging.info(f"📂 Backup cargado: {len(pending_confessions)} confesiones, {len(pending_polls)} encuestas, {len(pending_voices)} mensajes de voz")
                return True
                
        except Exception as e:
            logging.error(f"❌ Error cargando backup: {e}")
        
        return False
    
    async def start_auto_backup(self):
        while True:
            await asyncio.sleep(self.backup_interval)
            await self.save_backup()

backup_manager = BackupManager()

def is_user_banned(user_id: int) -> tuple:
    current_time = time.time()
    if user_id in banned_users and current_time < banned_users[user_id]:
        remaining_time = int(banned_users[user_id] - current_time)
        hours = remaining_time // 3600
        minutes = (remaining_time % 3600) // 60
        return True, f"🚫 Estás baneado. Tiempo restante: {hours}h {minutes}m"
    return False, ""

def check_rate_limit(user_id: int) -> tuple:
    current_time = time.time()
    if user_id in user_last_confession:
        time_since_last = current_time - user_last_confession[user_id]
        if time_since_last < 60:
            remaining_time = int(60 - time_since_last)
            return True, f"⏰ Por favor espera {remaining_time} segundos antes de enviar otra confesión."
    return False, ""

def generate_id(*args) -> int:
    return abs(hash("".join(str(arg) for arg in args))) % (10**8)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola 👋\n\nEnvíame tu confesión en texto, mensaje de voz o una encuesta nativa de Telegram "
        "y la publicaré anónimamente después de moderación."
    )

async def confesion(update: Update, context: ContextTypes.DEFAULT_TYPE):  
    user_id = update.message.from_user.id
    
    # Verificar si el usuario está baneado
    banned, message = is_user_banned(user_id)
    if banned:
        await update.message.reply_text(message)
        return

    await update.message.reply_text(
        "No se permitirán:\n\n"
        "Política\nOfensas sin sentido\n"
        "Mención repetida de una misma persona\n"
        "Datos privados ajenos sin consentimiento"
    )
    
async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando para hacer backup manual"""
    if str(update.message.chat.id) != str(MODERATION_GROUP_ID):
        await update.message.reply_text("❌ Este comando solo está disponible en el grupo de moderación")
        return
    
    await backup_manager.save_backup()
    await update.message.reply_text("💾 Backup realizado exitosamente!")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar mensajes de voz como confesiones"""
    if update.message.chat.type != "private":
        return

    user_id = update.message.from_user.id
    
    # Verificar baneo
    banned, message = is_user_banned(user_id)
    if banned:
        await update.message.reply_text(message)
        return

    # Verificar rate limit
    rate_limited, message = check_rate_limit(user_id)
    if rate_limited:
        await update.message.reply_text(message)
        return

    current_time = time.time()
    user_last_confession[user_id] = current_time
    
    voice = update.message.voice
    
    # Guardar información del mensaje de voz
    voice_id = generate_id(user_id, voice.file_id, current_time)
    
    pending_voices[voice_id] = {
        "file_id": voice.file_id,
        "duration": voice.duration,
        "file_size": voice.file_size,
        "user_id": user_id,
        "timestamp": current_time
    }
    
    await send_to_moderation(
        context, 
        voice_id, 
        None, 
        user_id, 
        is_voice=True,
        voice_data=pending_voices[voice_id]
    )
    
    await update.message.reply_text("✋ Tu mensaje de voz ha sido enviado a moderación.")

async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.poll and not update.message.voice and update.message.chat.type != "private":
        await update.message.reply_text("⚠️ Solo acepto confesiones en texto, mensajes de voz o encuestas nativas de Telegram.")

async def handle_confession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    user_id = update.message.from_user.id
    
    # Verificar baneo
    banned, message = is_user_banned(user_id)
    if banned:
        await update.message.reply_text(message)
        return

    # Verificar si es encuesta
    if update.message.poll:
        await handle_poll(update, context)
        return

    # Verificar si es mensaje de voz
    if update.message.voice:
        await handle_voice(update, context)
        return

    # Verificar rate limit
    rate_limited, message = check_rate_limit(user_id)
    if rate_limited:
        await update.message.reply_text(message)
        return

    current_time = time.time()
    user_last_confession[user_id] = current_time
    
    confession = update.message.text
    confession_id = generate_id(user_id, confession, current_time)
    
    pending_confessions[confession_id] = {
        "text": confession, 
        "user_id": user_id
    }
    
    await send_to_moderation(
        context, 
        confession_id, 
        confession, 
        user_id, 
        is_poll=False
    )
    
    await update.message.reply_text("✋ Tu confesión ha sido enviada a moderación.")

async def handle_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    
    user_id = update.message.from_user.id
    
    # Verificar baneo
    banned, message = is_user_banned(user_id)
    if banned:
        await update.message.reply_text(message)
        return

    # Verificar rate limit
    rate_limited, message = check_rate_limit(user_id)
    if rate_limited:
        await update.message.reply_text(message)
        return

    current_time = time.time()
    user_last_confession[user_id] = current_time
    
    poll = update.message.poll
    poll_id = generate_id(user_id, poll.question, poll.options[0].text, current_time)

    pending_polls[poll_id] = {
        "question": poll.question,
        "options": [option.text for option in poll.options],
        "is_anonymous": poll.is_anonymous,
        "type": poll.type,
        "allows_multiple_answers": poll.allows_multiple_answers,
        "user_id": user_id
    }
    
    await send_to_moderation(
        context, 
        poll_id, 
        None, 
        user_id, 
        is_poll=True, 
        poll_data=pending_polls[poll_id]
    )
    
    await update.message.reply_text("✋ Tu encuesta ha sido enviada a moderación.")

async def send_to_moderation(context, item_id, confession_text, user_id, is_poll=False, is_voice=False, poll_data=None, voice_data=None):
    if is_poll:
        options_text = "\n".join([f"• {option}" for option in poll_data["options"]])
        message_text = (
            f"📊 Nueva encuesta (ID: {item_id}) - User: {user_id}:\n\n"
            f"Pregunta: {poll_data['question']}\n\nOpciones:\n{options_text}\n\n"
            f"Tipo: {poll_data['type']}\nAnónima: {'Sí' if poll_data['is_anonymous'] else 'No'}\n"
            f"Múltiples respuestas: {'Sí' if poll_data['allows_multiple_answers'] else 'No'}"
        )
        callback_prefix = "poll"
    elif is_voice:
        message_text = (
            f"🎤 Nuevo mensaje de voz (ID: {item_id}) - User: {user_id}:\n\n"
            f"Duración: {voice_data['duration']} segundos\n"
            f"Tamaño: {voice_data['file_size']} bytes"
        )
        callback_prefix = "voice"
    else:
        message_text = f"📝 Nueva confesión (ID: {item_id}) - User: {user_id}:\n\n{confession_text}"
        callback_prefix = ""

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Aprobar", 
                callback_data=f"approve_{callback_prefix}_{item_id}"
            ),
            InlineKeyboardButton(
                "❌ Rechazar", 
                callback_data=f"reject_{callback_prefix}_{item_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "⚖️ Sancionar", 
                callback_data=f"sancionar_{callback_prefix}_{item_id}"
            )
        ]
    ]

    if is_voice:
        await context.bot.send_voice(
            chat_id=MODERATION_GROUP_ID,
            voice=voice_data['file_id'],
            caption=message_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await context.bot.send_message(
            chat_id=MODERATION_GROUP_ID,
            text=message_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_sancion_menu(query, item_id, item_type, user_id):
    keyboard = [
        [
            InlineKeyboardButton("1 hora", callback_data=f"ban_1_{item_id}_{item_type}_{user_id}"),
            InlineKeyboardButton("2 horas", callback_data=f"ban_2_{item_id}_{item_type}_{user_id}"),
            InlineKeyboardButton("4 horas", callback_data=f"ban_4_{item_id}_{item_type}_{user_id}"),
            InlineKeyboardButton("24 horas", callback_data=f"ban_24_{item_id}_{item_type}_{user_id}")
        ],
        [
            InlineKeyboardButton("↩️ Cancelar", callback_data=f"cancel_{item_id}_{item_type}")
        ]
    ]
    
    await query.edit_message_text(
        text=f"⏰ Selecciona el tiempo de sanción para el usuario {user_id}:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def aplicar_sancion(user_id: int, horas: int, context: ContextTypes.DEFAULT_TYPE):
    current_time = time.time()
    unban_time = current_time + (horas * 3600)
    banned_users[user_id] = unban_time
    
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🚫 Has sido sancionado por {horas} hora(s) por enviar contenido inapropiado."
        )
    except Exception:
        pass
    
    return unban_time

async def approve_item(item_id, item_type, context):
    """Aprobar item según su tipo"""
    if item_type == "poll":
        poll_data = pending_polls[item_id]
        await context.bot.send_poll(
            chat_id=PUBLIC_CHANNEL,
            question=poll_data["question"],
            options=poll_data["options"],
            is_anonymous=poll_data["is_anonymous"],
            type=poll_data["type"],
            allows_multiple_answers=poll_data["allows_multiple_answers"]
        )
        del pending_polls[item_id]
        return poll_data["user_id"], "encuesta"
    
    elif item_type == "voice":
        voice_data = pending_voices[item_id]
        # Asegurarnos de que el file_id existe
        if "file_id" not in voice_data:
            logging.error(f"Voice data missing file_id: {voice_data}")
            raise ValueError("Voice data is missing file_id")
        
        await context.bot.send_voice(
            chat_id=PUBLIC_CHANNEL,
            voice=voice_data["file_id"],
            caption="🎤 Confesión anónima en mensaje de voz"
        )
        del pending_voices[item_id]
        return voice_data["user_id"], "mensaje de voz"
    
    else:  # Texto
        confession_data = pending_confessions[item_id]
        await context.bot.send_message(
            chat_id=PUBLIC_CHANNEL,
            text=f"📢 Confesión anónima:\n\n{confession_data['text']}"
        )
        del pending_confessions[item_id]
        return confession_data["user_id"], "confesión"

async def reject_item(item_id, item_type):
    """Rechazar item según su tipo"""
    if item_type == "poll":
        user_id = pending_polls[item_id]["user_id"]
        del pending_polls[item_id]
    elif item_type == "voice":
        user_id = pending_voices[item_id]["user_id"]
        del pending_voices[item_id]
    else:
        user_id = pending_confessions[item_id]["user_id"]
        del pending_confessions[item_id]
    return user_id

async def handle_moderation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Función auxiliar para detectar si el mensaje original era de voz
    def is_voice_message():
        # Verificar si el mensaje tiene voice o si el caption existe (indicando que era un voice)
        return hasattr(query.message, 'voice') and query.message.voice is not None or hasattr(query.message, 'caption')

    # Función auxiliar para editar el mensaje según el tipo
    async def edit_moderation_message(text):
        if is_voice_message():
            try:
                await query.edit_message_caption(caption=text)
            except Exception as e:
                logging.error(f"Error editing voice caption: {e}")
                # Fallback: intentar editar como texto normal
                try:
                    await query.edit_message_text(text)
                except Exception as e2:
                    logging.error(f"Error editing as text: {e2}")
        else:
            await query.edit_message_text(text)

    # Manejar sanciones primero
    if query.data.startswith("sancionar_"):
        try:
            parts = query.data.split("_")
            if len(parts) == 3:  # Es texto: "sancionar__12345"
                item_type = ""  # texto
                item_id = int(parts[2])
            else:  # Es poll o voice: "sancionar_poll_12345" o "sancionar_voice_12345"
                item_type = parts[1]
                item_id = int(parts[2])
            
            if item_type == "poll":
                if item_id not in pending_polls:
                    await edit_moderation_message("⚠️ Esta encuesta ya fue procesada.")
                    return
                user_id = pending_polls[item_id]["user_id"]
            elif item_type == "voice":
                if item_id not in pending_voices:
                    await edit_moderation_message("⚠️ Este mensaje de voz ya fue procesado.")
                    return
                user_id = pending_voices[item_id]["user_id"]
            else:  # texto
                if item_id not in pending_confessions:
                    await edit_moderation_message("⚠️ Esta confesión ya fue procesada.")
                    return
                user_id = pending_confessions[item_id]["user_id"]
            
            await handle_sancion_menu(query, item_id, item_type, user_id)
            return
            
        except (IndexError, ValueError) as e:
            logging.error(f"Error procesando sanción: {e}")
            await edit_moderation_message("⚠️ Error al procesar la sanción.")
            return

    # Manejar bans
    if query.data.startswith("ban_"):
        try:
            parts = query.data.split("_")
            horas = int(parts[1])
            item_id = int(parts[2])
            item_type = parts[3]
            user_id = int(parts[4])
            
            unban_time = await aplicar_sancion(user_id, horas, context)
            
            # Eliminar el item pendiente
            if item_type == "poll":
                if item_id in pending_polls:
                    del pending_polls[item_id]
            elif item_type == "voice":
                if item_id in pending_voices:
                    del pending_voices[item_id]
            else:
                if item_id in pending_confessions:
                    del pending_confessions[item_id]
            
            horas_text = f"{horas} hora{'s' if horas > 1 else ''}"
            await edit_moderation_message(f"⚖️ Usuario {user_id} sancionado por {horas_text}.")
            
        except (IndexError, ValueError) as e:
            logging.error(f"Error aplicando ban: {e}")
            await edit_moderation_message("⚠️ Error al aplicar la sanción.")
        return

    # Manejar cancelación
    if query.data.startswith("cancel_"):
        try:
            parts = query.data.split("_")
            item_id = int(parts[1])
            item_type = parts[2]
            
            await edit_moderation_message("❌ Sanción cancelada.")
                    
        except (IndexError, ValueError) as e:
            logging.error(f"Error cancelando sanción: {e}")
            await edit_moderation_message("⚠️ Error al cancelar la sanción.")
        return

    # Procesamiento normal (aprobaciones/rechazos)
    if query.data.startswith("approve_") or query.data.startswith("reject_"):
        try:
            parts = query.data.split("_")
            action = parts[0]
            
            # Determinar el tipo de contenido
            if len(parts) == 3:  # Es texto: "approve__12345" o "reject__12345"
                item_type = ""  # texto
                item_id = int(parts[2])
            else:  # Es poll o voice: "approve_poll_12345" o "reject_voice_12345"
                item_type = parts[1]
                item_id = int(parts[2])
            
            if item_type == "poll":
                if item_id not in pending_polls:
                    await edit_moderation_message("⚠️ Esta encuesta ya fue procesada.")
                    return
                
                if action == "approve":
                    user_id, item_type_str = await approve_item(item_id, "poll", context)
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="🎉 Tu encuesta ha sido aprobada y publicada."
                        )
                    except Exception as e:
                        logging.error(f"Error notifying user about poll: {e}")
                    await edit_moderation_message(f"✅ Encuesta {item_id} aprobada")
                else:
                    user_id = await reject_item(item_id, "poll")
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="❌ Tu encuesta no cumple con nuestras normas."
                        )
                    except Exception as e:
                        logging.error(f"Error notifying user about poll rejection: {e}")
                    await edit_moderation_message(f"❌ Encuesta {item_id} rechazada")
            
            elif item_type == "voice":
                if item_id not in pending_voices:
                    await edit_moderation_message("⚠️ Este mensaje de voz ya fue procesado.")
                    return
                
                if action == "approve":
                    user_id, item_type_str = await approve_item(item_id, "voice", context)
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="🎉 Tu mensaje de voz ha sido aprobado y publicado."
                        )
                    except Exception as e:
                        logging.error(f"Error notifying user about voice: {e}")
                    await edit_moderation_message(f"✅ Mensaje de voz {item_id} aprobado")
                else:
                    user_id = await reject_item(item_id, "voice")
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="❌ Tu mensaje de voz no cumple con nuestras normas."
                        )
                    except Exception as e:
                        logging.error(f"Error notifying user about voice rejection: {e}")
                    await edit_moderation_message(f"❌ Mensaje de voz {item_id} rechazado")
            
            else:  # Texto
                if item_id not in pending_confessions:
                    await edit_moderation_message("⚠️ Esta confesión ya fue procesada.")
                    return
                
                if action == "approve":
                    user_id, item_type_str = await approve_item(item_id, "text", context)
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="🎉 Tu confesión ha sido aprobada y publicada."
                        )
                    except Exception as e:
                        logging.error(f"Error notifying user about confession: {e}")
                    await edit_moderation_message(f"✅ Confesión {item_id} aprobada")
                else:
                    user_id = await reject_item(item_id, "text")
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="❌ Tu confesión no cumple con nuestras normas."
                        )
                    except Exception as e:
                        logging.error(f"Error notifying user about confession rejection: {e}")
                    await edit_moderation_message(f"❌ Confesión {item_id} rechazada")
            
        except (IndexError, ValueError) as e:
            logging.error(f"Error procesando moderación: {e}")
            await edit_moderation_message("⚠️ Error al procesar la moderación.")

async def run_bot():
    # Cargar backup al iniciar
    await backup_manager.load_backup()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("confesion", confesion))
    app.add_handler(CommandHandler("backup", backup_cmd))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confession))
    app.add_handler(MessageHandler(filters.POLL & ~filters.COMMAND, handle_poll))
    app.add_handler(MessageHandler(filters.VOICE & ~filters.COMMAND, handle_voice))  # Cambiado a filters.VOICE
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.POLL & ~filters.VOICE & ~filters.COMMAND, handle_non_text))
    
    app.add_handler(CallbackQueryHandler(handle_moderation))
    
    # Iniciar backup automático en segundo plano
    asyncio.create_task(backup_manager.start_auto_backup())
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    while True:
        await asyncio.sleep(3600)

def run_fastapi():
    app = FastAPI()

    @app.get("/")
    def read_root():
        return {"status": "Bot is running"}
    
    uvicorn.run(app, host="0.0.0.0", port=10000)

async def self_ping():
    url = os.getenv("RENDER_EXTERNAL_URL") or "https://oneandysr-github-io.onrender.com"
    while True:
        try:
            urllib.request.urlopen(url, timeout=10)
            logging.info("Ping sent to keep server alive")
        except Exception as e:
            logging.warning(f"Ping failed: {e}")
        await asyncio.sleep(300)

async def main():
    await asyncio.gather(
        run_bot(),
        asyncio.to_thread(run_fastapi),
        self_ping()
    )

if __name__ == "__main__":
    asyncio.run(main())
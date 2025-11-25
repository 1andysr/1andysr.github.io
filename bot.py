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
from collections import deque

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
pending_voices = {}
pending_questions = {}  # Nueva variable para preguntas
user_last_confession = {}
banned_users = {}
# Nueva cola para publicación automática
publication_queue = deque()
# Estado de la publicación automática
auto_publishing_active = True

class BackupManager:
    def __init__(self, backup_file="bot_backup.json"):
        self.backup_file = backup_file
        self.backup_interval = 300
    
    async def save_backup(self):
        try:
            backup_data = {
                'pending_confessions': pending_confessions,
                'pending_polls': pending_polls,
                'pending_voices': pending_voices,
                'pending_questions': pending_questions,  # Nueva línea
                'banned_users': banned_users,
                'user_last_confession': user_last_confession,
                'publication_queue': list(publication_queue),
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
                pending_voices.update(backup_data.get('pending_voices', {}))
                pending_questions.update(backup_data.get('pending_questions', {}))  # Nueva línea
                banned_users.update(backup_data.get('banned_users', {}))
                user_last_confession.update(backup_data.get('user_last_confession', {}))
                
                # Cargar la cola de publicación si existe
                queue_data = backup_data.get('publication_queue', [])
                publication_queue.clear()
                publication_queue.extend(queue_data)
                
                logging.info(f"📂 Backup cargado: {len(pending_confessions)} confesiones, {len(pending_polls)} encuestas, {len(pending_voices)} mensajes de voz, {len(pending_questions)} preguntas, {len(publication_queue)} en cola")
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
        "y la publicaré anónimamente después de moderación.\n\n"
        "También puedes usar /preguntas para enviar una pregunta a los moderadores."
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

# NUEVO COMANDO PARA PREGUNTAS
async def preguntas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando para enviar preguntas a moderadores"""
    if update.message.chat.type != "private":
        return
        
    user_id = update.message.from_user.id
    
    # Verificar si el usuario está baneado
    banned, message = is_user_banned(user_id)
    if banned:
        await update.message.reply_text(message)
        return

    # Verificar rate limit
    rate_limited, message = check_rate_limit(user_id)
    if rate_limited:
        await update.message.reply_text(message)
        return

    # Guardar estado para esperar la pregunta
    context.user_data['waiting_for_question'] = True
    
    await update.message.reply_text(
        "📝 Por favor, escribe tu pregunta para los moderadores:\n\n"
        "Recuerda que las preguntas deben ser respetuosas y apropiadas. "
        "Un moderador te responderá directamente cuando esté disponible."
    )

async def handle_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar el texto de la pregunta enviada por el usuario"""
    if update.message.chat.type != "private":
        return
        
    user_id = update.message.from_user.id
    
    # Verificar si estamos esperando una pregunta
    if not context.user_data.get('waiting_for_question'):
        return
    
    # Limpiar el estado
    context.user_data['waiting_for_question'] = False
    
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
    
    question_text = update.message.text
    question_id = generate_id(user_id, question_text, current_time)
    
    # Guardar la pregunta
    pending_questions[question_id] = {
        "text": question_text, 
        "user_id": user_id,
        "timestamp": current_time
    }
    
    # Enviar a moderación
    await send_question_to_moderation(context, question_id, question_text, user_id)
    
    await update.message.reply_text("✅ Tu pregunta ha sido enviada a los moderadores. Te responderán cuando esté disponible.")

async def send_question_to_moderation(context, question_id, question_text, user_id):
    """Enviar pregunta al grupo de moderadores con botón de responder"""
    message_text = (
        f"❓ Nueva pregunta (ID: {question_id}):\n\n"
        f"{question_text}"
    )
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📝 Responder", callback_data=f"respond_question_{question_id}")
    ]])
    
    await context.bot.send_message(
        chat_id=MODERATION_GROUP_ID,
        text=message_text,
        reply_markup=keyboard
    )

async def handle_question_response(query, question_id, context):
    """Manejar la respuesta a una pregunta"""
    # Guardar el estado para esperar la respuesta
    context.user_data['responding_to_question'] = question_id
    context.user_data['responding_message_id'] = query.message.message_id
    
    await query.message.reply_text(
        f"✍️ Por favor, escribe la respuesta para la pregunta (ID: {question_id}):"
    )

async def handle_response_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejar el texto de respuesta del moderador"""
    if str(update.message.chat.id) != str(MODERATION_GROUP_ID):
        return
        
    # Verificar si estamos en modo respuesta
    question_id = context.user_data.get('responding_to_question')
    if not question_id:
        return
        
    # Limpiar el estado
    context.user_data['responding_to_question'] = None
    message_id = context.user_data.get('responding_message_id')
    context.user_data['responding_message_id'] = None
    
    response_text = update.message.text
    
    # Buscar la pregunta
    if question_id not in pending_questions:
        await update.message.reply_text("❌ La pregunta ya no existe o fue respondida anteriormente.")
        return
        
    question_data = pending_questions[question_id]
    user_id = question_data["user_id"]
    
    try:
        # Enviar respuesta al usuario
        await context.bot.send_message(
            chat_id=user_id,
            text=f"📨 Respuesta de los moderadores:\n\n{response_text}"
        )
        
        # Eliminar la pregunta de pendientes
        del pending_questions[question_id]
        
        # Editar el mensaje original para marcarlo como respondido
        try:
            original_message = f"✅ **PREGUNTA RESPONDIDA** (ID: {question_id}):\n\n{question_data['text']}\n\n---\n**Respuesta:** {response_text}"
            await context.bot.edit_message_text(
                chat_id=MODERATION_GROUP_ID,
                message_id=message_id,
                text=original_message
            )
        except Exception as e:
            logging.error(f"Error editando mensaje original: {e}")
            # Si no se puede editar, enviar un mensaje nuevo
            await context.bot.send_message(
                chat_id=MODERATION_GROUP_ID,
                text=f"✅ Pregunta {question_id} respondida exitosamente."
            )
        
        await update.message.reply_text("✅ Respuesta enviada al usuario.")
        
    except Exception as e:
        logging.error(f"Error enviando respuesta: {e}")
        await update.message.reply_text("❌ Error al enviar la respuesta. El usuario podría haber bloqueado el bot.")

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
        is_poll=False,
        is_voice=True,
        voice_data=pending_voices[voice_id]
    )
    
    await update.message.reply_text("✋ Tu mensaje de voz ha sido enviado a moderación.")

async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
        
    if not update.message.poll and not update.message.voice:
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

    # Verificar si es una pregunta (estado waiting_for_question)
    if context.user_data.get('waiting_for_question'):
        await handle_question(update, context)
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
        is_poll=False,
        is_voice=False
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
        is_voice=False,
        poll_data=pending_polls[poll_id]
    )
    
    await update.message.reply_text("✋ Tu encuesta ha sido enviada a moderación.")

async def send_to_moderation(context, item_id, confession_text, user_id, is_poll=False, is_voice=False, poll_data=None, voice_data=None):
    # MODIFICACIÓN: Eliminar el ID de usuario del mensaje de moderación
    if is_poll:
        options_text = "\n".join([f"• {option}" for option in poll_data["options"]])
        message_text = (
            f"📊 Nueva encuesta (ID: {item_id}):\n\n"
            f"Pregunta: {poll_data['question']}\n\nOpciones:\n{options_text}\n\n"
            f"Tipo: {poll_data['type']}\nAnónima: {'Sí' if poll_data['is_anonymous'] else 'No'}\n"
            f"Múltiples respuestas: {'Sí' if poll_data['allows_multiple_answers'] else 'No'}"
        )
        item_type_prefix = "poll"
    elif is_voice:
        message_text = (
            f"🎤 Nuevo mensaje de voz (ID: {item_id}):\n\n"
            f"Duración: {voice_data['duration']} segundos\n"
            f"Tamaño: {voice_data['file_size']} bytes"
        )
        item_type_prefix = "voice"
    else:
        # MODIFICACIÓN: Eliminar referencia al usuario en confesiones de texto
        message_text = f"📝 Nueva confesión (ID: {item_id}):\n\n{confession_text}"
        item_type_prefix = "text"

    if is_voice:
        await context.bot.send_voice(
            chat_id=MODERATION_GROUP_ID,
            voice=voice_data['file_id'],
            caption=message_text,
            reply_markup=create_moderation_keyboard(item_id, item_type_prefix)
        )
    else:
        await context.bot.send_message(
            chat_id=MODERATION_GROUP_ID,
            text=message_text,
            reply_markup=create_moderation_keyboard(item_id, item_type_prefix)
        )

def create_moderation_keyboard(item_id, item_type_prefix=""):
    """Crear teclado de moderación (Aprobar, Cola, Rechazar, Sancionar)"""
    # Usar "text" como prefijo para confesiones de texto en lugar de cadena vacía
    prefix = item_type_prefix if item_type_prefix else "text"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Aprobar", callback_data=f"approve_{prefix}_{item_id}"),
            InlineKeyboardButton("✅ Cola", callback_data=f"cola_{prefix}_{item_id}")
        ],
        [
            InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{prefix}_{item_id}"),
            InlineKeyboardButton("⚖️ Sancionar", callback_data=f"sancionar_{prefix}_{item_id}")
        ]
    ])

async def handle_sancion_menu(query, item_id, item_type, user_id):
    """Mostrar menú de sanciones"""
    # Determinar el prefijo correcto para el callback
    callback_prefix = item_type if item_type else "text"
    
    keyboard = [
        [
            InlineKeyboardButton("1 hora", callback_data=f"ban_1_{item_id}_{callback_prefix}_{user_id}"),
            InlineKeyboardButton("2 horas", callback_data=f"ban_2_{item_id}_{callback_prefix}_{user_id}"),
            InlineKeyboardButton("4 horas", callback_data=f"ban_4_{item_id}_{callback_prefix}_{user_id}"),            
        ],
        [
            InlineKeyboardButton("24 horas", callback_data=f"ban_24_{item_id}_{callback_prefix}_{user_id}"),
            InlineKeyboardButton("↩️ Cancelar", callback_data=f"cancel_{item_id}_{callback_prefix}")
        ]
    ]
    
    # Mantener el mismo mensaje, solo cambiar el teclado
    if query.message.caption:  # Si es un mensaje con caption (voz)
        await query.edit_message_caption(
            caption=query.message.caption,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:  # Si es un mensaje de texto normal
        await query.edit_message_text(
            text=query.message.text,
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

async def add_to_queue(item_id, item_type, context):
    """Agregar item a la cola de publicación automática"""
    if item_type == "poll":
        item_data = pending_polls[item_id].copy()
        item_data["_type"] = "poll"
        item_data["_id"] = item_id
        publication_queue.append(item_data)
        del pending_polls[item_id]
        return item_data["user_id"], "encuesta"
    
    elif item_type == "voice":
        item_data = pending_voices[item_id].copy()
        item_data["_type"] = "voice"
        item_data["_id"] = item_id
        publication_queue.append(item_data)
        del pending_voices[item_id]
        return item_data["user_id"], "mensaje de voz"
    
    else:  # Texto
        item_data = pending_confessions[item_id].copy()
        item_data["_type"] = "text"
        item_data["_id"] = item_id
        publication_queue.append(item_data)
        del pending_confessions[item_id]
        return item_data["user_id"], "confesión"

async def reject_item(item_id, item_type):
    """Rechazar item según su tipo"""
    if item_type == "poll":
        user_id = pending_polls[item_id]["user_id"]
        del pending_polls[item_id]
    elif item_type == "voice":
        user_id = pending_voices[item_id]["user_id"]
        del pending_voices[item_id]
    else:  # texto
        user_id = pending_confessions[item_id]["user_id"]
        del pending_confessions[item_id]
    return user_id

async def publish_from_queue(context: ContextTypes.DEFAULT_TYPE):
    """Publicar el siguiente elemento de la cola"""
    global auto_publishing_active
    
    if not auto_publishing_active:
        return
        
    if publication_queue:
        item_data = publication_queue.popleft()
        item_type = item_data["_type"]
        user_id = item_data["user_id"]
        
        try:
            if item_type == "poll":
                await context.bot.send_poll(
                    chat_id=PUBLIC_CHANNEL,
                    question=item_data["question"],
                    options=item_data["options"],
                    is_anonymous=item_data["is_anonymous"],
                    type=item_data["type"],
                    allows_multiple_answers=item_data["allows_multiple_answers"]
                )                
            elif item_type == "voice":
                await context.bot.send_voice(
                    chat_id=PUBLIC_CHANNEL,
                    voice=item_data["file_id"],
                    caption="🎤 Confesión anónima en mensaje de voz"
                )                
            else:  # Texto
                await context.bot.send_message(
                    chat_id=PUBLIC_CHANNEL,
                    text=f"📢 Confesión anónima:\n\n{item_data['text']}"
                )
                logging.info(f"📝 Confesión publicada desde cola (ID: {item_data['_id']})")
        except Exception as e:
            logging.error(f"Error publicando desde cola: {e}")
            # Reinsertar el elemento al principio de la cola si falla
            publication_queue.appendleft(item_data)    
    # Programar la siguiente publicación
    asyncio.create_task(schedule_next_publication(context))

async def schedule_next_publication(context: ContextTypes.DEFAULT_TYPE):
    """Programar la siguiente publicación automática"""
    await asyncio.sleep(1800)  # 30 minutos
    await publish_from_queue(context)

async def handle_moderation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # NUEVO: Manejar respuestas a preguntas
    if query.data.startswith("respond_question_"):
        try:
            question_id = int(query.data.split("_")[2])
            await handle_question_response(query, question_id, context)
        except (IndexError, ValueError) as e:
            logging.error(f"Error procesando respuesta a pregunta: {e}")
            await query.message.reply_text("❌ Error al procesar la solicitud de respuesta.")
        return

    # Manejar agregar a cola
    if query.data.startswith("cola_"):
        try:
            parts = query.data.split("_")
            item_type = parts[1]  # "text", "poll" o "voice"
            item_id = int(parts[2])
            
            if item_type == "poll":
                if item_id not in pending_polls:
                    await query.message.delete()
                    return
                
                user_id, item_type_str = await add_to_queue(item_id, "poll", context)
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="⏳ Tu encuesta ha sido añadida a la cola de publicación automática."
                    )
                except Exception as e:
                    logging.error(f"Error notifying user about queue: {e}")
                await query.message.delete()
            
            elif item_type == "voice":
                if item_id not in pending_voices:
                    await query.message.delete()
                    return
                
                user_id, item_type_str = await add_to_queue(item_id, "voice", context)
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="⏳ Tu mensaje de voz ha sido añadido a la cola de publicación automática."
                    )
                except Exception as e:
                    logging.error(f"Error notifying user about queue: {e}")
                await query.message.delete()
            
            else:  # Texto
                if item_id not in pending_confessions:
                    await query.message.delete()
                    return
                
                user_id, item_type_str = await add_to_queue(item_id, "text", context)
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="⏳ Tu confesión ha sido añadida a la cola de publicación automática."
                    )
                except Exception as e:
                    logging.error(f"Error notifying user about queue: {e}")
                await query.message.delete()
                
        except (IndexError, ValueError) as e:
            logging.error(f"Error agregando a cola: {e}")
            await query.message.delete()
        return

    # Manejar sanciones
    if query.data.startswith("sancionar_"):
        try:
            parts = query.data.split("_")
            if len(parts) == 3:  # Es texto: "sancionar_text_12345"
                item_type = parts[1]  # "text"
                item_id = int(parts[2])
            else:  # Es poll o voice: "sancionar_poll_12345" o "sancionar_voice_12345"
                item_type = parts[1]
                item_id = int(parts[2])
            
            if item_type == "poll":
                if item_id not in pending_polls:
                    await query.message.delete()
                    return
                user_id = pending_polls[item_id]["user_id"]
            elif item_type == "voice":
                if item_id not in pending_voices:
                    await query.message.delete()
                    return
                user_id = pending_voices[item_id]["user_id"]
            else:  # texto
                if item_id not in pending_confessions:
                    await query.message.delete()
                    return
                user_id = pending_confessions[item_id]["user_id"]
            
            await handle_sancion_menu(query, item_id, item_type, user_id)
            return
            
        except (IndexError, ValueError) as e:
            logging.error(f"Error procesando sanción: {e}")
            await query.message.delete()
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
            else:  # texto
                if item_id in pending_confessions:
                    del pending_confessions[item_id]
            
            # Eliminar mensaje de moderación
            await query.message.delete()
            
        except (IndexError, ValueError) as e:
            logging.error(f"Error aplicando ban: {e}")
            await query.message.delete()
        return

    # Manejar cancelación
    if query.data.startswith("cancel_"):
        try:
            parts = query.data.split("_")
            item_id = int(parts[1])
            item_type_prefix = parts[2] if len(parts) > 2 else "text"
            
            # Verificar si el item todavía existe
            item_exists = False
            if item_type_prefix == "poll" and item_id in pending_polls:
                item_exists = True
            elif item_type_prefix == "voice" and item_id in pending_voices:
                item_exists = True
            elif item_type_prefix == "text" and item_id in pending_confessions:
                item_exists = True
            
            if not item_exists:
                await query.message.delete()
                return

            if query.message.caption:
                await query.edit_message_caption(
                    caption=query.message.caption,
                    reply_markup=create_moderation_keyboard(item_id, item_type_prefix)
                )
            else:
                await query.edit_message_text(
                    text=query.message.text,
                    reply_markup=create_moderation_keyboard(item_id, item_type_prefix)
                )                    
        except (IndexError, ValueError) as e:
            logging.error(f"Error cancelando sanción: {e}")
            await query.message.delete()
        return

    # Procesamiento normal (aprobaciones/rechazos)
    if query.data.startswith("approve_") or query.data.startswith("reject_"):
        try:
            parts = query.data.split("_")
            action = parts[0]
            item_type = parts[1]  # "text", "poll" o "voice"
            item_id = int(parts[2])
            
            if item_type == "poll":
                if item_id not in pending_polls:
                    await query.message.delete()
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
                    await query.message.delete()
                else:
                    user_id = await reject_item(item_id, "poll")
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="❌ Tu encuesta no cumple con nuestras normas."
                        )
                    except Exception as e:
                        logging.error(f"Error notifying user about poll rejection: {e}")
                    await query.message.delete()
            
            elif item_type == "voice":
                if item_id not in pending_voices:
                    await query.message.delete()
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
                    await query.message.delete()
                else:
                    user_id = await reject_item(item_id, "voice")
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="❌ Tu mensaje de voz no cumple con nuestras normas."
                        )
                    except Exception as e:
                        logging.error(f"Error notifying user about voice rejection: {e}")
                    await query.message.delete()
            
            else:  # Texto
                if item_id not in pending_confessions:
                    await query.message.delete()
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
                    await query.message.delete()
                else:
                    user_id = await reject_item(item_id, "text")
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="❌ Tu confesión no cumple con nuestras normas."
                        )
                    except Exception as e:
                        logging.error(f"Error notifying user about confession rejection: {e}")
                    await query.message.delete()
            
        except (IndexError, ValueError) as e:
            logging.error(f"Error procesando moderación: {e}")
            await query.message.delete()

async def run_bot():
    # Cargar backup al iniciar
    await backup_manager.load_backup()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("confesion", confesion))
    app.add_handler(CommandHandler("preguntas", preguntas))  # Nuevo comando
    app.add_handler(CommandHandler("backup", backup_cmd))
    
    # NUEVO: Handler para respuestas de moderadores (solo en grupo de moderación)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Chat(int(MODERATION_GROUP_ID)), 
        handle_response_text
    ))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confession))
    app.add_handler(MessageHandler(filters.POLL & ~filters.COMMAND, handle_poll))
    app.add_handler(MessageHandler(filters.VOICE & ~filters.COMMAND, handle_voice))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.POLL & ~filters.VOICE & ~filters.COMMAND, handle_non_text))
    
    app.add_handler(CallbackQueryHandler(handle_moderation))
    
    # Iniciar backup automático en segundo plano
    asyncio.create_task(backup_manager.start_auto_backup())
    
    # Iniciar publicación automática desde cola
    asyncio.create_task(schedule_next_publication(app))
    
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
        await asyncio.sleep(10)

async def main():
    await asyncio.gather(
        run_bot(),
        asyncio.to_thread(run_fastapi),
        self_ping()
    )

if __name__ == "__main__":
    asyncio.run(main())
import os
import logging
import time
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

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
MODERATION_GROUP_ID = os.getenv("MODERATION_GROUP_ID")
PUBLIC_CHANNEL = os.getenv("PUBLIC_CHANNEL")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

pending_confessions = {}
pending_polls = {}
user_last_confession = {}
banned_users = {}  # Diccionario para usuarios baneados: {user_id: unban_timestamp}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola 👋\n\nEnvíame tu confesión en texto o una encuesta nativa de Telegram y la publicaré anónimamente después de moderación.")

async def confesion(update: Update, context: ContextTypes.DEFAULT_TYPE):  
    user_id = update.message.from_user.id
    current_time = time.time()
    
    # Verificar si el usuario está baneado
    if user_id in banned_users:
        if current_time < banned_users[user_id]:
            remaining_time = int(banned_users[user_id] - current_time)
            hours = remaining_time // 3600
            minutes = (remaining_time % 3600) // 60
            await update.message.reply_text(f"🚫 Estás baneado. Tiempo restante: {hours}h {minutes}m")
            return
    
    if user_id in user_last_confession:
        time_since_last = current_time - user_last_confession[user_id]
        if time_since_last < 60:
            remaining_time = int(60 - time_since_last)
            await update.message.reply_text(f"⏰ Por favor espera {remaining_time} segundos antes de enviar otra confesión.")
            return

    await update.message.reply_text("No se permitirán:\n\nPolítica\nOfensas sin sentido\nMención repetida de una misma persona\nDatos privados ajenos sin consentimiento")

async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.poll:
        await update.message.reply_text("⚠️ Solo acepto confesiones en texto o encuestas nativas de Telegram.")

async def handle_confession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    user_id = update.message.from_user.id
    current_time = time.time()
    
    # Verificar si el usuario está baneado
    if user_id in banned_users:
        if current_time < banned_users[user_id]:
            remaining_time = int(banned_users[user_id] - current_time)
            hours = remaining_time // 3600
            minutes = (remaining_time % 3600) // 60
            await update.message.reply_text(f"🚫 Estás baneado. Tiempo restante: {hours}h {minutes}m")
            return

    if update.message.poll:
        await handle_poll(update, context)
        return

    if user_id in user_last_confession:
        time_since_last = current_time - user_last_confession[user_id]
        if time_since_last < 60:
            remaining_time = int(60 - time_since_last)
            await update.message.reply_text(f"⏰ Por favor espera {remaining_time} segundos antes de enviar otra confesión.")
            return

    user_last_confession[user_id] = current_time
    
    confession = update.message.text
    
    confession_id = abs(hash(f"{user_id}{confession}{current_time}")) % (10**8)
    pending_confessions[confession_id] = {"text": confession, "user_id": user_id}
    
    # Nuevo teclado con botón de sanción
    keyboard = [
        [
            InlineKeyboardButton("✅ Aprobar", callback_data=f"approve_{confession_id}"),
            InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{confession_id}")
        ],
        [
            InlineKeyboardButton("⚖️ Sancionar", callback_data=f"sancionar_{confession_id}")
        ]
    ]
    
    await context.bot.send_message(
        chat_id=MODERATION_GROUP_ID,
        text=f"📝 Nueva confesión (ID: {confession_id}) - User: {user_id}:\n\n{confession}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text("✋ Tu confesión ha sido enviada a moderación.")

async def handle_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    
    user_id = update.message.from_user.id
    current_time = time.time()
    
    # Verificar si el usuario está baneado
    if user_id in banned_users:
        if current_time < banned_users[user_id]:
            remaining_time = int(banned_users[user_id] - current_time)
            hours = remaining_time // 3600
            minutes = (remaining_time % 3600) // 60
            await update.message.reply_text(f"🚫 Estás baneado. Tiempo restante: {hours}h {minutes}m")
            return

    if user_id in user_last_confession:
        time_since_last = current_time - user_last_confession[user_id]
        if time_since_last < 60:
            remaining_time = int(60 - time_since_last)
            await update.message.reply_text(f"⏰ Por favor espera {remaining_time} segundos antes de enviar otra confesión/encuesta.")
            return
    
    user_last_confession[user_id] = current_time
    
    poll = update.message.poll

    poll_id = abs(hash(f"{user_id}{poll.question}{poll.options[0].text}{current_time}")) % (10**8)

    pending_polls[poll_id] = {
        "question": poll.question,
        "options": [option.text for option in poll.options],
        "is_anonymous": poll.is_anonymous,
        "type": poll.type,
        "allows_multiple_answers": poll.allows_multiple_answers,
        "user_id": user_id
    }
    
    options_text = "\n".join([f"• {option}" for option in pending_polls[poll_id]["options"]])
    poll_info = f"📊 Nueva encuesta (ID: {poll_id}) - User: {user_id}:\n\nPregunta: {poll.question}\n\nOpciones:\n{options_text}\n\nTipo: {poll.type}\nAnónima: {'Sí' if poll.is_anonymous else 'No'}\nMúltiples respuestas: {'Sí' if poll.allows_multiple_answers else 'No'}"
    
    # Nuevo teclado con botón de sanción para encuestas
    keyboard = [
        [
            InlineKeyboardButton("✅ Aprobar Encuesta", callback_data=f"approve_poll_{poll_id}"),
            InlineKeyboardButton("❌ Rechazar Encuesta", callback_data=f"reject_poll_{poll_id}")
        ],
        [
            InlineKeyboardButton("⚖️ Sancionar", callback_data=f"sancionar_poll_{poll_id}")
        ]
    ]
    
    await context.bot.send_message(
        chat_id=MODERATION_GROUP_ID,
        text=poll_info,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    await update.message.reply_text("✋ Tu encuesta ha sido enviada a moderación.")

async def handle_sancion_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, item_id: int, is_poll: bool, user_id: int):
    query = update.callback_query
    await query.answer()
    
    # Crear menú de opciones de sanción
    keyboard = [
        [
            InlineKeyboardButton("1 hora", callback_data=f"ban_1_{item_id}_{'poll' if is_poll else 'conf'}_{user_id}"),
            InlineKeyboardButton("2 horas", callback_data=f"ban_2_{item_id}_{'poll' if is_poll else 'conf'}_{user_id}"),
            InlineKeyboardButton("4 horas", callback_data=f"ban_4_{item_id}_{'poll' if is_poll else 'conf'}_{user_id}")
        ],
        [
            InlineKeyboardButton("↩️ Cancelar", callback_data=f"cancel_{item_id}_{'poll' if is_poll else 'conf'}")
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
    
    # Notificar al usuario
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🚫 Has sido sancionado por {horas} hora(s) por enviar contenido inapropiado."
        )
    except Exception:
        pass
    
    return unban_time

async def handle_moderation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Manejar sanciones primero
    if query.data.startswith("sancionar_"):
        try:
            parts = query.data.split("_")
            item_id = int(parts[1])
            is_poll = "poll" in query.data
            
            if is_poll:
                if item_id not in pending_polls:
                    await query.edit_message_text("⚠️ Esta encuesta ya fue procesada.")
                    return
                user_id = pending_polls[item_id]["user_id"]
            else:
                if item_id not in pending_confessions:
                    await query.edit_message_text("⚠️ Esta confesión ya fue procesada.")
                    return
                user_id = pending_confessions[item_id]["user_id"]
            
            await handle_sancion_menu(update, context, item_id, is_poll, user_id)
            return
            
        except (IndexError, ValueError) as e:
            logging.error(f"Error procesando sanción: {e}")
            await query.edit_message_text("⚠️ Error al procesar la sanción.")
            return

    # Manejar bans
    if query.data.startswith("ban_"):
        try:
            parts = query.data.split("_")
            horas = int(parts[1])
            item_id = int(parts[2])
            tipo = parts[3]
            user_id = int(parts[4])
            
            unban_time = await aplicar_sancion(user_id, horas, context)
            
            # Eliminar el item pendiente
            if tipo == "poll":
                if item_id in pending_polls:
                    del pending_polls[item_id]
            else:
                if item_id in pending_confessions:
                    del pending_confessions[item_id]
            
            horas_text = f"{horas} hora{'s' if horas > 1 else ''}"
            await query.edit_message_text(f"⚖️ Usuario {user_id} sancionado por {horas_text}. Se desbaneará: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(unban_time))}")
            
        except (IndexError, ValueError) as e:
            logging.error(f"Error aplicando ban: {e}")
            await query.edit_message_text("⚠️ Error al aplicar la sanción.")
        return

    # Manejar cancelación
    if query.data.startswith("cancel_"):
        try:
            parts = query.data.split("_")
            item_id = int(parts[1])
            tipo = parts[2]
            
            if tipo == "poll":
                if item_id in pending_polls:
                    poll_data = pending_polls[item_id]
                    # Volver al menú original de la encuesta
                    options_text = "\n".join([f"• {option}" for option in poll_data["options"]])
                    poll_info = f"📊 Encuesta (ID: {item_id}) - User: {poll_data['user_id']}:\n\nPregunta: {poll_data['question']}\n\nOpciones:\n{options_text}"
                    
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ Aprobar Encuesta", callback_data=f"approve_poll_{item_id}"),
                            InlineKeyboardButton("❌ Rechazar Encuesta", callback_data=f"reject_poll_{item_id}")
                        ],
                        [
                            InlineKeyboardButton("⚖️ Sancionar", callback_data=f"sancionar_poll_{item_id}")
                        ]
                    ]
                    
                    await query.edit_message_text(
                        text=poll_info,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
            else:
                if item_id in pending_confessions:
                    confession_data = pending_confessions[item_id]
                    # Volver al menú original de la confesión
                    keyboard = [
                        [
                            InlineKeyboardButton("✅ Aprobar", callback_data=f"approve_{item_id}"),
                            InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{item_id}")
                        ],
                        [
                            InlineKeyboardButton("⚖️ Sancionar", callback_data=f"sancionar_{item_id}")
                        ]
                    ]
                    
                    await query.edit_message_text(
                        text=f"📝 Confesión (ID: {item_id}) - User: {confession_data['user_id']}:\n\n{confession_data['text']}",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
        except (IndexError, ValueError) as e:
            logging.error(f"Error cancelando sanción: {e}")
            await query.edit_message_text("⚠️ Error al cancelar la sanción.")
        return

    # Procesamiento normal (aprobaciones/rechazos)
    if "poll" in query.data:
        try:
            parts = query.data.split("_")
            action = parts[0]
            poll_id = int(parts[2])
            
            if poll_id not in pending_polls:
                await query.edit_message_text("⚠️ Esta encuesta ya fue procesada.")
                return
            
            poll_data = pending_polls[poll_id]
            
            if action == "approve":
                sent_poll = await context.bot.send_poll(
                    chat_id=PUBLIC_CHANNEL,
                    question=poll_data["question"],
                    options=poll_data["options"],
                    is_anonymous=poll_data["is_anonymous"],
                    type=poll_data["type"],
                    allows_multiple_answers=poll_data["allows_multiple_answers"]
                )
                
                try:
                    await context.bot.send_message(
                        chat_id=poll_data["user_id"],
                        text="🎉 Tu encuesta ha sido aprobada y publicada."
                    )
                except Exception:
                    pass
                await query.edit_message_text(f"✅ Encuesta {poll_id} aprobada")
            else:
                try:
                    await context.bot.send_message(
                        chat_id=poll_data["user_id"],
                        text="❌ Tu encuesta no cumple con nuestras normas."
                    )
                except Exception:
                    pass
                await query.edit_message_text(f"❌ Encuesta {poll_id} rechazada")
            
            del pending_polls[poll_id]
            
        except (IndexError, ValueError) as e:
            logging.error(f"Error procesando encuesta: {e}")
            await query.edit_message_text("⚠️ Error al procesar la encuesta.")
    
    else:
        try:
            parts = query.data.split("_")
            action = parts[0]
            confession_id = int(parts[1])
            
            if confession_id not in pending_confessions:
                await query.edit_message_text("⚠️ Esta confesión ya fue procesada.")
                return
            
            confession_data = pending_confessions[confession_id]
            
            if action == "approve":
                await context.bot.send_message(
                    chat_id=PUBLIC_CHANNEL,
                    text=f"📢 Confesión anónima:\n\n{confession_data['text']}"
                )
                try:
                    await context.bot.send_message(
                        chat_id=confession_data["user_id"],
                        text="🎉 Tu confesión ha sido aprobada y publicada."
                    )
                except Exception:
                    pass
                await query.edit_message_text(f"✅ Confesión {confession_id} aprobada")
            else:
                try:
                    await context.bot.send_message(
                        chat_id=confession_data["user_id"],
                        text="❌ Tu confesión no cumple con nuestras normas."
                    )
                except Exception:
                    pass
                await query.edit_message_text(f"❌ Confesión {confession_id} rechazada")
            
            del pending_confessions[confession_id]
            
        except (IndexError, ValueError) as e:
            logging.error(f"Error procesando confesión: {e}")
            await query.edit_message_text("⚠️ Error al procesar la confesión.")

async def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("confesion", confesion))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confession))
    app.add_handler(MessageHandler(filters.POLL & ~filters.COMMAND, handle_confession))
    app.add_handler(MessageHandler(~filters.TEXT & ~filters.POLL & ~filters.COMMAND, handle_non_text))
    app.add_handler(CallbackQueryHandler(handle_moderation))
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
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hola 👋\n\nEnvíame tu confesión en texto o una encuesta nativa de Telegram y la publicaré anónimamente después de moderación.\n\nNo se permitiran:\nPolitica\nOfensas sin sentido\nMencion repretida de una misma persona\nDatos privados ajenos sin concentimiento")

async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.poll:
        await update.message.reply_text("⚠️ Solo acepto confesiones en texto o encuestas nativas de Telegram.")

async def handle_confession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    if update.message.poll:
        await handle_poll(update, context)
        return

    user_id = update.message.from_user.id
    current_time = time.time()
    
    if user_id in user_last_confession:
        time_since_last = current_time - user_last_confession[user_id]
        if time_since_last < 60:
            remaining_time = int(60 - time_since_last)
            await update.message.reply_text(f"⏰ Por favor espera {remaining_time} segundos antes de enviar otra confesión.")
            return

    user_last_confession[user_id] = current_time
    
    confession = update.message.text
    
    confession_id = abs(hash(f"{user_id}{confession}")) % (10**8)
    pending_confessions[confession_id] = {"text": confession, "user_id": user_id}
    
    keyboard = [[
        InlineKeyboardButton("✅ Aprobar", callback_data=f"approve_{confession_id}"),
        InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{confession_id}")
    ]]
    
    await context.bot.send_message(
        chat_id=MODERATION_GROUP_ID,
        text=f"📝 Nueva confesión (ID: {confession_id}):\n\n{confession}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text("✋ Tu confesión ha sido enviada a moderación.")

async def handle_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return
    
    user_id = update.message.from_user.id
    current_time = time.time()

    if user_id in user_last_confession:
        time_since_last = current_time - user_last_confession[user_id]
        if time_since_last < 60:
            remaining_time = int(60 - time_since_last)
            await update.message.reply_text(f"⏰ Por favor espera {remaining_time} segundos antes de enviar otra encuesta.")
            return

    user_last_confession[user_id] = current_time
    
    poll = update.message.poll

    poll_id = abs(hash(f"{user_id}{poll.question}{poll.options[0].text}")) % (10**8)

    pending_polls[poll_id] = {
        "question": poll.question,
        "options": [option.text for option in poll.options],
        "is_anonymous": poll.is_anonymous,
        "type": poll.type,
        "allows_multiple_answers": poll.allows_multiple_answers,
        "user_id": user_id
    }
    
    options_text = "\n".join([f"• {option}" for option in pending_polls[poll_id]["options"]])
    poll_info = f"📊 Nueva encuesta (ID: {poll_id}):\n\nPregunta: {poll.question}\n\nOpciones:\n{options_text}\n\nTipo: {poll.type}\nAnónima: {'Sí' if poll.is_anonymous else 'No'}\nMúltiples respuestas: {'Sí' if poll.allows_multiple_answers else 'No'}"
    
    keyboard = [[
        InlineKeyboardButton("✅ Aprobar Encuesta", callback_data=f"approve_poll_{poll_id}"),
        InlineKeyboardButton("❌ Rechazar Encuesta", callback_data=f"reject_poll_{poll_id}")
    ]]
    
    await context.bot.send_message(
        chat_id=MODERATION_GROUP_ID,
        text=poll_info,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    await update.message.reply_text("✋ Tu encuesta ha sido enviada a moderación.")

async def handle_moderation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Procesar encuestas primero (tienen "poll" en el callback_data)
    if "poll" in query.data:
        try:
            # Para encuestas, el formato es "approve_poll_123" o "reject_poll_123"
            parts = query.data.split("_")
            action = parts[0]  # "approve" o "reject"
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
    
    # Procesar confesiones de texto
    else:
        try:
            # Para confesiones, el formato es "approve_123" o "reject_123"
            parts = query.data.split("_")
            action = parts[0]  # "approve" o "reject"
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
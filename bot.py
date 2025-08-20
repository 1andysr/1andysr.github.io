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
    await update.message.reply_text("Hola 👋\n\nEnvíame tu confesión en texto o una encuesta nativa de Telegram y la publicaré anónimamente después de moderación.\n\nUsa /confesion para ver las normas antes de enviar.")

async def confesion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    normas_text = """
📋 <b>NORMAS PARA CONFESIONES</b>

Antes de enviar tu confesión, por favor sigue estas normas:

🚫 <b>NO POLÍTICA</b> - No se permiten contenidos políticos.

🚫 <b>NO OFENSAS</b> - Prohibido insultos sin sentido.

🚫 <b>NO MENCIÓN REPETIDA</b> - Evita mencionar repetidamente a la misma persona.

🚫 <b>NO DATOS PERSONALES</b> - No compartas números de teléfono, direcciones, emails u otra información privada sin consentimiento.

✅ <b>CONFESIONES ANÓNIMAS</b> - Todas las confesiones se publican de forma anónima.

⚠️ <b>MODERACIÓN</b> - Todas las confesiones pasan por moderación antes de publicarse.

Si tu confesión incumple estas normas, será rechazada.
"""
    await update.message.reply_text(normas_text, parse_mode='HTML')

async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.poll:
        await update.message.reply_text("⚠️ Solo acepto confesiones en texto o encuestas nativas de Telegram.\n\nUsa /confesion para ver las normas.")

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
    
    # Debug: Log the callback data
    logging.info(f"Callback data received: {query.data}")
    
    # Procesar encuestas primero (tienen 3 partes: approve_poll_123)
    if query.data.startswith("approve_poll_") or query.data.startswith("reject_poll_"):
        try:
            parts = query.data.split("_")
            poll_id = int(parts[2])
            logging.info(f"Processing poll ID: {poll_id}")
        except (IndexError, ValueError) as e:
            logging.error(f"Error processing poll: {e}")
            await query.edit_message_text("⚠️ Error al procesar la encuesta.")
            return
        
        if poll_id not in pending_polls:
            logging.warning(f"Poll ID {poll_id} not found in pending_polls")
            await query.edit_message_text("⚠️ Esta encuesta ya fue procesada.")
            return
        
        poll_data = pending_polls[poll_id]
        
        if query.data.startswith("approve_poll_"):
            try:
                sent_poll = await context.bot.send_poll(
                    chat_id=PUBLIC_CHANNEL,
                    question=poll_data["question"],
                    options=poll_data["options"],
                    is_anonymous=poll_data["is_anonymous"],
                    type=poll_data["type"],
                    allows_multiple_answers=poll_data["allows_multiple_answers"]
                )
                logging.info(f"Poll {poll_id} approved and sent to channel")
            except Exception as e:
                logging.error(f"Error sending poll: {e}")
                await query.edit_message_text("❌ Error al publicar la encuesta.")
                return
            
            try:
                await context.bot.send_message(
                    chat_id=poll_data["user_id"],
                    text="🎉 Tu encuesta ha sido aprobada y publicada."
                )
            except Exception as e:
                logging.warning(f"Could not notify user: {e}")
            
            await query.edit_message_text(f"✅ Encuesta {poll_id} aprobada y publicada")
        else:
            try:
                await context.bot.send_message(
                    chat_id=poll_data["user_id"],
                    text="❌ Tu encuesta no cumple con nuestras normas."
                )
            except Exception as e:
                logging.warning(f"Could not notify user: {e}")
            
            await query.edit_message_text(f"❌ Encuesta {poll_id} rechazada")
        
        del pending_polls[poll_id]
        logging.info(f"Poll {poll_id} processed and removed from pending")
    
    # Procesar confesiones de texto (tienen 2 partes: approve_123)
    elif query.data.startswith("approve_") or query.data.startswith("reject_"):
        try:
            parts = query.data.split("_")
            # Verificar que no sea una encuesta (si tiene 3 partes es encuesta)
            if len(parts) == 2:
                confession_id = int(parts[1])
                logging.info(f"Processing confession ID: {confession_id}")
            else:
                logging.warning(f"Invalid confession format: {query.data}")
                return
        except (IndexError, ValueError) as e:
            logging.error(f"Error processing confession: {e}")
            await query.edit_message_text("⚠️ Error al procesar la confesión.")
            return
        
        if confession_id not in pending_confessions:
            logging.warning(f"Confession ID {confession_id} not found in pending_confessions")
            await query.edit_message_text("⚠️ Esta confesión ya fue procesada.")
            return
        
        confession_data = pending_confessions[confession_id]
        
        if query.data.startswith("approve_"):
            try:
                await context.bot.send_message(
                    chat_id=PUBLIC_CHANNEL,
                    text=f"📢 Confesión anónima:\n\n{confession_data['text']}"
                )
                logging.info(f"Confession {confession_id} approved and sent to channel")
            except Exception as e:
                logging.error(f"Error sending confession: {e}")
                await query.edit_message_text("❌ Error al publicar la confesión.")
                return
            
            try:
                await context.bot.send_message(
                    chat_id=confession_data["user_id"],
                    text="🎉 Tu confesión ha sido aprobada y publicada."
                )
            except Exception as e:
                logging.warning(f"Could not notify user: {e}")
            
            await query.edit_message_text(f"✅ Confesión {confession_id} aprobada y publicada")
        else:
            try:
                await context.bot.send_message(
                    chat_id=confession_data["user_id"],
                    text="❌ Tu confesión no cumple con nuestras normas."
                )
            except Exception as e:
                logging.warning(f"Could not notify user: {e}")
            
            await query.edit_message_text(f"❌ Confesión {confession_id} rechazada")
        
        del pending_confessions[confession_id]
        logging.info(f"Confession {confession_id} processed and removed from pending")

async def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("confesión", confesion))
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
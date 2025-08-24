import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from ..config import pending_confessions, pending_polls, user_last_confession, banned_users
from ..utils.helpers import is_user_banned, check_rate_limit, generate_id
from .moderation import send_to_moderation

async def handle_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.poll && update.message.chat.type != "private":
        await update.message.reply_text("⚠️ Solo acepto confesiones en texto o encuestas nativas de Telegram.")

async def handle_confession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    user_id = update.message.from_user.id
    
    # Verificar baneo
    banned, message = is_user_banned(user_id, banned_users)
    if banned:
        await update.message.reply_text(message)
        return

    # Verificar si es encuesta
    if update.message.poll:
        await handle_poll(update, context)
        return

    # Verificar rate limit
    rate_limited, message = check_rate_limit(user_id, user_last_confession)
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
    banned, message = is_user_banned(user_id, banned_users)
    if banned:
        await update.message.reply_text(message)
        return

    # Verificar rate limit
    rate_limited, message = check_rate_limit(user_id, user_last_confession)
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
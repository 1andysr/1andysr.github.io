import time
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from ..config import pending_confessions, pending_polls, banned_users, MODERATION_GROUP_ID, PUBLIC_CHANNEL
from ..utils.helpers import generate_id

async def send_to_moderation(context, item_id, confession_text, user_id, is_poll=False, poll_data=None):
    if is_poll:
        options_text = "\n".join([f"• {option}" for option in poll_data["options"]])
        message_text = (
            f"📊 Nueva encuesta (ID: {item_id}) - User: {user_id}:\n\n"
            f"Pregunta: {poll_data['question']}\n\nOpciones:\n{options_text}\n\n"
            f"Tipo: {poll_data['type']}\nAnónima: {'Sí' if poll_data['is_anonymous'] else 'No'}\n"
            f"Múltiples respuestas: {'Sí' if poll_data['allows_multiple_answers'] else 'No'}"
        )
        callback_prefix = "poll"
    elif is_audio:
        message_text = (
            f"🎵 Nueva audio confesión (ID: {item_id}) - User: {user_id}:\n\n"
            f"Duración: {audio_data['duration']} segundos\n"
            f"Tamaño: {audio_data['file_size']} bytes\n"
            f"File ID: {audio_data['file_id']}"
        )
        callback_prefix = "audio"    
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

    if is_audio:
        await context.bot.send_audio(
            chat_id=MODERATION_GROUP_ID,
            audio=audio_data['file_id'],
            caption=message_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await context.bot.send_message(
            chat_id=MODERATION_GROUP_ID,
            text=message_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_sancion_menu(query, item_id, is_poll, user_id):
    prefix = "poll" if is_poll else "conf"
    
    keyboard = [
        [
            InlineKeyboardButton("1 hora", callback_data=f"ban_1_{item_id}_{prefix}_{user_id}"),
            InlineKeyboardButton("2 horas", callback_data=f"ban_2_{item_id}_{prefix}_{user_id}"),
            InlineKeyboardButton("4 horas", callback_data=f"ban_4_{item_id}_{prefix}_{user_id}"),
            InlineKeyboardButton("24 horas", callback_data=f"ban_24_{item_id}_{prefix}_{user_id}")
        ],
        [
            InlineKeyboardButton("↩️ Cancelar", callback_data=f"cancel_{item_id}_{prefix}")
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

async def approve_item(item_id, is_poll, context):
    if is_poll:
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
    elif item_type == "audio":
        audio_data = pending_audios[item_id]
        await context.bot.send_audio(
            chat_id=PUBLIC_CHANNEL,
            audio=audio_data["file_id"],
            caption="🎵 Confesión anónima en audio"
        )
        del pending_audios[item_id]
        return audio_data["user_id"], "audio confesión"
    else:
        confession_data = pending_confessions[item_id]
        await context.bot.send_message(
            chat_id=PUBLIC_CHANNEL,
            text=f"📢 Confesión anónima:\n\n{confession_data['text']}"
        )
        del pending_confessions[item_id]
        return confession_data["user_id"], "confesión"

async def reject_item(item_id, is_poll):
    if is_poll:
        user_id = pending_polls[item_id]["user_id"]
        del pending_polls[item_id]
    else:
        user_id = pending_confessions[item_id]["user_id"]
        del pending_confessions[item_id]
    return user_id
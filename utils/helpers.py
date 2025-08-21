import time
import logging
from typing import Dict

def is_user_banned(user_id: int, banned_users: Dict[int, float]) -> tuple:
    current_time = time.time()
    if user_id in banned_users and current_time < banned_users[user_id]:
        remaining_time = int(banned_users[user_id] - current_time)
        hours = remaining_time // 3600
        minutes = (remaining_time % 3600) // 60
        return True, f"🚫 Estás baneado. Tiempo restante: {hours}h {minutes}m"
    return False, ""

def check_rate_limit(user_id: int, user_last_confession: Dict[int, float]) -> tuple:
    current_time = time.time()
    if user_id in user_last_confession:
        time_since_last = current_time - user_last_confession[user_id]
        if time_since_last < 60:
            remaining_time = int(60 - time_since_last)
            return True, f"⏰ Por favor espera {remaining_time} segundos antes de enviar otra confesión."
    return False, ""

def generate_id(*args) -> int:
    return abs(hash("".join(str(arg) for arg in args))) % (10**8)
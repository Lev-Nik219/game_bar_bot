from functools import wraps
from aiogram import types
from database import get_user

def require_started():
    def decorator(func):
        @wraps(func)
        async def wrapper(message: types.Message, *args, **kwargs):
            user_id = message.from_user.id
            user_data = await get_user(user_id)
            has_started = user_data[10]
            if not has_started:
                from handlers.main_bot.profile import show_welcome_with_invite
                await show_welcome_with_invite(
                    message, user_id,
                    message.from_user.first_name,
                    message.from_user.username,
                    message.bot
                )
                return
            return await func(message, *args, **kwargs)
        return wrapper
    return decorator

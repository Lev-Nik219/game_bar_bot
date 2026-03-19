from aiogram import Router, types
from aiogram.filters import StateFilter
from aiogram.types import ReplyKeyboardRemove
from database import get_user
from .common import get_game_over_text_and_keyboard
from .profile import show_agreement, show_welcome_with_invite

router = Router()

@router.message(StateFilter(None))
async def any_message_without_state(message: types.Message):
    # Эта функция будет вызываться только после middleware, так что пользователь уже прошёл проверку
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    user_data = await get_user(user_id, username)
    agreed = user_data[9]
    has_started = user_data[10]

    # Если согласие не принято или не начал игру – middleware должен был перенаправить,
    # но на всякий случай оставим защиту
    if not agreed:
        await show_agreement(message)
        return
    if agreed and not has_started:
        await show_welcome_with_invite(message, user_id, first_name, username, message.bot)
        return

    text, keyboard = await get_game_over_text_and_keyboard(user_id, first_name, username)
    await message.answer("Используйте кнопки меню.", reply_markup=keyboard)
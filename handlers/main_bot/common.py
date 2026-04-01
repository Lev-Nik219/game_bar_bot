import random
from aiogram import types
from database import get_user, check_referral_bonus
from keyboards import main_reply_keyboard

async def get_game_over_text_and_keyboard(user_id: int, first_name: str, username: str = None):
    """
    Возвращает текст и клавиатуру для экрана завершения игры (и для команды /start).
    """
    # Распаковываем все 16 значений
    (balance, total_games, wins, level, exp, theme, dbl, daily_streak, ts,
     agreed, has_started, referral_count, referral_earnings,
     current_win_streak, max_win_streak, withdrawals_count) = await get_user(user_id, username)

    win_percent = (wins / total_games * 100) if total_games > 0 else 0
    name = first_name if first_name and first_name != "Game_bar" else (username if username else "Игрок")
    text = (
        f"{name}, ✨ у тебя все получится!\n"
        f"Баланс: {balance} 💎\n"
        f"Процент побед: {win_percent:.1f}%\n"
        f"Выберите действие:⤵️"
    )
    keyboard = main_reply_keyboard()
    return text, keyboard

async def check_zero_balance_and_notify(message: types.Message, user_id: int):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    balance, *_ = await get_user(user_id, None)
    if balance == 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit")]
        ])
        await message.answer(
            "⚠️ У вас закончились баллы. Пополните баланс, чтобы продолжить играть!",
            reply_markup=keyboard
        )

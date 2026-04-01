import random
import logging
from aiogram import types
from aiogram.fsm.context import FSMContext

logger = logging.getLogger(__name__)

def adjust_win(win: bool, winnings: int, bet: int, factor: float = 0.2) -> tuple[bool, int]:
    """
    Корректирует исход игры для снижения процента побед.
    Если исход был выигрышным, с вероятностью WIN_REDUCTION_FACTOR превращаем его в проигрыш.
    """
    if win and random.random() < factor:
        return False, -bet
    return win, winnings

async def cancel_on_max_attempts(message: types.Message, state: FSMContext, main_menu_keyboard_func):
    user_id = message.from_user.id
    await state.clear()
    await message.answer(
        "❌ Слишком много неудачных попыток. Возврат в меню.",
        reply_markup=main_menu_keyboard_func(user_id)
    )

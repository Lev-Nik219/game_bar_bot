import asyncio
import time
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import (
    get_user, add_cashback, get_weekly_losses,
    get_last_cashback_time, set_last_cashback_time
)

logger = logging.getLogger(__name__)
router = Router()

CASHBACK_PERCENT = 5  # 5% кэшбек

async def process_cashback(user_id: int, bot) -> bool:
    """Проверяет и начисляет кэшбек, если прошла неделя."""
    last_cashback = await get_last_cashback_time(user_id)
    now = int(time.time())
    week_ago = now - 7 * 86400
    
    if last_cashback > week_ago:
        return False
    
    weekly_losses = await get_weekly_losses(user_id)
    if weekly_losses <= 0:
        await set_last_cashback_time(user_id, now)
        return False
    
    cashback_amount = int(weekly_losses * CASHBACK_PERCENT / 100)
    if cashback_amount <= 0:
        await set_last_cashback_time(user_id, now)
        return False
    
    await add_cashback(user_id, cashback_amount)
    await set_last_cashback_time(user_id, now)
    
    await bot.send_message(
        user_id,
        f"💰 <b>Кэшбек 5%!</b>\n\n"
        f"За последнюю неделю вы проиграли {weekly_losses} баллов.\n"
        f"Вам начислено {cashback_amount} бонусных баллов!\n\n"
        f"🎲 Отыграйте их с вейджером 3x, чтобы вывести.",
        parse_mode="HTML"
    )
    return True

@router.message(Command("cashback"))
async def cmd_cashback(message: types.Message):
    """Ручная проверка кэшбека (для теста)."""
    user_id = message.from_user.id
    await process_cashback(user_id, message.bot)
    await message.answer("✅ Проверка кэшбека выполнена.")
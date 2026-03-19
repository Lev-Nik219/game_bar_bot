import logging
import aiogram.exceptions
from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import get_bot_stats
from keyboards import bot_info_keyboard

logger = logging.getLogger(__name__)
router = Router()

@router.message(F.text == "ℹ️ О боте")
async def bot_info(message: types.Message):
    stats = await get_bot_stats()
    text = (
        f"📚 Информация о нашем боте:\n\n"
        f"🕜 Работаем дней: {stats['days']}\n"
        f"👨 Всего пользователей: {stats['total_users']}\n"
        f"😺 Новых за сегодня: {stats['new_today']}\n\n"
        f"🎰 Сегодня игр: 0 (в разработке)\n"
        f"🎰 Всего игр: {stats['total_games']}\n\n"
        f"💵 Выплачено всего: {stats['total_paid']} 💎"
    )
    await message.answer(text, reply_markup=bot_info_keyboard())

@router.callback_query(F.data == "bot_info_faq")
async def faq_callback(callback: types.CallbackQuery):
    await callback.answer()
    faq_text = "❓ Часто задаваемые вопросы:\n\n1. Как начать играть?\n   Нажмите «Играть» и выберите игру.\n\n2. Как пополнить баланс?\n   Зайдите в профиль и выберите «Пополнить».\n\n3. Как вывести средства?\n   В профиле нажмите «Вывести» и следуйте инструкциям.\n\n4. Что такое бонусный баланс?\n   Это сумма всех полученных вами бонусов.\n\n5. Как получить реферальную ссылку?\n   В главном меню нажмите «Пригласить друга».\n\nЕсли у вас остались вопросы, свяжитесь с администратором через кнопку ниже."
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💼 Связаться с администратором", callback_data="contact_admin")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="bot_info_back")]
    ])
    try:
        await callback.message.edit_text(faq_text, reply_markup=keyboard)
    except aiogram.exceptions.TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise

@router.callback_query(F.data == "contact_admin")
async def contact_admin_callback(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "👨‍💼 Для связи с администратором используйте бота поддержки: @lnAid_Bot\n\n"
        "Нажмите на ссылку, чтобы перейти: https://t.me/lnAid_Bot"
    )

@router.callback_query(F.data == "bot_info_back")
async def bot_info_back(callback: types.CallbackQuery):
    await callback.answer()
    stats = await get_bot_stats()
    text = (
        f"📚 Информация о нашем боте:\n\n"
        f"🕜 Работаем дней: {stats['days']}\n"
        f"👨 Всего пользователей: {stats['total_users']}\n"
        f"😺 Новых за сегодня: {stats['new_today']}\n\n"
        f"🎰 Сегодня игр: 0 (в разработке)\n"
        f"🎰 Всего игр: {stats['total_games']}\n\n"
        f"💵 Выплачено всего: {stats['total_paid']} 💎"
    )
    try:
        await callback.message.edit_text(text, reply_markup=bot_info_keyboard())
    except aiogram.exceptions.TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
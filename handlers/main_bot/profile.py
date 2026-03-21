import random
import logging
import time
import asyncio
import aiogram.exceptions
from aiogram import Router, types, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove

from database import (
    get_user, get_user_stats, update_balance, claim_daily_bonus,
    get_bonus_total, set_user_started, log_agreement,
    increment_referral_count, increment_withdrawals_count,
    get_active_tournament, get_tournament_leaders,
    create_withdraw_request
)
from keyboards import (
    profile_keyboard, main_reply_keyboard, games_menu_keyboard,
    back_to_menu_keyboard, agreement_short_keyboard, agreement_keyboard,
    achievements_menu_keyboard, achievements_back_keyboard
)
from states import WithdrawStates
from config import ADMIN_IDS, ADMIN_BOT_TOKEN
from .common import get_game_over_text_and_keyboard, check_zero_balance_and_notify
from agreement_logger import log_agreement_to_csv
from constants import WELCOME_WITH_INVITE_TEMPLATE

logger = logging.getLogger(__name__)
router = Router()

async def get_profile_text(user_id: int, username: str = None) -> str:
    (balance, total_games, wins, level, exp, theme, dbl, daily_streak, ts,
     agreed, has_started, referral_count, referral_earnings,
     current_win_streak, max_win_streak, withdrawals_count) = await get_user(user_id, username)
    bonus_total = await get_bonus_total(user_id)
    win_percent = (wins / total_games * 100) if total_games > 0 else 0
    return (f"👤 <b>Профиль</b>\n"
            f"Баланс: {balance} 💎\n"
            f"Бонусный баланс: {bonus_total} 💎\n"
            f"Уровень: {level} (опыт: {exp}/{level*100})\n"
            f"Всего игр: {total_games}\n"
            f"Побед: {wins}\n"
            f"Процент побед: {win_percent:.1f}%")

async def show_agreement(message: types.Message):
    from constants import AGREEMENT_SHORT
    await message.answer(
        AGREEMENT_SHORT,
        parse_mode="HTML",
        reply_markup=agreement_short_keyboard()
    )

async def show_full_agreement(message: types.Message):
    from constants import AGREEMENT_FULL
    await message.answer(
        AGREEMENT_FULL,
        reply_markup=agreement_keyboard()
    )

async def show_welcome_with_invite(
    message: types.Message, user_id: int, first_name: str, username: str, bot
):
    balance, *_ = await get_user(user_id, username)
    text = WELCOME_WITH_INVITE_TEMPLATE.format(first_name=first_name, balance=balance)
    inline_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пригласить друга", callback_data="invite_friend")],
        [InlineKeyboardButton(text="🎮 Начать игру", callback_data="back_to_menu")]
    ])
    await message.answer(text, reply_markup=inline_keyboard)

# --- Команды ---
@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    args = message.text.split()
    ref_id = None
    if len(args) > 1:
        try:
            ref_id = int(args[1])
        except ValueError:
            pass

    user_data = await get_user(user_id, username)
    agreed = user_data[9]
    has_started = user_data[10]

    if ref_id is not None and ref_id != user_id:
        from database import init_db_pool
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT invited_by FROM users WHERE user_id = $1", user_id)
            if row and row['invited_by'] is None:
                await conn.execute("UPDATE users SET invited_by = $1 WHERE user_id = $2", ref_id, user_id)
                await increment_referral_count(ref_id)
        await pool.close()

    if not agreed or (agreed and not has_started):
        await message.answer("🔄 Загрузка...", reply_markup=ReplyKeyboardRemove())

    if not agreed:
        await show_agreement(message)
        return

    if agreed and not has_started:
        await show_welcome_with_invite(message, user_id, first_name, username, message.bot)
        return

    await state.clear()
    text, keyboard = await get_game_over_text_and_keyboard(
        user_id, first_name, username
    )
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.message(Command("myid"))
async def cmd_myid(message: types.Message):
    await message.answer(f"Ваш Telegram ID: {message.from_user.id}")

# --- Обработчики reply-кнопок главного меню ---
@router.message(F.text == "🎰 Сыграть")
async def reply_play(message: types.Message):
    await message.answer("🎮 Выберите игру:", reply_markup=games_menu_keyboard())

@router.message(F.text == "👤 Мой профиль")
async def reply_profile(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    profile_text = await get_profile_text(user_id, username)
    await message.answer(
        profile_text,
        parse_mode="HTML",
        reply_markup=profile_keyboard(user_id)
    )

@router.message(F.text == "🏆 Турниры")
async def reply_tournaments(message: types.Message):
    from .tournaments import get_tournament_message
    text, keyboard = await get_tournament_message(message.from_user.id, message.bot)
    await message.answer(text, reply_markup=keyboard)

@router.message(F.text == "ℹ️ О боте")
async def reply_bot_info(message: types.Message):
    from .bot_info import bot_info
    await bot_info(message)

@router.message(F.text == "🎁 Ежедневный бонус")
async def reply_daily_bonus(message: types.Message):
    user_id = message.from_user.id
    success, new_balance = await claim_daily_bonus(user_id)
    back_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
    ])
    if success:
        await message.answer("🎉 Вы получили 20 бонусных баллов!", reply_markup=back_button)
        profile_text = await get_profile_text(user_id, message.from_user.username)
        await message.answer(
            profile_text,
            parse_mode="HTML",
            reply_markup=profile_keyboard(user_id)
        )
    else:
        user_data = await get_user(user_id)
        last_bonus = user_data[7]  # daily_bonus_last
        now = int(time.time())
        next_day_start = (now // 86400 + 1) * 86400
        seconds_left = next_day_start - now
        hours = seconds_left // 3600
        minutes = (seconds_left % 3600) // 60
        await message.answer(
            f"❌ Вы уже получали бонус сегодня. Следующий через {hours} ч {minutes} мин.",
            reply_markup=back_button
        )

@router.message(F.text == "👥 Пригласить друга")
async def reply_invite_friend(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    user_data = await get_user(user_id, username)
    referral_count = user_data[11]
    referral_earnings = user_data[12]

    bot_username = (await message.bot.me()).username
    link = f"https://t.me/{bot_username}?start={user_id}"

    text = (
        f"👥 Партнёрская программа:\n\n"
        f"Приглашайте игроков и получайте:\n"
        f"● 30 баллов за первую игру друга\n"
        f"● 15% от депозита партнёра\n\n"
        f"👥 Вы пригласили: {referral_count} чел\n"
        f"🔀 Доход от рефералов: {referral_earnings / 2:.2f} руб\n\n"
        f"🔗 Ваша партнёрская ссылка:\n{link}\n\n"
        f"📢 Приглашай по этой ссылке своих друзей, отправляй её во все чаты и зарабатывай деньги!"
    )
    await message.answer(text)

# --- Callback-обработчики ---
@router.callback_query(F.data == "profile")
async def profile_callback(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    username = callback.from_user.username
    profile_text = await get_profile_text(user_id, username)
    await callback.message.edit_text(
        profile_text,
        parse_mode="HTML",
        reply_markup=profile_keyboard(user_id)
    )

# ===== Достижения =====
@router.callback_query(F.data == "achievements")
async def achievements_menu_callback(callback: types.CallbackQuery):
    await callback.answer()
    text = "🏆 Раздел достижений\n\nВыберите действие:"
    await callback.message.edit_text(text, reply_markup=achievements_menu_keyboard())

@router.callback_query(F.data == "achievements_all")
async def achievements_all_callback(callback: types.CallbackQuery):
    await callback.answer()
    all_achievements = [
        ("first_win", "Первая победа", 50),
        ("10_wins", "10 побед", 200),
        ("100_games", "100 игр", 300),
        ("streak_3", "Везунчик (3 победы подряд)", 100),
        ("streak_5", "Удачливый (5 побед подряд)", 250),
        ("streak_10", "Непобедимый (10 побед подряд)", 500),
        ("daily_7", "Бонус-хантер (7 дней бонуса подряд)", 200),
        ("ref_1", "Друг человека (1 приглашённый)", 100),
        ("ref_3", "Популярный (3 приглашённых)", 300),
        ("ref_5", "Лидер (5 приглашённых)", 500),
        ("rich_5000", "Богач (5000 баллов)", 400),
        ("games_500", "Игроман (500 игр)", 600),
        ("tournament_5", "Турнирный боец (5 турниров)", 350),
    ]
    text = "📋 Все достижения:\n\n"
    for ach_id, name, prize in all_achievements:
        text += f"• {name} — {prize} 💎\n"
    await callback.message.edit_text(text, reply_markup=achievements_back_keyboard())

@router.callback_query(F.data == "achievements_my")
async def achievements_my_callback(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    from database import init_db_pool
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT achievement_id FROM achievements WHERE user_id = $1", user_id)
    await pool.close()
    if rows:
        achievement_names = {
            'first_win': 'Первая победа',
            '10_wins': '10 побед',
            '100_games': '100 игр',
            'streak_3': 'Везунчик (3 победы подряд)',
            'streak_5': 'Удачливый (5 побед подряд)',
            'streak_10': 'Непобедимый (10 побед подряд)',
            'daily_7': 'Бонус-хантер (7 дней бонуса подряд)',
            'ref_1': 'Друг человека (1 приглашённый)',
            'ref_3': 'Популярный (3 приглашённых)',
            'ref_5': 'Лидер (5 приглашённых)',
            'rich_5000': 'Богач (5000 баллов)',
            'games_500': 'Игроман (500 игр)',
            'tournament_5': 'Турнирный боец (5 турниров)',
        }
        text = "🏆 Твои достижения:\n" + "\n".join(
            f"• {achievement_names.get(row['achievement_id'], row['achievement_id'])}" for row in rows
        )
    else:
        text = "У тебя пока нет достижений. Играй и побеждай!"
    await callback.message.edit_text(text, reply_markup=achievements_back_keyboard())

@router.callback_query(F.data == "achievements_menu")
async def achievements_menu_back_callback(callback: types.CallbackQuery):
    await callback.answer()
    text = "🏆 Раздел достижений\n\nВыберите действие:"
    await callback.message.edit_text(text, reply_markup=achievements_menu_keyboard())

# ===== Конец достижений =====

# --- Вывод средств ---
@router.callback_query(F.data == "withdraw")
async def withdraw_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    username = callback.from_user.username
    user_data = await get_user(user_id, username)
    balance = user_data[0]
    withdrawals_count = user_data[15]

    if balance < 10:
        await callback.answer(
            f"❌ Минимальная сумма вывода — 10 баллов. У вас {balance}",
            show_alert=True
        )
        return

    if withdrawals_count == 0:
        rate = 4.5
        rate_text = "4.5 балла = 1 рубль (первый вывод)"
    else:
        rate = 2.0
        rate_text = "2 балла = 1 рубль"

    max_rub = int(balance / rate)
    max_usdt = round(max_rub / 90, 2) if max_rub > 0 else 0

    await state.set_state(WithdrawStates.waiting_for_amount)
    await callback.message.edit_text(
        f"💸 Введите сумму для вывода в баллах (минимум 10, максимум {balance}):\n\n"
        f"Курс: {rate_text}\n"
        f"Вы получите примерно {max_rub} руб ≈ {max_usdt} USDT (1 USDT ≈ 90 руб)\n\n"
        f"<i>Примечание: первый вывод по специальному курсу 4.5 балла = 1 рубль.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="profile")]
        ])
    )

@router.message(WithdrawStates.waiting_for_amount, F.text)
async def withdraw_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        user_id = message.from_user.id
        username = message.from_user.username
        user_data = await get_user(user_id, username)
        balance = user_data[0]

        if amount < 10 or amount > balance:
            await message.answer(f"❌ Сумма должна быть от 10 до {balance}")
            return

        await state.update_data(amount=amount)
        await state.set_state(WithdrawStates.waiting_for_wallet)
        await message.answer(
            "📤 Введите ваш контакт для связи (например, @username или номер телефона, "
            "к которому привязан ваш Telegram):\n"
            "<i>Админ отправит вам ваши средства с помощью @send</i>",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("❌ Введите число")

@router.message(WithdrawStates.waiting_for_wallet, F.text)
async def withdraw_wallet(message: types.Message, state: FSMContext):
    data = await state.get_data()
    amount_points = data['amount']
    user_id = message.from_user.id
    contact = message.text.strip()
    username = message.from_user.username

    user_data = await get_user(user_id, username)
    balance = user_data[0]
    withdrawals_count = user_data[15]

    if balance < amount_points:
        await message.answer("❌ Недостаточно средств.")
        await state.clear()
        return

    if withdrawals_count == 0:
        rate = 4.5
        rate_text = "4.5"
    else:
        rate = 2.0
        rate_text = "2"

    new_balance = balance - amount_points
    await update_balance(user_id, new_balance)

    amount_rub = round(amount_points / rate, 2)
    amount_usdt = round(amount_rub / 90, 2)

    await create_withdraw_request(user_id, amount_points, amount_usdt, contact)

    await increment_withdrawals_count(user_id)

    asyncio.create_task(notify_admins_about_withdraw(
        user_id, amount_points, amount_rub, amount_usdt, contact,
        username, message.bot, rate_text
    ))

    await message.answer(
        f"✅ Заявка на вывод {amount_points} баллов (≈{amount_rub} руб ≈ {amount_usdt} USDT) создана!\n"
        f"Ожидайте подтверждения администратора.",
        reply_markup=profile_keyboard(user_id)
    )
    await state.clear()

async def notify_admins_about_withdraw(
    user_id: int, amount_points: int, amount_rub: float,
    amount_usdt: float, contact: str, username: str, bot: Bot, rate_text: str
):
    try:
        admin_bot = Bot(token=ADMIN_BOT_TOKEN)
        for admin_id in ADMIN_IDS:
            try:
                user_link = f"tg://user?id={user_id}"
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✅ Подтвердить вывод",
                        callback_data=f"admin_confirm_withdraw_{user_id}_{amount_points}"
                    )],
                    [InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"admin_reject_withdraw_{user_id}"
                    )]
                ])
                await admin_bot.send_message(
                    admin_id,
                    f"🔔 <b>Новая заявка на вывод!</b>\n"
                    f"Пользователь: <a href='{user_link}'>{username} (ID: {user_id})</a>\n"
                    f"Контакт: {contact}\n"
                    f"Сумма: {amount_points} баллов = {amount_rub} руб (курс {rate_text}) "
                    f"≈ {amount_usdt} USDT",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")
        await admin_bot.session.close()
    except Exception as e:
        logger.error(f"Критическая ошибка в фоновой задаче уведомления админов: {e}")

# --- Обработчики для соглашения ---
@router.callback_query(F.data == "read_full_agreement")
async def read_full_agreement_callback(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    await show_full_agreement(callback.message)

@router.callback_query(F.data == "accept_agreement")
async def accept_agreement_callback(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    username = callback.from_user.username
    first_name = callback.from_user.first_name

    current_balance, *_ = await get_user(user_id, username)
    new_balance = current_balance + 50
    await update_balance(user_id, new_balance)

    try:
        await log_agreement(user_id)
        log_agreement_to_csv(user_id, username)
    except Exception as e:
        logger.error(f"Ошибка логирования соглашения: {e}")

    await callback.message.answer("🎁 Вы получили 50 бонусных баллов за принятие соглашения!")
    await callback.message.delete()
    await show_welcome_with_invite(
        callback.message, user_id, first_name, username, callback.bot
    )

@router.callback_query(F.data == "invite_friend")
async def invite_friend_callback(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    bot_username = (await callback.bot.me()).username
    link = f"https://t.me/{bot_username}?start={user_id}"
    await callback.message.answer(
        f"🔗 Твоя реферальная ссылка:\n{link}\n\n"
        f"Отправь её другу. Как только он перейдёт по ней и сыграет одну игру, "
        f"вы оба получите по 30 баллов!"
    )

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    username = callback.from_user.username
    first_name = callback.from_user.first_name

    await set_user_started(user_id)

    text, keyboard = await get_game_over_text_and_keyboard(
        user_id, first_name, username
    )
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
import logging
import time
import asyncio
import aiosqlite
from datetime import datetime
from aiogram import Router, types, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove

from database import (
    get_user, get_user_stats, update_balance, claim_daily_bonus,
    get_bonus_total, set_user_started, log_agreement,
    increment_referral_count, increment_withdrawals_count,
    create_withdraw_request, get_demo_games_played,
    get_daily_withdrawn, get_last_deposit_time, get_pending_withdraw_count,
    get_daily_total_withdrawn_rub, get_bonus_wagering_status, update_bonus_wagered,
    DB_NAME
)
from keyboards import (
    profile_keyboard, main_reply_keyboard, games_menu_keyboard,
    back_to_menu_keyboard, agreement_short_keyboard, agreement_keyboard,
    achievements_menu_keyboard, achievements_back_keyboard
)
from states import WithdrawStates
from config import (
    ADMIN_IDS, ADMIN_BOT_TOKEN, ADMIN_NAMES,
    FIRST_WITHDRAW_RATE, STANDARD_WITHDRAW_RATE, USD_RATE,
    REFERRAL_BONUS_THRESHOLDS, MIN_GAMES_BEFORE_WITHDRAW,
    DAILY_WITHDRAW_LIMIT, WITHDRAW_COOLDOWN_HOURS,
    BONUS_WAGER_MULTIPLIER, DAILY_PAYOUT_LIMIT_RUB
)
from .common import get_game_over_text_and_keyboard, check_zero_balance_and_notify
from agreement_logger import log_agreement_to_csv
from constants import WELCOME_WITH_INVITE_TEMPLATE, AGREEMENT_SHORT, AGREEMENT_FULL

logger = logging.getLogger(__name__)
router = Router()

async def get_profile_text(user_id: int, username: str = None) -> str:
    (balance, total_games, wins, level, exp, theme, dbl, daily_streak, ts,
     agreed, has_started, referral_count, referral_earnings,
     current_win_streak, max_win_streak, withdrawals_count) = await get_user(user_id, username)
    bonus_total = await get_bonus_total(user_id)
    real_balance = balance - bonus_total
    win_percent = (wins / total_games * 100) if total_games > 0 else 0
    
    bonus_balance, bonus_wagered, is_cleared = await get_bonus_wagering_status(user_id)
    wagering_status = ""
    if not is_cleared and bonus_balance > 0:
        required = bonus_balance * BONUS_WAGER_MULTIPLIER
        remaining = required - bonus_wagered
        wagering_status = f"\n🎲 Отыгрыш бонуса: {bonus_wagered}/{required} баллов (осталось {remaining})"
    
    return (f"👤 <b>Профиль</b>\n"
            f"Баланс: {balance} 💎\n"
            f"Бонусный баланс: {bonus_total} 💎\n"
            f"Доступно для вывода: {real_balance} 💎\n"
            f"Уровень: {level} (опыт: {exp}/{level*100})\n"
            f"Всего игр: {total_games}\n"
            f"Побед: {wins}\n"
            f"Процент побед: {win_percent:.1f}%{wagering_status}")

async def show_agreement(message: types.Message):
    await message.answer(
        AGREEMENT_SHORT,
        parse_mode="HTML",
        reply_markup=agreement_short_keyboard()
    )

async def show_full_agreement(message: types.Message):
    await message.answer(
        AGREEMENT_FULL,
        reply_markup=agreement_keyboard()
    )

async def show_welcome_with_invite(
    message: types.Message, user_id: int, first_name: str, username: str, bot
):
    balance, *_ = await get_user(user_id, username)
    display_name = username if username else first_name
    text = WELCOME_WITH_INVITE_TEMPLATE.format(username=display_name, balance=balance)
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
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT invited_by FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row and row[0] is None:
                await db.execute("UPDATE users SET invited_by = ? WHERE user_id = ?", (ref_id, user_id))
                await db.commit()
                await increment_referral_count(ref_id)

    if not agreed or (agreed and not has_started):
        await message.answer("🔄 Загрузка...", reply_markup=ReplyKeyboardRemove())

    if not agreed:
        await show_agreement(message)
        return

    if agreed and not has_started:
        await show_welcome_with_invite(message, user_id, first_name, username, message.bot)
        return

    await state.clear()
    text, keyboard = await get_game_over_text_and_keyboard(user_id, first_name, username)
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
    
    user_data = await get_user(user_id)
    daily_streak = user_data[7]
    remaining_days = 7 - daily_streak
    streak_text = f"\n\n🔥 {daily_streak} {'день' if daily_streak == 1 else 'дня' if daily_streak in [2,3,4] else 'дней'} подряд! Осталось {remaining_days} {'день' if remaining_days == 1 else 'дня' if remaining_days in [2,3,4] else 'дней'} до супер-бонуса (200 баллов)!"
    
    if success:
        text = f"🎉 Вы получили 20 бонусных баллов!{streak_text}"
        await message.answer(text, reply_markup=back_button)
        profile_text = await get_profile_text(user_id, message.from_user.username)
        await message.answer(
            profile_text,
            parse_mode="HTML",
            reply_markup=profile_keyboard(user_id)
        )
    else:
        now = int(time.time())
        next_day_start = (now // 86400 + 1) * 86400
        seconds_left = next_day_start - now
        hours = seconds_left // 3600
        minutes = (seconds_left % 3600) // 60
        text = f"❌ Вы уже получали бонус сегодня. Следующий через {hours} ч {minutes} мин.{streak_text}"
        await message.answer(text, reply_markup=back_button)

@router.message(F.text == "👥 Пригласить друга")
async def reply_invite_friend(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    user_data = await get_user(user_id, username)
    referral_count = user_data[11]
    referral_earnings = user_data[12]

    next_threshold = None
    for threshold in REFERRAL_BONUS_THRESHOLDS:
        if referral_count < threshold:
            next_threshold = threshold
            break
    if next_threshold is None:
        next_threshold = REFERRAL_BONUS_THRESHOLDS[-1]
        progress_text = "🏆 Вы достигли максимального уровня приглашений!"
    else:
        remaining = next_threshold - referral_count
        filled_bars = referral_count
        empty_bars = next_threshold - filled_bars
        bar = "▓" * filled_bars + "░" * empty_bars
        progress_text = f"🎯 Следующий бонус: {next_threshold} друзей (осталось {remaining})\n[{bar}] {filled_bars}/{next_threshold}"

    rub_earnings = referral_earnings / 2
    bot_username = (await message.bot.me()).username
    link = f"https://t.me/{bot_username}?start={user_id}"

    text = (
        f"👥 **Партнёрская программа**\n\n"
        f"Приглашайте игроков и получайте:\n"
        f"● 30 баллов за первую игру друга\n"
        f"● 15% от депозита партнёра\n\n"
        f"👥 Вы пригласили: **{referral_count}** чел\n"
        f"{progress_text}\n\n"
        f"💰 Доход от рефералов: **{referral_earnings} баллов** ≈ **{rub_earnings:.2f} руб**\n\n"
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
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT achievement_id FROM achievements WHERE user_id = ?", (user_id,))
        rows = await cursor.fetchall()
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
            f"• {achievement_names.get(row[0], row[0])}" for row in rows
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
async def check_withdraw_limits(user_id: int, amount: int, balance: int, bonus_total: int, total_games: int) -> tuple[bool, str]:
    from database import execute_query
    
    real_balance = balance - bonus_total
    
    if real_balance < 10:
        return False, f"❌ Минимальная сумма вывода — 10 баллов. Доступно: {real_balance} баллов."
    
    if amount > real_balance and amount > 0:
        return False, f"❌ Недостаточно средств. Доступно: {real_balance} баллов."
    
    if total_games < MIN_GAMES_BEFORE_WITHDRAW:
        return False, f"❌ Вывод доступен после {MIN_GAMES_BEFORE_WITHDRAW} игр. Сыграно: {total_games}."
    
    # Проверка на активную заявку
    pending_count = await execute_query(
        "SELECT COUNT(*) FROM withdraw_requests WHERE user_id = $1 AND status = 'pending'",
        user_id, fetch_val=True
    )
    if pending_count > 0:
        pending = await execute_query(
            "SELECT id, amount_points, created_at FROM withdraw_requests WHERE user_id = $1 AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
            user_id, fetch_one=True
        )
        if pending:
            req_id, amount_points, created_at = pending
            return False, f"❌ У вас уже есть активная заявка #{req_id} на {amount_points} баллов от {datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M')}. Дождитесь её обработки."
        return False, "❌ У вас уже есть активная заявка на вывод."
    
    daily_withdrawn = await get_daily_withdrawn(user_id)
    if daily_withdrawn + amount > DAILY_WITHDRAW_LIMIT:
        return False, f"❌ Дневной лимит: {DAILY_WITHDRAW_LIMIT} баллов. Сегодня выведено: {daily_withdrawn}."
    
    last_deposit = await get_last_deposit_time(user_id)
    cooldown_seconds = WITHDRAW_COOLDOWN_HOURS * 3600
    if last_deposit > 0 and time.time() - last_deposit < cooldown_seconds:
        hours_left = (cooldown_seconds - (time.time() - last_deposit)) // 3600
        return False, f"❌ Вывод доступен через {hours_left} ч после пополнения."
    
    bonus_balance, bonus_wagered, is_cleared = await get_bonus_wagering_status(user_id)
    if not is_cleared and bonus_balance > 0:
        required = bonus_balance * BONUS_WAGER_MULTIPLIER
        remaining = required - bonus_wagered
        # ПОДРОБНОЕ ПОЯСНЕНИЕ ДЛЯ ПОЛЬЗОВАТЕЛЯ
        return False, (
            f"❌ <b>Бонус не отыгран!</b>\n\n"
            f"У вас есть бонусные баллы: {bonus_balance} 💎\n"
            f"Чтобы их вывести, нужно сначала сыграть на сумму: {required} баллов\n"
            f"Вы уже отыграли: {bonus_wagered} баллов\n"
            f"<b>Осталось отыграть: {remaining} баллов</b>\n\n"
            f"💡 <b>Что это значит?</b>\n"
            f"• Бонусные баллы вы получили бесплатно (за регистрацию или депозит)\n"
            f"• Вы не можете сразу вывести бонус — это защита от мошенников\n"
            f"• Просто продолжайте играть — после отыгрыша бонус станет доступен для вывода\n\n"
            f"🎮 Сыграйте ещё на {remaining} баллов, и бонус разблокируется!"
        )
    
    return True, "OK"

@router.callback_query(F.data == "withdraw")
async def withdraw_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    
    user_id = callback.from_user.id
    username = callback.from_user.username
    user_data = await get_user(user_id, username)
    balance = user_data[0]
    bonus_total = await get_bonus_total(user_id)
    total_games = user_data[1]
    withdrawals_count = user_data[15]
    real_balance = balance - bonus_total
    
    allowed, error_msg = await check_withdraw_limits(user_id, 0, balance, bonus_total, total_games)
    if not allowed:
        # Отправляем сообщение в чат, а не только алерт
        await callback.message.answer(error_msg, parse_mode="HTML")
        return
    
    if withdrawals_count == 0:
        rate = FIRST_WITHDRAW_RATE
        rate_text = f"{FIRST_WITHDRAW_RATE} балла = 1 рубль (первый вывод)"
        explanation = (
            "ℹ️ <b>Почему первый вывод по курсу 3?</b>\n"
            "• Вы получили 50 бонусных баллов за регистрацию\n"
            "• Реферальные бонусы также увеличивают ваш баланс\n"
            "• Это защита от бонус-хантеров, которые пытаются вывести бонусы, не играя\n\n"
            "💡 <b>Совет:</b> Сыграйте 5 игр, и со второго вывода курс станет 1.5 балла = 1 рубль\n"
            "🎁 Вы всё равно в плюсе: за 1000 руб вы получаете 1500 баллов, а вывести можете по 3 (500 руб) + бонусы!"
        )
    else:
        rate = STANDARD_WITHDRAW_RATE
        rate_text = f"{STANDARD_WITHDRAW_RATE} балла = 1 рубль"
        explanation = (
            "ℹ️ Курс вывода: 1.5 балла = 1 рубль\n"
            "🎉 Поздравляем! Вы прошли первый вывод, теперь курс для вас стандартный."
        )
    
    max_rub = int(real_balance / rate)
    max_usdt = round(max_rub / USD_RATE, 2) if max_rub > 0 else 0
    
    await state.set_state(WithdrawStates.waiting_for_amount)
    
    await callback.bot.send_message(
        chat_id=user_id,
        text=(
            f"💸 <b>Вывод средств</b>\n\n"
            f"Введите сумму для вывода (минимум 10, максимум {real_balance} баллов):\n\n"
            f"📊 <b>Ваш баланс:</b>\n"
            f"💰 Общий: {balance} баллов\n"
            f"🎁 Бонусный: {bonus_total} баллов (не выводится)\n"
            f"💎 Доступно: {real_balance} баллов\n\n"
            f"🔄 <b>Курс вывода:</b> {rate_text}\n"
            f"💵 Вы получите примерно: {max_rub} руб ≈ {max_usdt} USDT\n\n"
            f"{explanation}\n\n"
            f"<i>Введите число от 10 до {real_balance}.</i>"
        ),
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
        bonus_total = await get_bonus_total(user_id)
        total_games = user_data[1]
        real_balance = balance - bonus_total
        
        if amount < 10:
            await message.answer("❌ Минимальная сумма — 10 баллов.")
            return
        if amount > real_balance:
            await message.answer(f"❌ Недостаточно средств. Доступно: {real_balance} баллов.")
            return
        
        allowed, error_msg = await check_withdraw_limits(user_id, amount, balance, bonus_total, total_games)
        if not allowed:
            await message.answer(error_msg)
            return
        
        await state.update_data(amount=amount)
        await state.set_state(WithdrawStates.waiting_for_wallet)
        
        withdrawals_count = user_data[15]
        if withdrawals_count == 0:
            rate = FIRST_WITHDRAW_RATE
            rate_text = f"{FIRST_WITHDRAW_RATE} балла = 1 рубль"
        else:
            rate = STANDARD_WITHDRAW_RATE
            rate_text = f"{STANDARD_WITHDRAW_RATE} балла = 1 рубль"
        
        amount_rub = round(amount / rate, 2)
        amount_usdt = round(amount_rub / USD_RATE, 2)
        
        await message.answer(
            f"💸 <b>Вывод средств</b>\n\n"
            f"Вы запросили вывод {amount} баллов.\n\n"
            f"💰 <b>Вы получите:</b>\n"
            f"• {amount_rub} руб (курс {rate_text})\n"
            f"• ≈ {amount_usdt} USDT\n\n"
            f"📤 Введите ваш контакт для связи (@username или номер телефона):\n"
            f"<i>Админ отправит вам средства с помощью @send</i>",
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

    from database import execute_query
    
    # Получаем данные пользователя из PostgreSQL
    row = await execute_query(
        "SELECT balance, total_games, wins, withdrawals_count, bonus_total FROM users WHERE user_id = $1",
        user_id, fetch_one=True
    )
    
    if not row:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    
    balance, total_games, wins, withdrawals_count, bonus_total = row
    real_balance = balance - bonus_total

    # Проверки
    if real_balance < 10:
        await message.answer(f"❌ Минимальная сумма вывода — 10 баллов. Доступно: {real_balance} баллов.")
        await state.clear()
        return
    
    if total_games < MIN_GAMES_BEFORE_WITHDRAW:
        await message.answer(f"❌ Вывод доступен после {MIN_GAMES_BEFORE_WITHDRAW} игр. Сыграно: {total_games}.")
        await state.clear()
        return
    
    if amount_points > real_balance:
        await message.answer(f"❌ Недостаточно средств. Доступно: {real_balance} баллов.")
        await state.clear()
        return

    # Проверка на активную заявку
    pending_count = await execute_query(
        "SELECT COUNT(*) FROM withdraw_requests WHERE user_id = $1 AND status = 'pending'",
        user_id, fetch_val=True
    )
    if pending_count > 0:
        await message.answer("❌ У вас уже есть активная заявка на вывод. Дождитесь её обработки.")
        await state.clear()
        return

    if withdrawals_count == 0:
        rate = FIRST_WITHDRAW_RATE
        rate_text = "2.0"
    else:
        rate = STANDARD_WITHDRAW_RATE
        rate_text = "1.5"

    # Атомарное списание баланса
    result = await execute_query(
        "UPDATE users SET balance = balance - $1 WHERE user_id = $2 AND balance >= $1",
        amount_points, user_id
    )
    
    if not result or 'UPDATE 1' not in result:
        await message.answer("❌ Ошибка списания средств.")
        await state.clear()
        return

    amount_rub = round(amount_points / rate, 2)
    amount_usdt = round(amount_rub / USD_RATE, 2)

    # Создаём заявку
    await execute_query(
        "INSERT INTO withdraw_requests (user_id, amount_points, amount_usdt, wallet_address, status) VALUES ($1, $2, $3, $4, 'pending')",
        user_id, amount_points, amount_usdt, contact
    )
    
    # Увеличиваем счётчик выводов
    await execute_query(
        "UPDATE users SET withdrawals_count = withdrawals_count + 1 WHERE user_id = $1",
        user_id
    )

    # Подтверждение пользователю
    await message.answer(
        f"✅ <b>Ваша заявка на вывод принята!</b>\n\n"
        f"📋 <b>Детали заявки:</b>\n"
        f"💸 Сумма: {amount_points} баллов\n"
        f"💰 Вы получите: ≈ {amount_rub} руб ≈ {amount_usdt} USDT\n"
        f"📞 Контакт: {contact}\n\n"
        f"⏳ Ожидайте подтверждения администратора.\n\n"
        f"ℹ️ <b>О курсе вывода:</b>\n"
        f"• Это {'первый' if withdrawals_count == 0 else ''} вывод (курс {rate_text})\n"
        f"• Со {'второго' if withdrawals_count == 0 else 'следующего'} вывода курс станет 1.5 балла = 1 рубль\n\n"
        f"🔙 Нажмите кнопку ниже, чтобы вернуться в профиль.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")]
        ])
    )
    await state.clear()

    # Уведомляем администраторов
    await notify_admins_about_withdraw(
        user_id, amount_points, amount_rub, amount_usdt, contact,
        username, message.bot, rate_text
    )

async def notify_admins_about_limit_exceeded():
    try:
        admin_bot = Bot(token=ADMIN_BOT_TOKEN)
        for admin_id in ADMIN_IDS:
            try:
                await admin_bot.send_message(
                    admin_id,
                    f"⚠️ <b>Превышен дневной лимит выплат!</b>\n"
                    f"Лимит: {DAILY_PAYOUT_LIMIT_RUB} руб\n"
                    f"Проверьте заявки.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить админа {admin_id}: {e}")
        await admin_bot.session.close()
    except Exception as e:
        logger.error(f"Ошибка: {e}")

async def notify_admins_about_withdraw(
    user_id: int, amount_points: int, amount_rub: float,
    amount_usdt: float, contact: str, username: str, bot: Bot, rate_text: str
):
    try:
        admin_bot = Bot(token=ADMIN_BOT_TOKEN)
        user_link = f"tg://user?id={user_id}"
        for admin_id in ADMIN_IDS:
            try:
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
                    f"👤 Пользователь: <a href='{user_link}'>{username if username else 'пользователь'}</a> (ID: {user_id})\n"
                    f"📞 Контакт: {contact}\n"
                    f"💸 Сумма: {amount_points} баллов = {amount_rub} руб (курс {rate_text}) ≈ {amount_usdt} USDT\n\n"
                    f"💡 Для отправки средств используйте команду:\n"
                    f"<code>/send {amount_usdt} USDT</code>\n\n"
                    f"Или нажмите на кнопку ниже:",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить админа {admin_id}: {e}")
        await admin_bot.session.close()
    except Exception as e:
        logger.error(f"Ошибка уведомления админов: {e}")

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
    
    from database import execute_query
    
    # Получаем текущий баланс
    balance = await execute_query("SELECT balance FROM users WHERE user_id = $1", user_id, fetch_val=True)
    if balance is None:
        balance = 0
    
    new_balance = balance + 50
    await execute_query("UPDATE users SET balance = $1, bonus_balance = bonus_balance + 50, bonus_total = bonus_total + 50 WHERE user_id = $2", new_balance, user_id)
    
    try:
        await log_agreement(user_id)
        log_agreement_to_csv(user_id, username)
    except Exception as e:
        logger.error(f"Ошибка логирования: {e}")
    
    from database import reset_demo_games_played
    await reset_demo_games_played(user_id)
    
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
        f"Отправь её другу. Как только он сыграет одну игру, "
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
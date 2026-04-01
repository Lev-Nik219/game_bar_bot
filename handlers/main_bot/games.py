import asyncio
import random
import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import (
    get_user, update_balance, update_stats, update_tournament_score,
    get_event_multiplier, get_demo_games_played, increment_demo_games_played,
    update_bonus_wagered
)
from keyboards import (
    games_menu_keyboard, back_to_menu_keyboard, roulette_choice_keyboard,
    blackjack_keyboard, bowling_choice_keyboard, darts_choice_keyboard,
    main_reply_keyboard
)
from states import (
    SlotStates, RouletteStates, DiceStates, BlackjackStates,
    BowlingStates, DartsStates, DemoSlotStates, DemoDiceStates
)
from utils import adjust_win, cancel_on_max_attempts
from config import WIN_REDUCTION_FACTOR, RUB_PER_BALL_RATE
from .common import (
    get_game_over_text_and_keyboard, check_referral_bonus,
    check_zero_balance_and_notify
)
from .achievements import check_achievements
from constants import DEMO_MAX_GAMES, DEMO_WELCOME

logger = logging.getLogger(__name__)
router = Router()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def format_rub_equivalent(ball_amount: int) -> str:
    rub = ball_amount / RUB_PER_BALL_RATE
    return f"≈ {rub:.0f} руб"

# ========== ОБРАБОТЧИК ДЛЯ REPLY-КНОПКИ "Сыграть" ==========
@router.message(F.text == "🎰 Сыграть")
async def reply_play(message: types.Message):
    await message.answer(
        "🎮 **Выберите игру:**\n\n"
        "🎰 Слоты — классика\n"
        "🎡 Рулетка — угадай цвет или число\n"
        "🎲 Кости — больше/меньше 7\n"
        "🃏 Блэкджек — против дилера\n"
        "🎳 Боулинг — больше/меньше 3\n"
        "🎯 Дартс — чёт/нечет",
        parse_mode="HTML",
        reply_markup=games_menu_keyboard()
    )

# ========== ДЕМО-РЕЖИМ ==========
@router.callback_query(F.data == "demo_mode")
async def demo_mode_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    played = await get_demo_games_played(user_id)
    if played >= DEMO_MAX_GAMES:
        await callback.message.answer(
            "❌ Вы уже использовали все демо-игры.\n\n"
            "✅ Пожалуйста, примите соглашение, чтобы играть на реальные баллы.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
            ])
        )
        return
    await callback.message.delete()
    remaining = DEMO_MAX_GAMES - played
    welcome_text = DEMO_WELCOME.format(remaining, DEMO_MAX_GAMES, DEMO_MAX_GAMES)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Слоты (демо)", callback_data="demo_slots")],
        [InlineKeyboardButton(text="🎲 Кости (демо)", callback_data="demo_dice")],
        [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
    ])
    await callback.message.answer(welcome_text, reply_markup=keyboard)

# --- Демо-слоты ---
@router.callback_query(F.data == "demo_slots")
async def demo_slots_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    played = await get_demo_games_played(user_id)
    if played >= DEMO_MAX_GAMES:
        await callback.message.answer("❌ Демо-режим исчерпан. Примите соглашение.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
        ]))
        return
    await state.set_state(DemoSlotStates.waiting_for_bet)
    await callback.message.edit_text(
        f"🎰 **ДЕМО-РЕЖИМ**\n\n"
        f"🎲 Осталось игр: {DEMO_MAX_GAMES - played} из {DEMO_MAX_GAMES}\n\n"
        "Введите сумму ставки (целое число, минимум 10, максимум 10000):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="demo_mode")]
        ])
    )

@router.message(DemoSlotStates.waiting_for_bet)
async def demo_slots_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    played = await get_demo_games_played(user_id)
    if played >= DEMO_MAX_GAMES:
        await message.answer("❌ Демо-режим исчерпан. Примите соглашение.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
        ]))
        await state.clear()
        return

    data = await state.get_data()
    attempts = data.get("bet_attempts", 0) + 1
    await state.update_data(bet_attempts=attempts)

    if attempts > 3:
        from keyboards import demo_menu_keyboard
        await cancel_on_max_attempts(message, state, lambda uid: demo_menu_keyboard())
        return

    try:
        bet = int(message.text)
        if bet < 10:
            await message.answer(
                f"❌ Минимальная ставка — 10 баллов.\n"
                f"Пример: 100\n\nПопробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Отмена", callback_data="demo_mode")]
                ])
            )
            return
        if bet > 10000:
            await message.answer(
                f"❌ Максимальная ставка — 10000 баллов.\n\n"
                f"Попробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Отмена", callback_data="demo_mode")]
                ])
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Пример: 100\n\n"
            f"Попробуйте ещё раз (попытка {attempts}/3):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Отмена", callback_data="demo_mode")]
            ])
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await demo_slots_play(message, state, bet, message.from_user.first_name, message.from_user.username, message.bot)

async def demo_slots_play(message: types.Message, state: FSMContext, bet: int, first_name: str, username: str, bot):
    user_id = message.from_user.id
    played = await get_demo_games_played(user_id)
    if played >= DEMO_MAX_GAMES:
        await message.answer("❌ Демо-режим исчерпан. Примите соглашение.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
        ]))
        await state.clear()
        return

    await message.answer("🎰 **Кручу барабаны...**", parse_mode="HTML")
    await asyncio.sleep(1)
    await message.answer_dice(emoji="🎰")
    await asyncio.sleep(1)
    await message.answer_dice(emoji="🎰")
    await asyncio.sleep(1)
    await message.answer_dice(emoji="🎰")
    await asyncio.sleep(1)

    symbols_list = ['🍒', '🍋', '💎', '7️⃣', 'BAR']
    reel1 = random.choice(symbols_list)
    reel2 = random.choice(symbols_list)
    reel3 = random.choice(symbols_list)

    win_multiplier = 0
    if reel1 == reel2 == reel3:
        if reel1 == '7️⃣':
            win_multiplier = 10
        elif reel1 == '💎':
            win_multiplier = 5
        elif reel1 == 'BAR':
            win_multiplier = 3
        elif reel1 in ('🍒', '🍋'):
            win_multiplier = 2
    elif reel1 == reel2 or reel1 == reel3 or reel2 == reel3:
        win_multiplier = 1.5

    demo_win_chance = random.randint(1, 100)
    if win_multiplier > 0 and demo_win_chance <= 60:
        winnings = int(bet * win_multiplier)
        win = True
    else:
        winnings = 0
        win = False

    result_text = (
        f"🎰 **ДЕМО-РЕЗУЛЬТАТ СЛОТОВ** 🎰\n\n"
        f"[ {reel1} ] [ {reel2} ] [ {reel3} ]\n\n"
        f"💰 Ставка: {bet} 💎\n"
    )
    if win:
        result_text += f"🎉 **ВЫИГРЫШ: {winnings} 💎**\n"
    else:
        result_text += "😞 **ПРОИГРЫШ**\n"
    result_text += f"\n🎲 Осталось игр: {DEMO_MAX_GAMES - played - 1} из {DEMO_MAX_GAMES}\n\n"
    result_text += "⚠️ Демо-режим: выигрыши не начисляются на реальный баланс."

    await message.answer(result_text, parse_mode="HTML")

    await increment_demo_games_played(user_id)

    new_played = played + 1
    if new_played >= DEMO_MAX_GAMES:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
        ])
        await message.answer("🎮 Демо-игры закончились. Примите соглашение, чтобы продолжить!", reply_markup=keyboard)
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎮 Вернуться в демо-меню", callback_data="demo_mode")],
            [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
        ])
        await message.answer("🎮 Выберите действие:", reply_markup=keyboard)
    await state.clear()

# --- Демо-кости ---
@router.callback_query(F.data == "demo_dice")
async def demo_dice_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    played = await get_demo_games_played(user_id)
    if played >= DEMO_MAX_GAMES:
        await callback.message.answer("❌ Демо-режим исчерпан. Примите соглашение.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
        ]))
        return
    await state.set_state(DemoDiceStates.waiting_for_bet)
    await callback.message.edit_text(
        f"🎲 **ДЕМО-РЕЖИМ**\n\n"
        f"🎲 Осталось игр: {DEMO_MAX_GAMES - played} из {DEMO_MAX_GAMES}\n\n"
        "Введите сумму ставки (целое число, минимум 10, максимум 10000):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="demo_mode")]
        ])
    )

@router.message(DemoDiceStates.waiting_for_bet)
async def demo_dice_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    played = await get_demo_games_played(user_id)
    if played >= DEMO_MAX_GAMES:
        await message.answer("❌ Демо-режим исчерпан. Примите соглашение.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
        ]))
        await state.clear()
        return

    data = await state.get_data()
    attempts = data.get("bet_attempts", 0) + 1
    await state.update_data(bet_attempts=attempts)

    if attempts > 3:
        from keyboards import demo_menu_keyboard
        await cancel_on_max_attempts(message, state, lambda uid: demo_menu_keyboard())
        return

    try:
        bet = int(message.text)
        if bet < 10:
            await message.answer(
                f"❌ Минимальная ставка — 10 баллов.\n"
                f"Пример: 100\n\nПопробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Отмена", callback_data="demo_mode")]
                ])
            )
            return
        if bet > 10000:
            await message.answer(
                f"❌ Максимальная ставка — 10000 баллов.\n\n"
                f"Попробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Отмена", callback_data="demo_mode")]
                ])
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Пример: 100\n\n"
            f"Попробуйте ещё раз (попытка {attempts}/3):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Отмена", callback_data="demo_mode")]
            ])
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await state.set_state(DemoDiceStates.waiting_for_choice)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬆️ Больше 7", callback_data="demo_dice_over"),
         InlineKeyboardButton(text="⬇️ Меньше 7", callback_data="demo_dice_under")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="demo_mode")]
    ])
    await message.answer("Сделайте ставку: больше 7 или меньше 7?", reply_markup=keyboard)

@router.callback_query(DemoDiceStates.waiting_for_choice, F.data.in_(["demo_dice_over", "demo_dice_under"]))
async def demo_dice_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    bet = data.get("bet")
    choice = callback.data.replace("demo_dice_", "")
    await demo_dice_play(callback.message, state, bet, callback.from_user.first_name, callback.from_user.username, callback.bot, choice)
    await callback.answer()

async def demo_dice_play(message: types.Message, state: FSMContext, bet: int, first_name: str, username: str, bot, choice: str = None):
    user_id = message.from_user.id
    played = await get_demo_games_played(user_id)
    if played >= DEMO_MAX_GAMES:
        await message.answer("❌ Демо-режим исчерпан. Примите соглашение.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
        ]))
        await state.clear()
        return

    await message.answer("🎲 **Кидаю кубики...**", parse_mode="HTML")
    await asyncio.sleep(1)
    dice1 = await message.answer_dice(emoji="🎲")
    await asyncio.sleep(1)
    dice2 = await message.answer_dice(emoji="🎲")
    await asyncio.sleep(1)

    value1 = dice1.dice.value
    value2 = dice2.dice.value
    total = value1 + value2

    demo_win_chance = random.randint(1, 100)
    if choice == "over" and total > 7:
        win = demo_win_chance <= 60
    elif choice == "under" and total < 7:
        win = demo_win_chance <= 60
    else:
        win = False

    winnings = int(bet * 2) if win else 0

    result_text = (
        f"🎲 **ДЕМО-РЕЗУЛЬТАТ**\n\n"
        f"🎲 Первый кубик: {value1}\n"
        f"🎲 Второй кубик: {value2}\n"
        f"<b>Сумма:</b> {total}\n\n"
        f"💰 Ставка: {bet} 💎\n"
    )
    if win:
        result_text += f"🎉 **ВЫИГРЫШ: {winnings} 💎**\n"
    else:
        result_text += "😞 **ПРОИГРЫШ**\n"
    result_text += f"\n🎲 Осталось игр: {DEMO_MAX_GAMES - played - 1} из {DEMO_MAX_GAMES}\n\n"
    result_text += "⚠️ Демо-режим: выигрыши не начисляются на реальный баланс."

    await message.answer(result_text, parse_mode="HTML")

    await increment_demo_games_played(user_id)

    new_played = played + 1
    if new_played >= DEMO_MAX_GAMES:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
        ])
        await message.answer("🎮 Демо-игры закончились. Примите соглашение, чтобы продолжить!", reply_markup=keyboard)
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎮 Вернуться в демо-меню", callback_data="demo_mode")],
            [InlineKeyboardButton(text="✅ Принять соглашение", callback_data="accept_agreement")]
        ])
        await message.answer("🎮 Выберите действие:", reply_markup=keyboard)
    await state.clear()

# ========== РЕАЛЬНЫЕ ИГРЫ ==========
# Слоты
@router.callback_query(F.data == "game_slots")
async def slot_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SlotStates.waiting_for_bet)
    await callback.message.edit_text(
        "🎰 **ИГРА СЛОТЫ** 🎰\n\n"
        "Введите сумму ставки (целое число, минимум 10):",
        parse_mode="HTML",
        reply_markup=back_to_menu_keyboard()
    )

@router.message(SlotStates.waiting_for_bet)
async def slot_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    (balance, total_games, wins, level, exp, theme, dbl, daily_streak, ts,
     agreed, has_started, referral_count, referral_earnings,
     current_win_streak, max_win_streak, withdrawals_count) = await get_user(user_id, username)

    data = await state.get_data()
    attempts = data.get("bet_attempts", 0) + 1
    await state.update_data(bet_attempts=attempts)

    if attempts > 3:
        await cancel_on_max_attempts(message, state, lambda uid: main_reply_keyboard())
        return

    try:
        bet = int(message.text)
        if bet < 10:
            await message.answer(
                f"❌ Минимальная ставка — 10 баллов.\n"
                f"Пример: 100\n\nПопробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Недостаточно средств. Ваш баланс: {balance} 💎 ({format_rub_equivalent(balance)}).\n\n"
                f"Попробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Пример: 100\n\n"
            f"Попробуйте ещё раз (попытка {attempts}/3):",
            reply_markup=back_to_menu_keyboard()
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await slot_play(message, state, bet, first_name, username, message.bot)

async def slot_play(message: types.Message, state: FSMContext, bet: int, first_name: str, username: str, bot):
    user_id = message.from_user.id
    balance, *_ = await get_user(user_id, username)

    await message.answer("🎰 **Кручу барабаны...**", parse_mode="HTML")
    await asyncio.sleep(1)
    await message.answer_dice(emoji="🎰")
    await asyncio.sleep(1)
    await message.answer_dice(emoji="🎰")
    await asyncio.sleep(1)
    await message.answer_dice(emoji="🎰")
    await asyncio.sleep(1)

    symbols_list = ['🍒', '🍋', '💎', '7️⃣', 'BAR']
    reel1 = random.choice(symbols_list)
    reel2 = random.choice(symbols_list)
    reel3 = random.choice(symbols_list)

    win_multiplier = 0
    if reel1 == reel2 == reel3:
        if reel1 == '7️⃣':
            win_multiplier = 10
        elif reel1 == '💎':
            win_multiplier = 5
        elif reel1 == 'BAR':
            win_multiplier = 3
        elif reel1 in ('🍒', '🍋'):
            win_multiplier = 2
    elif reel1 == reel2 or reel1 == reel3 or reel2 == reel3:
        win_multiplier = 1.5

    event_mult = await get_event_multiplier()
    winnings = round(bet * win_multiplier * event_mult) if win_multiplier > 0 else 0
    win = winnings > 0
    win, winnings = adjust_win(win, winnings, bet, WIN_REDUCTION_FACTOR)
    new_balance = balance - bet + winnings
    await update_balance(user_id, new_balance)
    await update_stats(user_id, win=win)
    await update_tournament_score(user_id, 10 if win else 5)
    await update_bonus_wagered(user_id, bet, win)

    result_text = (
        f"🎰 **РЕЗУЛЬТАТ СЛОТОВ** 🎰\n\n"
        f"[ {reel1} ] [ {reel2} ] [ {reel3} ]\n\n"
        f"💰 Ставка: {bet} 💎 ({format_rub_equivalent(bet)})\n"
    )
    if win:
        result_text += f"🎉 **ВЫИГРЫШ: {winnings} 💎** ({format_rub_equivalent(winnings)})\n"
    else:
        result_text += "😞 **ПРОИГРЫШ**\n"
    result_text += f"💳 Новый баланс: {new_balance} 💎 ({format_rub_equivalent(new_balance)})"
    await message.answer(result_text, parse_mode="HTML")

    await check_referral_bonus(user_id, bot)
    asyncio.create_task(check_achievements(user_id, bot))

    text, keyboard = await get_game_over_text_and_keyboard(user_id, first_name, username)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await check_zero_balance_and_notify(message, user_id)
    await state.clear()

# Рулетка
@router.callback_query(F.data == "game_roulette")
async def roulette_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RouletteStates.waiting_for_bet)
    await callback.message.edit_text(
        "🎡 **ИГРА РУЛЕТКА** 🎡\n\n"
        "Введите сумму ставки (целое число, минимум 10):",
        parse_mode="HTML",
        reply_markup=back_to_menu_keyboard()
    )

@router.message(RouletteStates.waiting_for_bet)
async def roulette_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    balance, *_ = await get_user(user_id, username)

    data = await state.get_data()
    attempts = data.get("bet_attempts", 0) + 1
    await state.update_data(bet_attempts=attempts)

    if attempts > 3:
        await cancel_on_max_attempts(message, state, lambda uid: main_reply_keyboard())
        return

    try:
        bet = int(message.text)
        if bet < 10:
            await message.answer(
                f"❌ Минимальная ставка — 10 баллов.\n"
                f"Пример: 100\n\nПопробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Недостаточно средств. Ваш баланс: {balance} 💎 ({format_rub_equivalent(balance)}).\n\n"
                f"Попробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Пример: 100\n\n"
            f"Попробуйте ещё раз (попытка {attempts}/3):",
            reply_markup=back_to_menu_keyboard()
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await state.set_state(RouletteStates.waiting_for_choice)
    await message.answer("🎡 Выберите тип ставки:", reply_markup=roulette_choice_keyboard())

@router.callback_query(RouletteStates.waiting_for_choice, F.data.startswith("roulette_"))
async def roulette_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    bet = data.get("bet")
    user_id = callback.from_user.id
    username = callback.from_user.username
    balance, *_ = await get_user(user_id, username)
    choice = callback.data

    if choice == "roulette_specific":
        await state.set_state(RouletteStates.waiting_for_number)
        await callback.message.edit_text(
            "🎯 Введите число от 1 до 36:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_menu")]
            ])
        )
        return

    await spin_roulette(callback.message, state, user_id, username, balance, bet, choice,
                        callback.from_user.first_name, callback.bot)

async def spin_roulette(message: types.Message, state: FSMContext, user_id: int, username: str,
                        balance: int, bet: int, choice: str, first_name: str, bot,
                        specific_number: int = None):
    await message.answer("🎡 **Кручу рулетку...**", parse_mode="HTML")
    await asyncio.sleep(2)

    number = random.randint(0, 36)
    if number == 0:
        color = "зеленое"
        color_emoji = "🟢"
    elif number in (1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36):
        color = "красное"
        color_emoji = "🔴"
    else:
        color = "черное"
        color_emoji = "⚫"
    parity = "четное" if number != 0 and number % 2 == 0 else "нечетное"

    win_multiplier = 0
    if choice == "roulette_color_red" and color == "красное":
        win_multiplier = 2
    elif choice == "roulette_color_black" and color == "черное":
        win_multiplier = 2
    elif choice == "roulette_color_green" and number == 0:
        win_multiplier = 35
    elif choice == "roulette_parity_even" and number != 0 and parity == "четное":
        win_multiplier = 2
    elif choice == "roulette_parity_odd" and number != 0 and parity == "нечетное":
        win_multiplier = 2
    elif choice == "roulette_specific" and specific_number is not None and number == specific_number:
        win_multiplier = 35

    event_mult = await get_event_multiplier()
    winnings = int(bet * win_multiplier * event_mult) if win_multiplier > 0 else 0
    win = winnings > 0
    win, winnings = adjust_win(win, winnings, bet, WIN_REDUCTION_FACTOR)
    new_balance = balance - bet + winnings

    await update_balance(user_id, new_balance)
    await update_stats(user_id, win=win)
    await update_tournament_score(user_id, 10 if win else 5)
    await update_bonus_wagered(user_id, bet, win)

    result_text = (
        f"🎡 **РЕЗУЛЬТАТ РУЛЕТКИ**\n\n"
        f"<b>Выпало:</b> {number} {color_emoji} ({color})\n\n"
        f"💰 Ставка: {bet} 💎 ({format_rub_equivalent(bet)})\n"
    )
    if win:
        result_text += f"🎉 **ВЫИГРЫШ: {winnings} 💎** ({format_rub_equivalent(winnings)})\n"
    else:
        result_text += "😞 **ПРОИГРЫШ**\n"
    result_text += f"💳 Новый баланс: {new_balance} 💎 ({format_rub_equivalent(new_balance)})"

    await message.answer(result_text, parse_mode="HTML")

    await check_referral_bonus(user_id, bot)
    asyncio.create_task(check_achievements(user_id, bot))

    text, keyboard = await get_game_over_text_and_keyboard(user_id, first_name, username)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await check_zero_balance_and_notify(message, user_id)
    await state.clear()

@router.message(RouletteStates.waiting_for_number)
async def roulette_number(message: types.Message, state: FSMContext):
    try:
        number = int(message.text)
        if number < 1 or number > 36:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число от 1 до 36:")
        return

    data = await state.get_data()
    bet = data.get("bet")
    user_id = message.from_user.id
    username = message.from_user.username
    balance, *_ = await get_user(user_id, username)

    await spin_roulette(message, state, user_id, username, balance, bet, "roulette_specific",
                        message.from_user.first_name, message.bot, specific_number=number)

# Кости
@router.callback_query(F.data == "game_dice")
async def dice_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(DiceStates.waiting_for_bet)
    await callback.message.edit_text(
        "🎲 **ИГРА КОСТИ** 🎲\n\n"
        "Введите сумму ставки (целое число, минимум 10):",
        parse_mode="HTML",
        reply_markup=back_to_menu_keyboard()
    )

@router.message(DiceStates.waiting_for_bet)
async def dice_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    balance, *_ = await get_user(user_id, username)

    data = await state.get_data()
    attempts = data.get("bet_attempts", 0) + 1
    await state.update_data(bet_attempts=attempts)

    if attempts > 3:
        await cancel_on_max_attempts(message, state, lambda uid: main_reply_keyboard())
        return

    try:
        bet = int(message.text)
        if bet < 10:
            await message.answer(
                f"❌ Минимальная ставка — 10 баллов.\n"
                f"Пример: 100\n\nПопробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Недостаточно средств. Ваш баланс: {balance} 💎 ({format_rub_equivalent(balance)}).\n\n"
                f"Попробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Пример: 100\n\n"
            f"Попробуйте ещё раз (попытка {attempts}/3):",
            reply_markup=back_to_menu_keyboard()
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await state.set_state(DiceStates.waiting_for_choice)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬆️ Больше 7", callback_data="dice_over"),
         InlineKeyboardButton(text="⬇️ Меньше 7", callback_data="dice_under")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_menu")]
    ])
    await message.answer("Сделайте ставку: больше 7 или меньше 7?", reply_markup=keyboard)

@router.callback_query(DiceStates.waiting_for_choice, F.data.in_(["dice_over", "dice_under"]))
async def dice_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    bet = data.get("bet")
    user_id = callback.from_user.id
    username = callback.from_user.username
    balance, *_ = await get_user(user_id, username)
    choice = callback.data

    await callback.message.answer("🎲 **Кидаю кубики...**", parse_mode="HTML")
    await asyncio.sleep(1)
    dice1 = await callback.message.answer_dice(emoji="🎲")
    await asyncio.sleep(1)
    dice2 = await callback.message.answer_dice(emoji="🎲")
    await asyncio.sleep(1)

    value1 = dice1.dice.value
    value2 = dice2.dice.value
    total = value1 + value2

    win_multiplier = 0
    if total == 7:
        win_multiplier = 0
    elif choice == "dice_over" and total > 7:
        win_multiplier = 2
    elif choice == "dice_under" and total < 7:
        win_multiplier = 2

    event_mult = await get_event_multiplier()
    winnings = int(bet * win_multiplier * event_mult) if win_multiplier > 0 else 0
    win = winnings > 0
    win, winnings = adjust_win(win, winnings, bet, WIN_REDUCTION_FACTOR)
    new_balance = balance - bet + winnings

    await update_balance(user_id, new_balance)
    await update_stats(user_id, win=win)
    await update_tournament_score(user_id, 10 if win else 5)
    await update_bonus_wagered(user_id, bet, win)

    result_text = (
        f"🎲 **РЕЗУЛЬТАТ КОСТЕЙ**\n\n"
        f"🎲 Первый кубик: {value1}\n"
        f"🎲 Второй кубик: {value2}\n"
        f"<b>Сумма:</b> {total}\n\n"
        f"💰 Ставка: {bet} 💎 ({format_rub_equivalent(bet)})\n"
    )
    if win:
        result_text += f"🎉 **ВЫИГРЫШ: {winnings} 💎** ({format_rub_equivalent(winnings)})\n"
    else:
        result_text += "😞 **ПРОИГРЫШ (казино выиграло)**\n"
    result_text += f"💳 Новый баланс: {new_balance} 💎 ({format_rub_equivalent(new_balance)})"

    await callback.message.answer(result_text, parse_mode="HTML")

    await check_referral_bonus(user_id, callback.bot)
    asyncio.create_task(check_achievements(user_id, callback.bot))

    text, keyboard = await get_game_over_text_and_keyboard(user_id, callback.from_user.first_name, username)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await check_zero_balance_and_notify(callback.message, user_id)
    await state.clear()

# Блэкджек
@router.callback_query(F.data == "game_blackjack")
async def blackjack_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BlackjackStates.waiting_for_bet)
    await callback.message.edit_text(
        "🃏 **ИГРА БЛЭКДЖЕК** 🃏\n\n"
        "Введите сумму ставки (целое число, минимум 10):",
        parse_mode="HTML",
        reply_markup=back_to_menu_keyboard()
    )

@router.message(BlackjackStates.waiting_for_bet)
async def blackjack_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    balance, *_ = await get_user(user_id, username)

    data = await state.get_data()
    attempts = data.get("bet_attempts", 0) + 1
    await state.update_data(bet_attempts=attempts)

    if attempts > 3:
        await cancel_on_max_attempts(message, state, lambda uid: main_reply_keyboard())
        return

    try:
        bet = int(message.text)
        if bet < 10:
            await message.answer(
                f"❌ Минимальная ставка — 10 баллов.\n"
                f"Пример: 100\n\nПопробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Недостаточно средств. Ваш баланс: {balance} 💎 ({format_rub_equivalent(balance)}).\n\n"
                f"Попробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Пример: 100\n\n"
            f"Попробуйте ещё раз (попытка {attempts}/3):",
            reply_markup=back_to_menu_keyboard()
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await blackjack_init_game(message, state, bet, message.from_user.first_name, message.from_user.username, message.bot)

async def blackjack_init_game(message: types.Message, state: FSMContext, bet: int, first_name: str, username: str, bot):
    deck = [2,3,4,5,6,7,8,9,10,10,10,10,11] * 4
    random.shuffle(deck)
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop()]
    await state.update_data(deck=deck, player_hand=player_hand, dealer_hand=dealer_hand, bet=bet)

    player_sum = sum(player_hand)
    text = (
        f"🃏 **БЛЭКДЖЕК**\n\n"
        f"Твои карты: {player_hand[0]} и {player_hand[1]} (сумма: {player_sum})\n"
        f"🃏 Карта дилера: {dealer_hand[0]}\n\n"
        f"💰 Ставка: {bet} 💎 ({format_rub_equivalent(bet)})\n\n"
        f"Выбери действие:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=blackjack_keyboard())
    await state.set_state(BlackjackStates.in_game)

@router.callback_query(BlackjackStates.in_game, F.data.in_(["bj_hit", "bj_stand"]))
async def blackjack_action(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    deck = data['deck']
    player_hand = data['player_hand']
    dealer_hand = data['dealer_hand']
    bet = data['bet']
    user_id = callback.from_user.id
    username = callback.from_user.username
    balance, *_ = await get_user(user_id, username)

    if callback.data == "bj_hit":
        new_card = deck.pop()
        player_hand.append(new_card)
        player_sum = sum(player_hand)
        if player_sum > 21:
            new_balance = balance - bet
            await update_balance(user_id, new_balance)
            await update_stats(user_id, win=False)
            await update_tournament_score(user_id, 5)
            result_text = (
                f"💥 **Ты взял карту {new_card}**\n\n"
                f"Твои карты: {player_hand} (сумма: {player_sum})\n\n"
                f"😞 <b>ПЕРЕБОР! Ты проиграл {bet} 💎</b>\n"
                f"💳 Новый баланс: {new_balance} 💎 ({format_rub_equivalent(new_balance)})"
            )
            await callback.message.edit_text(result_text, parse_mode="HTML", reply_markup=back_to_menu_keyboard())
            await check_achievements(user_id, callback.bot)
            text, keyboard = await get_game_over_text_and_keyboard(user_id, callback.from_user.first_name, username)
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
            await state.clear()
            return
        else:
            text = (
                f"🃏 Ты взял карту {new_card}\n"
                f"Твои карты: {', '.join(map(str, player_hand))} (сумма: {player_sum})\n"
                f"🃏 Карта дилера: {dealer_hand[0]}\n\n"
                f"Выбери действие:"
            )
            await callback.message.edit_text(text, reply_markup=blackjack_keyboard())
            await state.update_data(deck=deck, player_hand=player_hand)
            return

    elif callback.data == "bj_stand":
        while sum(dealer_hand) < 17:
            dealer_hand.append(deck.pop())
        player_sum = sum(player_hand)
        dealer_sum = sum(dealer_hand)

        if player_sum > 21:
            win = False
            winnings = -bet
            result_message = "Ты проиграл"
        else:
            if dealer_sum > 21:
                win = True
                winnings = bet * 2
                result_message = "Ты выиграл"
            else:
                if player_sum > dealer_sum:
                    win = True
                    winnings = bet * 2
                    result_message = "Ты выиграл"
                elif player_sum < dealer_sum:
                    win = False
                    winnings = -bet
                    result_message = "Ты проиграл"
                else:
                    win = True
                    winnings = int(bet * 1.5)
                    result_message = "Ничья"

        event_mult = await get_event_multiplier()
        if winnings > 0:
            winnings = int(winnings * event_mult)
            win, winnings = adjust_win(win, winnings, bet, WIN_REDUCTION_FACTOR)
        new_balance = balance + winnings
        await update_balance(user_id, new_balance)
        await update_stats(user_id, win=win)
        await update_tournament_score(user_id, 10 if win else 5)
        await update_bonus_wagered(user_id, bet, win)

        result_text = (
            f"🃏 **РЕЗУЛЬТАТ БЛЭКДЖЕКА**\n\n"
            f"Твои карты: {player_hand} (сумма: {player_sum})\n"
            f"Карты дилера: {dealer_hand} (сумма: {dealer_sum})\n\n"
        )
        if winnings > 0:
            result_text += f"🎉 {result_message}! Ты получил {winnings} 💎 ({format_rub_equivalent(winnings)})\n"
        elif winnings == 0:
            result_text += f"🤝 {result_message}. Ставка возвращена.\n"
        else:
            result_text += f"😞 {result_message}. Ты потерял {bet} 💎\n"
        result_text += f"💳 Новый баланс: {new_balance} 💎 ({format_rub_equivalent(new_balance)})"

        await callback.message.edit_text(result_text, parse_mode="HTML", reply_markup=back_to_menu_keyboard())
        await check_achievements(user_id, callback.bot)

        text, keyboard = await get_game_over_text_and_keyboard(user_id, callback.from_user.first_name, username)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

        await state.clear()

# Боулинг
@router.callback_query(F.data == "game_bowling")
async def bowling_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BowlingStates.waiting_for_bet)
    await callback.message.edit_text(
        "🎳 **ИГРА БОУЛИНГ** 🎳\n\n"
        "Введите сумму ставки (целое число, минимум 10):",
        parse_mode="HTML",
        reply_markup=back_to_menu_keyboard()
    )

@router.message(BowlingStates.waiting_for_bet)
async def bowling_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    balance, *_ = await get_user(user_id, username)

    data = await state.get_data()
    attempts = data.get("bet_attempts", 0) + 1
    await state.update_data(bet_attempts=attempts)

    if attempts > 3:
        await cancel_on_max_attempts(message, state, lambda uid: main_reply_keyboard())
        return

    try:
        bet = int(message.text)
        if bet < 10:
            await message.answer(
                f"❌ Минимальная ставка — 10 баллов.\n"
                f"Пример: 100\n\nПопробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Недостаточно средств. Ваш баланс: {balance} 💎 ({format_rub_equivalent(balance)}).\n\n"
                f"Попробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Пример: 100\n\n"
            f"Попробуйте ещё раз (попытка {attempts}/3):",
            reply_markup=back_to_menu_keyboard()
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await state.set_state(BowlingStates.waiting_for_choice)
    await message.answer("🎳 Сделайте ставку:", reply_markup=bowling_choice_keyboard())

@router.callback_query(BowlingStates.waiting_for_choice, F.data.in_(["bowling_over", "bowling_under"]))
async def bowling_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    bet = data.get("bet")
    user_id = callback.from_user.id
    username = callback.from_user.username
    balance, *_ = await get_user(user_id, username)
    choice = callback.data

    await callback.message.answer("🎳 **Кидаю шар...**", parse_mode="HTML")
    await asyncio.sleep(2)
    dice_message = await callback.message.answer_dice(emoji="🎳")
    await asyncio.sleep(3)

    value = dice_message.dice.value
    win = (choice == "bowling_over" and value > 3) or (choice == "bowling_under" and value < 4)

    event_mult = await get_event_multiplier()
    winnings = int(bet * 2 * event_mult) if win else 0
    win, winnings = adjust_win(win, winnings, bet, WIN_REDUCTION_FACTOR)
    new_balance = balance - bet + winnings

    await update_balance(user_id, new_balance)
    await update_stats(user_id, win=win)
    await update_tournament_score(user_id, 10 if win else 5)
    await update_bonus_wagered(user_id, bet, win)

    result_text = (
        f"🎳 **РЕЗУЛЬТАТ БОУЛИНГА**\n\n"
        f"<b>Результат броска:</b> {value}\n\n"
        f"💰 Ставка: {bet} 💎 ({format_rub_equivalent(bet)})\n"
    )
    if win:
        result_text += f"🎉 **ВЫИГРЫШ: {winnings} 💎** ({format_rub_equivalent(winnings)})\n"
    else:
        result_text += "😞 **ПРОИГРЫШ**\n"
    result_text += f"💳 Новый баланс: {new_balance} 💎 ({format_rub_equivalent(new_balance)})"

    await callback.message.answer(result_text, parse_mode="HTML")

    await check_referral_bonus(user_id, callback.bot)
    asyncio.create_task(check_achievements(user_id, callback.bot))

    text, keyboard = await get_game_over_text_and_keyboard(user_id, callback.from_user.first_name, username)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await check_zero_balance_and_notify(callback.message, user_id)
    await state.clear()

# Дартс
@router.callback_query(F.data == "game_darts")
async def darts_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(DartsStates.waiting_for_bet)
    await callback.message.edit_text(
        "🎯 **ИГРА ДАРТС** 🎯\n\n"
        "Введите сумму ставки (целое число, минимум 10):",
        parse_mode="HTML",
        reply_markup=back_to_menu_keyboard()
    )

@router.message(DartsStates.waiting_for_bet)
async def darts_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    balance, *_ = await get_user(user_id, username)

    data = await state.get_data()
    attempts = data.get("bet_attempts", 0) + 1
    await state.update_data(bet_attempts=attempts)

    if attempts > 3:
        await cancel_on_max_attempts(message, state, lambda uid: main_reply_keyboard())
        return

    try:
        bet = int(message.text)
        if bet < 10:
            await message.answer(
                f"❌ Минимальная ставка — 10 баллов.\n"
                f"Пример: 100\n\nПопробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Недостаточно средств. Ваш баланс: {balance} 💎 ({format_rub_equivalent(balance)}).\n\n"
                f"Попробуйте ещё раз (попытка {attempts}/3):",
                reply_markup=back_to_menu_keyboard()
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Пример: 100\n\n"
            f"Попробуйте ещё раз (попытка {attempts}/3):",
            reply_markup=back_to_menu_keyboard()
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await state.set_state(DartsStates.waiting_for_choice)
    await message.answer("🎯 Сделайте ставку (чёт/нечет):", reply_markup=darts_choice_keyboard())

@router.callback_query(DartsStates.waiting_for_choice, F.data.in_(["darts_even", "darts_odd"]))
async def darts_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    bet = data.get("bet")
    user_id = callback.from_user.id
    username = callback.from_user.username
    balance, *_ = await get_user(user_id, username)
    choice = callback.data

    await callback.message.answer("🎯 **Кидаю дротик...**", parse_mode="HTML")
    await asyncio.sleep(2)
    dice_message = await callback.message.answer_dice(emoji="🎯")
    await asyncio.sleep(3)

    value = dice_message.dice.value
    is_even = value % 2 == 0
    win = (choice == "darts_even" and is_even) or (choice == "darts_odd" and not is_even)

    event_mult = await get_event_multiplier()
    winnings = int(bet * 2 * event_mult) if win else 0
    win, winnings = adjust_win(win, winnings, bet, WIN_REDUCTION_FACTOR)
    new_balance = balance - bet + winnings

    await update_balance(user_id, new_balance)
    await update_stats(user_id, win=win)
    await update_tournament_score(user_id, 10 if win else 5)
    await update_bonus_wagered(user_id, bet, win)

    result_text = (
        f"🎯 **РЕЗУЛЬТАТ ДАРТС**\n\n"
        f"<b>Результат броска:</b> {value} {'(чётное)' if is_even else '(нечётное)'}\n\n"
        f"💰 Ставка: {bet} 💎 ({format_rub_equivalent(bet)})\n"
    )
    if win:
        result_text += f"🎉 **ВЫИГРЫШ: {winnings} 💎** ({format_rub_equivalent(winnings)})\n"
    else:
        result_text += "😞 **ПРОИГРЫШ**\n"
    result_text += f"💳 Новый баланс: {new_balance} 💎 ({format_rub_equivalent(new_balance)})"

    await callback.message.answer(result_text, parse_mode="HTML")

    await check_referral_bonus(user_id, callback.bot)
    asyncio.create_task(check_achievements(user_id, callback.bot))

    text, keyboard = await get_game_over_text_and_keyboard(user_id, callback.from_user.first_name, username)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await check_zero_balance_and_notify(callback.message, user_id)
    await state.clear()

# ========== ОБРАБОТЧИК ОТМЕНЫ СТАВКИ ==========
@router.callback_query(F.data == "cancel_bet")
async def cancel_bet(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text, keyboard = await get_game_over_text_and_keyboard(
        callback.from_user.id,
        callback.from_user.first_name,
        callback.from_user.username
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer("Ставка отменена")
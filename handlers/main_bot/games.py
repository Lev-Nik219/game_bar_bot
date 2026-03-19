import asyncio
import random
import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import (
    get_user, update_balance, update_stats, update_tournament_score,
    get_event_multiplier
)
from keyboards import (
    games_menu_keyboard, back_to_menu_keyboard, roulette_choice_keyboard,
    blackjack_keyboard, bowling_choice_keyboard, darts_choice_keyboard,
    main_reply_keyboard  # <--- добавлен импорт
)
from states import (
    SlotStates, RouletteStates, DiceStates, BlackjackStates,
    BowlingStates, DartsStates
)
from utils import adjust_win, cancel_on_max_attempts
from config import WIN_REDUCTION_FACTOR
from .common import (
    get_game_over_text_and_keyboard, check_referral_bonus,
    check_zero_balance_and_notify
)
from .achievements import check_achievements

logger = logging.getLogger(__name__)
router = Router()

# --- Обработчик для reply-кнопки "Сыграть" ---
@router.message(F.text == "🎰 Сыграть")
async def reply_play(message: types.Message):
    await message.answer(
        "🎮 Выберите игру:",
        reply_markup=games_menu_keyboard()
    )

# --- Слоты ---
@router.callback_query(F.data == "game_slots")
async def slot_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SlotStates.waiting_for_bet)
    await callback.message.edit_text(
        "🎰 Введите сумму ставки (целое число, минимум 10):\n(У вас есть 3 попытки)",
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
                f"❌ Минимальная ставка — 10 баллов. Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Недостаточно средств. Ваш баланс: {balance} 💎. "
                f"Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Попробуйте ещё раз (попытка {attempts}/3):"
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)

    await message.answer("🎰 Крутим барабаны...")
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

    result_text = (
        f"🎰 <b>РЕЗУЛЬТАТ СЛОТОВ</b> 🎰\n"
        f"[ {reel1} ] [ {reel2} ] [ {reel3} ]\n"
        f"💰 Ставка: {bet} 💎\n"
    )
    if win:
        result_text += f"🎉 <b>ВЫИГРЫШ: {winnings} 💎</b>\n"
    else:
        result_text += "😞 <b>ПРОИГРЫШ</b>\n"
    result_text += f"💳 Новый баланс: {new_balance} 💎"
    await message.answer(result_text, parse_mode="HTML")

    await check_referral_bonus(user_id, message.bot)
    asyncio.create_task(check_achievements(user_id, message.bot))

    text, keyboard = await get_game_over_text_and_keyboard(
        user_id, first_name, username
    )
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await check_zero_balance_and_notify(message, user_id)
    await state.clear()

# --- Рулетка ---
@router.callback_query(F.data == "game_roulette")
async def roulette_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(RouletteStates.waiting_for_bet)
    await callback.message.edit_text(
        "🎡 Введите сумму ставки (целое число, минимум 10):\n(У вас есть 3 попытки)",
        reply_markup=back_to_menu_keyboard()
    )

@router.message(RouletteStates.waiting_for_bet)
async def roulette_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
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
                f"❌ Минимальная ставка — 10 баллов. Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Неверная сумма. У вас {balance} 💎. "
                f"Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Попробуйте ещё раз (попытка {attempts}/3):"
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await state.set_state(RouletteStates.waiting_for_choice)

    await message.answer(
        "Выберите тип ставки:",
        reply_markup=roulette_choice_keyboard()
    )

@router.callback_query(RouletteStates.waiting_for_choice, F.data.startswith("roulette_"))
async def roulette_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()  # сразу подтверждаем
    data = await state.get_data()
    bet = data.get("bet")
    user_id = callback.from_user.id
    username = callback.from_user.username
    balance, *_ = await get_user(user_id, username)

    choice = callback.data
    if choice == "roulette_specific":
        await state.set_state(RouletteStates.waiting_for_number)
        await callback.message.edit_text(
            "Введите число от 1 до 36:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="🔙 Отмена",
                        callback_data="back_to_menu"
                    )
                ]]
            )
        )
        return

    await state.update_data(roulette_choice=choice)
    await spin_roulette(
        callback.message, state, user_id, username, balance, bet, choice,
        callback.from_user.first_name, callback.bot
    )

async def spin_roulette(
    message: types.Message, state: FSMContext, user_id: int, username: str,
    balance: int, bet: int, choice: str, first_name: str, bot,
    specific_number: int = None
):
    await message.answer("🎡 Кручу рулетку...")
    await asyncio.sleep(3)

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

    result_text = (
        f"🎡 <b>Результат:</b> {number} {color_emoji} ({color})\n"
        f"💰 Ставка: {bet} 💎\n"
    )
    if win:
        result_text += f"🎉 <b>Выигрыш: {winnings} 💎</b>\n"
    else:
        result_text += "😞 <b>Проигрыш</b>\n"
    result_text += f"💳 Новый баланс: {new_balance} 💎"

    await message.answer(result_text, parse_mode="HTML")

    await check_referral_bonus(user_id, bot)
    asyncio.create_task(check_achievements(user_id, bot))

    text, keyboard = await get_game_over_text_and_keyboard(
        user_id, first_name, username
    )
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

    await spin_roulette(
        message, state, user_id, username, balance, bet, "roulette_specific",
        message.from_user.first_name, message.bot, specific_number=number
    )

# --- Кости ---
@router.callback_query(F.data == "game_dice")
async def dice_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(DiceStates.waiting_for_bet)
    await callback.message.edit_text(
        "🎲 Введите сумму ставки (целое число, минимум 10):\n(У вас есть 3 попытки)",
        reply_markup=back_to_menu_keyboard()
    )

@router.message(DiceStates.waiting_for_bet)
async def dice_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
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
                f"❌ Минимальная ставка — 10 баллов. Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Неверная сумма. У вас {balance} 💎. "
                f"Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Попробуйте ещё раз (попытка {attempts}/3):"
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await state.set_state(DiceStates.waiting_for_choice)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬆️ Больше 7", callback_data="dice_over"),
         InlineKeyboardButton(text="⬇️ Меньше 7", callback_data="dice_under")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await message.answer(
        "Сделайте ставку: больше 7 или меньше 7?",
        reply_markup=keyboard
    )

@router.callback_query(DiceStates.waiting_for_choice, F.data.in_(["dice_over", "dice_under"]))
async def dice_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()  # сразу подтверждаем
    data = await state.get_data()
    bet = data.get("bet")
    user_id = callback.from_user.id
    username = callback.from_user.username
    balance, *_ = await get_user(user_id, username)
    choice = callback.data

    await callback.message.answer("🎲 Кидаю первый кубик...")
    dice1 = await callback.message.answer_dice(emoji="🎲")
    await asyncio.sleep(1)
    await callback.message.answer("🎲 Кидаю второй кубик...")
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

    result_text = (
        f"🎲 <b>Первый кубик:</b> {value1}\n"
        f"🎲 <b>Второй кубик:</b> {value2}\n"
        f"<b>Сумма:</b> {total}\n"
        f"💰 Ставка: {bet} 💎\n"
    )
    if win:
        result_text += f"🎉 <b>Выигрыш: {winnings} 💎</b>\n"
    else:
        result_text += "😞 <b>Проигрыш (казино выиграло)</b>\n"
    result_text += f"💳 Новый баланс: {new_balance} 💎"

    await callback.message.answer(result_text, parse_mode="HTML")

    await check_referral_bonus(user_id, callback.bot)
    asyncio.create_task(check_achievements(user_id, callback.bot))

    text, keyboard = await get_game_over_text_and_keyboard(
        user_id, callback.from_user.first_name, username
    )
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await check_zero_balance_and_notify(callback.message, user_id)
    await state.clear()

# --- Блэкджек ---
@router.callback_query(F.data == "game_blackjack")
async def blackjack_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BlackjackStates.waiting_for_bet)
    await callback.message.edit_text(
        "🃏 Введите сумму ставки для игры в блэкджек (целое число, минимум 10):\n(У вас есть 3 попытки)",
        reply_markup=back_to_menu_keyboard()
    )

@router.message(BlackjackStates.waiting_for_bet)
async def blackjack_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
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
                f"❌ Минимальная ставка — 10 баллов. Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Неверная сумма. У вас {balance} 💎. "
                f"Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Попробуйте ещё раз (попытка {attempts}/3):"
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    # Инициализация игры
    deck = [2,3,4,5,6,7,8,9,10,10,10,10,11] * 4
    random.shuffle(deck)
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop()]
    await state.update_data(deck=deck, player_hand=player_hand, dealer_hand=dealer_hand)

    text = (
        f"🃏 Твои карты: {player_hand[0]} и {player_hand[1]} (сумма: {sum(player_hand)})\n"
        f"🃏 Карта дилера: {dealer_hand[0]}\n\n"
        f"Выбери действие:"
    )
    await message.answer(text, reply_markup=blackjack_keyboard())
    await state.set_state(BlackjackStates.in_game)

@router.callback_query(BlackjackStates.in_game, F.data.in_(["bj_hit", "bj_stand"]))
async def blackjack_action(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()  # сразу подтверждаем
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
        if sum(player_hand) > 21:
            new_balance = balance - bet
            await update_balance(user_id, new_balance)
            await update_stats(user_id, win=False)
            await update_tournament_score(user_id, 5)
            await callback.message.edit_text(
                f"💥 Ты взял карту {new_card}. Перебор! Ты проиграл {bet} 💎.",
                reply_markup=back_to_menu_keyboard()
            )
            await check_achievements(user_id, callback.bot)
            text, keyboard = await get_game_over_text_and_keyboard(
                user_id, callback.from_user.first_name, username
            )
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
            await state.clear()
            return
        else:
            text = (
                f"🃏 Твои карты: {', '.join(map(str, player_hand))} (сумма: {sum(player_hand)})\n"
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
                else:  # player_sum == dealer_sum
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

        result_text = (
            f"🃏 Твои карты: {player_hand} (сумма: {player_sum})\n"
            f"🃏 Карты дилера: {dealer_hand} (сумма: {dealer_sum})\n\n"
        )
        if winnings > 0:
            result_text += f"🎉 {result_message}! Ты получил {winnings} 💎!"
        elif winnings == 0:
            result_text += f"🤝 {result_message}. Ставка возвращена."
        else:
            result_text += f"😞 {result_message}. Ты потерял {bet} 💎."

        await callback.message.edit_text(
            result_text,
            reply_markup=back_to_menu_keyboard()
        )
        await check_achievements(user_id, callback.bot)

        text, keyboard = await get_game_over_text_and_keyboard(
            user_id, callback.from_user.first_name, username
        )
        await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

        await state.clear()

# --- Боулинг ---
@router.callback_query(F.data == "game_bowling")
async def bowling_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BowlingStates.waiting_for_bet)
    await callback.message.edit_text(
        "🎳 Введите сумму ставки (целое число, минимум 10):\n(У вас есть 3 попытки)",
        reply_markup=back_to_menu_keyboard()
    )

@router.message(BowlingStates.waiting_for_bet)
async def bowling_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
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
                f"❌ Минимальная ставка — 10 баллов. Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Неверная сумма. У вас {balance} 💎. "
                f"Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Попробуйте ещё раз (попытка {attempts}/3):"
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await state.set_state(BowlingStates.waiting_for_choice)

    await message.answer(
        "🎳 Сделайте ставку:",
        reply_markup=bowling_choice_keyboard()
    )

@router.callback_query(BowlingStates.waiting_for_choice, F.data.in_(["bowling_over", "bowling_under"]))
async def bowling_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    bet = data.get("bet")
    user_id = callback.from_user.id
    username = callback.from_user.username
    balance, *_ = await get_user(user_id, username)
    choice = callback.data

    await callback.message.answer("🎳 Кидаю шар...")
    dice_message = await callback.message.answer_dice(emoji="🎳")
    await asyncio.sleep(5)

    value = dice_message.dice.value
    win = False
    if choice == "bowling_over" and value > 3:
        win = True
    elif choice == "bowling_under" and value < 4:
        win = True

    event_mult = await get_event_multiplier()
    winnings = int(bet * 2 * event_mult) if win else 0
    win, winnings = adjust_win(win, winnings, bet, WIN_REDUCTION_FACTOR)
    new_balance = balance - bet + winnings

    await update_balance(user_id, new_balance)
    await update_stats(user_id, win=win)
    await update_tournament_score(user_id, 10 if win else 5)

    result_text = (
        f"🎳 <b>Результат броска:</b> {value}\n"
        f"💰 Ставка: {bet} 💎\n"
    )
    if win:
        result_text += f"🎉 <b>Выигрыш: {winnings} 💎</b>\n"
    else:
        result_text += "😞 <b>Проигрыш</b>\n"
    result_text += f"💳 Новый баланс: {new_balance} 💎"

    await callback.message.answer(result_text, parse_mode="HTML")

    await check_referral_bonus(user_id, callback.bot)
    asyncio.create_task(check_achievements(user_id, callback.bot))

    text, keyboard = await get_game_over_text_and_keyboard(
        user_id, callback.from_user.first_name, username
    )
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await check_zero_balance_and_notify(callback.message, user_id)
    await state.clear()

# --- Дартс ---
@router.callback_query(F.data == "game_darts")
async def darts_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(DartsStates.waiting_for_bet)
    await callback.message.edit_text(
        "🎯 Введите сумму ставки (целое число, минимум 10):\n(У вас есть 3 попытки)",
        reply_markup=back_to_menu_keyboard()
    )

@router.message(DartsStates.waiting_for_bet)
async def darts_bet(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
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
                f"❌ Минимальная ставка — 10 баллов. Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
        if bet > balance:
            await message.answer(
                f"❌ Неверная сумма. У вас {balance} 💎. "
                f"Попробуйте ещё раз (попытка {attempts}/3):"
            )
            return
    except ValueError:
        await message.answer(
            f"❌ Введите число. Попробуйте ещё раз (попытка {attempts}/3):"
        )
        return

    await state.update_data(bet=bet, bet_attempts=0)
    await state.set_state(DartsStates.waiting_for_choice)

    await message.answer(
        "🎯 Сделайте ставку (чёт/нечет):",
        reply_markup=darts_choice_keyboard()
    )

@router.callback_query(DartsStates.waiting_for_choice, F.data.in_(["darts_even", "darts_odd"]))
async def darts_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    bet = data.get("bet")
    user_id = callback.from_user.id
    username = callback.from_user.username
    balance, *_ = await get_user(user_id, username)
    choice = callback.data

    await callback.message.answer("🎯 Кидаю дротик...")
    dice_message = await callback.message.answer_dice(emoji="🎯")
    await asyncio.sleep(5)

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

    result_text = (
        f"🎯 <b>Результат броска:</b> {value} {'(чётное)' if is_even else '(нечётное)'}\n"
        f"💰 Ставка: {bet} 💎\n"
    )
    if win:
        result_text += f"🎉 <b>Выигрыш: {winnings} 💎</b>\n"
    else:
        result_text += "😞 <b>Проигрыш</b>\n"
    result_text += f"💳 Новый баланс: {new_balance} 💎"

    await callback.message.answer(result_text, parse_mode="HTML")

    await check_referral_bonus(user_id, callback.bot)
    asyncio.create_task(check_achievements(user_id, callback.bot))

    text, keyboard = await get_game_over_text_and_keyboard(
        user_id, callback.from_user.first_name, username
    )
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)

    await check_zero_balance_and_notify(callback.message, user_id)
    await state.clear()
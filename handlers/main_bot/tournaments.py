import time
import aiogram.exceptions
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import (
    get_active_tournament, get_tournament_leaders,
    register_for_tournament, is_registered_for_tournament,
    get_user_tournaments, count_user_tournaments,
    finish_tournament
)
from .common import get_game_over_text_and_keyboard

router = Router()

async def get_tournament_message(user_id: int, bot) -> tuple[str, InlineKeyboardMarkup]:
    tournament_data = await get_active_tournament()
    if not tournament_data:
        text = "🏆 Сейчас нет активных турниров."
        buttons = [
            [InlineKeyboardButton(text="📋 Мои турниры", callback_data="my_tournaments")],
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
        ]
        return text, InlineKeyboardMarkup(inline_keyboard=buttons)

    tournament_id, name, prize, end_time = tournament_data
    if time.time() > end_time:
        await finish_tournament(tournament_id, bot)
        return await get_tournament_message(user_id, bot)

    leaders = await get_tournament_leaders(tournament_id)
    registered = await is_registered_for_tournament(user_id, tournament_id)

    text = f"🏆 Активный турнир: {name}\nПриз: {prize} 💎\n"
    time_left = end_time - int(time.time())
    hours = time_left // 3600
    minutes = (time_left % 3600) // 60
    text += f"⏳ Осталось: {hours} ч {minutes} мин\n\nТоп-10 участников:\n"
    if leaders:
        for i, (uid, uname, score) in enumerate(leaders, 1):
            name_display = uname if uname else f"ID {uid}"
            text += f"{i}. {name_display} — {score} очков\n"
    else:
        text += "Пока нет участников.\n"

    if registered:
        text += "\n✅ Вы уже участвуете в этом турнире."
        join_button = None
    else:
        text += "\n❌ Вы ещё не участвуете."
        join_button = [InlineKeyboardButton(text="✅ Участвовать", callback_data=f"tournament_join_{tournament_id}")]

    buttons = []
    if join_button:
        buttons.append(join_button)
    buttons.append([InlineKeyboardButton(text="📋 Мои турниры", callback_data="my_tournaments")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")])
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(F.text == "🏆 Турниры")
async def reply_tournaments(message: types.Message):
    text, keyboard = await get_tournament_message(message.from_user.id, message.bot)
    await message.answer(text, reply_markup=keyboard)

@router.callback_query(F.data.startswith("tournament_join_"))
async def tournament_join(callback: types.CallbackQuery):
    await callback.answer()
    tournament_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    if await is_registered_for_tournament(user_id, tournament_id):
        await callback.answer("Вы уже участвуете в этом турнире!", show_alert=True)
        return
    await register_for_tournament(user_id, tournament_id)
    await callback.answer("✅ Вы успешно зарегистрированы в турнире!", show_alert=True)
    new_text, new_keyboard = await get_tournament_message(user_id, callback.bot)
    await callback.message.edit_text(new_text, reply_markup=new_keyboard)

@router.callback_query(F.data == "my_tournaments")
async def my_tournaments_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    page = data.get("tournament_page", 0)
    await show_user_tournaments(callback.message, callback.from_user.id, page,
                                 callback.from_user.first_name, callback.from_user.username, edit=True)

async def show_user_tournaments(message: types.Message, user_id: int, page: int,
                                first_name: str, username: str, edit=False):
    limit = 5
    offset = page * limit
    tournaments = await get_user_tournaments(user_id, offset, limit)
    total = await count_user_tournaments(user_id)
    total_pages = (total + limit - 1) // limit

    if not tournaments:
        text = "📋 Вы ещё не участвовали ни в одном турнире."
    else:
        text = f"📋 Ваши турниры (страница {page+1}/{total_pages}):\n\n"
        now = time.time()
        for t in tournaments:
            tid, name, prize, start, end, score, winner_id, winner_username = t
            status = "активен" if start <= now <= end else "завершён"
            if start <= now <= end:
                text += f"⭐ <b>{name}</b> — {prize} 💎, ваш счёт: {score} ({status})\n"
            else:
                if winner_id == user_id:
                    text += f"🏆 <b>{name}</b> — вы победитель! Приз: {prize} 💎\n"
                else:
                    text += f"• {name} — {prize} 💎, ваш счёт: {score} ({status})\n"

    buttons = []
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data="tournaments_prev"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data="tournaments_next"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="🔙 Назад к турнирам", callback_data="back_to_tournaments")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        if edit:
            await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    except aiogram.exceptions.TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise

@router.callback_query(F.data == "tournaments_next")
async def tournaments_next(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    page = data.get("tournament_page", 0) + 1
    await state.update_data(tournament_page=page)
    await show_user_tournaments(callback.message, callback.from_user.id, page,
                                callback.from_user.first_name, callback.from_user.username, edit=True)

@router.callback_query(F.data == "tournaments_prev")
async def tournaments_prev(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    page = data.get("tournament_page", 0) - 1
    await state.update_data(tournament_page=page)
    await show_user_tournaments(callback.message, callback.from_user.id, page,
                                callback.from_user.first_name, callback.from_user.username, edit=True)

@router.callback_query(F.data == "back_to_tournaments")
async def back_to_tournaments(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(tournament_page=0)
    text, keyboard = await get_tournament_message(callback.from_user.id, callback.bot)
    await callback.message.edit_text(text, reply_markup=keyboard)

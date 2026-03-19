import aiosqlite
import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import (
    DB_NAME, get_user, update_balance, get_user_stats,
    get_all_users, get_users_count
)
from keyboards import admin_panel_keyboard, cancel_keyboard
from states import AdminGiveStates, AdminTakeStates, AdminUserInfoStates, AdminListStates
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

# ===== Главная админ-панель =====
@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: types.CallbackQuery):
    print(">>> admin_panel_callback вызван")
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await callback.message.edit_text(
        "👑 Админ панель\nВыберите действие:",
        reply_markup=admin_panel_keyboard()
    )
    await callback.answer()

# ===== Начисление баллов =====
@router.callback_query(F.data == "admin_give")
async def admin_give_callback(callback: types.CallbackQuery, state: FSMContext):
    print(">>> admin_give_callback вызван")
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminGiveStates.waiting_for_target_id)
    await callback.message.edit_text(
        "Введите ID пользователя, которому хотите начислить баллы:",
        reply_markup=cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminGiveStates.waiting_for_target_id, F.text)
async def admin_give_target_id(message: types.Message, state: FSMContext):
    print(">>> admin_give_target_id вызван")
    try:
        target_id = int(message.text)
    except ValueError:
        await message.answer("❌ ID должен быть числом. Попробуйте снова:", reply_markup=cancel_keyboard())
        return
    await state.update_data(target_id=target_id)
    await state.set_state(AdminGiveStates.waiting_for_amount)
    await message.answer("Введите сумму для начисления:", reply_markup=cancel_keyboard())

@router.message(AdminGiveStates.waiting_for_amount, F.text)
async def admin_give_amount(message: types.Message, state: FSMContext):
    print(">>> admin_give_amount вызван")
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительным числом. Попробуйте снова:", reply_markup=cancel_keyboard())
            return
    except ValueError:
        await message.answer("❌ Введите число. Попробуйте снова:", reply_markup=cancel_keyboard())
        return

    data = await state.get_data()
    target_id = data.get("target_id")
    target_balance, *_ = await get_user(target_id, None)
    new_balance = target_balance + amount
    await update_balance(target_id, new_balance)

    await message.answer(
        f"✅ Пользователю {target_id} начислено {amount} 💎.\n"
        f"Новый баланс: {new_balance} 💎."
    )
    try:
        await message.bot.send_message(
            target_id,
            f"🎁 Вам начислено {amount} 💎 администратором!\nТекущий баланс: {new_balance} 💎."
        )
    except Exception:
        pass

    await state.clear()
    await message.answer(
        "👑 Админ панель\nВыберите действие:",
        reply_markup=admin_panel_keyboard()
    )

# ===== Списание баллов =====
@router.callback_query(F.data == "admin_take")
async def admin_take_callback(callback: types.CallbackQuery, state: FSMContext):
    print(">>> admin_take_callback вызван")
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminTakeStates.waiting_for_target_id)
    await callback.message.edit_text(
        "Введите ID пользователя, у которого хотите забрать баллы:",
        reply_markup=cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminTakeStates.waiting_for_target_id, F.text)
async def admin_take_target_id(message: types.Message, state: FSMContext):
    print(">>> admin_take_target_id вызван")
    try:
        target_id = int(message.text)
    except ValueError:
        await message.answer("❌ ID должен быть числом. Попробуйте снова:", reply_markup=cancel_keyboard())
        return
    await state.update_data(target_id=target_id)
    await state.set_state(AdminTakeStates.waiting_for_amount)
    await message.answer("Введите сумму для списания:", reply_markup=cancel_keyboard())

@router.message(AdminTakeStates.waiting_for_amount, F.text)
async def admin_take_amount(message: types.Message, state: FSMContext):
    print(">>> admin_take_amount вызван")
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительным числом. Попробуйте снова:", reply_markup=cancel_keyboard())
            return
    except ValueError:
        await message.answer("❌ Введите число. Попробуйте снова:", reply_markup=cancel_keyboard())
        return

    data = await state.get_data()
    target_id = data.get("target_id")
    target_balance, *_ = await get_user(target_id, None)
    if target_balance < amount:
        await message.answer(f"❌ Недостаточно баллов. У пользователя {target_balance} 💎.")
        return
    new_balance = target_balance - amount
    await update_balance(target_id, new_balance)

    await message.answer(
        f"✅ У пользователя {target_id} списано {amount} 💎.\n"
        f"Новый баланс: {new_balance} 💎."
    )
    try:
        await message.bot.send_message(
            target_id,
            f"⚠️ У вас списано {amount} 💎 администратором.\nТекущий баланс: {new_balance} 💎."
        )
    except Exception:
        pass

    await state.clear()
    await message.answer(
        "👑 Админ панель\nВыберите действие:",
        reply_markup=admin_panel_keyboard()
    )

# ===== Информация о пользователе =====
@router.callback_query(F.data == "admin_userinfo")
async def admin_userinfo_callback(callback: types.CallbackQuery, state: FSMContext):
    print(">>> admin_userinfo_callback вызван")
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminUserInfoStates.waiting_for_target_id)
    await callback.message.edit_text(
        "Введите ID пользователя для получения информации:",
        reply_markup=cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminUserInfoStates.waiting_for_target_id, F.text)
async def admin_userinfo_result(message: types.Message, state: FSMContext):
    print(">>> admin_userinfo_result вызван")
    try:
        target_id = int(message.text)
    except ValueError:
        await message.answer("❌ ID должен быть числом. Попробуйте снова:", reply_markup=cancel_keyboard())
        return

    stats = await get_user_stats(target_id)
    if not stats:
        await message.answer("❌ Пользователь с таким ID не найден в базе данных.")
        await state.clear()
        return

    balance, total_games, wins = stats
    losses = total_games - wins
    win_percent = (wins / total_games * 100) if total_games > 0 else 0

    info_text = (
        f"👤 <b>Информация о пользователе</b>\n"
        f"🆔 <b>ID:</b> <code>{target_id}</code>\n"
        f"💎 <b>Баланс:</b> {balance}\n"
        f"🎮 <b>Всего игр:</b> {total_games}\n"
        f"🏆 <b>Побед:</b> {wins}\n"
        f"💔 <b>Проигрышей:</b> {losses}\n"
        f"📊 <b>Процент побед:</b> {win_percent:.1f}%"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Открыть чат", url=f"tg://user?id={target_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

    await message.answer(info_text, parse_mode="HTML", reply_markup=keyboard)
    await state.clear()

# ===== Список игроков (с пагинацией) =====
@router.callback_query(F.data == "admin_list")
async def admin_list_callback(callback: types.CallbackQuery, state: FSMContext):
    print(">>> admin_list_callback вызван")
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminListStates.browsing)
    await state.update_data(page=0)
    await show_users_page(callback.message, state, edit=True)
    await callback.answer()

async def show_users_page(message: types.Message, state: FSMContext, edit=False):
    print(">>> show_users_page вызвана")
    data = await state.get_data()
    page = data.get("page", 0)
    limit = 5
    offset = page * limit

    users = await get_all_users(offset, limit, active_days=30)
    total = await get_users_count(active_days=30)
    total_pages = (total + limit - 1) // limit

    if not users:
        text = "👥 Нет активных игроков за последние 30 дней."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в админ-панель", callback_data="admin_panel")]
        ])
    else:
        text_lines = [f"👥 <b>Активные игроки (последние 30 дней) — страница {page+1}/{total_pages}:</b>"]
        for uid, username, balance, total_games in users:
            name = f"@{username}" if username else "нет username"
            text_lines.append(f"🆔 <code>{uid}</code> | {name} | 💎 {balance} | 🎮 {total_games}")
        text = "\n".join(text_lines)

        buttons = []
        if page > 0:
            buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data="users_prev"))
        if page < total_pages - 1:
            buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data="users_next"))
        nav_buttons = [buttons] if buttons else []
        back_button = [InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_panel")]
        keyboard = InlineKeyboardMarkup(inline_keyboard=nav_buttons + [back_button])

    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(AdminListStates.browsing, F.data == "users_next")
async def users_next(callback: types.CallbackQuery, state: FSMContext):
    print(">>> users_next вызван")
    data = await state.get_data()
    page = data.get("page", 0) + 1
    await state.update_data(page=page)
    await show_users_page(callback.message, state, edit=True)
    await callback.answer()

@router.callback_query(AdminListStates.browsing, F.data == "users_prev")
async def users_prev(callback: types.CallbackQuery, state: FSMContext):
    print(">>> users_prev вызван")
    data = await state.get_data()
    page = data.get("page", 0) - 1
    await state.update_data(page=page)
    await show_users_page(callback.message, state, edit=True)
    await callback.answer()

# ===== Заявки на вывод =====
@router.callback_query(F.data == "admin_withdraw_requests")
async def admin_withdraw_requests(callback: types.CallbackQuery):
    print(">>> admin_withdraw_requests вызван")
    user_id = callback.from_user.id
    if user_id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, user_id, amount_points, amount_usdt, wallet_address FROM withdraw_requests WHERE status = 'pending'"
        ) as cursor:
            requests = await cursor.fetchall()

    if not requests:
        await callback.message.edit_text(
            "📭 Нет ожидающих заявок на вывод.",
            reply_markup=admin_panel_keyboard()
        )
        return

    text = "💸 **Ожидающие заявки:**\n\n"
    for req in requests:
        text += f"ID: {req[0]}\n"
        text += f"Пользователь: {req[1]}\n"
        text += f"Сумма: {req[2]} баллов ≈ {req[3]} USDT\n"
        text += f"Контакт: {req[4]}\n"
        text += f"Подтвердить: /confirm_withdraw {req[0]}\n"
        text += f"Отклонить: /reject_withdraw {req[0]}\n\n"

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_panel_keyboard())

# ===== Управление турнирами (заглушка) =====
@router.callback_query(F.data == "admin_tournaments")
async def admin_tournaments_callback(callback: types.CallbackQuery):
    print(">>> admin_tournaments_callback вызван")
    user_id = callback.from_user.id
    if user_id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await callback.message.edit_text(
        "⚙️ Функция управления турнирами находится в разработке.",
        reply_markup=admin_panel_keyboard()
    )
    await callback.answer()



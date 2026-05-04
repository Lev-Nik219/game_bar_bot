import asyncio
import time
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_IDS
from database import get_user, update_balance, get_user_stats, get_all_users, get_users_count, get_bonus_total, execute_query, get_deposit_stats
from keyboards.admin import (
    admin_main_keyboard, admin_stats_keyboard, admin_stats_back_keyboard, users_list_keyboard
)

router = Router()

class AdminStates(StatesGroup):
    waiting_for_target_id = State()
    waiting_for_amount = State()
    waiting_for_broadcast_message = State()
    waiting_for_reply_message = State()  # Для ответа пользователю из поддержки

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_cancel")]
    ])

def back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    user_id = message.from_user.id
    if user_id in ADMIN_IDS:
        await message.answer("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard())
    else:
        await message.answer("❌ У вас нет доступа к админ-панели.")

# ---------- НАЧИСЛЕНИЕ БАЛЛОВ ----------
@router.callback_query(F.data == "admin_give")
async def admin_give_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_target_id)
    await callback.message.edit_text("Введите ID пользователя:", reply_markup=cancel_keyboard())
    await callback.answer()

@router.message(AdminStates.waiting_for_target_id, F.text)
async def admin_give_target_id(message: types.Message, state: FSMContext):
    try:
        target_id = int(message.text)
    except ValueError:
        await message.answer("❌ ID должен быть числом.", reply_markup=cancel_keyboard())
        return
    await state.update_data(target_id=target_id)
    await state.set_state(AdminStates.waiting_for_amount)
    await message.answer("Введите сумму для начисления:", reply_markup=cancel_keyboard())

@router.message(AdminStates.waiting_for_amount, F.text)
async def admin_give_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительной.", reply_markup=cancel_keyboard())
            return
    except ValueError:
        await message.answer("❌ Введите число.", reply_markup=cancel_keyboard())
        return

    data = await state.get_data()
    target_id = data.get("target_id")
    target_balance, *_ = await get_user(target_id, None)
    new_balance = target_balance + amount
    await update_balance(target_id, new_balance)

    await message.answer(f"✅ Пользователю {target_id} начислено {amount} 💎.\nНовый баланс: {new_balance} 💎.")
    await state.clear()
    await message.answer("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard())

# ---------- СПИСАНИЕ БАЛЛОВ ----------
@router.callback_query(F.data == "admin_take")
async def admin_take_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_target_id)
    await callback.message.edit_text("Введите ID пользователя:", reply_markup=cancel_keyboard())
    await callback.answer()

@router.message(AdminStates.waiting_for_target_id, F.text)
async def admin_take_target_id(message: types.Message, state: FSMContext):
    try:
        target_id = int(message.text)
    except ValueError:
        await message.answer("❌ ID должен быть числом.", reply_markup=cancel_keyboard())
        return
    await state.update_data(target_id=target_id)
    await state.set_state(AdminStates.waiting_for_amount)
    await message.answer("Введите сумму для списания:", reply_markup=cancel_keyboard())

@router.message(AdminStates.waiting_for_amount, F.text)
async def admin_take_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительной.", reply_markup=cancel_keyboard())
            return
    except ValueError:
        await message.answer("❌ Введите число.", reply_markup=cancel_keyboard())
        return

    data = await state.get_data()
    target_id = data.get("target_id")
    target_balance, *_ = await get_user(target_id, None)
    if target_balance < amount:
        await message.answer(f"❌ Недостаточно баллов. У пользователя {target_balance} 💎.")
        return
    new_balance = target_balance - amount
    await update_balance(target_id, new_balance)

    await message.answer(f"✅ У пользователя {target_id} списано {amount} 💎.\nНовый баланс: {new_balance} 💎.")
    await state.clear()
    await message.answer("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard())

# ---------- СПИСОК ИГРОКОВ ----------
@router.callback_query(F.data == "admin_list")
async def admin_list_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.update_data(page=0)
    await show_users_page(callback.message, state, edit=True)
    await callback.answer()

async def show_users_page(message: types.Message, state: FSMContext, edit=False):
    data = await state.get_data()
    page = data.get("page", 0)
    limit = 5
    offset = page * limit

    users = await get_all_users(offset, limit, active_days=0)
    total = await get_users_count(active_days=0)
    total_pages = (total + limit - 1) // limit

    back_btn = [[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]

    if not users:
        text = "👥 Нет пользователей."
        keyboard = InlineKeyboardMarkup(inline_keyboard=back_btn)
    else:
        text = f"👥 <b>Список игроков — стр. {page+1}/{total_pages}</b>\n\n"
        keyboard = users_list_keyboard(users, page, total_pages)

    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(F.data == "admin_list_next")
async def admin_list_next(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    page = data.get("page", 0) + 1
    await state.update_data(page=page)
    await show_users_page(callback.message, state, edit=True)
    await callback.answer()

@router.callback_query(F.data == "admin_list_prev")
async def admin_list_prev(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    page = data.get("page", 0) - 1
    await state.update_data(page=page)
    await show_users_page(callback.message, state, edit=True)
    await callback.answer()

@router.callback_query(F.data.startswith("user_info_"))
async def user_info_callback(callback: types.CallbackQuery):
    user_id = int(callback.data.replace("user_info_", ""))
    
    stats = await get_user_stats(user_id)
    if not stats:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    balance, total_games, wins = stats
    bonus_total = await get_bonus_total(user_id)
    win_percent = (wins / total_games * 100) if total_games > 0 else 0
    
    ad_views = await execute_query(
        "SELECT COUNT(*) FROM game_history WHERE user_id = $1 AND game_type = 'ad_reward'",
        user_id, fetch_val=True
    ) or 0

    info_text = (
        f"👤 <b>Информация о пользователе</b>\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"💎 <b>Баланс:</b> {balance}\n"
        f"🎁 <b>Бонусный баланс:</b> {bonus_total}\n"
        f"🎮 <b>Всего игр:</b> {total_games}\n"
        f"🏆 <b>Побед:</b> {wins}\n"
        f"📊 <b>Процент побед:</b> {win_percent:.1f}%\n\n"
        f"📺 <b>Реклама:</b>\n"
        f"   Просмотрено роликов: {ad_views}\n"
        f"   Заработано для казино: ≈ ${ad_views * 0.0005:.2f}"
    )
    
    await callback.message.edit_text(info_text, parse_mode="HTML", reply_markup=back_keyboard())
    await callback.answer()

# ---------- СТАТИСТИКА ----------
@router.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await callback.message.edit_text("📊 <b>Статистика</b>\n\nВыберите тип:", parse_mode="HTML", reply_markup=admin_stats_keyboard())
    await callback.answer()

@router.callback_query(F.data == "admin_stats_main")
async def admin_stats_main_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return

    total_users = await execute_query("SELECT COUNT(*) FROM users", fetch_val=True) or 0
    threshold = int(time.time()) - 30*86400
    active_users = await execute_query("SELECT COUNT(*) FROM users WHERE last_active > $1", threshold, fetch_val=True) or 0
    total_deposits = await execute_query("SELECT COUNT(*) FROM crypto_transactions WHERE status='paid'", fetch_val=True) or 0
    total_deposit_sum = await execute_query("SELECT COALESCE(SUM(amount), 0) FROM deposits", fetch_val=True) or 0
    
    ad_views_total = await execute_query("SELECT COUNT(*) FROM game_history WHERE game_type = 'ad_reward'", fetch_val=True) or 0
    ad_views_today = await execute_query("SELECT COUNT(*) FROM game_history WHERE game_type = 'ad_reward' AND played_at >= strftime('%s','now') - 86400", fetch_val=True) or 0
    ad_earnings = round(ad_views_total * 0.0005, 2)

    text = (
        f"📊 <b>Общая статистика</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🟢 Активных за 30 дней: {active_users}\n"
        f"💰 Всего депозитов: {total_deposits} на сумму {total_deposit_sum} баллов\n\n"
        f"📺 <b>Реклама:</b>\n"
        f"   Просмотров сегодня: {ad_views_today}\n"
        f"   Всего просмотров: {ad_views_total}\n"
        f"   Примерный доход: ${ad_earnings} USDT"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_stats_back_keyboard())
    await callback.answer()

@router.callback_query(F.data == "admin_stats_deposits")
async def admin_stats_deposits_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return

    stats = await get_deposit_stats()
    
    text = (
        f"💰 <b>Статистика пополнений</b>\n\n"
        f"📊 Всего пополнений: {stats['total_deposits']}\n"
        f"✅ Успешных: {stats['successful']}\n"
        f"💵 Общая сумма: {stats['total_amount']} баллов ≈ {stats['total_amount_usdt']} USDT\n"
        f"📈 Средний чек: {stats['avg_amount']:.0f} баллов\n"
        f"🏆 Максимальное: {stats['max_amount']} баллов"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_stats_back_keyboard())
    await callback.answer()

# ---------- МАССОВАЯ РАССЫЛКА ----------
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    await callback.message.edit_text("📢 Введите сообщение для массовой рассылки ВСЕМ пользователям:", reply_markup=cancel_keyboard())
    await callback.answer()

@router.message(AdminStates.waiting_for_broadcast_message, F.text)
async def admin_broadcast_message(message: types.Message, state: FSMContext):
    text = message.text
    await message.answer("⏳ Начинаю массовую рассылку...")

    rows = await execute_query("SELECT user_id FROM users", fetch_all=True)
    users = rows if rows else []

    success = 0
    failed = 0

    for (user_id,) in users:
        try:
            await message.bot.send_message(user_id, f"📢 <b>Массовая рассылка от администратора</b>\n\n{text}", parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await message.answer(f"✅ Массовая рассылка завершена.\n\n📨 Успешно: {success}\n❌ Неудачно: {failed}")
    await state.clear()
    await message.answer("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard())

# ---------- ОТМЕНА И НАЗАД ----------
@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard())
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard())
    await callback.answer()
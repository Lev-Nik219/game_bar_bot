import asyncio
import time
import logging
import aiosqlite
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

from config import ADMIN_BOT_TOKEN, ADMIN_IDS, ADMIN_NAMES, MAIN_BOT_TOKEN
from database import (
    DB_NAME, get_user, update_balance, get_user_stats,
    get_all_users, get_users_count, get_bonus_total,
    create_withdraw_request, get_pending_withdraw_requests,
    get_all_withdraw_requests, count_withdraw_requests, update_withdraw_request_status,
    create_crypto_transaction, get_crypto_transaction, update_crypto_transaction_status,
    get_withdraw_stats, get_deposit_stats, get_user_withdraw_stats, get_user_deposit_stats,
    get_daily_withdrawn, get_last_deposit_time, get_pending_withdraw_count,
    get_daily_total_withdrawn_rub, update_bonus_wagered, get_bonus_wagering_status,
    get_demo_games_played, increment_demo_games_played, reset_demo_games_played
)
from keyboards import (
    admin_main_keyboard, admin_cancel_keyboard, admin_back_keyboard,
    admin_bot_choice_keyboard, admin_stats_keyboard, admin_stats_back_keyboard
)
from states import (
    AdminGiveStates, AdminTakeStates, AdminUserInfoStates,
    AdminBroadcastStates, CreateTournamentStates, AdminListStates,
    AdminStatsUserStates
)

logger = logging.getLogger(__name__)
router = Router()

# ---- HTTP API для отправки сообщений через основного бота ----
async def send_message_via_main_bot(chat_id: int, text: str, parse_mode: str = "HTML"):
    """Отправляет сообщение через основного бота, используя HTTP API."""
    import aiohttp
    url = f"https://api.telegram.org/bot{MAIN_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                result = await resp.json()
                if not result.get('ok'):
                    logger.error(f"Ошибка отправки: {result}")
                return result
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения через HTTP API: {e}")
        return None

async def send_message_via_main_bot_silent(chat_id: int, text: str, parse_mode: str = "HTML"):
    """Отправляет сообщение, игнорируя ошибки."""
    try:
        await send_message_via_main_bot(chat_id, text, parse_mode)
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления пользователю {chat_id}: {e}")

# ---- Фоновая задача для проверки висящих заявок ----
async def check_pending_withdrawals():
    """Периодическая проверка висящих заявок (каждые 10 минут)."""
    while True:
        await asyncio.sleep(600)  # 10 минут
        try:
            async with aiosqlite.connect(DB_NAME) as conn:
                cursor = await conn.execute(
                    "SELECT id, user_id, amount_points, created_at FROM withdraw_requests WHERE status = 'pending' AND created_at < strftime('%s','now') - 86400"
                )
                old_requests = await cursor.fetchall()
                for req in old_requests:
                    request_id, user_id, amount_points, created_at = req
                    for admin_id in ADMIN_IDS:
                        await send_message_via_main_bot_silent(
                            admin_id,
                            f"⚠️ <b>Напоминание о висящей заявке!</b>\n\n"
                            f"🆔 Заявка #{request_id}\n"
                            f"👤 Пользователь: <code>{user_id}</code>\n"
                            f"💸 Сумма: {amount_points} баллов\n"
                            f"📅 Создана: {datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M')}\n"
                            f"⏳ Ожидает более 24 часов.\n\n"
                            f"Используйте /confirm_withdraw {request_id} или /reject_withdraw {request_id}"
                        )
        except Exception as e:
            logger.error(f"Ошибка в фоновой проверке заявок: {e}")

# Запускаем фоновую задачу при старте
async def start_background_tasks():
    asyncio.create_task(check_pending_withdrawals())

# --- Команда старт ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этому боту.")
        return
    await message.answer(
        "👑 Панель администратора\n\nВыберите действие:",
        reply_markup=admin_main_keyboard()
    )

@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👑 Панель администратора\n\nВыберите действие:",
        reply_markup=admin_main_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👑 Панель администратора\n\nВыберите действие:",
        reply_markup=admin_main_keyboard()
    )
    await callback.answer()

# ===== Начисление баллов =====
@router.callback_query(F.data == "admin_give")
async def admin_give_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminGiveStates.waiting_for_target_id)
    await callback.message.edit_text(
        "Введите ID пользователя, которому хотите начислить баллы:",
        reply_markup=admin_cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminGiveStates.waiting_for_target_id, F.text)
async def admin_give_target_id(message: types.Message, state: FSMContext):
    try:
        target_id = int(message.text)
    except ValueError:
        await message.answer("❌ ID должен быть числом. Попробуйте снова:", reply_markup=admin_cancel_keyboard())
        return
    await state.update_data(target_id=target_id)
    await state.set_state(AdminGiveStates.waiting_for_amount)
    await message.answer("Введите сумму для начисления:", reply_markup=admin_cancel_keyboard())

@router.message(AdminGiveStates.waiting_for_amount, F.text)
async def admin_give_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительным числом. Попробуйте снова:", reply_markup=admin_cancel_keyboard())
            return
    except ValueError:
        await message.answer("❌ Введите число. Попробуйте снова:", reply_markup=admin_cancel_keyboard())
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

    await send_message_via_main_bot_silent(
        target_id,
        f"🎁 <b>Вам начислено {amount} 💎 администратором!</b>\n\n"
        f"Текущий баланс: {new_balance} 💎."
    )

    await state.clear()
    await message.answer(
        "👑 Панель администратора\n\nВыберите действие:",
        reply_markup=admin_main_keyboard()
    )

# ===== Списание баллов =====
@router.callback_query(F.data == "admin_take")
async def admin_take_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminTakeStates.waiting_for_target_id)
    await callback.message.edit_text(
        "Введите ID пользователя, у которого хотите забрать баллы:",
        reply_markup=admin_cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminTakeStates.waiting_for_target_id, F.text)
async def admin_take_target_id(message: types.Message, state: FSMContext):
    try:
        target_id = int(message.text)
    except ValueError:
        await message.answer("❌ ID должен быть числом. Попробуйте снова:", reply_markup=admin_cancel_keyboard())
        return
    await state.update_data(target_id=target_id)
    await state.set_state(AdminTakeStates.waiting_for_amount)
    await message.answer("Введите сумму для списания:", reply_markup=admin_cancel_keyboard())

@router.message(AdminTakeStates.waiting_for_amount, F.text)
async def admin_take_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount <= 0:
            await message.answer("❌ Сумма должна быть положительным числом. Попробуйте снова:", reply_markup=admin_cancel_keyboard())
            return
    except ValueError:
        await message.answer("❌ Введите число. Попробуйте снова:", reply_markup=admin_cancel_keyboard())
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

    await send_message_via_main_bot_silent(
        target_id,
        f"⚠️ <b>У вас списано {amount} 💎 администратором.</b>\n\n"
        f"Текущий баланс: {new_balance} 💎."
    )

    await state.clear()
    await message.answer(
        "👑 Панель администратора\n\nВыберите действие:",
        reply_markup=admin_main_keyboard()
    )

# ===== Информация о пользователе =====
@router.callback_query(F.data == "admin_userinfo")
async def admin_userinfo_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminUserInfoStates.waiting_for_target_id)
    await callback.message.edit_text(
        "Введите ID пользователя для получения информации:",
        reply_markup=admin_cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminUserInfoStates.waiting_for_target_id, F.text)
async def admin_userinfo_result(message: types.Message, state: FSMContext):
    try:
        target_id = int(message.text)
    except ValueError:
        await message.answer("❌ ID должен быть числом. Попробуйте снова:", reply_markup=admin_cancel_keyboard())
        return

    stats = await get_user_stats(target_id)
    if not stats:
        await message.answer("❌ Пользователь с таким ID не найден в базе данных.", reply_markup=admin_back_keyboard())
        await state.clear()
        return

    balance, total_games, wins = stats
    bonus_total = await get_bonus_total(target_id)
    bonus_balance, bonus_wagered, is_cleared = await get_bonus_wagering_status(target_id)
    losses = total_games - wins
    win_percent = (wins / total_games * 100) if total_games > 0 else 0

    withdraw_stats = await get_user_withdraw_stats(target_id)
    deposit_stats = await get_user_deposit_stats(target_id)
    pending_count = await get_pending_withdraw_count(target_id)

    info_text = (
        f"👤 <b>Информация о пользователе</b>\n"
        f"🆔 <b>ID:</b> <code>{target_id}</code>\n"
        f"💎 <b>Баланс:</b> {balance}\n"
        f"🎁 <b>Бонусный баланс:</b> {bonus_total}\n"
        f"🎮 <b>Всего игр:</b> {total_games}\n"
        f"🏆 <b>Побед:</b> {wins}\n"
        f"💔 <b>Проигрышей:</b> {losses}\n"
        f"📊 <b>Процент побед:</b> {win_percent:.1f}%\n\n"
        f"🎲 <b>Отыгрыш бонуса:</b>\n"
        f"   Бонусный баланс: {bonus_balance} баллов\n"
        f"   Отыграно: {bonus_wagered} баллов\n"
        f"   Нужно: {bonus_balance * 3} баллов\n\n"
        f"💸 <b>Статистика выводов:</b>\n"
        f"   Всего: {withdraw_stats['count']} на {withdraw_stats['total']} баллов\n"
        f"   Успешных: {withdraw_stats['completed']} на {withdraw_stats['completed_amount']} баллов\n"
        f"   Ожидающих: {withdraw_stats['pending']}\n\n"
        f"💰 <b>Статистика пополнений:</b>\n"
        f"   Всего: {deposit_stats['count']} на {deposit_stats['total']} баллов\n"
        f"⏳ <b>Активных заявок:</b> {pending_count}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])

    await message.answer(info_text, parse_mode="HTML", reply_markup=keyboard)
    await state.clear()

# ===== Список игроков =====
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

    if not users:
        text = "👥 Нет пользователей в базе данных."
        keyboard = [[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]
    else:
        text_lines = [f"👥 <b>Все пользователи — страница {page+1}/{total_pages}:</b>"]
        for uid, username, balance, total_games in users:
            name = f"@{username}" if username else "нет username"
            text_lines.append(f"🆔 <code>{uid}</code> | {name} | 💎 {balance} | 🎮 {total_games}")
        text = "\n".join(text_lines)

        keyboard = []
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_list_prev"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data="admin_list_next"))
        if nav_row:
            keyboard.append(nav_row)
        keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])

    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

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

# ===== Статистика =====
@router.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await state.update_data(stats_submenu=True)
    await callback.message.edit_text(
        "📊 <b>Статистика</b>\n\nВыберите тип статистики:",
        parse_mode="HTML",
        reply_markup=admin_stats_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_stats_main")
async def admin_stats_main_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        total_users = (await cursor.fetchone())[0]
        
        threshold = int(time.time()) - 30*86400
        cursor = await conn.execute("SELECT COUNT(*) FROM users WHERE last_active > ?", (threshold,))
        active_users = (await cursor.fetchone())[0]
        
        cursor = await conn.execute("SELECT COUNT(*) FROM crypto_transactions WHERE status='paid'")
        total_deposits = (await cursor.fetchone())[0]
        
        cursor = await conn.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status='pending'")
        pending_withdrawals = (await cursor.fetchone())[0]
        
        cursor = await conn.execute("SELECT SUM(amount) FROM deposits")
        total_deposit_sum_row = await cursor.fetchone()
        total_deposit_sum = total_deposit_sum_row[0] if total_deposit_sum_row[0] else 0

    text = (
        f"📊 <b>Общая статистика</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🟢 Активных за 30 дней: {active_users}\n"
        f"💰 Всего депозитов: {total_deposits} на сумму {total_deposit_sum} баллов\n"
        f"⏳ Ожидающих выводов: {pending_withdrawals}"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_stats_back_keyboard())
    await callback.answer()

@router.callback_query(F.data == "admin_stats_withdrawals")
async def admin_stats_withdrawals_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return

    stats = await get_withdraw_stats()
    
    text = (
        f"💸 <b>Статистика выводов</b>\n\n"
        f"📊 <b>Всего заявок:</b> {stats['total_requests']}\n"
        f"✅ <b>Успешных выводов:</b> {stats['completed_requests']}\n"
        f"❌ <b>Отклонённых:</b> {stats['rejected_requests']}\n"
        f"⏳ <b>Ожидают:</b> {stats['pending_requests']}\n\n"
        f"💰 <b>Общая сумма успешных выводов:</b>\n"
        f"   {stats['completed_amount']} баллов\n"
        f"   ≈ {stats['completed_amount_usdt']} USDT\n"
        f"   ≈ {stats['completed_amount_rub']} руб\n\n"
        f"🕐 <b>Среднее время обработки заявки:</b>\n"
        f"   {stats['avg_processing_time']:.1f} часов"
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
        f"📊 <b>Всего пополнений:</b> {stats['total_deposits']}\n"
        f"✅ <b>Успешных:</b> {stats['successful']}\n"
        f"⏳ <b>В обработке:</b> {stats['pending']}\n"
        f"❌ <b>Неудачных:</b> {stats['failed']}\n\n"
        f"💵 <b>Общая сумма пополнений:</b>\n"
        f"   {stats['total_amount']} баллов\n"
        f"   ≈ {stats['total_amount_rub']} руб\n"
        f"   ≈ {stats['total_amount_usdt']} USDT\n\n"
        f"📈 <b>Средний чек:</b> {stats['avg_amount']:.0f} баллов\n"
        f"🏆 <b>Максимальное пополнение:</b> {stats['max_amount']} баллов"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_stats_back_keyboard())
    await callback.answer()

@router.callback_query(F.data == "admin_stats_user")
async def admin_stats_user_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStatsUserStates.waiting_for_user_id)
    await callback.message.edit_text(
        "Введите ID пользователя для просмотра его статистики выводов и пополнений:",
        reply_markup=admin_cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminStatsUserStates.waiting_for_user_id, F.text)
async def admin_stats_user_result(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ ID должен быть числом. Попробуйте снова:", reply_markup=admin_cancel_keyboard())
        return

    user_data = await get_user_stats(user_id)
    if not user_data:
        await message.answer("❌ Пользователь с таким ID не найден в базе данных.", reply_markup=admin_back_keyboard())
        await state.clear()
        return

    withdraw_stats = await get_user_withdraw_stats(user_id)
    deposit_stats = await get_user_deposit_stats(user_id)
    pending_count = await get_pending_withdraw_count(user_id)

    text = (
        f"📊 <b>Статистика пользователя <code>{user_id}</code></b>\n\n"
        f"💸 <b>Выводы:</b>\n"
        f"   Всего: {withdraw_stats['count']} на {withdraw_stats['total']} баллов\n"
        f"   Успешных: {withdraw_stats['completed']} на {withdraw_stats['completed_amount']} баллов\n"
        f"   Ожидает: {withdraw_stats['pending']} заявок\n\n"
        f"💰 <b>Пополнения:</b>\n"
        f"   Всего: {deposit_stats['count']} на {deposit_stats['total']} баллов\n"
        f"   Средний чек: {deposit_stats['avg']:.0f} баллов\n"
        f"   Максимальное: {deposit_stats['max']} баллов\n\n"
        f"⏳ <b>Активных заявок:</b> {pending_count}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в статистику", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 Назад в админ-панель", callback_data="admin_back")]
    ])
    
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await state.clear()

# ===== Заявки на вывод (новые) =====
@router.callback_query(F.data == "admin_withdraw_requests")
async def admin_withdraw_requests(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return

    requests = await get_pending_withdraw_requests()

    if not requests:
        await callback.message.edit_text(
            "📭 Нет ожидающих заявок на вывод.",
            reply_markup=admin_back_keyboard()
        )
        return

    text = "💸 <b>Ожидающие заявки на вывод</b>\n\n"
    keyboard = []
    
    for req in requests:
        req_id, user_id, amount_points, amount_usdt, wallet = req
        user_data = await get_user(user_id, None)
        username = user_data[1] if user_data and user_data[1] else str(user_id)
        
        text += (
            f"┌ <b>Заявка #{req_id}</b>\n"
            f"├ 👤 Пользователь: <code>{username}</code> (ID: {user_id})\n"
            f"├ 💸 Сумма: {amount_points} баллов ≈ {amount_usdt} USDT\n"
            f"└ 📞 Контакт: {wallet}\n\n"
        )
        
        keyboard.append([
            InlineKeyboardButton(
                text=f"✅ Подтвердить #{req_id}",
                callback_data=f"admin_confirm_withdraw_{user_id}_{amount_points}"
            ),
            InlineKeyboardButton(
                text=f"❌ Отклонить #{req_id}",
                callback_data=f"admin_reject_withdraw_{user_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

# ===== История заявок на вывод =====
@router.callback_query(F.data == "admin_withdraw_history")
async def admin_withdraw_history_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.update_data(withdraw_history_page=0)
    await show_withdraw_history(callback.message, state, edit=True)
    await callback.answer()

async def show_withdraw_history(message: types.Message, state: FSMContext, edit=False):
    data = await state.get_data()
    page = data.get("withdraw_history_page", 0)
    limit = 5
    offset = page * limit

    requests = await get_all_withdraw_requests(offset, limit)
    total = await count_withdraw_requests()
    total_pages = (total + limit - 1) // limit if total > 0 else 1

    if not requests:
        text = "📜 Нет заявок на вывод."
        keyboard = [[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]
    else:
        text = f"📜 <b>Общие заявки на вывод — страница {page+1}/{total_pages}</b>\n\n"
        keyboard = []
        
        for req in requests:
            req_id, uid, amount_points, amount_usdt, wallet, status, created_at, completed_at = req
            status_emoji = "🟡" if status == 'pending' else ("✅" if status == 'completed' else "❌")
            
            text += f"{status_emoji} <b>Заявка #{req_id}</b>\n"
            text += f"👤 Пользователь: <code>{uid}</code>\n"
            text += f"💸 Сумма: {amount_points} баллов (~{amount_usdt} USDT)\n"
            text += f"📞 Контакт: {wallet}\n"
            text += f"📅 Создана: {datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M')}\n"
            if status == 'completed' and completed_at:
                text += f"✅ Подтверждена: {datetime.fromtimestamp(completed_at).strftime('%Y-%m-%d %H:%M')}\n"
            elif status == 'rejected':
                text += f"❌ Отклонена\n"
            text += "\n"
            
            if status == 'pending':
                keyboard.append([
                    InlineKeyboardButton(
                        text=f"✅ Подтвердить #{req_id}",
                        callback_data=f"admin_confirm_withdraw_{uid}_{amount_points}"
                    ),
                    InlineKeyboardButton(
                        text=f"❌ Отклонить #{req_id}",
                        callback_data=f"admin_reject_withdraw_{uid}"
                    )
                ])
        
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data="withdraw_history_prev"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data="withdraw_history_next"))
        if nav_row:
            keyboard.append(nav_row)
        keyboard.append([InlineKeyboardButton(text="🔙 Назад в админ-панель", callback_data="admin_back")])

    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@router.callback_query(F.data == "withdraw_history_next")
async def withdraw_history_next(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    page = data.get("withdraw_history_page", 0) + 1
    await state.update_data(withdraw_history_page=page)
    await show_withdraw_history(callback.message, state, edit=True)
    await callback.answer()

@router.callback_query(F.data == "withdraw_history_prev")
async def withdraw_history_prev(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    page = data.get("withdraw_history_page", 0) - 1
    await state.update_data(withdraw_history_page=page)
    await show_withdraw_history(callback.message, state, edit=True)
    await callback.answer()

# ===== Рассылка =====
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(AdminBroadcastStates.waiting_for_bot_choice)
    await callback.message.edit_text(
        "Выберите бота для рассылки:",
        reply_markup=admin_bot_choice_keyboard()
    )
    await callback.answer()

@router.callback_query(AdminBroadcastStates.waiting_for_bot_choice, F.data.startswith("broadcast_bot_"))
async def broadcast_bot_choice(callback: types.CallbackQuery, state: FSMContext):
    choice = callback.data.replace("broadcast_bot_", "")
    await state.update_data(bot_choice=choice)
    await state.set_state(AdminBroadcastStates.waiting_for_message)
    await callback.message.edit_text(
        "Введите сообщение для рассылки всем пользователям:",
        reply_markup=admin_cancel_keyboard()
    )
    await callback.answer()

@router.message(AdminBroadcastStates.waiting_for_message, F.text)
async def admin_broadcast_message(message: types.Message, state: FSMContext):
    text = message.text
    data = await state.get_data()
    bot_choice = data.get("bot_choice", "admin")

    await message.answer("⏳ Начинаю рассылку...")

    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT user_id FROM users")
        users = await cursor.fetchall()

    success = 0
    failed = 0

    if bot_choice == "main":
        for (user_id,) in users:
            try:
                await send_message_via_main_bot(user_id, text)
                success += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
    else:
        for (user_id,) in users:
            try:
                await message.bot.send_message(user_id, text)
                success += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1

    await message.answer(
        f"✅ Рассылка завершена.\n\n"
        f"📨 Успешно: {success}\n"
        f"❌ Неудачно: {failed}"
    )
    await state.clear()
    await message.answer(
        "👑 Панель администратора\n\nВыберите действие:",
        reply_markup=admin_main_keyboard()
    )

# ===== Создание турнира =====
@router.callback_query(F.data == "admin_create_tournament")
async def admin_create_tournament_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    await state.set_state(CreateTournamentStates.waiting_for_name)
    await callback.message.edit_text(
        "Введите название турнира:",
        reply_markup=admin_cancel_keyboard()
    )
    await callback.answer()

@router.message(CreateTournamentStates.waiting_for_name, F.text)
async def create_tournament_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(CreateTournamentStates.waiting_for_prize)
    await message.answer("Введите призовой фонд (в баллах):", reply_markup=admin_cancel_keyboard())

@router.message(CreateTournamentStates.waiting_for_prize, F.text)
async def create_tournament_prize(message: types.Message, state: FSMContext):
    try:
        prize = int(message.text)
        if prize <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число.", reply_markup=admin_cancel_keyboard())
        return
    await state.update_data(prize=prize)
    await state.set_state(CreateTournamentStates.waiting_for_duration)
    await message.answer("Введите длительность турнира в часах:", reply_markup=admin_cancel_keyboard())

@router.message(CreateTournamentStates.waiting_for_duration, F.text)
async def create_tournament_duration(message: types.Message, state: FSMContext):
    try:
        hours = int(message.text)
        if hours <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число.", reply_markup=admin_cancel_keyboard())
        return
    data = await state.get_data()
    name = data['name']
    prize = data['prize']
    now = int(time.time())
    end_time = now + hours * 3600
    
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute(
            "INSERT INTO tournaments (name, prize_points, start_time, end_time, status) VALUES (?, ?, ?, ?, 'active')",
            (name, prize, now, end_time)
        )
        await conn.commit()
    
    # Отправляем уведомление в основной бот о создании турнира
    await send_message_via_main_bot_silent(
        1167503795,  # ID администратора (можно отправить всем админам)
        f"🏆 <b>Создан новый турнир!</b>\n\n"
        f"📌 <b>Название:</b> {name}\n"
        f"💰 <b>Приз:</b> {prize} баллов\n"
        f"⏱️ <b>Длительность:</b> {hours} часов\n\n"
        f"🎮 Турнир будет доступен в основном боте в разделе «Турниры»."
    )
    
    # Также уведомляем всех пользователей (опционально)
    # Здесь можно добавить массовую рассылку, но для начала уведомляем только админа
    
    await message.answer(f"✅ Турнир «{name}» создан и продлится {hours} часов.\n\nУведомление отправлено в основной бот.")
    await state.clear()
    await message.answer(
        "👑 Панель администратора\n\nВыберите действие:",
        reply_markup=admin_main_keyboard()
    )

# ===== Обработка заявок на вывод (подтверждение/отклонение) =====
@router.callback_query(F.data.startswith("admin_confirm_withdraw_"))
async def admin_confirm_withdraw(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    if len(parts) == 5:
        try:
            user_id = int(parts[3])
            amount_points = int(parts[4])
        except ValueError:
            await callback.answer("❌ Неверный формат данных", show_alert=True)
            return
    else:
        await callback.answer("❌ Неверный формат данных", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute(
            "SELECT id, amount_usdt, wallet_address FROM withdraw_requests WHERE user_id = ? AND amount_points = ? AND status='pending' ORDER BY created_at DESC LIMIT 1",
            (user_id, amount_points)
        )
        row = await cursor.fetchone()
        if not row:
            await callback.answer("❌ Заявка не найдена или уже обработана", show_alert=True)
            return
        request_id, amount_usdt, wallet_address = row

        await conn.execute(
            "UPDATE withdraw_requests SET status='completed', completed_at=? WHERE id=?",
            (int(time.time()), request_id)
        )
        await conn.commit()

        cursor2 = await conn.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        user_row = await cursor2.fetchone()
        username = user_row[0] if user_row else None

    await send_message_via_main_bot_silent(
        user_id,
        f"✅ <b>Ваш запрос на вывод {amount_points} баллов подтверждён администратором!</b>\n\n"
        f"Средства будут отправлены на указанный вами контакт в ближайшее время."
    )

    admin_id = callback.from_user.id
    if username:
        user_link = f"https://t.me/{username}"
        user_link_text = f"@{username}"
    else:
        user_link = f"tg://user?id={user_id}"
        user_link_text = f"пользователь {user_id}"

    admin_message = (
        f"✅ <b>Заявка #{request_id} подтверждена!</b>\n\n"
        f"👤 Пользователь: <a href='{user_link}'>{user_link_text}</a>\n"
        f"📞 Контакт: {wallet_address}\n"
        f"💸 Сумма: {amount_points} баллов ≈ {amount_usdt} USDT\n\n"
        f"💡 <b>Для отправки средств:</b>\n"
        f"1. Нажмите на ссылку выше, чтобы открыть чат с пользователем.\n"
        f"2. Отправьте команду:\n"
        f"<code>@send {amount_usdt} USDT</code>\n\n"
        f"После отправки нажмите «Готово» в админ-панели (если требуется)."
    )

    try:
        await callback.bot.send_message(
            chat_id=admin_id,
            text=admin_message,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение администратору {admin_id}: {e}")

    await callback.message.edit_text(
        f"✅ Заявка пользователя {user_id} на {amount_points} баллов подтверждена.\n"
        f"Пользователь уведомлён.\n"
        f"Администратору отправлены инструкции для отправки средств.",
        reply_markup=admin_back_keyboard()
    )
    await callback.answer("Вывод подтверждён", show_alert=True)

@router.callback_query(F.data.startswith("admin_reject_withdraw_"))
async def admin_reject_withdraw(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    if len(parts) == 4:
        try:
            user_id = int(parts[3])
        except ValueError:
            await callback.answer("❌ Неверный формат данных", show_alert=True)
            return
    else:
        await callback.answer("❌ Неверный формат данных", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute(
            "SELECT id, amount_points FROM withdraw_requests WHERE user_id = ? AND status='pending' ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        )
        row = await cursor.fetchone()
        if not row:
            await callback.answer("❌ Нет ожидающих заявок у этого пользователя", show_alert=True)
            return
        request_id, amount_points = row
        await conn.execute("UPDATE withdraw_requests SET status='rejected' WHERE id=?", (request_id,))
        await conn.commit()

    balance, *_ = await get_user(user_id, None)
    new_balance = balance + amount_points
    await update_balance(user_id, new_balance)

    await send_message_via_main_bot_silent(
        user_id,
        f"❌ <b>Ваш запрос на вывод {amount_points} баллов был отклонён администратором.</b>\n\n"
        f"Средства возвращены на ваш баланс.\n"
        f"Текущий баланс: {new_balance} 💎."
    )

    await callback.message.edit_text(
        f"❌ Заявка пользователя {user_id} на {amount_points} баллов отклонена.\n"
        f"Баллы возвращены пользователю."
    )
    await callback.answer("Заявка отклонена", show_alert=True)

@router.message(Command("confirm_withdraw"))
async def confirm_withdraw_command(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /confirm_withdraw <ID_заявки>")
        return

    try:
        request_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID заявки должен быть числом.")
        return

    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute(
            "SELECT user_id, amount_points, amount_usdt, wallet_address FROM withdraw_requests WHERE id = ? AND status = 'pending'",
            (request_id,)
        )
        row = await cursor.fetchone()
        if not row:
            await message.answer(f"❌ Заявка с ID {request_id} не найдена или уже обработана.")
            return

        target_user_id, amount_points, amount_usdt, contact = row
        amount_rub = round(amount_usdt * 90, 2)

        await conn.execute(
            "UPDATE withdraw_requests SET status = 'completed', completed_at = ? WHERE id = ?",
            (int(time.time()), request_id)
        )
        await conn.commit()

    await send_message_via_main_bot_silent(
        target_user_id,
        f"✅ <b>Ваш запрос на вывод {amount_points} баллов подтверждён администратором!</b>\n\n"
        f"Средства будут отправлены на указанный вами контакт."
    )

    await message.answer(
        f"✅ Заявка #{request_id} подтверждена.\n\n"
        f"👤 Пользователь: <code>{target_user_id}</code>\n"
        f"💸 Сумма: {amount_points} баллов ≈ {amount_rub} руб ≈ {amount_usdt} USDT\n"
        f"📞 Контакт: {contact}\n\n"
        f"Пользователь уведомлён."
    )

@router.message(Command("reject_withdraw"))
async def reject_withdraw_command(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /reject_withdraw <ID_заявки>")
        return

    try:
        request_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID заявки должен быть числом.")
        return

    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute(
            "SELECT user_id, amount_points, amount_usdt, wallet_address FROM withdraw_requests WHERE id = ? AND status = 'pending'",
            (request_id,)
        )
        row = await cursor.fetchone()
        if not row:
            await message.answer(f"❌ Заявка с ID {request_id} не найдена или уже обработана.")
            return

        target_user_id, amount_points, amount_usdt, contact = row
        amount_rub = round(amount_usdt * 90, 2)

        await conn.execute("UPDATE withdraw_requests SET status = 'rejected' WHERE id = ?", (request_id,))
        await conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount_points, target_user_id))
        await conn.commit()

    await send_message_via_main_bot_silent(
        target_user_id,
        f"❌ <b>Ваш запрос на вывод {amount_points} баллов был отклонён администратором.</b>\n\n"
        f"Средства возвращены на ваш баланс."
    )

    await message.answer(
        f"❌ Заявка #{request_id} отклонена.\n\n"
        f"👤 Пользователь: <code>{target_user_id}</code>\n"
        f"💸 Сумма: {amount_points} баллов ≈ {amount_rub} руб ≈ {amount_usdt} USDT\n"
        f"📞 Контакт: {contact}\n\n"
        f"Баллы возвращены пользователю."
    )

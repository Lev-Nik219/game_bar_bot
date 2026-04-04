#!/usr/bin/env python3
import asyncio
import logging
import os
import time
import aiohttp
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

from config import ADMIN_BOT_TOKEN, ADMIN_IDS, MAIN_BOT_TOKEN
from database import (
    get_user, update_balance, get_user_stats,
    get_all_users, get_users_count, get_bonus_total,
    get_pending_withdraw_requests,
    get_all_withdraw_requests, count_withdraw_requests,
    get_withdraw_stats, get_deposit_stats, get_user_withdraw_stats, get_user_deposit_stats,
    get_pending_withdraw_count, get_bonus_wagering_status,
    create_db, execute_query, init_db_pool, close_db_pool
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
router = Router()

# Простой HTTP сервер для healthcheck
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
        self.end_headers()
    
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get('PORT', 10001))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

# ---- HTTP API для отправки сообщений через основного бота ----
async def send_message_via_main_bot(chat_id: int, text: str, parse_mode: str = "HTML"):
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
    try:
        await send_message_via_main_bot(chat_id, text, parse_mode)
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления пользователю {chat_id}: {e}")

# ===== ДИАГНОСТИЧЕСКИЕ КОМАНДЫ =====
@router.message(Command("debug_tournament"))
async def debug_tournament_admin(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    now = int(time.time())
    rows = await execute_query("SELECT id, name, prize_points, start_time, end_time, status FROM tournaments", fetch_all=True)
    
    if not rows:
        await message.answer("❌ Нет турниров в БД")
        return
    
    text = "🔍 Диагностика турниров (админ-бот):\n\n"
    for row in rows:
        tid, name, prize, start_time, end_time, status = row
        start_str = datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M')
        end_str = datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M')
        now_str = datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M')
        is_active = status == 'active' and start_time <= now <= end_time
        text += f"{'✅' if is_active else '❌'} ID: {tid}\n"
        text += f"   Название: {name}\n"
        text += f"   Приз: {prize}\n"
        text += f"   Статус: {status}\n"
        text += f"   Начало: {start_str}\n"
        text += f"   Конец: {end_str}\n"
        text += f"   Сейчас: {now_str}\n"
        text += "\n"
    await message.answer(text)

@router.message(Command("debug_withdrawals"))
async def debug_withdrawals(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ Нет доступа")
        return
    
    rows = await execute_query(
        "SELECT id, user_id, amount_points, amount_usdt, wallet_address, status, created_at FROM withdraw_requests ORDER BY created_at DESC",
        fetch_all=True
    )
    
    if not rows:
        await message.answer("📭 Нет заявок на вывод в БД")
        return
    
    text = "📋 Заявки на вывод:\n\n"
    for row in rows:
        req_id, uid, amount, usdt, wallet, status, created = row
        created_str = datetime.fromtimestamp(created).strftime('%Y-%m-%d %H:%M')
        text += f"ID: {req_id}\n"
        text += f"Пользователь: {uid}\n"
        text += f"Сумма: {amount} баллов ≈ {usdt} USDT\n"
        text += f"Контакт: {wallet}\n"
        text += f"Статус: {status}\n"
        text += f"Создана: {created_str}\n"
        text += "\n"
    await message.answer(text)

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

    total_users = await execute_query("SELECT COUNT(*) FROM users", fetch_val=True) or 0
    threshold = int(time.time()) - 30*86400
    active_users = await execute_query("SELECT COUNT(*) FROM users WHERE last_active > $1", threshold, fetch_val=True) or 0
    total_deposits = await execute_query("SELECT COUNT(*) FROM crypto_transactions WHERE status='paid'", fetch_val=True) or 0
    pending_withdrawals = await execute_query("SELECT COUNT(*) FROM withdraw_requests WHERE status='pending'", fetch_val=True) or 0
    total_deposit_sum = await execute_query("SELECT COALESCE(SUM(amount), 0) FROM deposits", fetch_val=True) or 0

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
                callback_data=f"admin_confirm_withdraw_{req_id}"
            ),
            InlineKeyboardButton(
                text=f"❌ Отклонить #{req_id}",
                callback_data=f"admin_reject_withdraw_{req_id}"
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
                        callback_data=f"admin_confirm_withdraw_{req_id}"
                    ),
                    InlineKeyboardButton(
                        text=f"❌ Отклонить #{req_id}",
                        callback_data=f"admin_reject_withdraw_{req_id}"
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

# ===== Обработка заявок на вывод =====
@router.callback_query(F.data.startswith("admin_confirm_withdraw_"))
async def admin_confirm_withdraw(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    if len(parts) >= 4:
        try:
            request_id = int(parts[3])
        except (ValueError, IndexError):
            await callback.answer("❌ Неверный формат данных", show_alert=True)
            return
    else:
        await callback.answer("❌ Неверный формат данных", show_alert=True)
        return

    row = await execute_query(
        "SELECT user_id, amount_points, amount_usdt, wallet_address FROM withdraw_requests WHERE id = $1 AND status='pending'",
        request_id, fetch_one=True
    )
    if not row:
        await callback.answer("❌ Заявка не найдена или уже обработана", show_alert=True)
        return
    
    target_user_id, amount_points, amount_usdt, wallet_address = row

    await execute_query(
        "UPDATE withdraw_requests SET status='completed', completed_at=$1 WHERE id=$2",
        int(time.time()), request_id
    )

    await send_message_via_main_bot(
        target_user_id,
        f"✅ <b>Ваш запрос на вывод {amount_points} баллов подтверждён администратором!</b>\n\n"
        f"Средства будут отправлены на указанный вами контакт в ближайшее время."
    )

    await callback.message.edit_text(
        f"✅ Заявка #{request_id} подтверждена.\n"
        f"Пользователь уведомлён.\n"
        f"📞 Контакт: {wallet_address}\n"
        f"💸 Сумма: {amount_points} баллов ≈ {amount_usdt} USDT",
        reply_markup=admin_back_keyboard()
    )
    await callback.answer("Вывод подтверждён", show_alert=True)

@router.callback_query(F.data.startswith("admin_reject_withdraw_"))
async def admin_reject_withdraw(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    if len(parts) >= 4:
        try:
            request_id = int(parts[3])
        except (ValueError, IndexError):
            await callback.answer("❌ Неверный формат данных", show_alert=True)
            return
    else:
        await callback.answer("❌ Неверный формат данных", show_alert=True)
        return

    row = await execute_query(
        "SELECT user_id, amount_points FROM withdraw_requests WHERE id = $1 AND status='pending'",
        request_id, fetch_one=True
    )
    if not row:
        await callback.answer("❌ Заявка не найдена или уже обработана", show_alert=True)
        return
    
    target_user_id, amount_points = row

    await execute_query("UPDATE withdraw_requests SET status='rejected' WHERE id=$1", request_id)
    await execute_query("UPDATE users SET balance = balance + $1 WHERE user_id = $2", amount_points, target_user_id)

    await send_message_via_main_bot(
        target_user_id,
        f"❌ <b>Ваш запрос на вывод {amount_points} баллов был отклонён администратором.</b>\n\n"
        f"Средства возвращены на ваш баланс."
    )

    await callback.message.edit_text(
        f"❌ Заявка #{request_id} отклонена.\n"
        f"Баллы возвращены пользователю.",
        reply_markup=admin_back_keyboard()
    )
    await callback.answer("Заявка отклонена", show_alert=True)

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

    rows = await execute_query("SELECT user_id FROM users", fetch_all=True)
    users = rows if rows else []

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
    
    await execute_query(
        "INSERT INTO tournaments (name, prize_points, start_time, end_time, status) VALUES ($1, $2, $3, $4, 'active')",
        name, prize, now, end_time
    )
    
    await send_message_via_main_bot_silent(
        ADMIN_IDS[0] if ADMIN_IDS else 1167503795,
        f"🏆 <b>Создан новый турнир!</b>\n\n"
        f"📌 <b>Название:</b> {name}\n"
        f"💰 <b>Приз:</b> {prize} баллов\n"
        f"⏱️ <b>Длительность:</b> {hours} часов\n\n"
        f"🎮 Турнир будет доступен в основном боте в разделе «Турниры»."
    )
    
    await message.answer(f"✅ Турнир «{name}» создан и продлится {hours} часов.\n\nУведомление отправлено в основной бот.")
    await state.clear()
    await message.answer(
        "👑 Панель администратора\n\nВыберите действие:",
        reply_markup=admin_main_keyboard()
    )

# ===== ОСНОВНАЯ ФУНКЦИЯ =====
async def main():
    await init_db_pool()
    await create_db()
    
    # Запускаем healthcheck сервер в отдельном потоке
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    await asyncio.sleep(1)
    
    bot = Bot(token=ADMIN_BOT_TOKEN)
    await bot.delete_webhook()
    
    dp = Dispatcher()
    dp.include_router(router)
    
    # Глобальный обработчик ошибок для dp
    @dp.errors()
    async def dp_error_handler(event: types.ErrorEvent):
        logger.error(f"Глобальная ошибка: {event.exception}", exc_info=True)
        return True
    
    try:
        await dp.start_polling(bot)
    finally:
        await close_db_pool()

if __name__ == "__main__":
    asyncio.run(main())
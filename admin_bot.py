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

from config import ADMIN_BOT_TOKEN, ADMIN_IDS, MAIN_BOT_TOKEN
from database import (
    get_user, update_balance, get_user_stats,
    get_all_users, get_users_count, get_bonus_total,
    get_withdraw_stats, get_deposit_stats,
    create_db, execute_query, init_db_pool, close_db_pool
)
from keyboards import (
    admin_main_keyboard, admin_cancel_keyboard, admin_back_keyboard,
    admin_bot_choice_keyboard, admin_stats_keyboard, admin_stats_back_keyboard
)
from states import (
    AdminGiveStates, AdminTakeStates, AdminUserInfoStates,
    AdminBroadcastStates, AdminListStates
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

# ===== ДИАГНОСТИЧЕСКАЯ КОМАНДА =====
@router.message(Command("debug_stats"))
async def debug_stats(message: types.Message):
    """Показывает общую статистику: донаты, реклама, ролики"""
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    
    # Статистика по депозитам
    deposit_stats = await get_deposit_stats()
    total_deposits_usdt = deposit_stats['total_amount_usdt']
    total_deposits_count = deposit_stats['successful']
    
    # Статистика по рекламе (просмотры роликов)
    ad_views_today = await execute_query(
        "SELECT COUNT(*) FROM game_history WHERE game_type = 'ad_reward' AND played_at >= strftime('%s','now') - 86400",
        fetch_val=True
    ) or 0
    
    ad_views_total = await execute_query(
        "SELECT COUNT(*) FROM game_history WHERE game_type = 'ad_reward'",
        fetch_val=True
    ) or 0
    
    # Доход с рекламы (примерная оценка: $0.5 за 1000 показов)
    ad_earnings = round(ad_views_total * 0.0005, 2)
    ad_earnings_today = round(ad_views_today * 0.0005, 2)
    
    # Всего пользователей
    total_users = await get_users_count()
    active_today = await execute_query(
        "SELECT COUNT(DISTINCT user_id) FROM game_history WHERE played_at >= strftime('%s','now') - 86400",
        fetch_val=True
    ) or 0
    
    text = (
        f"📊 <b>Общая статистика</b>\n\n"
        f"👥 <b>Пользователи:</b>\n"
        f"   Всего: {total_users}\n"
        f"   Активных сегодня: {active_today}\n\n"
        f"💰 <b>Донаты (USDT):</b>\n"
        f"   Всего донатов: {total_deposits_count}\n"
        f"   Сумма: {total_deposits_usdt} USDT\n\n"
        f"📺 <b>Реклама:</b>\n"
        f"   Просмотров сегодня: {ad_views_today}\n"
        f"   Всего просмотров: {ad_views_total}\n"
        f"   Примерный доход: ${ad_earnings} USDT\n"
        f"   Доход сегодня: ${ad_earnings_today} USDT\n\n"
        f"💡 <i>Доход с рекламы считается из расчёта $0.5 за 1000 показов</i>"
    )
    
    await message.answer(text, parse_mode="HTML")

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
async def get_user_deposit_stats_simple(user_id: int) -> dict:
    """Получает статистику пополнений пользователя"""
    count = await execute_query(
        "SELECT COUNT(*) FROM crypto_transactions WHERE user_id = $1 AND status = 'paid'",
        user_id, fetch_val=True
    ) or 0
    total = await execute_query(
        "SELECT COALESCE(SUM(amount_points), 0) FROM crypto_transactions WHERE user_id = $1 AND status = 'paid'",
        user_id, fetch_val=True
    ) or 0
    return {"count": count, "total": total}

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
    losses = total_games - wins
    win_percent = (wins / total_games * 100) if total_games > 0 else 0
    
    # Статистика донатов
    deposit_stats = await get_user_deposit_stats_simple(target_id)
    
    # Статистика просмотров рекламы
    ad_views = await execute_query(
        "SELECT COUNT(*) FROM game_history WHERE user_id = $1 AND game_type = 'ad_reward'",
        target_id, fetch_val=True
    ) or 0

    info_text = (
        f"👤 <b>Информация о пользователе</b>\n"
        f"🆔 <b>ID:</b> <code>{target_id}</code>\n"
        f"💎 <b>Баланс:</b> {balance}\n"
        f"🎁 <b>Бонусный баланс:</b> {bonus_total}\n"
        f"🎮 <b>Всего игр:</b> {total_games}\n"
        f"🏆 <b>Побед:</b> {wins}\n"
        f"💔 <b>Проигрышей:</b> {losses}\n"
        f"📊 <b>Процент побед:</b> {win_percent:.1f}%\n\n"
        f"💰 <b>Донаты:</b>\n"
        f"   Всего пополнений: {deposit_stats['count']}\n"
        f"   Сумма: {deposit_stats['total']} баллов\n\n"
        f"📺 <b>Реклама:</b>\n"
        f"   Просмотрено роликов: {ad_views}\n"
        f"   Заработано для казино: ≈ ${ad_views * 0.0005:.2f}"
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
        text_lines = [f"👥 <b>Список игроков — страница {page+1}/{total_pages}:</b>"]
        for uid, username, balance, total_games in users:
            name = f"@{username}" if username else f"ID {uid}"
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
    total_deposit_sum = await execute_query("SELECT COALESCE(SUM(amount), 0) FROM deposits", fetch_val=True) or 0
    
    # Статистика рекламы
    ad_views_total = await execute_query(
        "SELECT COUNT(*) FROM game_history WHERE game_type = 'ad_reward'",
        fetch_val=True
    ) or 0
    ad_views_today = await execute_query(
        "SELECT COUNT(*) FROM game_history WHERE game_type = 'ad_reward' AND played_at >= strftime('%s','now') - 86400",
        fetch_val=True
    ) or 0
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
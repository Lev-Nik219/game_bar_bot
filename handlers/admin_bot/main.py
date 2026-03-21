import asyncio
import time
import logging
import asyncpg
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
from database import init_db_pool
from config import BOT_TOKEN


from database import (
    get_user, update_balance, get_user_stats,
    get_all_users, get_users_count, get_bonus_total,
    init_db_pool, create_withdraw_request, get_pending_withdraw_requests,
    get_all_withdraw_requests, count_withdraw_requests, update_withdraw_request_status,
    create_crypto_transaction, get_crypto_transaction, update_crypto_transaction_status
)
from keyboards import (
    admin_main_keyboard, admin_cancel_keyboard, admin_back_keyboard,
    admin_bot_choice_keyboard
)
from states import (
    AdminGiveStates, AdminTakeStates, AdminUserInfoStates,
    AdminBroadcastStates, CreateTournamentStates, AdminListStates
)
from config import ADMIN_IDS, BOT_TOKEN

logger = logging.getLogger(__name__)
router = Router()

# --- Вспомогательная функция для получения бота по выбору ---
async def get_bot_by_choice(choice: str, original_bot: Bot) -> Bot:
    if choice == "main":
        return Bot(token=BOT_TOKEN)
    else:
        return original_bot

# --- Команда старт ---
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этому боту.")
        return
    await message.answer(
        "👑 Панель администратора\nВыберите действие:",
        reply_markup=admin_main_keyboard()
    )

@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👑 Панель администратора\nВыберите действие:",
        reply_markup=admin_main_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👑 Панель администратора\nВыберите действие:",
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

    # Уведомление пользователю через основного бота
    try:
        main_bot = Bot(token=BOT_TOKEN)
        await main_bot.send_message(
            target_id,
            f"🎁 Вам начислено {amount} 💎 администратором!\nТекущий баланс: {new_balance} 💎."
        )
        await main_bot.session.close()
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление пользователю {target_id}: {e}")

    await state.clear()
    await message.answer(
        "👑 Панель администратора\nВыберите действие:",
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

    try:
        main_bot = Bot(token=BOT_TOKEN)
        await main_bot.send_message(
            target_id,
            f"⚠️ У вас списано {amount} 💎 администратором.\nТекущий баланс: {new_balance} 💎."
        )
        await main_bot.session.close()
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление пользователю {target_id}: {e}")

    await state.clear()
    await message.answer(
        "👑 Панель администратора\nВыберите действие:",
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
    losses = total_games - wins
    win_percent = (wins / total_games * 100) if total_games > 0 else 0

    info_text = (
        f"👤 <b>Информация о пользователе</b>\n"
        f"🆔 <b>ID:</b> <code>{target_id}</code>\n"
        f"💎 <b>Баланс:</b> {balance}\n"
        f"🎁 <b>Бонусный баланс:</b> {bonus_total}\n"
        f"🎮 <b>Всего игр:</b> {total_games}\n"
        f"🏆 <b>Побед:</b> {wins}\n"
        f"💔 <b>Проигрышей:</b> {losses}\n"
        f"📊 <b>Процент побед:</b> {win_percent:.1f}%"
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
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
        ])
    else:
        text_lines = [f"👥 <b>Все пользователи — страница {page+1}/{total_pages}:</b>"]
        for uid, username, balance, total_games in users:
            name = f"@{username}" if username else "нет username"
            text_lines.append(f"🆔 <code>{uid}</code> | {name} | 💎 {balance} | 🎮 {total_games}")
        text = "\n".join(text_lines)

        buttons = []
        if page > 0:
            buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_list_prev"))
        if page < total_pages - 1:
            buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data="admin_list_next"))
        nav_buttons = [buttons] if buttons else []
        back_button = [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
        keyboard = InlineKeyboardMarkup(inline_keyboard=nav_buttons + [back_button])

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

# ===== Статистика =====
@router.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return

    pool = await init_db_pool()
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        threshold = int(time.time()) - 30*86400
        active_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_active > $1", threshold)
        total_deposits = await conn.fetchval("SELECT COUNT(*) FROM crypto_transactions WHERE status='paid'")
        pending_withdrawals = await conn.fetchval("SELECT COUNT(*) FROM withdraw_requests WHERE status='pending'")
        total_deposit_sum = await conn.fetchval("SELECT SUM(amount) FROM deposits") or 0

    text = (
        f"📊 <b>Общая статистика</b>\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🟢 Активных за 30 дней: {active_users}\n"
        f"💰 Всего депозитов: {total_deposits} на сумму {total_deposit_sum} баллов\n"
        f"⏳ Ожидающих выводов: {pending_withdrawals}"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_back_keyboard())
    await callback.answer()

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

    text = "💸 **Ожидающие заявки:**\n\n"
    for req in requests:
        text += f"ID: {req[0]}\n"
        text += f"Пользователь: {req[1]}\n"
        text += f"Сумма: {req[2]} баллов ≈ {req[3]} USDT\n"
        text += f"Контакт: {req[4]}\n"
        text += f"Подтвердить: /confirm_withdraw {req[0]}\n"
        text += f"Отклонить: /reject_withdraw {req[0]}\n\n"

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_back_keyboard())
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
    else:
        text = f"📜 Общие заявки на вывод — страница {page+1}/{total_pages}:\n\n"
        for req in requests:
            req_id, uid, amount_points, amount_usdt, wallet, status, created_at, completed_at = req
            status_emoji = "🟡" if status == 'pending' else ("✅" if status == 'completed' else "❌")
            text += f"{status_emoji} Заявка #{req_id}\n"
            text += f"👤 Пользователь: <code>{uid}</code>\n"
            text += f"💸 Сумма: {amount_points} баллов (~{amount_usdt} USDT)\n"
            text += f"📞 Контакт: {wallet}\n"
            text += f"📅 Создана: {datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M')}\n"
            if status == 'completed' and completed_at:
                text += f"✅ Подтверждена: {datetime.fromtimestamp(completed_at).strftime('%Y-%m-%d %H:%M')}\n"
            elif status == 'rejected':
                text += f"❌ Отклонена\n"
            text += "\n"

    buttons = []
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data="withdraw_history_prev"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data="withdraw_history_next"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="🔙 Назад в админ-панель", callback_data="admin_back")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

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

    if bot_choice == "main":
        broadcast_bot = Bot(token=BOT_TOKEN)
    else:
        broadcast_bot = message.bot

    await message.answer("⏳ Начинаю рассылку...")
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users")
    success = 0
    failed = 0
    for (user_id,) in users:
        try:
            await broadcast_bot.send_message(user_id, text)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    if bot_choice != "admin":
        await broadcast_bot.session.close()

    await message.answer(f"✅ Рассылка завершена.\nУспешно: {success}\nНеудачно: {failed}")
    await state.clear()
    await message.answer(
        "👑 Панель администратора\nВыберите действие:",
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
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tournaments (name, prize_points, start_time, end_time, status) VALUES ($1, $2, $3, $4, 'active')",
            name, prize, now, end_time
        )
    await message.answer(f"✅ Турнир «{name}» создан и продлится {hours} часов.")
    await state.clear()
    await message.answer(
        "👑 Панель администратора\nВыберите действие:",
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

    pool = await init_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM withdraw_requests WHERE user_id = $1 AND amount_points = $2 AND status='pending' ORDER BY created_at DESC LIMIT 1",
            user_id, amount_points
        )
        if not row:
            await callback.answer("❌ Заявка не найдена или уже обработана", show_alert=True)
            return
        request_id = row[0]
        await conn.execute(
            "UPDATE withdraw_requests SET status='completed', completed_at=$1 WHERE id=$2",
            int(time.time()), request_id
        )

    try:
        main_bot = Bot(token=BOT_TOKEN)
        await main_bot.send_message(
            user_id,
            f"✅ Ваш запрос на вывод {amount_points} баллов подтверждён администратором!\n"
            f"Средства будут отправлены на указанный вами контакт."
        )
        await main_bot.session.close()
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

    await callback.message.edit_text(
        f"✅ Заявка пользователя {user_id} на {amount_points} баллов подтверждена.\n"
        f"Пользователь уведомлён."
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

    pool = await init_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, amount_points FROM withdraw_requests WHERE user_id = $1 AND status='pending' ORDER BY created_at DESC LIMIT 1",
            user_id
        )
        if not row:
            await callback.answer("❌ Нет ожидающих заявок у этого пользователя", show_alert=True)
            return
        request_id, amount_points = row
        await conn.execute(
            "UPDATE withdraw_requests SET status='rejected' WHERE id=$1",
            request_id
        )

    balance, *_ = await get_user(user_id, None)
    new_balance = balance + amount_points
    await update_balance(user_id, new_balance)

    try:
        main_bot = Bot(token=BOT_TOKEN)
        await main_bot.send_message(
            user_id,
            f"❌ Ваш запрос на вывод {amount_points} баллов был отклонён администратором.\n"
            f"Средства возвращены на ваш баланс."
        )
        await main_bot.session.close()
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")

    await callback.message.edit_text(
        f"❌ Заявка пользователя {user_id} на {amount_points} баллов отклонена.\n"
        f"Баллы возвращены пользователю."
    )
    await callback.answer("Заявка отклонена", show_alert=True)

@router.message(Command("confirmwithdraw"))
async def confirm_withdraw_command(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /confirmwithdraw <ID_заявки>")
        return

    try:
        request_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID заявки должен быть числом.")
        return

    # Получаем данные заявки из БД
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, amount_points FROM withdraw_requests WHERE id = $1 AND status = 'pending'",
            request_id
        )
        if not row:
            await message.answer(f"❌ Заявка с ID {request_id} не найдена или уже обработана.")
            await pool.close()
            return

        target_user_id = row['user_id']
        amount_points = row['amount_points']

        # Обновляем статус
        await conn.execute(
            "UPDATE withdraw_requests SET status = 'completed', completed_at = $1 WHERE id = $2",
            int(time.time()), request_id
        )
    await pool.close()

    # Уведомляем пользователя через основного бота
    try:
        main_bot = Bot(token=BOT_TOKEN)
        await main_bot.send_message(
            target_user_id,
            f"✅ Ваш запрос на вывод {amount_points} баллов подтверждён администратором!\n"
            f"Средства будут отправлены на указанный вами контакт."
        )
        await main_bot.session.close()
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {target_user_id}: {e}")

    await message.answer(f"✅ Заявка #{request_id} подтверждена. Пользователь уведомлён.")

@router.message(Command("rejectwithdraw"))
async def reject_withdraw_command(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /rejectwithdraw <ID_заявки>")
        return

    try:
        request_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID заявки должен быть числом.")
        return

    pool = await init_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, amount_points FROM withdraw_requests WHERE id = $1 AND status = 'pending'",
            request_id
        )
        if not row:
            await message.answer(f"❌ Заявка с ID {request_id} не найдена или уже обработана.")
            await pool.close()
            return

        target_user_id = row['user_id']
        amount_points = row['amount_points']

        # Обновляем статус на rejected
        await conn.execute(
            "UPDATE withdraw_requests SET status = 'rejected' WHERE id = $1",
            request_id
        )
        # Возвращаем баллы пользователю
        await conn.execute(
            "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
            amount_points, target_user_id
        )
    await pool.close()

    # Уведомляем пользователя
    try:
        main_bot = Bot(token=BOT_TOKEN)
        await main_bot.send_message(
            target_user_id,
            f"❌ Ваш запрос на вывод {amount_points} баллов был отклонён администратором.\n"
            f"Средства возвращены на ваш баланс."
        )
        await main_bot.session.close()
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {target_user_id}: {e}")

    await message.answer(f"❌ Заявка #{request_id} отклонена. Баллы возвращены пользователю.")
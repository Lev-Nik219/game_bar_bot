import asyncio
import time
import logging
import aiosqlite
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import (
    DB_NAME, get_user, update_balance, get_user_stats,
    get_all_users, get_users_count, get_bonus_total
)
from keyboards import (
    admin_main_keyboard, admin_cancel_keyboard, admin_back_keyboard,
    admin_bot_choice_keyboard
)
from states import (
    AdminGiveStates, AdminTakeStates, AdminUserInfoStates,
    AdminBroadcastStates, CreateTournamentStates
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

    # Уведомление пользователю через основного бота
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

# ===== Информация о пользователе (исправлено – убрана кнопка открытия чата) =====
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
    total_users = await get_users_count(active_days=0)
    active_users = await get_users_count(active_days=30)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM crypto_transactions WHERE status='paid'") as c:
            total_deposits = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status='pending'") as c:
            pending_withdrawals = (await c.fetchone())[0]
        async with db.execute("SELECT SUM(amount) FROM deposits") as c:
            total_deposit_sum = (await c.fetchone())[0] or 0
    text = (
        f"📊 <b>Общая статистика</b>\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🟢 Активных за 30 дней: {active_users}\n"
        f"💰 Всего депозитов: {total_deposits} на сумму {total_deposit_sum} баллов\n"
        f"⏳ Ожидающих выводов: {pending_withdrawals}"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_back_keyboard())
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
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()
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
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO tournaments (name, prize_points, start_time, end_time, status) VALUES (?, ?, ?, ?, 'active')",
            (name, prize, now, end_time)
        )
        await db.commit()
    await message.answer(f"✅ Турнир «{name}» создан и продлится {hours} часов.")
    await state.clear()
    await message.answer(
        "👑 Панель администратора\nВыберите действие:",
        reply_markup=admin_main_keyboard()
    )

# ===== Обработка заявок на вывод =====
@router.callback_query(F.data.startswith("admin_confirm_withdraw_"))
async def admin_confirm_withdraw(callback: types.CallbackQuery):
    # callback.data = "admin_confirm_withdraw_123456_100"
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

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id FROM withdraw_requests WHERE user_id = ? AND amount_points = ? AND status='pending' ORDER BY created_at DESC LIMIT 1",
            (user_id, amount_points)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            await callback.answer("❌ Заявка не найдена или уже обработана", show_alert=True)
            return
        request_id = row[0]

        await db.execute(
            "UPDATE withdraw_requests SET status='completed', completed_at=strftime('%s','now') WHERE id=?",
            (request_id,)
        )
        await db.commit()

    # Уведомление пользователю через основного бота
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
    # callback.data = "admin_reject_withdraw_123456"
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

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, amount_points FROM withdraw_requests WHERE user_id = ? AND status='pending' ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            await callback.answer("❌ Нет ожидающих заявок у этого пользователя", show_alert=True)
            return
        request_id, amount_points = row

        await db.execute(
            "UPDATE withdraw_requests SET status='rejected' WHERE id=?",
            (request_id,)
        )
        await db.commit()

    # Возвращаем баллы пользователю
    balance, *_ = await get_user(user_id, None)
    new_balance = balance + amount_points
    await update_balance(user_id, new_balance)

    # Уведомление пользователю через основного бота
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
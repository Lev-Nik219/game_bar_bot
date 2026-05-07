import asyncio
import logging
import time
import sqlite3
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_IDS
from database import get_user, update_balance, get_user_stats, get_all_users, get_users_count, execute_query, get_deposit_stats
from keyboards.admin import (
    admin_main_keyboard, admin_stats_keyboard, admin_stats_back_keyboard, users_list_keyboard, clear_db_confirm_keyboard
)

logger = logging.getLogger(__name__)
router = Router()

class AdminStates(StatesGroup):
    waiting_for_target_id = State()
    waiting_for_amount = State()
    waiting_for_broadcast_message = State()

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_cancel")]])

def back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]])

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id in ADMIN_IDS:
        await message.answer("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard())
    else:
        await message.answer("❌ У вас нет доступа к админ-панели.")

# ---------- НАЧИСЛЕНИЕ БАЛЛОВ ----------
@router.callback_query(F.data == "admin_give")
async def admin_give_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: await callback.answer("❌ Доступ запрещён", show_alert=True); return
    await state.set_state(AdminStates.waiting_for_target_id)
    await callback.message.edit_text("Введите ID пользователя:", reply_markup=cancel_keyboard()); await callback.answer()

@router.message(AdminStates.waiting_for_target_id, F.text)
async def admin_give_target_id(message: types.Message, state: FSMContext):
    try: target_id = int(message.text)
    except ValueError: await message.answer("❌ ID должен быть числом.", reply_markup=cancel_keyboard()); return
    await state.update_data(target_id=target_id); await state.set_state(AdminStates.waiting_for_amount)
    await message.answer("Введите сумму для начисления:", reply_markup=cancel_keyboard())

@router.message(AdminStates.waiting_for_amount, F.text)
async def admin_give_amount(message: types.Message, state: FSMContext):
    try: amount = int(message.text)
    except ValueError: await message.answer("❌ Введите число.", reply_markup=cancel_keyboard()); return
    if amount <= 0: await message.answer("❌ Сумма должна быть положительной.", reply_markup=cancel_keyboard()); return
    data = await state.get_data(); target_id = data.get("target_id")
    target_balance, *_ = await get_user(target_id, None); new_balance = target_balance + amount
    await update_balance(target_id, new_balance)
    
    # Синхронизация с SQLite для Mini App
    try:
        conn = sqlite3.connect("casino.db")
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, target_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"SQLite sync error: {e}")
    
    await message.answer(f"✅ Пользователю {target_id} начислено {amount} 💎.\nНовый баланс: {new_balance} 💎.")
    await state.clear(); await message.answer("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard())

# ---------- СПИСАНИЕ БАЛЛОВ ----------
@router.callback_query(F.data == "admin_take")
async def admin_take_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: await callback.answer("❌ Доступ запрещён", show_alert=True); return
    await state.set_state(AdminStates.waiting_for_target_id)
    await callback.message.edit_text("Введите ID пользователя:", reply_markup=cancel_keyboard()); await callback.answer()

@router.message(AdminStates.waiting_for_target_id, F.text)
async def admin_take_target_id(message: types.Message, state: FSMContext):
    try: target_id = int(message.text)
    except ValueError: await message.answer("❌ ID должен быть числом.", reply_markup=cancel_keyboard()); return
    await state.update_data(target_id=target_id); await state.set_state(AdminStates.waiting_for_amount)
    await message.answer("Введите сумму для списания:", reply_markup=cancel_keyboard())

@router.message(AdminStates.waiting_for_amount, F.text)
async def admin_take_amount(message: types.Message, state: FSMContext):
    try: amount = int(message.text)
    except ValueError: await message.answer("❌ Введите число.", reply_markup=cancel_keyboard()); return
    if amount <= 0: await message.answer("❌ Сумма должна быть положительной.", reply_markup=cancel_keyboard()); return
    data = await state.get_data(); target_id = data.get("target_id")
    target_balance, *_ = await get_user(target_id, None)
    if target_balance < amount: await message.answer(f"❌ Недостаточно баллов. У пользователя {target_balance} 💎."); return
    new_balance = target_balance - amount
    await update_balance(target_id, new_balance)
    
    # Синхронизация с SQLite для Mini App
    try:
        conn = sqlite3.connect("casino.db")
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, target_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"SQLite sync error: {e}")
    
    await message.answer(f"✅ У пользователя {target_id} списано {amount} 💎.\nНовый баланс: {new_balance} 💎.")
    await state.clear(); await message.answer("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard())

# ---------- СПИСОК ИГРОКОВ ----------
@router.callback_query(F.data == "admin_list")
async def admin_list_callback(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: await callback.answer("❌ Доступ запрещён", show_alert=True); return
    await state.update_data(page=0); await show_users_page(callback.message, state, edit=True); await callback.answer()

async def show_users_page(message: types.Message, state: FSMContext, edit=False):
    data = await state.get_data(); page = data.get("page", 0); limit = 5; offset = page * limit
    users = await get_all_users(offset, limit, active_days=0); total = await get_users_count(active_days=0)
    total_pages = (total + limit - 1) // limit
    if not users:
        text = "👥 Нет пользователей."; keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]])
    else:
        text = f"👥 <b>Список игроков — стр. {page+1}/{total_pages}</b>\n\n"; keyboard = users_list_keyboard(users, page, total_pages)
    if edit: await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    else: await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@router.callback_query(F.data == "admin_list_next")
async def admin_list_next(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data(); page = data.get("page", 0) + 1
    await state.update_data(page=page); await show_users_page(callback.message, state, edit=True); await callback.answer()

@router.callback_query(F.data == "admin_list_prev")
async def admin_list_prev(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data(); page = data.get("page", 0) - 1
    await state.update_data(page=page); await show_users_page(callback.message, state, edit=True); await callback.answer()

@router.callback_query(F.data.startswith("user_info_"))
async def user_info_callback(callback: types.CallbackQuery):
    user_id = int(callback.data.replace("user_info_", ""))
    stats = await get_user_stats(user_id)
    if not stats: await callback.answer("❌ Пользователь не найден", show_alert=True); return
    balance, total_games, wins = stats
    win_percent = (wins / total_games * 100) if total_games > 0 else 0
    info_text = (
        f"👤 <b>Информация о пользователе</b>\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"💎 <b>Баланс:</b> {balance}\n"
        f"🎮 <b>Всего игр:</b> {total_games}\n"
        f"🏆 <b>Побед:</b> {wins}\n"
        f"📊 <b>Процент побед:</b> {win_percent:.1f}%\n"
    )
    await callback.message.edit_text(info_text, parse_mode="HTML", reply_markup=back_keyboard()); await callback.answer()

# ---------- РЕФЕРАЛЬНАЯ СТАТИСТИКА ----------
@router.callback_query(F.data == "admin_referral_stats")
async def admin_referral_stats_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: await callback.answer("❌ Доступ запрещён", show_alert=True); return
    try:
        from main_bot import get_admin_referral_stats_sync, REFERRAL_BONUS_INVITER, REFERRAL_BONUS_INVITED
        stats = get_admin_referral_stats_sync()
        top_text = "\n".join([f"{i+1}. {'@'+r['username'] if r['username'] else 'ID'+str(r['user_id'])} — {r['count']} друзей, 💎{r['balance']}" for i,r in enumerate(stats['top_referrers'][:10])])
        text = (
            f"📊 <b>Реферальная статистика</b>\n\n"
            f"👥 Всего рефералов: {stats['total_referrals']}\n"
            f"👤 Активных рефереров: {stats['active_referrers']}\n"
            f"✅ Начислено бонусов: {stats['claimed_rewards']}\n"
            f"💰 Всего выплат: ~{stats['total_earnings']} 💎\n\n"
            f"🎁 За переход: {REFERRAL_BONUS_INVITED} 💎\n"
            f"🎉 За игру: {REFERRAL_BONUS_INVITER} 💎\n\n"
            f"<b>🏆 Топ рефереров:</b>\n{top_text or 'Пока нет'}"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_keyboard()); await callback.answer()
    except Exception as e:
        logger.error(f"Referral stats error: {e}")
        await callback.answer("Ошибка загрузки статистики", show_alert=True)

# ---------- ОЧИСТКА БАЗЫ ----------
@router.callback_query(F.data == "admin_clear_db")
async def admin_clear_db_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: await callback.answer("❌ Доступ запрещён", show_alert=True); return
    try: await callback.answer()
    except: pass
    await callback.message.edit_text("⚠️ <b>ВНИМАНИЕ!</b>\n\nВы собираетесь <b>ПОЛНОСТЬЮ ОЧИСТИТЬ</b> базу данных!\n\nЭто действие НЕВОЗМОЖНО отменить!\n\nВы уверены?", parse_mode="HTML", reply_markup=clear_db_confirm_keyboard())

@router.callback_query(F.data == "admin_clear_db_confirm")
async def admin_clear_db_confirm_callback(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: await callback.answer("❌ Доступ запрещён", show_alert=True); return
    try: await callback.answer()
    except: pass
    try:
        import sqlite3, shutil
        backup_name = f"casino_backup_{int(time.time())}.db"
        shutil.copy2("casino.db", backup_name)
        conn = sqlite3.connect("casino.db"); conn.execute("PRAGMA busy_timeout = 10000"); c = conn.cursor()
        c.execute("DELETE FROM users"); c.execute("DELETE FROM game_history"); c.execute("DELETE FROM crypto_payments"); c.execute("DELETE FROM support_messages"); c.execute("DELETE FROM achievements"); c.execute("DELETE FROM sqlite_sequence")
        conn.commit(); conn.close()
        await callback.message.edit_text(f"✅ <b>База данных полностью очищена!</b>\n\n📁 Бэкап сохранён: <code>{backup_name}</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Вернуться в админ-панель", callback_data="admin_back")]]))
        logger.info(f"БАЗА ДАННЫХ ОЧИЩЕНА! Бэкап: {backup_name}")
    except Exception as e:
        logger.error(f"Clear DB error: {e}")
        await callback.message.edit_text(f"❌ <b>Ошибка при очистке:</b>\n\n<code>{str(e)}</code>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Вернуться в админ-панель", callback_data="admin_back")]]))

# ---------- ОТМЕНА И НАЗАД ----------
@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear(); await callback.message.edit_text("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard()); await callback.answer()

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery, state: FSMContext):
    await state.clear(); await callback.message.edit_text("👑 Админ-панель\n\nВыберите действие:", reply_markup=admin_main_keyboard()); await callback.answer()
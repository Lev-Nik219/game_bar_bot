import asyncio
import logging
import time
from uuid import uuid4
from datetime import datetime
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import get_user, update_balance, add_deposit, create_crypto_transaction, execute_query
from keyboards import profile_keyboard, deposit_keyboard
from config import CRYPTOBOT_TOKEN
from services.crypto_pay import crypto_pay_service
from services.referral import award_referral_deposit_bonus
from states import CustomDepositStates

logger = logging.getLogger(__name__)
router = Router()

# Словарь для блокировки уже обработанных платежей
processed_payments = set()

def parse_crypto_time(time_str):
    """Преобразует время из формата CryptoPay в timestamp"""
    if isinstance(time_str, int):
        return time_str
    if isinstance(time_str, str):
        try:
            # Формат: 2026-04-04T13:05:36.703Z
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            return int(dt.timestamp())
        except:
            return int(time.time())
    return int(time.time())

@router.callback_query(F.data == "deposit")
async def deposit_callback(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в callback.answer (deposit): {e}")
    await callback.message.edit_text(
        "💰 Выберите сумму пополнения.\n\n"
        "Оплата в криптовалюте USDT по текущему курсу.\n"
        "После оплаты нажмите «Я оплатил» для зачисления баллов.\n\n"
        "⚠️ ВНИМАНИЕ: Кнопку «Я оплатил» можно нажать ТОЛЬКО ОДИН раз!",
        reply_markup=deposit_keyboard()
    )

# --- Фиксированные суммы ---
@router.callback_query(F.data.startswith("deposit_") & ~F.data.startswith("deposit_custom"))
async def process_deposit(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в callback.answer (process_deposit): {e}")

    amount_map = {
        "deposit_1000": (1000, 1000),
        "deposit_750": (750, 750),
        "deposit_500": (500, 500),
        "deposit_250": (250, 250)
    }
    amount_rub, amount_points = amount_map[callback.data]
    user_id = callback.from_user.id
    payment_id = f"{user_id}_{uuid4().hex[:8]}"

    try:
        usdt_amount = round(amount_rub / 90, 2)
        invoice_response = await crypto_pay_service.create_invoice(
            asset="USDT",
            amount=str(usdt_amount),
            payload=payment_id,
            description=f"Пополнение баланса на {amount_points} баллов"
        )
        if not invoice_response.get('ok'):
            raise Exception(f"Ошибка CryptoBot: {invoice_response}")
        invoice = invoice_response['result']
        invoice_id = str(invoice.get('invoice_id'))
        pay_url = invoice.get('pay_url') or invoice.get('bot_invoice_url')
        if not pay_url:
            raise Exception("Не удалось получить ссылку на оплату")

        await create_crypto_transaction(user_id, amount_rub, amount_points, payment_id, invoice_id)

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"pay_{payment_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
        ])

        await callback.message.edit_text(
            f"💳 Для пополнения на {amount_points} баллов ({amount_rub} руб) "
            f"перейдите по ссылке и оплатите {usdt_amount} USDT:\n\n"
            f"{pay_url}\n\n"
            f"⚠️ <b>ВАЖНО:</b> После оплаты нажмите кнопку «Я оплатил».",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        await callback.message.edit_text(
            f"❌ Ошибка при создании платежа: {str(e)}",
            reply_markup=profile_keyboard(user_id)
        )

# --- Произвольная сумма ---
@router.callback_query(F.data == "deposit_custom")
async def deposit_custom_start(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в callback.answer (deposit_custom_start): {e}")

    await state.set_state(CustomDepositStates.waiting_for_amount)
    await callback.message.edit_text(
        "💰 Введите желаемое количество баллов (целое число, минимум 10):\n\n"
        "Курс: 1 рубль = 1 балл.\n"
        "После оплаты нажмите «Я оплатил» для зачисления.\n\n"
        "⚠️ Кнопку можно нажать ТОЛЬКО ОДИН раз!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="deposit")]
        ])
    )

@router.message(CustomDepositStates.waiting_for_amount, F.text)
async def deposit_custom_amount(message: types.Message, state: FSMContext):
    try:
        amount_points = int(message.text)
        if amount_points < 10:
            await message.answer("❌ Минимальная сумма — 10 баллов.")
            return
    except ValueError:
        await message.answer("❌ Введите целое число.")
        return

    user_id = message.from_user.id
    amount_rub = amount_points
    payment_id = f"{user_id}_{uuid4().hex[:8]}"
    usdt_amount = round(amount_rub / 90, 2)

    try:
        invoice_response = await crypto_pay_service.create_invoice(
            asset="USDT",
            amount=str(usdt_amount),
            payload=payment_id,
            description=f"Пополнение баланса на {amount_points} баллов"
        )
        if not invoice_response.get('ok'):
            raise Exception(f"Ошибка CryptoBot: {invoice_response}")
        invoice = invoice_response['result']
        invoice_id = str(invoice.get('invoice_id'))
        pay_url = invoice.get('pay_url') or invoice.get('bot_invoice_url')
        if not pay_url:
            raise Exception("Не удалось получить ссылку на оплату")

        await create_crypto_transaction(user_id, amount_rub, amount_points, payment_id, invoice_id)

        await state.clear()
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"pay_{payment_id}")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
        ])
        
        await message.answer(
            f"💳 Для пополнения на {amount_points} баллов ({amount_rub} руб) "
            f"перейдите по ссылке и оплатите {usdt_amount} USDT:\n\n"
            f"{pay_url}\n\n"
            f"⚠️ <b>ВАЖНО:</b> После оплаты нажмите кнопку «Я оплатил».",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании платежа: {str(e)}")
        await state.clear()

# ===== НОВАЯ СИСТЕМА КНОПКИ "Я ОПЛАТИЛ" =====
@router.callback_query(F.data.startswith("pay_"))
async def process_payment_click(callback: types.CallbackQuery):
    payment_id = callback.data.replace("pay_", "")
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id
    
    # Показываем уведомление о начале обработки
    await callback.answer("⏳ Обрабатываю платеж...", show_alert=False)
    
    # 1. СРАЗУ УДАЛЯЕМ СООБЩЕНИЕ С КНОПКОЙ
    try:
        await callback.bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"Не удалось удалить сообщение: {e}")
    
    # Отправляем временное сообщение о проверке
    temp_msg = await callback.bot.send_message(
        chat_id,
        "⏳ Проверяю статус платежа. Пожалуйста, подождите..."
    )
    
    # 2. Проверяем, не обработан ли уже этот платёж
    if payment_id in processed_payments:
        await temp_msg.delete()
        await callback.bot.send_message(
            chat_id,
            "⚠️ Этот платёж уже был обработан ранее.\n\nПовторное начисление невозможно.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
            ])
        )
        return
    
    # 3. Получаем транзакцию
    row = await execute_query(
        "SELECT amount_points, status, invoice_id FROM crypto_transactions WHERE payment_id = $1",
        payment_id, fetch_one=True
    )
    
    if not row:
        await temp_msg.delete()
        await callback.bot.send_message(
            chat_id,
            "❌ Транзакция не найдена",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
            ])
        )
        return
    
    amount_points, status, invoice_id = row
    
    # 4. Если уже оплачено в БД
    if status == 'paid':
        processed_payments.add(payment_id)
        await temp_msg.delete()
        await callback.bot.send_message(
            chat_id,
            f"✅ Платёж на {amount_points} баллов уже был зачислен ранее.\n\nПовторное начисление невозможно.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
            ])
        )
        return
    
    # 5. Проверяем статус в CryptoPay
    try:
        response = await crypto_pay_service.get_invoice(int(invoice_id))
        if not response.get('ok'):
            await temp_msg.delete()
            await callback.bot.send_message(
                chat_id,
                "❌ Ошибка проверки платежа. Попробуйте позже.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
                ])
            )
            return
        
        items = response.get('result', {}).get('items', [])
        if not items:
            await temp_msg.delete()
            await callback.bot.send_message(
                chat_id,
                "❌ Инвойс не найден.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
                ])
            )
            return
        
        invoice = items[0]
        invoice_status = invoice.get('status')
        
        if invoice_status == 'paid':
            # ИСПРАВЛЕНО: правильно обрабатываем дату из CryptoPay
            paid_at_raw = invoice.get('paid_at') or int(time.time())
            paid_at = parse_crypto_time(paid_at_raw)
            
            # 6. НАЧИСЛЯЕМ БАЛЛЫ
            balance = await execute_query("SELECT balance FROM users WHERE user_id = $1", user_id, fetch_val=True) or 0
            new_balance = balance + amount_points
            
            await execute_query("UPDATE users SET balance = $1 WHERE user_id = $2", new_balance, user_id)
            await execute_query(
                "UPDATE crypto_transactions SET status = 'paid', confirmed_at = $1 WHERE payment_id = $2",
                paid_at, payment_id
            )
            await add_deposit(user_id, amount_points)
            
            # Бонус за первый депозит
            first_deposit_claimed = await execute_query(
                "SELECT first_deposit_bonus_claimed FROM users WHERE user_id = $1",
                user_id, fetch_val=True
            )
            
            bonus_text = ""
            if not first_deposit_claimed:
                bonus_amount = int(amount_points * 0.5)
                await execute_query(
                    "UPDATE users SET balance = balance + $1, bonus_total = bonus_total + $1, "
                    "bonus_balance = bonus_balance + $1, first_deposit_bonus_claimed = 1 WHERE user_id = $2",
                    bonus_amount, user_id
                )
                new_balance += bonus_amount
                bonus_text = f"\n\n🎁 Бонус за первый депозит: +{bonus_amount} баллов!"
            
            await award_referral_deposit_bonus(user_id, amount_points, callback.bot)
            
            # 7. Удаляем временное сообщение
            await temp_msg.delete()
            
            # 8. Отправляем сообщение об успехе
            paid_date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(paid_at))
            
            await callback.bot.send_message(
                chat_id,
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"📅 Дата: {paid_date}\n"
                f"💰 Сумма: {amount_points} баллов\n"
                f"💎 Новый баланс: {new_balance} баллов{bonus_text}\n\n"
                f"Спасибо за пополнение!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
                    [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
                ])
            )
            
            # 9. Добавляем в список обработанных
            processed_payments.add(payment_id)
            
        else:
            # Платёж не оплачен - сообщаем об этом
            await temp_msg.delete()
            await callback.bot.send_message(
                chat_id,
                "❌ Платёж не найден или не оплачен.\n\n"
                "1. Оплатите по ссылке\n"
                "2. Вернитесь в бота\n"
                "3. Нажмите кнопку «Я оплатил» снова\n\n"
                "Если вы уже оплатили, подождите 1-2 минуты и попробуйте снова.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💰 Пополнить снова", callback_data="deposit")],
                    [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
                ])
            )
            
    except Exception as e:
        logger.error(f"Ошибка при проверке платежа: {e}")
        await temp_msg.delete()
        await callback.bot.send_message(
            chat_id,
            f"❌ Ошибка проверки платежа: {str(e)[:100]}\n\nПопробуйте позже или обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
            ])
        )
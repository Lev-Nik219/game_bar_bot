import asyncio
import logging
from uuid import uuid4
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import (
    get_user, update_balance, add_deposit, create_crypto_transaction,
    get_crypto_transaction_full, update_crypto_transaction_status
)
from keyboards import profile_keyboard, deposit_keyboard
from config import CRYPTOBOT_TOKEN
from services.crypto_pay import crypto_pay_service
from services.referral import award_referral_deposit_bonus
from states import CustomDepositStates

logger = logging.getLogger(__name__)
router = Router()

@router.callback_query(F.data == "deposit")
async def deposit_callback(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в callback.answer (deposit): {e}")
    await callback.message.edit_text(
        "💰 Выберите сумму пополнения.\n\n"
        "Оплата в криптовалюте USDT по текущему курсу.\n"
        "После оплаты нажмите «Я оплатил» для зачисления баллов.",
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
        "deposit_1000": (667, 1000),
        "deposit_750": (500, 750),
        "deposit_500": (333, 500),
        "deposit_250": (167, 250)
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

        await callback.message.edit_text(
            f"💳 Для пополнения на {amount_points} баллов ({amount_rub} руб) "
            f"перейдите по ссылке и оплатите {usdt_amount} USDT:\n\n"
            f"{pay_url}\n\n"
            f"✅ После оплаты нажмите кнопку «Я оплатил» для проверки.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_payment_{payment_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
            ])
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
        "Курс: 1.5 балла = 1 рубль.\n"
        "После оплаты нажмите «Я оплатил» для зачисления.",
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
    amount_rub = round(amount_points / 1.5)
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
        await message.answer(
            f"💳 Для пополнения на {amount_points} баллов ({amount_rub} руб) "
            f"перейдите по ссылке и оплатите {usdt_amount} USDT:\n\n"
            f"{pay_url}\n\n"
            f"✅ После оплаты нажмите кнопку «Я оплатил» для проверки.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check_payment_{payment_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="deposit")]
            ])
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании платежа: {str(e)}")
        await state.clear()

# --- Проверка оплаты ---
@router.callback_query(F.data.startswith("check_payment_"))
async def check_payment(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в callback.answer (check_payment): {e}")

    payment_id = callback.data.replace("check_payment_", "")
    user_id = callback.from_user.id

    txn = await get_crypto_transaction_full(payment_id)
    if not txn:
        await callback.answer("❌ Транзакция не найдена", show_alert=True)
        return
    amount_points, status, invoice_id = txn
    if status == 'paid':
        await callback.answer("✅ Платёж уже был зачислен ранее", show_alert=True)
        return

    try:
        response = await crypto_pay_service.get_invoice(int(invoice_id))
        logger.debug(f"Ответ CryptoPay: {response}")

        if not response.get('ok'):
            await callback.answer(f"❌ Ошибка API", show_alert=True)
            return

        result = response.get('result', {})
        items = result.get('items', [])
        if not items:
            await callback.answer("❌ Инвойс не найден.", show_alert=True)
            return

        invoice = items[0]
        invoice_status = invoice.get('status')

        if invoice_status == 'paid':
            balance, *_ = await get_user(user_id, callback.from_user.username)
            new_balance = balance + amount_points
            await update_balance(user_id, new_balance)
            await update_crypto_transaction_status(payment_id, 'paid')
            await add_deposit(user_id, amount_points)

            await award_referral_deposit_bonus(user_id, amount_points, callback.bot)

            # Создаём кнопку "Вернуться в меню"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_menu")]
            ])

            await callback.message.edit_text(
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"💰 Начислено: {amount_points} баллов\n"
                f"💎 Новый баланс: {new_balance} баллов\n\n"
                f"Нажмите на кнопку ниже, чтобы вернуться в главное меню:",
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            await callback.answer("❌ Платёж ещё не найден или не оплачен. Попробуйте позже.", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при проверке: {e}")
        await callback.answer(f"❌ Ошибка проверки: {str(e)}", show_alert=True)
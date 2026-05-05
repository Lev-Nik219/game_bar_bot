#!/usr/bin/env python3
import asyncio
import logging
import os
import json
import sqlite3
import time
import hashlib
import hmac
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from config import MAIN_BOT_TOKEN, ADMIN_IDS
from database import init_db_pool, close_db_pool, create_db
from handlers import user_router, admin_router, support_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = "casino.db"

# Константы для рекламы
AD_REWARD_AMOUNT = 25
AD_COOLDOWN_SECONDS = 20

# CryptoPay конфиг
CRYPTOPAY_TOKEN = os.environ.get('CRYPTOPAY_TOKEN', '455143:AA35WjAeKxzuurvYbMCZewcqzQ7VmtAQbDZ')
CRYPTOPAY_API_URL = 'https://pay.crypt.bot/api'

# Прайс-лист: amount_points -> price_usdt
PRICE_LIST = {
    501: 0.1,    # Тестовый
    250: 20,
    500: 35,
    750: 50,
    1000: 65
}

# ========== ФУНКЦИИ РАБОТЫ С SQLite ДЛЯ API ==========
def get_balance_sync(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def update_balance_sync(user_id: int, new_balance: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    conn.close()

def update_stats_sync(user_id: int, win: bool):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT total_games, wins FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        total_games, wins = row
        new_total = total_games + 1
        new_wins = wins + (1 if win else 0)
        cursor.execute("UPDATE users SET total_games = ?, wins = ? WHERE user_id = ?", (new_total, new_wins, user_id))
    conn.commit()
    conn.close()

def save_game_history_sync(user_id: int, bet: int, win_amount: int, game_type: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO game_history (user_id, game_type, bet_amount, win_amount, played_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, game_type, bet, win_amount, int(time.time()))
    )
    conn.commit()
    conn.close()

def get_last_ad_time_sync(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT last_ad_watch FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def set_last_ad_time_sync(user_id: int, timestamp: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_ad_watch = ? WHERE user_id = ?", (timestamp, user_id))
    conn.commit()
    conn.close()

def get_pending_payment(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT payment_id, amount_points, status, invoice_id FROM crypto_payments WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return row

def create_payment(user_id: int, amount_points: int, price_usdt: float, payment_id: str, invoice_id: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO crypto_payments (user_id, amount_points, price_usdt, payment_id, invoice_id, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (user_id, amount_points, price_usdt, payment_id, invoice_id, int(time.time()))
    )
    conn.commit()
    conn.close()

def confirm_payment(payment_id: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, amount_points, status FROM crypto_payments WHERE payment_id = ?", (payment_id,))
    row = cursor.fetchone()
    if not row or row[2] != 'pending':
        conn.close()
        return None
    user_id, amount_points, _ = row
    cursor.execute("UPDATE crypto_payments SET status = 'paid' WHERE payment_id = ?", (payment_id,))
    current_balance = get_balance_sync(user_id)
    update_balance_sync(user_id, current_balance + amount_points)
    conn.commit()
    conn.close()
    return (user_id, amount_points)

def init_sqlite_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            total_games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            last_ad_watch INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            game_type TEXT NOT NULL,
            bet_amount INTEGER NOT NULL,
            win_amount INTEGER DEFAULT 0,
            played_at INTEGER NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            is_read INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS crypto_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount_points INTEGER NOT NULL,
            price_usdt REAL NOT NULL,
            payment_id TEXT UNIQUE NOT NULL,
            invoice_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("SQLite tables created/verified")

# ========== TELEGRAM БОТ ==========
bot = Bot(token=MAIN_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ВАЖНЫЙ ПОРЯДОК
dp.include_router(support_router)
dp.include_router(admin_router)
dp.include_router(user_router)

# ========== Aiohttp СЕРВЕР ДЛЯ API ==========
app = web.Application()

@web.middleware
async def cors_middleware(request, handler):
    if request.method == 'OPTIONS':
        response = web.Response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, crypto-pay-api-sign'
        return response
    response = await handler(request)
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

app.middlewares.append(cors_middleware)

# ===== ВСЕ ФУНКЦИИ-ОБРАБОТЧИКИ API =====

async def handle_get_balance(request):
    try:
        data = await request.json()
        user_id = data.get('user_id')
        if not user_id:
            return web.json_response({'success': False, 'error': 'user_id required'}, status=400)
        balance = get_balance_sync(int(user_id))
        return web.json_response({'success': True, 'balance': balance})
    except Exception as e:
        logger.error(f"get_balance error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_get_profile(request):
    try:
        data = await request.json()
        user_id = data.get('user_id')
        if not user_id:
            return web.json_response({'success': False, 'error': 'user_id required'}, status=400)
        
        uid = int(user_id)
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute("SELECT balance, total_games, wins FROM users WHERE user_id = ?", (uid,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return web.json_response({'success': False, 'error': 'User not found'}, status=404)
        
        balance, total_games, wins = row
        losses = total_games - wins
        winrate = round(wins / total_games * 100, 1) if total_games > 0 else 0
        
        cursor.execute(
            "SELECT game_type, bet_amount, win_amount, played_at FROM game_history "
            "WHERE user_id = ? ORDER BY played_at DESC LIMIT 10",
            (uid,)
        )
        games = cursor.fetchall()
        
        recent_games = []
        for game_type, bet, win_amount, timestamp in games:
            recent_games.append({
                'game': game_type,
                'bet': bet,
                'win_amount': win_amount,
                'result': 'win' if win_amount > 0 else 'lose',
                'time': timestamp
            })
        
        conn.close()
        
        return web.json_response({
            'success': True,
            'profile': {
                'user_id': uid,
                'balance': balance,
                'total_games': total_games,
                'wins': wins,
                'losses': losses,
                'winrate': winrate,
                'recent_games': recent_games,
            }
        })
    except Exception as e:
        logger.error(f"get_profile error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_game_result(request):
    try:
        data = await request.json()
        user_id = data.get('user_id')
        game = data.get('game')
        bet = data.get('bet')
        win = data.get('win')
        win_amount = data.get('win_amount', 0)
        
        if not user_id or not game or bet is None:
            return web.json_response({'success': False, 'error': 'Missing fields'}, status=400)
        
        current_balance = get_balance_sync(int(user_id))
        new_balance = current_balance + win_amount if win else current_balance - bet
        
        update_balance_sync(int(user_id), new_balance)
        update_stats_sync(int(user_id), win)
        save_game_history_sync(int(user_id), bet, win_amount if win else 0, game)
        
        return web.json_response({'success': True, 'new_balance': new_balance, 'win': win})
    except Exception as e:
        logger.error(f"game_result error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_claim_ad_reward(request):
    try:
        data = await request.json()
        user_id = data.get('user_id')
        if not user_id:
            return web.json_response({'success': False, 'error': 'user_id required'}, status=400)
        
        last_ad = get_last_ad_time_sync(int(user_id))
        now = int(time.time())
        
        if last_ad and now - last_ad < AD_COOLDOWN_SECONDS:
            remaining = AD_COOLDOWN_SECONDS - (now - last_ad)
            return web.json_response({'success': False, 'error': 'cooldown', 'remaining': remaining}, status=200)
        
        current_balance = get_balance_sync(int(user_id))
        new_balance = current_balance + AD_REWARD_AMOUNT
        update_balance_sync(int(user_id), new_balance)
        set_last_ad_time_sync(int(user_id), now)
        
        return web.json_response({'success': True, 'new_balance': new_balance, 'reward': AD_REWARD_AMOUNT})
    except Exception as e:
        logger.error(f"claim_ad_reward error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_create_invoice(request):
    """Создание счёта в CryptoPay"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        amount_points = data.get('amount_points')
        
        if not user_id or not amount_points:
            return web.json_response({'success': False, 'error': 'user_id and amount_points required'}, status=400)
        
        amount_points = int(amount_points)
        if amount_points not in PRICE_LIST:
            return web.json_response({'success': False, 'error': 'Invalid amount'}, status=400)
        
        price_usdt = PRICE_LIST[amount_points]
        
        async with aiohttp.ClientSession() as session:
            headers = {
                'Crypto-Pay-API-Token': CRYPTOPAY_TOKEN,
                'Content-Type': 'application/json'
            }
            payload = {
                'asset': 'USDT',
                'amount': str(price_usdt),
                'description': f'Пополнение {amount_points} баллов для Game Bar Casino',
                'payload': json.dumps({'user_id': user_id, 'amount_points': amount_points}),
                'allow_comments': False,
                'allow_anonymous': False
            }
            
            try:
                async with session.post(f'{CRYPTOPAY_API_URL}/createInvoice', json=payload, headers=headers) as resp:
                    result = await resp.json()
                logger.info(f"CryptoPay createInvoice response: ok={result.get('ok')}")
            except Exception as e:
                logger.error(f"CryptoPay API error: {e}")
                return web.json_response({'success': False, 'error': f'CryptoPay API error: {str(e)}'}, status=500)
            
            if not result.get('ok'):
                logger.error(f"CryptoPay error: {result}")
                return web.json_response({'success': False, 'error': f'CryptoPay error: {result.get("error", "unknown")}'}, status=500)
            
            invoice = result['result']
            payment_id = str(invoice['invoice_id'])
            invoice_url = invoice['pay_url']
            
            # Сохраняем в БД
            create_payment(int(user_id), amount_points, price_usdt, payment_id, str(invoice['invoice_id']))
            
            return web.json_response({
                'success': True,
                'payment_id': payment_id,
                'invoice_url': invoice_url,
                'amount_points': amount_points,
                'price_usdt': price_usdt
            })
            
    except Exception as e:
        logger.error(f"Create invoice error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_check_payment(request):
    """Проверка статуса платежа (сначала локально, потом через API)"""
    try:
        data = await request.json()
        payment_id = data.get('payment_id')
        user_id = data.get('user_id')
        
        logger.info(f"Check payment: user_id={user_id}, payment_id={payment_id}")
        
        # Если нет payment_id, ищем последний pending платёж пользователя
        if not payment_id and user_id:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT payment_id, amount_points, status FROM crypto_payments WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1",
                (int(user_id),)
            )
            row = cursor.fetchone()
            conn.close()
            
            if not row:
                # Проверим - может уже оплачен?
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT payment_id, amount_points FROM crypto_payments WHERE user_id = ? AND status = 'paid' ORDER BY created_at DESC LIMIT 1",
                    (int(user_id),)
                )
                paid_row = cursor.fetchone()
                conn.close()
                if paid_row:
                    new_balance = get_balance_sync(int(user_id))
                    return web.json_response({
                        'success': True,
                        'status': 'already_credited',
                        'message': f'✅ Баллы уже начислены! ({paid_row[1]} 💎)',
                        'new_balance': new_balance,
                        'amount_points': paid_row[1]
                    })
                
                return web.json_response({
                    'success': True,
                    'status': 'no_pending',
                    'message': 'Нет ожидающих платежей. Возможно, платёж уже обработан.'
                })
            
            payment_id = row[0]
            logger.info(f"Found pending payment: {payment_id}, amount: {row[1]}, status: {row[2]}")
        
        if not payment_id:
            return web.json_response({'success': False, 'error': 'payment_id required'}, status=400)
        
        # ПРОВЕРКА 1: Локально в SQLite
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount_points, status FROM crypto_payments WHERE payment_id = ?", (payment_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            local_user_id, amount, local_status = row
            logger.info(f"Local status for {payment_id}: {local_status}")
            
            if local_status == 'paid':
                new_balance = get_balance_sync(local_user_id)
                return web.json_response({
                    'success': True,
                    'status': 'paid',
                    'amount_points': amount,
                    'new_balance': new_balance,
                    'message': f'✅ Начислено {amount} баллов!'
                })
        
        # ПРОВЕРКА 2: Через CryptoPay API
        logger.info(f"Checking CryptoPay API for {payment_id}")
        async with aiohttp.ClientSession() as session:
            headers = {
                'Crypto-Pay-API-Token': CRYPTOPAY_TOKEN,
                'Content-Type': 'application/json'
            }
            params = {'invoice_ids': payment_id}
            
            try:
                async with session.get(f'{CRYPTOPAY_API_URL}/getInvoices', params=params, headers=headers, timeout=10) as resp:
                    result = await resp.json()
                logger.info(f"CryptoPay API response: ok={result.get('ok')}, items_count={len(result.get('result', {}).get('items', []))}")
            except Exception as api_err:
                logger.error(f"CryptoPay API error: {api_err}")
                return web.json_response({
                    'success': True,
                    'status': 'api_error',
                    'message': f'⏳ Ошибка связи с CryptoPay. Попробуйте позже.'
                })
            
            if not result.get('ok'):
                logger.error(f"CryptoPay API not ok: {result}")
                return web.json_response({
                    'success': True,
                    'status': 'api_error',
                    'message': '⏳ Ошибка CryptoPay API. Попробуйте позже.'
                })
            
            if not result['result']['items']:
                logger.warning(f"Invoice {payment_id} not found in CryptoPay")
                return web.json_response({
                    'success': True,
                    'status': 'not_found',
                    'message': '❌ Счёт не найден. Возможно, он был удалён.'
                })
            
            invoice = result['result']['items'][0]
            api_status = invoice['status']
            logger.info(f"Invoice {payment_id} status from API: {api_status}")
            
            if api_status == 'paid':
                # Обновляем локально
                confirmed = confirm_payment(payment_id)
                if confirmed:
                    uid, amount = confirmed
                    new_balance = get_balance_sync(uid)
                    logger.info(f"Payment confirmed! User {uid}, amount {amount}, new balance {new_balance}")
                    
                    # Уведомление в бот
                    try:
                        await bot.send_message(
                            uid,
                            f"✅ <b>Платёж подтверждён!</b>\n\n"
                            f"💰 Начислено: <b>{amount} 💎</b>\n"
                            f"💵 Сумма: <b>{PRICE_LIST.get(amount, '?')} USDT</b>\n\n"
                            f"Спасибо за пополнение! 🎉",
                            parse_mode="HTML"
                        )
                    except Exception as notify_err:
                        logger.error(f"Failed to notify user {uid}: {notify_err}")
                    
                    return web.json_response({
                        'success': True,
                        'status': 'paid',
                        'user_id': uid,
                        'amount_points': amount,
                        'new_balance': new_balance,
                        'message': f'✅ Начислено {amount} баллов!'
                    })
                else:
                    return web.json_response({
                        'success': True,
                        'status': 'already_credited',
                        'message': '✅ Баллы уже были начислены ранее'
                    })
            
            status_messages = {
                'active': '⏳ Счёт активен, но не оплачен. Проверьте оплату в CryptoBot.',
                'expired': '❌ Срок действия счёта истёк. Создайте новый.',
                'pending': '⏳ Платёж обрабатывается...'
            }
            message = status_messages.get(api_status, f'⏳ Статус: {api_status}. Попробуйте позже.')
            
            return web.json_response({
                'success': True,
                'status': api_status,
                'message': message
            })
            
    except Exception as e:
        logger.error(f"Check payment error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_crypto_webhook(request):
    """Webhook для CryptoPay (автоматическое подтверждение)"""
    try:
        body = await request.text()
        signature = request.headers.get('crypto-pay-api-sign', '')
        
        # Проверяем подпись
        secret = hashlib.sha256(CRYPTOPAY_TOKEN.encode()).digest()
        expected_signature = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
        
        if signature != expected_signature:
            logger.warning("Invalid webhook signature")
            return web.json_response({'error': 'Invalid signature'}, status=403)
        
        data = json.loads(body)
        logger.info(f"CryptoPay webhook received: {data}")
        
        if data.get('update_type') == 'invoice_paid':
            invoice_id = str(data['payload']['invoice_id'])
            confirmed = confirm_payment(invoice_id)
            if confirmed:
                user_id, amount = confirmed
                logger.info(f"Webhook: Payment confirmed for user {user_id}, amount {amount}")
                
                try:
                    await bot.send_message(
                        user_id,
                        f"✅ <b>Платёж подтверждён!</b>\n\n"
                        f"💰 Начислено: <b>{amount} 💎</b>\n"
                        f"💵 Сумма: <b>{PRICE_LIST.get(amount, '?')} USDT</b>\n\n"
                        f"Спасибо за пополнение! 🎉",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user {user_id}: {e}")
        
        return web.json_response({'success': True})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.json_response({'error': str(e)}, status=500)

async def handle_get_price_list(request):
    try:
        return web.json_response({
            'success': True,
            'prices': {str(k): v for k, v in PRICE_LIST.items()}
        })
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def health(request):
    return web.json_response({'status': 'ok'})

# ===== ВСЕ РОУТЫ (после определения всех функций) =====
app.router.add_post('/api/get_balance', handle_get_balance)
app.router.add_post('/api/get_profile', handle_get_profile)
app.router.add_post('/api/game_result', handle_game_result)
app.router.add_post('/api/claim_ad_reward', handle_claim_ad_reward)
app.router.add_post('/api/create_invoice', handle_create_invoice)
app.router.add_post('/api/check_payment', handle_check_payment)
app.router.add_post('/api/crypto_webhook', handle_crypto_webhook)
app.router.add_get('/api/get_price_list', handle_get_price_list)
app.router.add_get('/health', health)
app.router.add_get('/', health)

async def handle_webhook(request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return web.Response()

app.router.add_post('/webhook', handle_webhook)

# ========== ЗАПУСК ==========
async def on_startup():
    await init_db_pool()
    await create_db()
    init_sqlite_db()
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="myid", description="Мой Telegram ID"),
        BotCommand(command="admin", description="Админ-панель"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("Бот запущен")

async def on_shutdown():
    await bot.session.close()
    await close_db_pool()
    logger.info("Бот остановлен")

async def main():
    port = int(os.environ.get('PORT', 10000))
    
    await on_startup()
    
    webhook_url = f"https://game-bar-bot.onrender.com/webhook"
    
    await bot.delete_webhook()
    await bot.set_webhook(webhook_url)
    logger.info(f"Webhook установлен на {webhook_url}")
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"HTTP сервер запущен на порту {port}")
    
    try:
        await asyncio.Future()
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())
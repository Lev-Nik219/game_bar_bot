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
from datetime import datetime
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

AD_REWARD_AMOUNT = 25
AD_COOLDOWN_SECONDS = 20

CRYPTOPAY_TOKEN = os.environ.get('CRYPTOPAY_TOKEN', '455143:AA35WjAeKxzuurvYbMCZewcqzQ7VmtAQbDZ')
CRYPTOPAY_API_URL = 'https://pay.crypt.bot/api'

PRICE_LIST = {
    250: 20,
    500: 35,
    750: 50,
    1000: 65
}

CASHBACK_PERCENT = 5  # 5% от проигрышей
CASHBACK_DAY = 6  # Воскресенье (0=ПН, 6=ВС)

REFERRAL_BONUS_INVITER = 100  # Баллов пригласившему
REFERRAL_BONUS_INVITED = 25   # Баллов приглашённому

# ===== ДОСТИЖЕНИЯ =====
ACHIEVEMENTS = {
    'first_game': {'name': '🎮 Первая игра', 'desc': 'Сыграть первую игру', 'icon': '🎮', 'target': 1},
    '10_games': {'name': '🎰 Игрок', 'desc': 'Сыграть 10 игр', 'icon': '🎰', 'target': 10},
    '50_games': {'name': '🎲 Завсегдатай', 'desc': 'Сыграть 50 игр', 'icon': '🎲', 'target': 50},
    '100_games': {'name': '🃏 Ветеран', 'desc': 'Сыграть 100 игр', 'icon': '🃏', 'target': 100},
    '500_games': {'name': '👑 Легенда', 'desc': 'Сыграть 500 игр', 'icon': '👑', 'target': 500},
    'first_win': {'name': '🍀 Первая победа', 'desc': 'Одержать первую победу', 'icon': '🍀', 'target': 1},
    '10_wins': {'name': '🏆 Победитель', 'desc': 'Одержать 10 побед', 'icon': '🏆', 'target': 10},
    '50_wins': {'name': '💪 Чемпион', 'desc': 'Одержать 50 побед', 'icon': '💪', 'target': 50},
    '100_wins': {'name': '🌟 Мастер', 'desc': 'Одержать 100 побед', 'icon': '🌟', 'target': 100},
    'big_win': {'name': '💰 Крупный выигрыш', 'desc': 'Выиграть 500+ баллов за раз', 'icon': '💰', 'target': 1},
    'balance_1000': {'name': '💎 Тысячник', 'desc': 'Накопить 1000 баллов', 'icon': '💎', 'target': 1},
    'balance_5000': {'name': '💵 Богач', 'desc': 'Накопить 5000 баллов', 'icon': '💵', 'target': 1},
    'depositor': {'name': '📥 Инвестор', 'desc': 'Пополнить баланс', 'icon': '📥', 'target': 1},
}

def check_achievements_sync(user_id: int, balance: int, total_games: int, wins: int, win_amount: int = 0):
    """Проверяет и выдаёт достижения"""
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.execute("PRAGMA busy_timeout = 5000")
    cursor = conn.cursor()
    
    # Убедимся что таблица есть
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            achieved_at INTEGER NOT NULL,
            UNIQUE(user_id, achievement_id)
        )
    ''')
    
    # Получаем уже выданные достижения
    cursor.execute("SELECT achievement_id FROM achievements WHERE user_id = ?", (user_id,))
    existing = {row[0] for row in cursor.fetchall()}
    
    new_achievements = []
    
    # Проверяем каждое достижение
    checks = {
        'first_game': total_games >= 1,
        '10_games': total_games >= 10,
        '50_games': total_games >= 50,
        '100_games': total_games >= 100,
        '500_games': total_games >= 500,
        'first_win': wins >= 1,
        '10_wins': wins >= 10,
        '50_wins': wins >= 50,
        '100_wins': wins >= 100,
        'big_win': win_amount >= 500,
        'balance_1000': balance >= 1000,
        'balance_5000': balance >= 5000,
    }
    
    now = int(time.time())
    for ach_id, achieved in checks.items():
        if achieved and ach_id not in existing:
            cursor.execute(
                "INSERT OR IGNORE INTO achievements (user_id, achievement_id, achieved_at) VALUES (?, ?, ?)",
                (user_id, ach_id, now)
            )
            new_achievements.append(ach_id)
    
    conn.commit()
    conn.close()
    return new_achievements

def check_depositor_achievement(user_id: int):
    """Отдельная проверка достижения за пополнение"""
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.execute("PRAGMA busy_timeout = 5000")
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            achieved_at INTEGER NOT NULL,
            UNIQUE(user_id, achievement_id)
        )
    ''')
    
    cursor.execute(
        "INSERT OR IGNORE INTO achievements (user_id, achievement_id, achieved_at) VALUES (?, 'depositor', ?)",
        (user_id, int(time.time()))
    )
    conn.commit()
    conn.close()

def get_achievements_sync(user_id: int):
    """Получает все достижения пользователя"""
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.execute("PRAGMA busy_timeout = 5000")
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            achieved_at INTEGER NOT NULL,
            UNIQUE(user_id, achievement_id)
        )
    ''')
    
    cursor.execute(
        "SELECT achievement_id, achieved_at FROM achievements WHERE user_id = ? ORDER BY achieved_at DESC",
        (user_id,)
    )
    earned = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Формируем полный список с прогрессом
    conn.close()
    return earned

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ SQLite =====

def execute_sqlite_with_retry(func, max_retries=5, delay=0.5):
    for attempt in range(max_retries):
        try:
            return func()
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and attempt < max_retries - 1:
                logger.warning(f"SQLite locked, retry {attempt + 1}/{max_retries}...")
                time.sleep(delay * (attempt + 1))
            else:
                raise
    raise Exception("SQLite still locked after retries")

def get_balance_sync(user_id: int):
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0
    return execute_sqlite_with_retry(_do)

def update_balance_sync(user_id: int, new_balance: int):
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        conn.commit()
        conn.close()
    return execute_sqlite_with_retry(_do)

def update_stats_sync(user_id: int, win: bool):
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
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
    return execute_sqlite_with_retry(_do)

def get_user_stats_sync(user_id: int):
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute("SELECT balance, total_games, wins FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return (row[0], row[1], row[2]) if row else (0, 0, 0)
    return execute_sqlite_with_retry(_do)

def process_referral_sync(inviter_id: int, invited_id: int):
    """Обрабатывает реферальное приглашение"""
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        
        # Проверяем, не был ли уже приглашён
        cursor.execute("SELECT invited_by FROM users WHERE user_id = ?", (invited_id,))
        row = cursor.fetchone()
        if row and row[0] is not None:
            conn.close()
            return None  # Уже приглашён кем-то
        
        # Обновляем приглашённого
        cursor.execute("UPDATE users SET invited_by = ? WHERE user_id = ?", (inviter_id, invited_id))
        
        # Начисляем бонус приглашённому
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (invited_id,))
        inv_bal = cursor.fetchone()[0]
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (inv_bal + REFERRAL_BONUS_INVITED, invited_id))
        
        conn.commit()
        conn.close()
        return inviter_id
    return execute_sqlite_with_retry(_do)

def claim_referral_reward_sync(invited_id: int):
    """Начисляет бонус пригласившему после первой игры приглашённого"""
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        
        cursor.execute("SELECT invited_by, referral_claimed FROM users WHERE user_id = ?", (invited_id,))
        row = cursor.fetchone()
        if not row or not row[0]:
            conn.close()
            return None
        
        inviter_id = row[0]
        already_claimed = row[1] if len(row) > 1 else 0
        
        if already_claimed:
            conn.close()
            return None
        
        # Начисляем пригласившему
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (inviter_id,))
        inv_bal = cursor.fetchone()[0]
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (inv_bal + REFERRAL_BONUS_INVITER, inviter_id))
        
        # Помечаем, что бонус начислен
        cursor.execute("UPDATE users SET referral_claimed = 1 WHERE user_id = ?", (invited_id,))
        
        # Увеличиваем счётчик рефералов
        cursor.execute("UPDATE users SET referral_count = COALESCE(referral_count, 0) + 1 WHERE user_id = ?", (inviter_id,))
        
        conn.commit()
        conn.close()
        return (inviter_id, inv_bal + REFERRAL_BONUS_INVITER)
    return execute_sqlite_with_retry(_do)

def get_referral_stats_sync(user_id: int):
    """Статистика рефералов"""
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE invited_by = ?", (user_id,))
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE invited_by = ? AND total_games > 0", (user_id,))
        played = cursor.fetchone()[0]
        
        cursor.execute("SELECT user_id, username, total_games FROM users WHERE invited_by = ? ORDER BY total_games DESC LIMIT 10", (user_id,))
        friends = [{'user_id': r[0], 'username': r[1] or f'ID{r[0]}', 'games': r[2]} for r in cursor.fetchall()]
        
        conn.close()
        return {'total': total, 'played': played, 'friends': friends}
    return execute_sqlite_with_retry(_do)

async def handle_referral_join(request):
    """Присоединение по реферальной ссылке"""
    try:
        data = await request.json()
        invited_id = data.get('user_id')
        inviter_id = data.get('inviter_id')
        
        if not invited_id or not inviter_id:
            return web.json_response({'success': False, 'error': 'user_id and inviter_id required'}, status=400)
        
        if int(invited_id) == int(inviter_id):
            return web.json_response({'success': False, 'error': 'Cannot refer yourself'}, status=400)
        
        result = process_referral_sync(int(inviter_id), int(invited_id))
        
        if result is None:
            return web.json_response({'success': False, 'error': 'Already referred or invalid'}, status=200)
        
        return web.json_response({
            'success': True,
            'message': f'Вы присоединились по реферальной ссылке! +{REFERRAL_BONUS_INVITED} баллов',
            'bonus': REFERRAL_BONUS_INVITED
        })
    except Exception as e:
        logger.error(f"referral_join error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_get_referral_stats(request):
    """Получение статистики рефералов"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        if not user_id:
            return web.json_response({'success': False, 'error': 'user_id required'}, status=400)
        
        stats = get_referral_stats_sync(int(user_id))
        balance = get_balance_sync(int(user_id))
        stats['balance'] = balance
        
        return web.json_response({'success': True, 'stats': stats})
    except Exception as e:
        logger.error(f"referral_stats error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_get_referral_link(request):
    """Получение реферальной ссылки"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        if not user_id:
            return web.json_response({'success': False, 'error': 'user_id required'}, status=400)
        
        link = f"https://t.me/GamesAsino_bot/GamesAsino?startapp=ref_{user_id}"
        
        return web.json_response({'success': True, 'link': link, 'user_id': user_id})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=500)

def save_game_history_sync(user_id: int, bet: int, win_amount: int, game_type: str):
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO game_history (user_id, game_type, bet_amount, win_amount, played_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, game_type, bet, win_amount, int(time.time()))
        )
        conn.commit()
        conn.close()
    return execute_sqlite_with_retry(_do)

def get_last_ad_time_sync(user_id: int):
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute("SELECT last_ad_watch FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0
    return execute_sqlite_with_retry(_do)

def set_last_ad_time_sync(user_id: int, timestamp: int):
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_ad_watch = ? WHERE user_id = ?", (timestamp, user_id))
        conn.commit()
        conn.close()
    return execute_sqlite_with_retry(_do)

def create_payment(user_id: int, amount_points: int, price_usdt: float, payment_id: str, invoice_id: str):
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO crypto_payments (user_id, amount_points, price_usdt, payment_id, invoice_id, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (user_id, amount_points, price_usdt, payment_id, invoice_id, int(time.time()))
        )
        conn.commit()
        conn.close()
    return execute_sqlite_with_retry(_do)

def confirm_payment(payment_id: str):
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount_points, status FROM crypto_payments WHERE payment_id = ?", (payment_id,))
        row = cursor.fetchone()
        if not row or row[2] != 'pending':
            conn.close()
            return None
        user_id, amount_points, _ = row
        cursor.execute("UPDATE crypto_payments SET status = 'paid' WHERE payment_id = ?", (payment_id,))
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance_row = cursor.fetchone()
        current_balance = balance_row[0] if balance_row else 0
        new_balance = current_balance + amount_points
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        conn.commit()
        conn.close()
        logger.info(f"Payment {payment_id} confirmed: user {user_id}, +{amount_points}, balance {new_balance}")
        # Выдаём достижение за пополнение
        check_depositor_achievement(user_id)
        return (user_id, amount_points)
    try:
        return execute_sqlite_with_retry(_do, max_retries=10, delay=0.3)
    except Exception as e:
        logger.error(f"Failed to confirm payment {payment_id}: {e}")
        return None

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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            achieved_at INTEGER NOT NULL,
            UNIQUE(user_id, achievement_id)
        )
    ''')
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN invited_by INTEGER DEFAULT NULL")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN referral_claimed INTEGER DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN avatar_emoji TEXT DEFAULT '🦊'")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
    logger.info("SQLite tables created/verified")

# ========== TELEGRAM БОТ ==========
bot = Bot(token=MAIN_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

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
        uid = int(user_id)
        def _do():
            conn = sqlite3.connect(DB_NAME, timeout=10)
            conn.execute("PRAGMA busy_timeout = 5000")
            cursor = conn.cursor()
            cursor.execute("SELECT balance, total_games FROM users WHERE user_id = ?", (uid,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO users (user_id, balance, total_games, wins, avatar_emoji) VALUES (?, 50, 0, 0, '🦊')", (uid,))
                conn.commit()
                conn.close()
                logger.info(f"New user {uid} created with 50 bonus points!")
                return 50
            conn.close()
            return row[0]
        balance = execute_sqlite_with_retry(_do)
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
        def _do():
            conn = sqlite3.connect(DB_NAME, timeout=10)
            conn.execute("PRAGMA busy_timeout = 5000")
            cursor = conn.cursor()
            cursor.execute("SELECT balance, total_games, wins, display_name, avatar_emoji FROM users WHERE user_id = ?", (uid,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return None
            balance, total_games, wins = row[0], row[1], row[2]
            display_name = row[3] if len(row) > 3 else None
            avatar_emoji = row[4] if len(row) > 4 else '🦊'
            cursor.execute("SELECT game_type, bet_amount, win_amount, played_at FROM game_history WHERE user_id = ? ORDER BY played_at DESC LIMIT 10", (uid,))
            games = cursor.fetchall()
            conn.close()
            return (balance, total_games, wins, display_name, avatar_emoji, games)
        result = execute_sqlite_with_retry(_do)
        if not result:
            return web.json_response({'success': False, 'error': 'User not found'}, status=404)
        balance, total_games, wins, display_name, avatar_emoji, games = result
        losses = total_games - wins
        winrate = round(wins / total_games * 100, 1) if total_games > 0 else 0
        recent_games = []
        for game_type, bet, win_amount, timestamp in games:
            recent_games.append({'game': game_type, 'bet': bet, 'win_amount': win_amount, 'result': 'win' if win_amount > 0 else 'lose', 'time': timestamp})
        return web.json_response({'success': True, 'profile': {'user_id': uid, 'balance': balance, 'total_games': total_games, 'wins': wins, 'losses': losses, 'winrate': winrate, 'recent_games': recent_games, 'display_name': display_name, 'avatar_emoji': avatar_emoji or '🦊'}})
    except Exception as e:
        logger.error(f"get_profile error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_get_achievements(request):
    """Возвращает все достижения с прогрессом"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        if not user_id:
            return web.json_response({'success': False, 'error': 'user_id required'}, status=400)
        uid = int(user_id)
        balance, total_games, wins = get_user_stats_sync(uid)
        earned = get_achievements_sync(uid)
        all_achievements = []
        for ach_id, ach_data in ACHIEVEMENTS.items():
            progress = 0
            if ach_id in ['first_game', '10_games', '50_games', '100_games', '500_games']:
                progress = total_games
            elif ach_id in ['first_win', '10_wins', '50_wins', '100_wins']:
                progress = wins
            elif ach_id == 'big_win':
                progress = 1 if ach_id in earned else 0
            elif ach_id in ['balance_1000', 'balance_5000']:
                progress = balance
            elif ach_id == 'depositor':
                progress = 1 if ach_id in earned else 0
            all_achievements.append({
                'id': ach_id,
                'name': ach_data['name'],
                'desc': ach_data['desc'],
                'icon': ach_data['icon'],
                'target': ach_data['target'],
                'progress': progress,
                'earned': ach_id in earned,
                'earned_at': earned.get(ach_id, 0)
            })
        return web.json_response({'success': True, 'achievements': all_achievements})
    except Exception as e:
        logger.error(f"get_achievements error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_save_profile(request):
    try:
        data = await request.json()
        user_id = data.get('user_id')
        display_name = data.get('display_name', '').strip()
        avatar_emoji = data.get('avatar_emoji', '🦊')
        if not user_id:
            return web.json_response({'success': False, 'error': 'user_id required'}, status=400)
        if display_name and len(display_name) > 30:
            return web.json_response({'success': False, 'error': 'Никнейм слишком длинный (макс 30 символов)'}, status=400)
        allowed_emojis = ['🦊', '🐺', '🦁', '🐯', '🐻', '🐼', '🐨', '🐰', '🦄', '🐲', '🎃', '🤖', '👑', '💀', '👻']
        if avatar_emoji not in allowed_emojis:
            avatar_emoji = '🦊'
        def _do():
            conn = sqlite3.connect(DB_NAME, timeout=10)
            conn.execute("PRAGMA busy_timeout = 5000")
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET display_name = ?, avatar_emoji = ? WHERE user_id = ?", (display_name or None, avatar_emoji, int(user_id)))
            conn.commit()
            conn.close()
        execute_sqlite_with_retry(_do)
        return web.json_response({'success': True, 'message': 'Профиль сохранён!', 'display_name': display_name, 'avatar_emoji': avatar_emoji})
    except Exception as e:
        logger.error(f"save_profile error: {e}")
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
        uid = int(user_id)
        current_balance = get_balance_sync(uid)
        
        # Проверяем, первая ли это игра (для рефералки)
        bal_before, tg_before, w_before = get_user_stats_sync(uid)
        is_first_game = tg_before == 0
        
        new_balance = current_balance + win_amount if win else current_balance - bet
        update_balance_sync(uid, new_balance)
        update_stats_sync(uid, win)
        save_game_history_sync(uid, bet, win_amount if win else 0, game)
        
        # Реферальный бонус после первой игры
        if is_first_game:
            claim_result = claim_referral_reward_sync(uid)
            if claim_result:
                try:
                    await bot.send_message(claim_result[0], f"🎉 Ваш друг сыграл первую игру!\n💰 Вы получили +{REFERRAL_BONUS_INVITER} 💎!")
                except:
                    pass
        
        bal, tgames, w = get_user_stats_sync(uid)
        new_achs = check_achievements_sync(uid, new_balance, tgames, w, win_amount if win else 0)
        
        return web.json_response({'success': True, 'new_balance': new_balance, 'win': win, 'new_achievements': new_achs if new_achs else []})
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
            headers = {'Crypto-Pay-API-Token': CRYPTOPAY_TOKEN, 'Content-Type': 'application/json'}
            payload = {'asset': 'USDT', 'amount': str(price_usdt), 'description': f'Пополнение {amount_points} баллов для Game Bar Casino', 'payload': json.dumps({'user_id': user_id, 'amount_points': amount_points}), 'allow_comments': False, 'allow_anonymous': False}
            try:
                async with session.post(f'{CRYPTOPAY_API_URL}/createInvoice', json=payload, headers=headers) as resp:
                    result = await resp.json()
            except Exception as e:
                return web.json_response({'success': False, 'error': f'CryptoPay API error: {str(e)}'}, status=500)
            if not result.get('ok'):
                return web.json_response({'success': False, 'error': f'CryptoPay error: {result.get("error", "unknown")}'}, status=500)
            invoice = result['result']
            payment_id = str(invoice['invoice_id'])
            invoice_url = invoice['pay_url']
            create_payment(int(user_id), amount_points, price_usdt, payment_id, str(invoice['invoice_id']))
            return web.json_response({'success': True, 'payment_id': payment_id, 'invoice_url': invoice_url, 'amount_points': amount_points, 'price_usdt': price_usdt})
    except Exception as e:
        logger.error(f"Create invoice error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_check_payment(request):
    try:
        data = await request.json()
        payment_id = data.get('payment_id')
        user_id = data.get('user_id')
        if not payment_id and user_id:
            def _find():
                conn = sqlite3.connect(DB_NAME, timeout=10)
                conn.execute("PRAGMA busy_timeout = 5000")
                cursor = conn.cursor()
                cursor.execute("SELECT payment_id, amount_points, status FROM crypto_payments WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC LIMIT 1", (int(user_id),))
                row = cursor.fetchone()
                conn.close()
                return row
            row = execute_sqlite_with_retry(_find)
            if not row:
                def _find_paid():
                    conn = sqlite3.connect(DB_NAME, timeout=10)
                    conn.execute("PRAGMA busy_timeout = 5000")
                    cursor = conn.cursor()
                    cursor.execute("SELECT payment_id, amount_points FROM crypto_payments WHERE user_id = ? AND status = 'paid' ORDER BY created_at DESC LIMIT 1", (int(user_id),))
                    paid_row = cursor.fetchone()
                    conn.close()
                    return paid_row
                paid_row = execute_sqlite_with_retry(_find_paid)
                if paid_row:
                    new_balance = get_balance_sync(int(user_id))
                    return web.json_response({'success': True, 'status': 'already_credited', 'message': f'✅ Баллы уже начислены! ({paid_row[1]} 💎)', 'new_balance': new_balance, 'amount_points': paid_row[1]})
                return web.json_response({'success': True, 'status': 'no_pending', 'message': 'Нет ожидающих платежей.'})
            payment_id = row[0]
        if not payment_id:
            return web.json_response({'success': False, 'error': 'payment_id required'}, status=400)
        def _check_local():
            conn = sqlite3.connect(DB_NAME, timeout=10)
            conn.execute("PRAGMA busy_timeout = 5000")
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, amount_points, status FROM crypto_payments WHERE payment_id = ?", (payment_id,))
            row = cursor.fetchone()
            conn.close()
            return row
        row = execute_sqlite_with_retry(_check_local)
        if row and row[2] == 'paid':
            new_balance = get_balance_sync(row[0])
            return web.json_response({'success': True, 'status': 'paid', 'amount_points': row[1], 'new_balance': new_balance, 'message': f'✅ Начислено {row[1]} баллов!'})
        async with aiohttp.ClientSession() as session:
            headers = {'Crypto-Pay-API-Token': CRYPTOPAY_TOKEN, 'Content-Type': 'application/json'}
            params = {'invoice_ids': payment_id}
            try:
                async with session.get(f'{CRYPTOPAY_API_URL}/getInvoices', params=params, headers=headers, timeout=10) as resp:
                    result = await resp.json()
            except Exception:
                return web.json_response({'success': True, 'status': 'api_error', 'message': '⏳ Ошибка связи с CryptoPay.'})
            if not result.get('ok') or not result['result']['items']:
                return web.json_response({'success': True, 'status': 'not_found', 'message': '❌ Счёт не найден.'})
            invoice = result['result']['items'][0]
            if invoice['status'] == 'paid':
                confirmed = confirm_payment(payment_id)
                if confirmed:
                    uid, amount = confirmed
                    new_balance = get_balance_sync(uid)
                    return web.json_response({'success': True, 'status': 'paid', 'user_id': uid, 'amount_points': amount, 'new_balance': new_balance, 'message': f'✅ Начислено {amount} баллов!'})
                return web.json_response({'success': True, 'status': 'already_credited', 'message': '✅ Баллы уже начислены.'})
            return web.json_response({'success': True, 'status': invoice['status'], 'message': f'⏳ Статус: {invoice["status"]}.'})
    except Exception as e:
        logger.error(f"Check payment error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_crypto_webhook(request):
    try:
        body = await request.text()
        signature = request.headers.get('crypto-pay-api-sign', '')
        secret = hashlib.sha256(CRYPTOPAY_TOKEN.encode()).digest()
        expected_signature = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
        if signature != expected_signature:
            return web.json_response({'error': 'Invalid signature'}, status=403)
        data = json.loads(body)
        if data.get('update_type') == 'invoice_paid':
            invoice_id = str(data['payload']['invoice_id'])
            confirmed = confirm_payment(invoice_id)
            if confirmed:
                user_id, amount = confirmed
                try:
                    await bot.send_message(user_id, f"✅ <b>Платёж подтверждён!</b>\n\n💰 Начислено: <b>{amount} 💎</b>\n💵 Сумма: <b>{PRICE_LIST.get(amount, '?')} USDT</b>\n\nСпасибо за пополнение! 🎉", parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to notify user {user_id}: {e}")
        return web.json_response({'success': True})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.json_response({'error': str(e)}, status=500)

async def handle_get_price_list(request):
    return web.json_response({'success': True, 'prices': {str(k): v for k, v in PRICE_LIST.items()}})

async def health(request):
    return web.json_response({'status': 'ok'})

# ===== КЭШБЕК =====

def get_weekly_losses_sync(user_id: int) -> int:
    """Сумма проигрышей за последние 7 дней"""
    week_ago = int(time.time()) - 7 * 86400
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(bet_amount), 0) FROM game_history "
            "WHERE user_id = ? AND played_at >= ? AND win_amount = 0",
            (user_id, week_ago)
        )
        total = cursor.fetchone()[0]
        conn.close()
        return total
    return execute_sqlite_with_retry(_do)

def get_last_cashback_sync(user_id: int) -> int:
    """Время последнего кэшбека"""
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT last_cashback FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            conn.close()
            return row[0] if row and row[0] else 0
        except:
            conn.close()
            return 0
    return execute_sqlite_with_retry(_do)

def set_last_cashback_sync(user_id: int, timestamp: int):
    def _do():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN last_cashback INTEGER DEFAULT 0")
        except:
            pass
        cursor.execute("UPDATE users SET last_cashback = ? WHERE user_id = ?", (timestamp, user_id))
        conn.commit()
        conn.close()
    execute_sqlite_with_retry(_do)

async def process_weekly_cashback():
    """Обработка еженедельного кэшбека для всех пользователей"""
    logger.info("🔄 Запущена обработка еженедельного кэшбека...")
    
    now = int(time.time())
    week_ago = now - 7 * 86400
    
    def _get_users():
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA busy_timeout = 5000")
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return users
    
    users = execute_sqlite_with_retry(_get_users)
    total_cashback = 0
    users_notified = 0
    
    for user_id in users:
        try:
            last_cb = get_last_cashback_sync(user_id)
            # Проверяем, прошла ли неделя с последнего кэшбека
            if last_cb > week_ago:
                continue
            
            losses = get_weekly_losses_sync(user_id)
            if losses <= 0:
                continue
            
            cashback = int(losses * CASHBACK_PERCENT / 100)
            if cashback <= 0:
                continue
            
            # Начисляем кэшбек
            current_balance = get_balance_sync(user_id)
            new_balance = current_balance + cashback
            update_balance_sync(user_id, new_balance)
            set_last_cashback_sync(user_id, now)
            
            total_cashback += cashback
            users_notified += 1
            
            # Отправляем уведомление
            try:
                await bot.send_message(
                    user_id,
                    f"💰 <b>Еженедельный кэшбек!</b>\n\n"
                    f"📊 Ваши проигрыши за неделю: <b>{losses} 💎</b>\n"
                    f"🔄 Кэшбек {CASHBACK_PERCENT}%: <b>+{cashback} 💎</b>\n"
                    f"💳 Новый баланс: <b>{new_balance} 💎</b>\n\n"
                    f"Спасибо за игру! 🎉",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to notify user {user_id} about cashback: {e}")
            
            await asyncio.sleep(0.05)  # Защита от флуда
            
        except Exception as e:
            logger.error(f"Cashback error for user {user_id}: {e}")
    
    logger.info(f"✅ Кэшбек обработан: {users_notified} пользователей, {total_cashback} баллов")
    
    # Уведомляем админов
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💰 <b>Еженедельный кэшбек завершён!</b>\n\n"
                f"👥 Пользователей: {users_notified}\n"
                f"💎 Всего начислено: {total_cashback} баллов",
                parse_mode="HTML"
            )
        except:
            pass

async def cashback_scheduler():
    """Фоновая задача: проверяет каждые 30 минут, не пора ли запустить кэшбек"""
    while True:
        now = datetime.now()
        # Запускаем в воскресенье между 00:00 и 00:30
        if now.weekday() == CASHBACK_DAY and now.hour == 0 and now.minute < 30:
            await process_weekly_cashback()
            # Ждём час после запуска, чтобы не сработать повторно
            await asyncio.sleep(3600)
        else:
            # Проверяем каждые 30 минут
            await asyncio.sleep(1800)

async def handle_manual_cashback(request):
    """Ручной запуск кэшбека (для админа через WebApp)"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        
        if not user_id or int(user_id) not in ADMIN_IDS:
            return web.json_response({'success': False, 'error': 'Access denied'}, status=403)
        
        # Запускаем в фоне
        asyncio.create_task(process_weekly_cashback())
        
        return web.json_response({'success': True, 'message': 'Кэшбек запущен в фоновом режиме'})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def handle_get_cashback_info(request):
    """Информация о кэшбеке для пользователя"""
    try:
        data = await request.json()
        user_id = data.get('user_id')
        if not user_id:
            return web.json_response({'success': False, 'error': 'user_id required'}, status=400)
        
        uid = int(user_id)
        losses = get_weekly_losses_sync(uid)
        cashback = int(losses * CASHBACK_PERCENT / 100)
        last_cb = get_last_cashback_sync(uid)
        now = int(time.time())
        week_ago = now - 7 * 86400
        can_claim = last_cb < week_ago and cashback > 0
        
        return web.json_response({
            'success': True,
            'weekly_losses': losses,
            'cashback_amount': cashback,
            'percent': CASHBACK_PERCENT,
            'last_cashback': last_cb,
            'can_claim': can_claim
        })
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=500)

# ===== ВСЕ РОУТЫ =====
app.router.add_post('/api/get_balance', handle_get_balance)
app.router.add_post('/api/get_profile', handle_get_profile)
app.router.add_post('/api/get_achievements', handle_get_achievements)
app.router.add_post('/api/save_profile', handle_save_profile)
app.router.add_post('/api/game_result', handle_game_result)
app.router.add_post('/api/claim_ad_reward', handle_claim_ad_reward)
app.router.add_post('/api/create_invoice', handle_create_invoice)
app.router.add_post('/api/check_payment', handle_check_payment)
app.router.add_post('/api/crypto_webhook', handle_crypto_webhook)
app.router.add_post('/api/manual_cashback', handle_manual_cashback)
app.router.add_post('/api/get_cashback_info', handle_get_cashback_info)
app.router.add_post('/api/referral_join', handle_referral_join)
app.router.add_post('/api/get_referral_stats', handle_get_referral_stats)
app.router.add_post('/api/get_referral_link', handle_get_referral_link)
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
    commands = [BotCommand(command="start", description="Запустить бота"), BotCommand(command="myid", description="Мой Telegram ID"), BotCommand(command="admin", description="Админ-панель")]
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
        # Запускаем планировщик кэшбека
    asyncio.create_task(cashback_scheduler())
    logger.info("Планировщик кэшбека запущен")
    logger.info(f"HTTP сервер запущен на порту {port}")
    try:
        await asyncio.Future()
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())
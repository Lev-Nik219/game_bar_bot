import asyncpg
import asyncio
import time
import random
import os
from typing import Optional, Tuple, List, Any

# Получаем URL базы данных из переменных окружения Render
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Для совместимости со старым кодом
DB_NAME = "postgresql"

# Глобальный пул соединений
db_pool = None

# ========== КОНСТАНТЫ ==========
BONUS_WAGER_MULTIPLIER = 3
CASHBACK_PERCENT = 5

async def init_db_pool():
    """Инициализирует пул соединений с PostgreSQL."""
    global db_pool
    if db_pool is None:
        if not DATABASE_URL:
            raise Exception("DATABASE_URL environment variable not set")
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
        print("✅ PostgreSQL пул соединений создан")
    return db_pool

async def close_db_pool():
    """Закрывает пул соединений."""
    global db_pool
    if db_pool:
        await db_pool.close()
        db_pool = None
        print("✅ PostgreSQL пул соединений закрыт")

async def execute_query(query: str, *args, fetch_one: bool = False, fetch_all: bool = False, fetch_val: bool = False):
    """Выполняет SQL запрос с автоматическим получением пула."""
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        if fetch_one:
            return await conn.fetchrow(query, *args)
        elif fetch_all:
            return await conn.fetch(query, *args)
        elif fetch_val:
            row = await conn.fetchrow(query, *args)
            return row[0] if row else None
        else:
            return await conn.execute(query, *args)

async def execute_with_retry(func, *args, max_attempts=5, base_delay=0.5):
    """Выполняет функцию с повторными попытками при ошибках."""
    for attempt in range(max_attempts):
        try:
            return await func(*args)
        except Exception as e:
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                print(f"⚠️ Ошибка БД: {e}, повтор через {delay:.2f} сек...")
                await asyncio.sleep(delay)
            else:
                raise

# ========== СОЗДАНИЕ ТАБЛИЦ ==========
async def create_db():
    """Создаёт все необходимые таблицы в PostgreSQL."""
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                bonus_total INTEGER DEFAULT 0,
                total_games INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                last_active INTEGER DEFAULT 0,
                invited_by BIGINT DEFAULT NULL,
                referral_bonus_claimed INTEGER DEFAULT 0,
                friend_played INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                theme TEXT DEFAULT 'classic',
                daily_bonus_last INTEGER DEFAULT 0,
                daily_bonus_streak INTEGER DEFAULT 0,
                tournament_score INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())::INTEGER,
                agreed INTEGER DEFAULT 0,
                has_started INTEGER DEFAULT 0,
                referral_count INTEGER DEFAULT 0,
                referral_earnings INTEGER DEFAULT 0,
                current_win_streak INTEGER DEFAULT 0,
                max_win_streak INTEGER DEFAULT 0,
                withdrawals_count INTEGER DEFAULT 0,
                demo_games_played INTEGER DEFAULT 0,
                bonus_balance INTEGER DEFAULT 0,
                bonus_wagered INTEGER DEFAULT 0,
                last_cashback INTEGER DEFAULT 0,
                first_deposit_bonus_claimed INTEGER DEFAULT 0
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                achievement_id TEXT NOT NULL,
                achieved_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())::INTEGER,
                UNIQUE(user_id, achievement_id)
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tournaments (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                prize_points INTEGER NOT NULL,
                start_time INTEGER NOT NULL,
                end_time INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                winner_id BIGINT DEFAULT NULL,
                winner_username TEXT DEFAULT NULL,
                winner_notified INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())::INTEGER
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tournament_participants (
                tournament_id INTEGER NOT NULL,
                user_id BIGINT NOT NULL,
                score INTEGER DEFAULT 0,
                registered INTEGER DEFAULT 0,
                last_update INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())::INTEGER,
                PRIMARY KEY (tournament_id, user_id)
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS crypto_transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount_rub INTEGER NOT NULL,
                amount_points INTEGER NOT NULL,
                payment_id TEXT UNIQUE NOT NULL,
                invoice_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())::INTEGER,
                confirmed_at INTEGER
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount_points INTEGER NOT NULL,
                amount_usdt REAL NOT NULL,
                wallet_address TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())::INTEGER,
                completed_at INTEGER,
                admin_comment TEXT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agreements (
                user_id BIGINT PRIMARY KEY,
                agreed_at INTEGER NOT NULL,
                ip_address TEXT,
                user_agent TEXT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS deposits (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount INTEGER NOT NULL,
                created_at INTEGER DEFAULT EXTRACT(EPOCH FROM NOW())::INTEGER
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                multiplier REAL DEFAULT 1.0,
                start_date INTEGER NOT NULL,
                end_date INTEGER NOT NULL,
                active INTEGER DEFAULT 1
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS game_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                game_type TEXT NOT NULL,
                bet_amount INTEGER NOT NULL,
                win_amount INTEGER DEFAULT 0,
                played_at INTEGER NOT NULL
            )
        ''')
        
        print("✅ Таблицы PostgreSQL созданы / проверены.")

# ========== ОСНОВНЫЕ ФУНКЦИИ ==========
async def get_user(user_id: int, username: str = None, initial_balance: int = 0) -> Tuple:
    async def _get_user():
        row = await execute_query(
            "SELECT balance, total_games, wins, level, exp, theme, daily_bonus_last, "
            "daily_bonus_streak, tournament_score, agreed, has_started, referral_count, "
            "referral_earnings, current_win_streak, max_win_streak, withdrawals_count "
            "FROM users WHERE user_id = $1",
            user_id, fetch_one=True
        )
        
        if row:
            await execute_query(
                "UPDATE users SET last_active = $1 WHERE user_id = $2",
                int(time.time()), user_id
            )
            return tuple(row)
        
        await execute_query(
            "INSERT INTO users (user_id, username, balance, last_active, agreed, has_started) "
            "VALUES ($1, $2, $3, $4, 0, 0)",
            user_id, username, initial_balance, int(time.time())
        )
        return (initial_balance, 0, 0, 1, 0, 'classic', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    
    return await execute_with_retry(_get_user)

async def get_bonus_total(user_id: int) -> int:
    val = await execute_query("SELECT bonus_total FROM users WHERE user_id = $1", user_id, fetch_val=True)
    return val if val else 0

async def claim_daily_bonus(user_id: int) -> Tuple[bool, int]:
    async def _claim():
        now = int(time.time())
        today_start = now - (now % 86400)
        result = await execute_query(
            "UPDATE users SET balance = balance + 20, bonus_total = bonus_total + 20, "
            "bonus_balance = bonus_balance + 20, "
            "daily_bonus_last = $1, daily_bonus_streak = daily_bonus_streak + 1 "
            "WHERE user_id = $2 AND daily_bonus_last < $3",
            now, user_id, today_start
        )
        if result and 'UPDATE 1' in result:
            new_balance = await execute_query("SELECT balance FROM users WHERE user_id = $1", user_id, fetch_val=True)
            return True, new_balance
        else:
            balance = await execute_query("SELECT balance FROM users WHERE user_id = $1", user_id, fetch_val=True)
            return False, balance
    return await execute_with_retry(_claim)

async def update_balance(user_id: int, new_balance: int):
    await execute_query("UPDATE users SET balance = $1, last_active = $2 WHERE user_id = $3", new_balance, int(time.time()), user_id)

async def update_stats(user_id: int, win: bool) -> bool:
    async def _update():
        row = await execute_query(
            "SELECT exp, level, total_games, wins, current_win_streak, max_win_streak FROM users WHERE user_id = $1",
            user_id, fetch_one=True
        )
        exp, level, total_games, wins, current_streak, max_streak = row
        exp_gain = 10 + (5 if win else 0)
        new_exp = exp + exp_gain
        level_up = False
        while new_exp >= level * 100:
            new_exp -= level * 100
            level += 1
            level_up = True
        if win:
            new_streak = current_streak + 1
            new_max_streak = max(new_streak, max_streak)
            await execute_query(
                "UPDATE users SET total_games = total_games + 1, wins = wins + 1, exp = $1, level = $2, "
                "last_active = $3, current_win_streak = $4, max_win_streak = $5 WHERE user_id = $6",
                new_exp, level, int(time.time()), new_streak, new_max_streak, user_id
            )
        else:
            new_streak = 0
            await execute_query(
                "UPDATE users SET total_games = total_games + 1, exp = $1, level = $2, last_active = $3, "
                "current_win_streak = $4 WHERE user_id = $5",
                new_exp, level, int(time.time()), new_streak, user_id
            )
        return level_up
    return await execute_with_retry(_update)

async def get_user_stats(user_id: int) -> Optional[Tuple[int, int, int]]:
    row = await execute_query("SELECT balance, total_games, wins FROM users WHERE user_id = $1", user_id, fetch_one=True)
    return tuple(row) if row else None

async def get_all_users(offset=0, limit=5, active_days=30) -> List[tuple]:
    if active_days == 0:
        rows = await execute_query(
            "SELECT user_id, username, balance, total_games FROM users ORDER BY user_id LIMIT $1 OFFSET $2",
            limit, offset, fetch_all=True
        )
    else:
        threshold = int(time.time()) - active_days * 86400
        rows = await execute_query(
            "SELECT user_id, username, balance, total_games FROM users WHERE last_active > $1 ORDER BY user_id LIMIT $2 OFFSET $3",
            threshold, limit, offset, fetch_all=True
        )
    return [tuple(row) for row in rows] if rows else []

async def get_users_count(active_days=30) -> int:
    if active_days == 0:
        val = await execute_query("SELECT COUNT(*) FROM users", fetch_val=True)
    else:
        threshold = int(time.time()) - active_days * 86400
        val = await execute_query("SELECT COUNT(*) FROM users WHERE last_active > $1", threshold, fetch_val=True)
    return val if val else 0

async def set_user_agreed(user_id: int):
    await execute_query("UPDATE users SET agreed = 1 WHERE user_id = $1", user_id)

async def is_user_agreed(user_id: int) -> bool:
    val = await execute_query("SELECT agreed FROM users WHERE user_id = $1", user_id, fetch_val=True)
    return val == 1 if val else False

async def set_user_started(user_id: int):
    await execute_query("UPDATE users SET has_started = 1 WHERE user_id = $1", user_id)

async def increment_referral_count(inviter_id: int):
    await execute_query("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = $1", inviter_id)

async def add_referral_earnings(inviter_id: int, amount: int):
    await execute_query("UPDATE users SET referral_earnings = referral_earnings + $1 WHERE user_id = $2", amount, inviter_id)

async def increment_withdrawals_count(user_id: int):
    await execute_query("UPDATE users SET withdrawals_count = withdrawals_count + 1 WHERE user_id = $1", user_id)

async def check_referral_bonus(user_id: int, bot):
    async def _check():
        row = await execute_query(
            "SELECT invited_by FROM users WHERE user_id = $1 AND friend_played = 0",
            user_id, fetch_one=True
        )
        if row and row['invited_by'] is not None:
            invited_by = row['invited_by']
            await execute_query("UPDATE users SET friend_played = 1 WHERE user_id = $1", user_id)
            await execute_query(
                "UPDATE users SET balance = balance + 30, bonus_total = bonus_total + 30, "
                "bonus_balance = bonus_balance + 30 WHERE user_id IN ($1, $2)",
                user_id, invited_by
            )
            try:
                await bot.send_message(user_id, "🎉 Поздравляем! Вы сыграли первую игру и получили 30 бонусных баллов!")
                await bot.send_message(invited_by, "🎉 Ваш друг сыграл первую игру! Вы получаете 30 бонусных баллов!")
            except Exception:
                pass
    await execute_with_retry(_check)

async def get_active_tournament() -> Optional[Tuple[int, str, int, int]]:
    now = int(time.time())
    row = await execute_query(
        "SELECT id, name, prize_points, end_time FROM tournaments WHERE status = 'active' AND start_time <= $1 AND end_time > $1",
        now, fetch_one=True
    )
    if row:
        return tuple(row) if row else None
    
    row = await execute_query(
        "SELECT id, name, prize_points, end_time FROM tournaments WHERE status = 'pending' AND start_time <= $1",
        now, fetch_one=True
    )
    if row:
        await execute_query("UPDATE tournaments SET status = 'active' WHERE id = $1", row[0])
        return (row[0], row[1], row[2], row[3])
    
    return None

async def get_tournament_leaders(tournament_id: int, limit=10) -> List[tuple]:
    rows = await execute_query(
        "SELECT tp.user_id, u.username, tp.score FROM tournament_participants tp "
        "JOIN users u ON tp.user_id = u.user_id "
        "WHERE tp.tournament_id = $1 ORDER BY tp.score DESC LIMIT $2",
        tournament_id, limit, fetch_all=True
    )
    return [tuple(row) for row in rows] if rows else []

async def register_for_tournament(user_id: int, tournament_id: int):
    await execute_query(
        "INSERT INTO tournament_participants (tournament_id, user_id, registered) VALUES ($1, $2, 1) "
        "ON CONFLICT (tournament_id, user_id) DO UPDATE SET registered = 1",
        tournament_id, user_id
    )

async def is_registered_for_tournament(user_id: int, tournament_id: int) -> bool:
    val = await execute_query(
        "SELECT registered FROM tournament_participants WHERE tournament_id = $1 AND user_id = $2",
        tournament_id, user_id, fetch_val=True
    )
    return val == 1 if val else False

async def get_user_tournaments(user_id: int, offset: int = 0, limit: int = 5) -> List[tuple]:
    rows = await execute_query(
        "SELECT t.id, t.name, t.prize_points, t.start_time, t.end_time, tp.score, t.winner_id, t.winner_username "
        "FROM tournaments t JOIN tournament_participants tp ON t.id = tp.tournament_id "
        "WHERE tp.user_id = $1 ORDER BY t.start_time DESC LIMIT $2 OFFSET $3",
        user_id, limit, offset, fetch_all=True
    )
    return [tuple(row) for row in rows] if rows else []

async def count_user_tournaments(user_id: int) -> int:
    val = await execute_query("SELECT COUNT(*) FROM tournament_participants WHERE user_id = $1", user_id, fetch_val=True)
    return val if val else 0

async def update_tournament_score(user_id: int, score_gain: int):
    now = int(time.time())
    row = await execute_query(
        "SELECT id FROM tournaments WHERE status = 'active' AND start_time <= $1 AND end_time > $1",
        now, fetch_one=True
    )
    if row:
        tournament_id = row[0]
        await execute_query(
            "INSERT INTO tournament_participants (tournament_id, user_id, score) VALUES ($1, $2, $3) "
            "ON CONFLICT (tournament_id, user_id) DO UPDATE SET score = score + $3, last_update = $4",
            tournament_id, user_id, score_gain, now
        )

async def finish_tournament(tournament_id: int, bot):
    async def _finish():
        async with (await init_db_pool()).acquire() as conn:
            async with conn.transaction():
                tournament = await conn.fetchrow(
                    "SELECT name, prize_points, winner_id FROM tournaments WHERE id = $1 AND status = 'active'",
                    tournament_id
                )
                if not tournament or tournament['winner_id'] is not None:
                    return
                
                participants = await conn.fetch(
                    "SELECT tp.user_id, u.username, tp.score FROM tournament_participants tp "
                    "JOIN users u ON tp.user_id = u.user_id WHERE tp.tournament_id = $1 ORDER BY tp.score DESC",
                    tournament_id
                )
                if not participants:
                    await conn.execute("UPDATE tournaments SET status = 'finished' WHERE id = $1", tournament_id)
                    return
                
                max_score = participants[0]['score']
                top_users = [p for p in participants if p['score'] == max_score]
                winner = random.choice(top_users)
                winner_id, winner_username = winner['user_id'], winner['username']
                
                await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2", tournament['prize_points'], winner_id)
                await conn.execute(
                    "UPDATE tournaments SET status = 'finished', winner_id = $1, winner_username = $2 WHERE id = $3",
                    winner_id, winner_username, tournament_id
                )
        
        try:
            await bot.send_message(winner_id, f"🏆 Поздравляем! Вы выиграли турнир «{tournament['name']}» и получили {tournament['prize_points']} 💎!")
            from config import ADMIN_IDS
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"🏆 Турнир «{tournament['name']}» завершён. Победитель: {winner_username} (ID {winner_id}) – {tournament['prize_points']} 💎.")
        except Exception as e:
            print(f"Ошибка при отправке уведомления: {e}")
    await execute_with_retry(_finish)

async def add_deposit(user_id: int, amount: int):
    await execute_query("INSERT INTO deposits (user_id, amount) VALUES ($1, $2)", user_id, amount)

async def get_event_multiplier() -> float:
    now = int(time.time())
    val = await execute_query(
        "SELECT multiplier FROM events WHERE active = 1 AND start_date <= $1 AND end_date > $1",
        now, fetch_val=True
    )
    return val if val else 1.0

async def log_agreement(user_id: int, ip_address: str = None, user_agent: str = None):
    async with (await init_db_pool()).acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO agreements (user_id, agreed_at, ip_address, user_agent) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (user_id) DO UPDATE SET agreed_at = $2, ip_address = $3, user_agent = $4",
                user_id, int(time.time()), ip_address, user_agent
            )
            await conn.execute("UPDATE users SET agreed = 1 WHERE user_id = $1", user_id)

async def check_agreement(user_id: int) -> bool:
    return await is_user_agreed(user_id)

async def get_bot_stats() -> dict:
    first_date = await execute_query("SELECT MIN(created_at) FROM users", fetch_val=True)
    first_date = first_date if first_date else int(time.time())
    days = (int(time.time()) - first_date) // 86400
    total_users = await execute_query("SELECT COUNT(*) FROM users", fetch_val=True) or 0
    now = time.time()
    today_start = int(now - (now % 86400))
    new_today = await execute_query("SELECT COUNT(*) FROM users WHERE created_at >= $1", today_start, fetch_val=True) or 0
    total_games = await execute_query("SELECT SUM(total_games) FROM users", fetch_val=True) or 0
    total_paid = await execute_query("SELECT SUM(amount_points) FROM withdraw_requests WHERE status='completed'", fetch_val=True) or 0
    return {"days": days, "total_users": total_users, "new_today": new_today, "total_games": total_games, "total_paid": total_paid}

# ===== Крипто-транзакции =====
async def create_crypto_transaction(user_id: int, amount_rub: int, amount_points: int, payment_id: str, invoice_id: str):
    await execute_query(
        "INSERT INTO crypto_transactions (user_id, amount_rub, amount_points, payment_id, invoice_id) VALUES ($1, $2, $3, $4, $5)",
        user_id, amount_rub, amount_points, payment_id, invoice_id
    )

async def get_crypto_transaction(payment_id: str) -> Optional[Tuple[int, str]]:
    row = await execute_query(
        "SELECT amount_points, status FROM crypto_transactions WHERE payment_id = $1",
        payment_id, fetch_one=True
    )
    return (row[0], row[1]) if row else None

async def get_crypto_transaction_full(payment_id: str) -> Optional[Tuple[int, str, str]]:
    row = await execute_query(
        "SELECT amount_points, status, invoice_id FROM crypto_transactions WHERE payment_id = $1",
        payment_id, fetch_one=True
    )
    return (row[0], row[1], row[2]) if row else None

async def update_crypto_transaction_status(payment_id: str, status: str, confirmed_at: int = None):
    if status == 'paid':
        result = await execute_query(
            "UPDATE crypto_transactions SET status = $1, confirmed_at = $2 WHERE payment_id = $3 AND status = 'pending'",
            status, confirmed_at or int(time.time()), payment_id
        )
        return 'UPDATE 1' in result
    else:
        await execute_query("UPDATE crypto_transactions SET status = $1 WHERE payment_id = $2", status, payment_id)
        return True

# ===== Заявки на вывод =====
async def create_withdraw_request(user_id: int, amount_points: int, amount_usdt: float, wallet_address: str):
    await execute_query(
        "INSERT INTO withdraw_requests (user_id, amount_points, amount_usdt, wallet_address, status) VALUES ($1, $2, $3, $4, 'pending')",
        user_id, amount_points, amount_usdt, wallet_address
    )

async def get_pending_withdraw_requests() -> List[tuple]:
    rows = await execute_query(
        "SELECT id, user_id, amount_points, amount_usdt, wallet_address FROM withdraw_requests WHERE status = 'pending' ORDER BY created_at ASC",
        fetch_all=True
    )
    return [tuple(row) for row in rows] if rows else []

async def get_all_withdraw_requests(offset: int = 0, limit: int = 5) -> List[tuple]:
    rows = await execute_query(
        "SELECT id, user_id, amount_points, amount_usdt, wallet_address, status, created_at, completed_at "
        "FROM withdraw_requests ORDER BY created_at DESC LIMIT $1 OFFSET $2",
        limit, offset, fetch_all=True
    )
    return [tuple(row) for row in rows] if rows else []

async def count_withdraw_requests(status: str = None) -> int:
    if status:
        val = await execute_query("SELECT COUNT(*) FROM withdraw_requests WHERE status = $1", status, fetch_val=True)
    else:
        val = await execute_query("SELECT COUNT(*) FROM withdraw_requests", fetch_val=True)
    return val if val else 0

async def update_withdraw_request_status(request_id: int, status: str, completed_at: int = None):
    if status == 'completed':
        await execute_query(
            "UPDATE withdraw_requests SET status = $1, completed_at = $2 WHERE id = $3",
            status, completed_at or int(time.time()), request_id
        )
    else:
        await execute_query("UPDATE withdraw_requests SET status = $1 WHERE id = $2", status, request_id)

# ===== Статистика =====
async def get_withdraw_stats() -> dict:
    total_requests = await execute_query("SELECT COUNT(*) FROM withdraw_requests", fetch_val=True) or 0
    completed_requests = await execute_query("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'completed'", fetch_val=True) or 0
    rejected_requests = await execute_query("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'rejected'", fetch_val=True) or 0
    pending_requests = await execute_query("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'pending'", fetch_val=True) or 0
    completed_amount = await execute_query("SELECT COALESCE(SUM(amount_points), 0) FROM withdraw_requests WHERE status = 'completed'", fetch_val=True) or 0
    completed_amount_usdt = await execute_query("SELECT COALESCE(SUM(amount_usdt), 0) FROM withdraw_requests WHERE status = 'completed'", fetch_val=True) or 0
    avg_processing_time = await execute_query(
        "SELECT AVG(completed_at - created_at) / 3600.0 FROM withdraw_requests WHERE status = 'completed' AND completed_at IS NOT NULL",
        fetch_val=True
    ) or 0
    return {
        "total_requests": total_requests,
        "completed_requests": completed_requests,
        "rejected_requests": rejected_requests,
        "pending_requests": pending_requests,
        "completed_amount": completed_amount,
        "completed_amount_usdt": completed_amount_usdt,
        "completed_amount_rub": round(completed_amount_usdt * 90, 2),
        "avg_processing_time": avg_processing_time
    }

async def get_deposit_stats() -> dict:
    total_deposits = await execute_query("SELECT COUNT(*) FROM crypto_transactions", fetch_val=True) or 0
    successful = await execute_query("SELECT COUNT(*) FROM crypto_transactions WHERE status = 'paid'", fetch_val=True) or 0
    pending = await execute_query("SELECT COUNT(*) FROM crypto_transactions WHERE status = 'pending'", fetch_val=True) or 0
    failed = await execute_query("SELECT COUNT(*) FROM crypto_transactions WHERE status = 'failed'", fetch_val=True) or 0
    total_amount = await execute_query("SELECT COALESCE(SUM(amount_points), 0) FROM crypto_transactions WHERE status = 'paid'", fetch_val=True) or 0
    avg_amount = await execute_query("SELECT COALESCE(AVG(amount_points), 0) FROM crypto_transactions WHERE status = 'paid'", fetch_val=True) or 0
    max_amount = await execute_query("SELECT COALESCE(MAX(amount_points), 0) FROM crypto_transactions WHERE status = 'paid'", fetch_val=True) or 0
    return {
        "total_deposits": total_deposits,
        "successful": successful,
        "pending": pending,
        "failed": failed,
        "total_amount": total_amount,
        "total_amount_rub": round(total_amount / 1.5, 2),
        "total_amount_usdt": round(total_amount / 1.5 / 90, 2),
        "avg_amount": avg_amount,
        "max_amount": max_amount
    }

async def get_user_withdraw_stats(user_id: int) -> dict:
    count = await execute_query("SELECT COUNT(*) FROM withdraw_requests WHERE user_id = $1", user_id, fetch_val=True) or 0
    total = await execute_query("SELECT COALESCE(SUM(amount_points), 0) FROM withdraw_requests WHERE user_id = $1", user_id, fetch_val=True) or 0
    completed = await execute_query("SELECT COUNT(*) FROM withdraw_requests WHERE user_id = $1 AND status = 'completed'", user_id, fetch_val=True) or 0
    completed_amount = await execute_query("SELECT COALESCE(SUM(amount_points), 0) FROM withdraw_requests WHERE user_id = $1 AND status = 'completed'", user_id, fetch_val=True) or 0
    pending = await execute_query("SELECT COUNT(*) FROM withdraw_requests WHERE user_id = $1 AND status = 'pending'", user_id, fetch_val=True) or 0
    return {
        "count": count,
        "total": total,
        "completed": completed,
        "completed_amount": completed_amount,
        "pending": pending
    }

async def get_user_deposit_stats(user_id: int) -> dict:
    count = await execute_query("SELECT COUNT(*) FROM crypto_transactions WHERE user_id = $1 AND status = 'paid'", user_id, fetch_val=True) or 0
    total = await execute_query("SELECT COALESCE(SUM(amount_points), 0) FROM crypto_transactions WHERE user_id = $1 AND status = 'paid'", user_id, fetch_val=True) or 0
    avg = await execute_query("SELECT COALESCE(AVG(amount_points), 0) FROM crypto_transactions WHERE user_id = $1 AND status = 'paid'", user_id, fetch_val=True) or 0
    max_val = await execute_query("SELECT COALESCE(MAX(amount_points), 0) FROM crypto_transactions WHERE user_id = $1 AND status = 'paid'", user_id, fetch_val=True) or 0
    return {"count": count, "total": total, "avg": avg, "max": max_val}

# ===== Демо-режим =====
async def get_demo_games_played(user_id: int) -> int:
    val = await execute_query("SELECT demo_games_played FROM users WHERE user_id = $1", user_id, fetch_val=True)
    return val if val else 0

async def increment_demo_games_played(user_id: int) -> bool:
    result = await execute_query(
        "UPDATE users SET demo_games_played = demo_games_played + 1 WHERE user_id = $1 AND demo_games_played < 5",
        user_id
    )
    return 'UPDATE 1' in result

async def reset_demo_games_played(user_id: int):
    await execute_query("UPDATE users SET demo_games_played = 0 WHERE user_id = $1", user_id)

# ===== Защитные механизмы =====
async def get_daily_withdrawn(user_id: int) -> int:
    today_start = int(time.time()) - (int(time.time()) % 86400)
    val = await execute_query(
        "SELECT COALESCE(SUM(amount_points), 0) FROM withdraw_requests "
        "WHERE user_id = $1 AND status='completed' AND completed_at >= $2",
        user_id, today_start, fetch_val=True
    )
    return val if val else 0

async def get_last_deposit_time(user_id: int) -> int:
    val = await execute_query("SELECT MAX(created_at) FROM deposits WHERE user_id = $1", user_id, fetch_val=True)
    return val if val else 0

async def get_pending_withdraw_count(user_id: int) -> int:
    val = await execute_query("SELECT COUNT(*) FROM withdraw_requests WHERE user_id = $1 AND status = 'pending'", user_id, fetch_val=True)
    return val if val else 0

async def get_daily_total_withdrawn_rub() -> float:
    today_start = int(time.time()) - (int(time.time()) % 86400)
    usdt_total = await execute_query(
        "SELECT COALESCE(SUM(amount_usdt), 0) FROM withdraw_requests WHERE status='pending' AND created_at >= $1",
        today_start, fetch_val=True
    ) or 0
    from config import USD_RATE
    return usdt_total * USD_RATE

async def update_bonus_wagered(user_id: int, bet_amount: int, win: bool):
    await execute_query("UPDATE users SET bonus_wagered = bonus_wagered + $1 WHERE user_id = $2", bet_amount, user_id)

async def get_bonus_wagering_status(user_id: int) -> Tuple[int, int, bool]:
    row = await execute_query("SELECT bonus_balance, bonus_wagered FROM users WHERE user_id = $1", user_id, fetch_one=True)
    if not row:
        return 0, 0, True
    bonus_balance, bonus_wagered = row[0], row[1]
    required_wagered = bonus_balance * BONUS_WAGER_MULTIPLIER
    is_cleared = bonus_balance == 0 or bonus_wagered >= required_wagered
    return bonus_balance, bonus_wagered, is_cleared

# ===== Кэшбек =====
async def get_weekly_losses(user_id: int) -> int:
    week_ago = int(time.time()) - 7 * 86400
    val = await execute_query(
        "SELECT COALESCE(SUM(bet_amount - win_amount), 0) FROM game_history "
        "WHERE user_id = $1 AND played_at >= $2 AND bet_amount > win_amount",
        user_id, week_ago, fetch_val=True
    )
    return val if val else 0

async def add_cashback(user_id: int, amount: int):
    await execute_query(
        "UPDATE users SET balance = balance + $1, bonus_total = bonus_total + $1, "
        "bonus_balance = bonus_balance + $1 WHERE user_id = $2",
        amount, user_id
    )

async def get_last_cashback_time(user_id: int) -> int:
    val = await execute_query("SELECT last_cashback FROM users WHERE user_id = $1", user_id, fetch_val=True)
    return val if val else 0

async def set_last_cashback_time(user_id: int, timestamp: int):
    await execute_query("UPDATE users SET last_cashback = $1 WHERE user_id = $2", timestamp, user_id)

async def save_game_history(user_id: int, bet: int, win: int, game_type: str):
    await execute_query(
        "INSERT INTO game_history (user_id, game_type, bet_amount, win_amount, played_at) "
        "VALUES ($1, $2, $3, $4, $5)",
        user_id, game_type, bet, win if win > 0 else 0, int(time.time())
    )
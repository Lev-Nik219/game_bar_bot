import asyncio
import random
import time
import asyncpg
import os
from typing import Optional, Tuple, List, Any

DB_URL = os.getenv('DATABASE_URL', 'postgresql://localhost/casino')
_pool = None

async def init_db_pool():
    """Инициализирует пул соединений (глобально)."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=10)
    return _pool

async def close_db_pool():
    """Закрывает пул (вызывать при завершении бота)."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None

async def execute_with_retry(func, *args, max_attempts=20, base_delay=0.1):
    """Повторяет попытки при временных ошибках БД."""
    for attempt in range(max_attempts):
        try:
            return await func(*args)
        except (asyncpg.exceptions.ConnectionDoesNotExistError,
                asyncpg.exceptions.TooManyConnectionsError,
                asyncpg.exceptions.InterfaceError,
                ConnectionError) as e:
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                print(f"⚠️ Ошибка БД ({e}), повтор через {delay:.2f} сек...")
                await asyncio.sleep(delay)
            else:
                raise
        except Exception as e:
            raise

# ---- Создание таблиц ----
async def create_db():
    """Создаёт таблицы (вызывается при старте)."""
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        # Таблица users
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                bonus_total INTEGER DEFAULT 0,
                total_games INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                last_active BIGINT DEFAULT 0,
                invited_by BIGINT DEFAULT NULL,
                referral_bonus_claimed INTEGER DEFAULT 0,
                friend_played INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                theme TEXT DEFAULT 'classic',
                daily_bonus_last BIGINT DEFAULT 0,
                daily_bonus_streak INTEGER DEFAULT 0,
                tournament_score INTEGER DEFAULT 0,
                created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                agreed INTEGER DEFAULT 0,
                has_started INTEGER DEFAULT 0,
                referral_count INTEGER DEFAULT 0,
                referral_earnings INTEGER DEFAULT 0,
                current_win_streak INTEGER DEFAULT 0,
                max_win_streak INTEGER DEFAULT 0,
                withdrawals_count INTEGER DEFAULT 0
            )
        ''')
        # Достижения
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                achievement_id TEXT NOT NULL,
                achieved_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                UNIQUE(user_id, achievement_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        # Турниры
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tournaments (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                prize_points INTEGER NOT NULL,
                start_time BIGINT NOT NULL,
                end_time BIGINT NOT NULL,
                status TEXT DEFAULT 'pending',
                winner_id BIGINT DEFAULT NULL,
                winner_username TEXT DEFAULT NULL,
                winner_notified INTEGER DEFAULT 0,
                created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())
            )
        ''')
        # Участники турниров
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS tournament_participants (
                tournament_id INTEGER NOT NULL,
                user_id BIGINT NOT NULL,
                score INTEGER DEFAULT 0,
                registered INTEGER DEFAULT 0,
                last_update BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                PRIMARY KEY (tournament_id, user_id),
                FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        # Крипто-транзакции
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS crypto_transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount_rub INTEGER NOT NULL,
                amount_points INTEGER NOT NULL,
                payment_id TEXT UNIQUE NOT NULL,
                invoice_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                confirmed_at BIGINT,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        # Заявки на вывод
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount_points INTEGER NOT NULL,
                amount_usdt REAL NOT NULL,
                wallet_address TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                completed_at BIGINT,
                admin_comment TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        # Таблица согласий
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS agreements (
                user_id BIGINT PRIMARY KEY,
                agreed_at BIGINT NOT NULL,
                ip_address TEXT,
                user_agent TEXT
            )
        ''')
        # Депозиты
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS deposits (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount INTEGER NOT NULL,
                created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        # События (множители)
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                multiplier REAL DEFAULT 1.0,
                start_date BIGINT NOT NULL,
                end_date BIGINT NOT NULL,
                active INTEGER DEFAULT 1
            )
        ''')
        # Уведомления
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                message TEXT NOT NULL,
                created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                read INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        # Розыгрыши
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS giveaways (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                prize INTEGER NOT NULL,
                start_time BIGINT NOT NULL,
                end_time BIGINT NOT NULL,
                max_winners INTEGER DEFAULT 1,
                status TEXT DEFAULT 'pending',
                created_by BIGINT,
                created_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())
            )
        ''')
        # Участники розыгрышей
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS giveaway_participants (
                giveaway_id INTEGER NOT NULL,
                user_id BIGINT NOT NULL,
                joined_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                PRIMARY KEY (giveaway_id, user_id),
                FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        # Партнёры
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS partners (
                user_id BIGINT PRIMARY KEY,
                referral_link TEXT UNIQUE,
                commission_rate REAL DEFAULT 0.10,
                total_earned INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        # Реферальные уровни
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS referral_levels (
                user_id BIGINT PRIMARY KEY,
                level INTEGER DEFAULT 1,
                commission_rate REAL DEFAULT 0.05,
                total_earned INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        # Чат с администратором
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS admin_chats (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                admin_id BIGINT NOT NULL,
                last_message_time BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                UNIQUE(user_id, admin_id)
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS admin_messages (
                id SERIAL PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                from_user BIGINT NOT NULL,
                message TEXT,
                is_reply INTEGER DEFAULT 0,
                timestamp BIGINT DEFAULT EXTRACT(EPOCH FROM NOW()),
                FOREIGN KEY (chat_id) REFERENCES admin_chats(id) ON DELETE CASCADE
            )
        ''')
    print("✅ Таблицы созданы / проверены.")

# ---- Основные функции работы с пользователями ----
async def get_user(user_id: int, username: str = None, initial_balance: int = 0) -> Tuple:
    async def _get_user():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT balance, total_games, wins, level, exp, theme, daily_bonus_last, "
                "daily_bonus_streak, tournament_score, agreed, has_started, referral_count, "
                "referral_earnings, current_win_streak, max_win_streak, withdrawals_count "
                "FROM users WHERE user_id = $1",
                user_id
            )
            if row:
                await conn.execute(
                    "UPDATE users SET last_active = $1 WHERE user_id = $2",
                    int(time.time()), user_id
                )
                return tuple(row)
            # Новый пользователь
            await conn.execute(
                "INSERT INTO users (user_id, username, balance, last_active, agreed, has_started) "
                "VALUES ($1, $2, $3, $4, 0, 0)",
                user_id, username, initial_balance, int(time.time())
            )
            return (initial_balance, 0, 0, 1, 0, 'classic', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    return await execute_with_retry(_get_user)

async def get_bonus_total(user_id: int) -> int:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT bonus_total FROM users WHERE user_id = $1", user_id)
            return row[0] if row else 0
    return await execute_with_retry(_get)

async def claim_daily_bonus(user_id: int) -> Tuple[bool, int]:
    async def _claim():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT daily_bonus_last, balance, bonus_total, daily_bonus_streak "
                "FROM users WHERE user_id = $1",
                user_id
            )
            if not row:
                return False, 0
            last_bonus, balance, bonus_total, streak = row
            now = int(time.time())
            today_start = now - (now % 86400)
            if last_bonus >= today_start:
                return False, balance
            new_balance = balance + 20
            new_bonus_total = bonus_total + 20
            new_streak = streak + 1
            await conn.execute(
                "UPDATE users SET balance = $1, bonus_total = $2, daily_bonus_last = $3, daily_bonus_streak = $4 "
                "WHERE user_id = $5",
                new_balance, new_bonus_total, now, new_streak, user_id
            )
            return True, new_balance
    return await execute_with_retry(_claim)

async def update_balance(user_id: int, new_balance: int):
    async def _update():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET balance = $1, last_active = $2 WHERE user_id = $3",
                new_balance, int(time.time()), user_id
            )
    await execute_with_retry(_update)

async def update_stats(user_id: int, win: bool) -> bool:
    async def _update():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT exp, level, total_games, wins, current_win_streak, max_win_streak "
                "FROM users WHERE user_id = $1",
                user_id
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
                await conn.execute(
                    "UPDATE users SET total_games = total_games + 1, wins = wins + 1, exp = $1, level = $2, "
                    "last_active = $3, current_win_streak = $4, max_win_streak = $5 WHERE user_id = $6",
                    new_exp, level, int(time.time()), new_streak, new_max_streak, user_id
                )
            else:
                new_streak = 0
                await conn.execute(
                    "UPDATE users SET total_games = total_games + 1, exp = $1, level = $2, last_active = $3, "
                    "current_win_streak = $4 WHERE user_id = $5",
                    new_exp, level, int(time.time()), new_streak, user_id
                )
            return level_up
    return await execute_with_retry(_update)

async def get_user_stats(user_id: int) -> Optional[Tuple[int, int, int]]:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT balance, total_games, wins FROM users WHERE user_id = $1",
                user_id
            )
    return await execute_with_retry(_get)

async def get_all_users(offset=0, limit=5, active_days=30) -> List[tuple]:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            if active_days == 0:
                return await conn.fetch(
                    "SELECT user_id, username, balance, total_games FROM users "
                    "ORDER BY user_id LIMIT $1 OFFSET $2",
                    limit, offset
                )
            else:
                threshold = int(time.time()) - active_days * 86400
                return await conn.fetch(
                    "SELECT user_id, username, balance, total_games FROM users "
                    "WHERE last_active > $1 ORDER BY user_id LIMIT $2 OFFSET $3",
                    threshold, limit, offset
                )
    return await execute_with_retry(_get)

async def get_users_count(active_days=30) -> int:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            if active_days == 0:
                row = await conn.fetchrow("SELECT COUNT(*) FROM users")
            else:
                threshold = int(time.time()) - active_days * 86400
                row = await conn.fetchrow("SELECT COUNT(*) FROM users WHERE last_active > $1", threshold)
            return row[0] if row else 0
    return await execute_with_retry(_get)

async def set_user_agreed(user_id: int):
    async def _set():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET agreed = 1 WHERE user_id = $1", user_id)
    await execute_with_retry(_set)

async def is_user_agreed(user_id: int) -> bool:
    async def _is():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT agreed FROM users WHERE user_id = $1", user_id)
            return row and row[0] == 1
    return await execute_with_retry(_is)

async def set_user_started(user_id: int):
    async def _set():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE users SET has_started = 1 WHERE user_id = $1", user_id)
    await execute_with_retry(_set)

async def increment_referral_count(inviter_id: int):
    async def _inc():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET referral_count = referral_count + 1 WHERE user_id = $1",
                inviter_id
            )
    await execute_with_retry(_inc)

async def add_referral_earnings(inviter_id: int, amount: int):
    async def _add():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET referral_earnings = referral_earnings + $1 WHERE user_id = $2",
                amount, inviter_id
            )
    await execute_with_retry(_add)

async def increment_withdrawals_count(user_id: int):
    async def _inc():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET withdrawals_count = withdrawals_count + 1 WHERE user_id = $1",
                user_id
            )
    await execute_with_retry(_inc)

async def check_referral_bonus(user_id: int, bot):
    async def _check():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT invited_by, friend_played FROM users WHERE user_id = $1",
                user_id
            )
            if row and row['invited_by'] is not None and row['friend_played'] == 0:
                invited_by = row['invited_by']
                await conn.execute("UPDATE users SET friend_played = 1 WHERE user_id = $1", user_id)
                await conn.execute("UPDATE users SET balance = balance + 30 WHERE user_id = $1", user_id)
                await conn.execute("UPDATE users SET balance = balance + 30 WHERE user_id = $1", invited_by)
                try:
                    await bot.send_message(user_id, "🎉 Поздравляем! Вы сыграли первую игру и получили 30 бонусных баллов!")
                    await bot.send_message(invited_by, "🎉 Ваш друг сыграл первую игру! Вы получаете 30 бонусных баллов!")
                except Exception:
                    pass
    await execute_with_retry(_check)

# ---- Турниры ----
async def get_active_tournament() -> Optional[Tuple[int, str, int, int]]:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            now = int(time.time())
            row = await conn.fetchrow(
                "SELECT id, name, prize_points, end_time FROM tournaments "
                "WHERE status='active' AND start_time <= $1 AND end_time > $1",
                now
            )
            return tuple(row) if row else None
    return await execute_with_retry(_get)

async def get_tournament_leaders(tournament_id: int, limit=10) -> List[tuple]:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(
                "SELECT tp.user_id, u.username, tp.score "
                "FROM tournament_participants tp "
                "JOIN users u ON tp.user_id = u.user_id "
                "WHERE tp.tournament_id = $1 ORDER BY tp.score DESC LIMIT $2",
                tournament_id, limit
            )
    return await execute_with_retry(_get)

async def register_for_tournament(user_id: int, tournament_id: int):
    async def _reg():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO tournament_participants (tournament_id, user_id, registered) "
                "VALUES ($1, $2, 1) "
                "ON CONFLICT (tournament_id, user_id) DO UPDATE SET registered = 1",
                tournament_id, user_id
            )
    await execute_with_retry(_reg)

async def is_registered_for_tournament(user_id: int, tournament_id: int) -> bool:
    async def _is():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT registered FROM tournament_participants "
                "WHERE tournament_id = $1 AND user_id = $2",
                tournament_id, user_id
            )
            return row and row['registered'] == 1
    return await execute_with_retry(_is)

async def get_user_tournaments(user_id: int, offset: int = 0, limit: int = 5) -> List[tuple]:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(
                "SELECT t.id, t.name, t.prize_points, t.start_time, t.end_time, tp.score, t.winner_id, t.winner_username "
                "FROM tournaments t "
                "JOIN tournament_participants tp ON t.id = tp.tournament_id "
                "WHERE tp.user_id = $1 ORDER BY t.start_time DESC LIMIT $2 OFFSET $3",
                user_id, limit, offset
            )
    return await execute_with_retry(_get)

async def count_user_tournaments(user_id: int) -> int:
    async def _count():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) FROM tournament_participants WHERE user_id = $1",
                user_id
            )
            return row[0] if row else 0
    return await execute_with_retry(_count)

async def update_tournament_score(user_id: int, score_gain: int):
    async def _update():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            now = int(time.time())
            row = await conn.fetchrow(
                "SELECT id FROM tournaments WHERE status = 'active' AND start_time <= $1 AND end_time > $1",
                now
            )
            if row:
                tournament_id = row['id']
                await conn.execute(
                    "INSERT INTO tournament_participants (tournament_id, user_id, score) "
                    "VALUES ($1, $2, $3) "
                    "ON CONFLICT (tournament_id, user_id) DO UPDATE SET score = score + $3, last_update = $4",
                    tournament_id, user_id, score_gain, now
                )
    await execute_with_retry(_update)

async def finish_tournament(tournament_id: int, bot):
    async def _finish():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            tournament = await conn.fetchrow(
                "SELECT name, prize_points, winner_id FROM tournaments WHERE id = $1 AND status = 'active'",
                tournament_id
            )
            if not tournament or tournament['winner_id'] is not None:
                return
            participants = await conn.fetch(
                "SELECT tp.user_id, u.username, tp.score "
                "FROM tournament_participants tp "
                "JOIN users u ON tp.user_id = u.user_id "
                "WHERE tp.tournament_id = $1 ORDER BY tp.score DESC",
                tournament_id
            )
            if not participants:
                await conn.execute(
                    "UPDATE tournaments SET status = 'finished' WHERE id = $1",
                    tournament_id
                )
                return
            max_score = participants[0]['score']
            top_users = [p for p in participants if p['score'] == max_score]
            winner = random.choice(top_users)
            winner_id, winner_username = winner['user_id'], winner['username']
            await conn.execute(
                "UPDATE users SET balance = balance + $1 WHERE user_id = $2",
                tournament['prize_points'], winner_id
            )
            await conn.execute(
                "UPDATE tournaments SET status = 'finished', winner_id = $1, winner_username = $2 WHERE id = $3",
                winner_id, winner_username, tournament_id
            )
        try:
            await bot.send_message(
                winner_id,
                f"🏆 Поздравляем! Вы выиграли турнир «{tournament['name']}» и получили {tournament['prize_points']} 💎!"
            )
            from config import ADMIN_IDS
            for admin_id in ADMIN_IDS:
                await bot.send_message(
                    admin_id,
                    f"🏆 Турнир «{tournament['name']}» завершён. Победитель: {winner_username} (ID {winner_id}) – {tournament['prize_points']} 💎."
                )
        except Exception as e:
            print(f"Ошибка при отправке уведомления: {e}")
    await execute_with_retry(_finish)

# ---- Депозиты, события, соглашения ----
async def add_deposit(user_id: int, amount: int):
    async def _add():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO deposits (user_id, amount) VALUES ($1, $2)",
                user_id, amount
            )
    await execute_with_retry(_add)

async def get_event_multiplier() -> float:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            now = int(time.time())
            row = await conn.fetchrow(
                "SELECT multiplier FROM events WHERE active = 1 AND start_date <= $1 AND end_date > $1",
                now
            )
            return row['multiplier'] if row else 1.0
    return await execute_with_retry(_get)

async def log_agreement(user_id: int, ip_address: str = None, user_agent: str = None):
    async def _log():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO agreements (user_id, agreed_at, ip_address, user_agent) "
                "VALUES ($1, $2, $3, $4) "
                "ON CONFLICT (user_id) DO UPDATE SET agreed_at = $2, ip_address = $3, user_agent = $4",
                user_id, int(time.time()), ip_address, user_agent
            )
            await conn.execute("UPDATE users SET agreed = 1 WHERE user_id = $1", user_id)
    await execute_with_retry(_log)

async def check_agreement(user_id: int) -> bool:
    return await is_user_agreed(user_id)

async def get_bot_stats() -> dict:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            first_date_row = await conn.fetchrow("SELECT MIN(created_at) FROM users")
            first_date = first_date_row[0] if first_date_row and first_date_row[0] else int(time.time())
            days = (int(time.time()) - first_date) // 86400
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            now = int(time.time())
            today_start = now - (now % 86400)
            new_today = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at >= $1", today_start)
            total_games = await conn.fetchval("SELECT SUM(total_games) FROM users") or 0
            total_paid = await conn.fetchval("SELECT SUM(amount_points) FROM withdraw_requests WHERE status='completed'") or 0
            return {"days": days, "total_users": total_users, "new_today": new_today,
                    "total_games": total_games, "total_paid": total_paid}
    return await execute_with_retry(_get)

# ---- Крипто-транзакции ----
async def create_crypto_transaction(user_id: int, amount_rub: int, amount_points: int, payment_id: str, invoice_id: str):
    async def _create():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO crypto_transactions (user_id, amount_rub, amount_points, payment_id, invoice_id) "
                "VALUES ($1, $2, $3, $4, $5)",
                user_id, amount_rub, amount_points, payment_id, invoice_id
            )
    await execute_with_retry(_create)

async def get_crypto_transaction(payment_id: str) -> Optional[Tuple[int, str]]:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT amount_points, status FROM crypto_transactions WHERE payment_id = $1",
                payment_id
            )
            return (row['amount_points'], row['status']) if row else None
    return await execute_with_retry(_get)

async def get_crypto_transaction_full(payment_id: str) -> Optional[Tuple[int, str, str]]:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT amount_points, status, invoice_id FROM crypto_transactions WHERE payment_id = $1",
                payment_id
            )
            return (row['amount_points'], row['status'], row['invoice_id']) if row else None
    return await execute_with_retry(_get)

async def update_crypto_transaction_status(payment_id: str, status: str, confirmed_at: int = None):
    async def _update():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE crypto_transactions SET status = $1, confirmed_at = $2 WHERE payment_id = $3",
                status, confirmed_at or int(time.time()), payment_id
            )
    await execute_with_retry(_update)

# ---- Заявки на вывод ----
async def create_withdraw_request(user_id: int, amount_points: int, amount_usdt: float, wallet_address: str):
    async def _create():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO withdraw_requests (user_id, amount_points, amount_usdt, wallet_address, status) "
                "VALUES ($1, $2, $3, $4, 'pending')",
                user_id, amount_points, amount_usdt, wallet_address
            )
    await execute_with_retry(_create)

async def get_pending_withdraw_requests() -> List[tuple]:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(
                "SELECT id, user_id, amount_points, amount_usdt, wallet_address FROM withdraw_requests WHERE status = 'pending' ORDER BY created_at ASC"
            )
    return await execute_with_retry(_get)

async def get_all_withdraw_requests(offset: int = 0, limit: int = 5) -> List[tuple]:
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(
                "SELECT id, user_id, amount_points, amount_usdt, wallet_address, status, created_at, completed_at "
                "FROM withdraw_requests ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                limit, offset
            )
    return await execute_with_retry(_get)

async def count_withdraw_requests(status: str = None) -> int:
    async def _count():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            if status:
                return await conn.fetchval("SELECT COUNT(*) FROM withdraw_requests WHERE status = $1", status)
            else:
                return await conn.fetchval("SELECT COUNT(*) FROM withdraw_requests")
    return await execute_with_retry(_count)

async def update_withdraw_request_status(request_id: int, status: str, completed_at: int = None):
    async def _update():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            if status == 'completed':
                await conn.execute(
                    "UPDATE withdraw_requests SET status = $1, completed_at = $2 WHERE id = $3",
                    status, completed_at or int(time.time()), request_id
                )
            else:
                await conn.execute(
                    "UPDATE withdraw_requests SET status = $1 WHERE id = $2",
                    status, request_id
                )
    await execute_with_retry(_update)

    # ===== Статистика выводов и пополнений ===== 
async def get_withdraw_stats() -> dict:
    """Возвращает общую статистику по выводам."""
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            # Общая статистика
            total_requests = await conn.fetchval("SELECT COUNT(*) FROM withdraw_requests")
            completed_requests = await conn.fetchval("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'completed'")
            rejected_requests = await conn.fetchval("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'rejected'")
            pending_requests = await conn.fetchval("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'pending'")
            
            # Сумма успешных выводов
            completed_amount = await conn.fetchval("SELECT COALESCE(SUM(amount_points), 0) FROM withdraw_requests WHERE status = 'completed'") or 0
            completed_amount_usdt = await conn.fetchval("SELECT COALESCE(SUM(amount_usdt), 0) FROM withdraw_requests WHERE status = 'completed'") or 0
            
            # Среднее время обработки (только для успешных)
            avg_processing_time = await conn.fetchval(
                "SELECT AVG(completed_at - created_at) / 3600.0 FROM withdraw_requests WHERE status = 'completed' AND completed_at IS NOT NULL"
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
    return await execute_with_retry(_get)

async def get_deposit_stats() -> dict:
    """Возвращает общую статистику по пополнениям."""
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            # Общая статистика
            total_deposits = await conn.fetchval("SELECT COUNT(*) FROM crypto_transactions")
            successful = await conn.fetchval("SELECT COUNT(*) FROM crypto_transactions WHERE status = 'paid'")
            pending = await conn.fetchval("SELECT COUNT(*) FROM crypto_transactions WHERE status = 'pending'")
            failed = await conn.fetchval("SELECT COUNT(*) FROM crypto_transactions WHERE status = 'failed'")
            
            # Сумма пополнений
            total_amount = await conn.fetchval("SELECT COALESCE(SUM(amount_points), 0) FROM crypto_transactions WHERE status = 'paid'") or 0
            
            # Средний и максимальный чек
            avg_amount = await conn.fetchval("SELECT COALESCE(AVG(amount_points), 0) FROM crypto_transactions WHERE status = 'paid'") or 0
            max_amount = await conn.fetchval("SELECT COALESCE(MAX(amount_points), 0) FROM crypto_transactions WHERE status = 'paid'") or 0
            
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
    return await execute_with_retry(_get)

async def get_user_withdraw_stats(user_id: int) -> dict:
    """Возвращает статистику выводов для конкретного пользователя."""
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            # Все заявки
            total_requests = await conn.fetchval("SELECT COUNT(*) FROM withdraw_requests WHERE user_id = $1", user_id)
            total_amount = await conn.fetchval("SELECT COALESCE(SUM(amount_points), 0) FROM withdraw_requests WHERE user_id = $1", user_id) or 0
            
            # Успешные
            completed = await conn.fetchval("SELECT COUNT(*) FROM withdraw_requests WHERE user_id = $1 AND status = 'completed'", user_id)
            completed_amount = await conn.fetchval("SELECT COALESCE(SUM(amount_points), 0) FROM withdraw_requests WHERE user_id = $1 AND status = 'completed'", user_id) or 0
            
            # Ожидающие
            pending = await conn.fetchval("SELECT COUNT(*) FROM withdraw_requests WHERE user_id = $1 AND status = 'pending'", user_id)
            
        return {
            "count": total_requests,
            "total": total_amount,
            "completed": completed,
            "completed_amount": completed_amount,
            "pending": pending
        }
    return await execute_with_retry(_get)

async def get_user_deposit_stats(user_id: int) -> dict:
    """Возвращает статистику пополнений для конкретного пользователя."""
    async def _get():
        pool = await init_db_pool()
        async with pool.acquire() as conn:
            # Все пополнения
            total_deposits = await conn.fetchval("SELECT COUNT(*) FROM crypto_transactions WHERE user_id = $1 AND status = 'paid'", user_id)
            total_amount = await conn.fetchval("SELECT COALESCE(SUM(amount_points), 0) FROM crypto_transactions WHERE user_id = $1 AND status = 'paid'", user_id) or 0
            
            # Средний и максимальный чек
            avg_amount = await conn.fetchval("SELECT COALESCE(AVG(amount_points), 0) FROM crypto_transactions WHERE user_id = $1 AND status = 'paid'", user_id) or 0
            max_amount = await conn.fetchval("SELECT COALESCE(MAX(amount_points), 0) FROM crypto_transactions WHERE user_id = $1 AND status = 'paid'", user_id) or 0
            
        return {
            "count": total_deposits,
            "total": total_amount,
            "avg": avg_amount,
            "max": max_amount
        }
    return await execute_with_retry(_get)
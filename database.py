import aiosqlite
import asyncio
import time
import random
from typing import Optional, Tuple, List, Any

DB_NAME = "casino.db"

# ========== КОНСТАНТЫ ==========
BONUS_WAGER_MULTIPLIER = 3
CASHBACK_PERCENT = 5

# ========== ЗАГЛУШКИ ДЛЯ СОВМЕСТИМОСТИ ==========
async def init_db_pool():
    return None

async def close_db_pool():
    pass

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def execute_with_retry(func, *args, max_attempts=20, base_delay=0.1):
    for attempt in range(max_attempts):
        try:
            return await func(*args)
        except aiosqlite.OperationalError as e:
            if "locked" in str(e) and attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                print(f"⚠️ БД заблокирована, повтор через {delay:.2f} сек...")
                await asyncio.sleep(delay)
            else:
                raise
        except Exception as e:
            raise

# ========== СОЗДАНИЕ ТАБЛИЦ ==========
async def create_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=30000")
        
        # Таблица users
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                bonus_total INTEGER DEFAULT 0,
                total_games INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                last_active INTEGER DEFAULT 0,
                invited_by INTEGER DEFAULT NULL,
                referral_bonus_claimed INTEGER DEFAULT 0,
                friend_played INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                theme TEXT DEFAULT 'classic',
                daily_bonus_last INTEGER DEFAULT 0,
                daily_bonus_streak INTEGER DEFAULT 0,
                tournament_score INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s','now')),
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
        
        # Добавляем колонки, если их нет
        try:
            await db.execute("ALTER TABLE users ADD COLUMN demo_games_played INTEGER DEFAULT 0")
        except:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN bonus_balance INTEGER DEFAULT 0")
        except:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN bonus_wagered INTEGER DEFAULT 0")
        except:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN last_cashback INTEGER DEFAULT 0")
        except:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN first_deposit_bonus_claimed INTEGER DEFAULT 0")
        except:
            pass
        
        # Достижения
        await db.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                achieved_at INTEGER DEFAULT (strftime('%s','now')),
                UNIQUE(user_id, achievement_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Турниры
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                prize_points INTEGER NOT NULL,
                start_time INTEGER NOT NULL,
                end_time INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                winner_id INTEGER DEFAULT NULL,
                winner_username TEXT DEFAULT NULL,
                winner_notified INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s','now'))
            )
        ''')
        
        # Участники турниров
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tournament_participants (
                tournament_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                score INTEGER DEFAULT 0,
                registered INTEGER DEFAULT 0,
                last_update INTEGER DEFAULT (strftime('%s','now')),
                PRIMARY KEY (tournament_id, user_id),
                FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Крипто-транзакции
        await db.execute('''
            CREATE TABLE IF NOT EXISTS crypto_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_rub INTEGER NOT NULL,
                amount_points INTEGER NOT NULL,
                payment_id TEXT UNIQUE NOT NULL,
                invoice_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at INTEGER DEFAULT (strftime('%s','now')),
                confirmed_at INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Заявки на вывод
        await db.execute('''
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_points INTEGER NOT NULL,
                amount_usdt REAL NOT NULL,
                wallet_address TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at INTEGER DEFAULT (strftime('%s','now')),
                completed_at INTEGER,
                admin_comment TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Таблица согласий
        await db.execute('''
            CREATE TABLE IF NOT EXISTS agreements (
                user_id INTEGER PRIMARY KEY,
                agreed_at INTEGER NOT NULL,
                ip_address TEXT,
                user_agent TEXT
            )
        ''')
        
        # Депозиты
        await db.execute('''
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                created_at INTEGER DEFAULT (strftime('%s','now')),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # События (множители)
        await db.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                multiplier REAL DEFAULT 1.0,
                start_date INTEGER NOT NULL,
                end_date INTEGER NOT NULL,
                active INTEGER DEFAULT 1
            )
        ''')
        
        # История игр для кэшбека
        await db.execute('''
            CREATE TABLE IF NOT EXISTS game_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_type TEXT NOT NULL,
                bet_amount INTEGER NOT NULL,
                win_amount INTEGER DEFAULT 0,
                played_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        await db.commit()
    
    print("✅ Таблицы созданы / проверены.")

# ========== ОСНОВНЫЕ ФУНКЦИИ ==========
async def get_user(user_id: int, username: str = None, initial_balance: int = 0) -> Tuple:
    async def _get_user():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT balance, total_games, wins, level, exp, theme, daily_bonus_last, "
                "daily_bonus_streak, tournament_score, agreed, has_started, referral_count, "
                "referral_earnings, current_win_streak, max_win_streak, withdrawals_count "
                "FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            
            if row:
                await db.execute(
                    "UPDATE users SET last_active = ? WHERE user_id = ?",
                    (int(time.time()), user_id)
                )
                await db.commit()
                return row
            
            await db.execute(
                "INSERT INTO users (user_id, username, balance, last_active, agreed, has_started) "
                "VALUES (?, ?, ?, ?, 0, 0)",
                (user_id, username, initial_balance, int(time.time()))
            )
            await db.commit()
            return (initial_balance, 0, 0, 1, 0, 'classic', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    
    return await execute_with_retry(_get_user)

async def get_bonus_total(user_id: int) -> int:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT bonus_total FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0
    return await execute_with_retry(_get)

async def update_balance(user_id: int, new_balance: int):
    async def _update():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET balance = ?, last_active = ? WHERE user_id = ?",
                (new_balance, int(time.time()), user_id)
            )
            await db.commit()
    await execute_with_retry(_update)

async def update_stats(user_id: int, win: bool) -> bool:
    async def _update():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT exp, level, total_games, wins, current_win_streak, max_win_streak FROM users WHERE user_id = ?",
                (user_id,)
            )
            exp, level, total_games, wins, current_streak, max_streak = await cursor.fetchone()
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
                await db.execute(
                    "UPDATE users SET total_games = total_games + 1, wins = wins + 1, exp = ?, level = ?, "
                    "last_active = ?, current_win_streak = ?, max_win_streak = ? WHERE user_id = ?",
                    (new_exp, level, int(time.time()), new_streak, new_max_streak, user_id)
                )
            else:
                new_streak = 0
                await db.execute(
                    "UPDATE users SET total_games = total_games + 1, exp = ?, level = ?, last_active = ?, "
                    "current_win_streak = ? WHERE user_id = ?",
                    (new_exp, level, int(time.time()), new_streak, user_id)
                )
            await db.commit()
            return level_up
    return await execute_with_retry(_update)

async def get_user_stats(user_id: int) -> Optional[Tuple[int, int, int]]:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT balance, total_games, wins FROM users WHERE user_id = ?", (user_id,))
            return await cursor.fetchone()
    return await execute_with_retry(_get)

async def get_all_users(offset=0, limit=5, active_days=30) -> List[tuple]:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            if active_days == 0:
                cursor = await db.execute(
                    "SELECT user_id, username, balance, total_games FROM users ORDER BY user_id LIMIT ? OFFSET ?",
                    (limit, offset)
                )
            else:
                threshold = int(time.time()) - active_days * 86400
                cursor = await db.execute(
                    "SELECT user_id, username, balance, total_games FROM users WHERE last_active > ? ORDER BY user_id LIMIT ? OFFSET ?",
                    (threshold, limit, offset)
                )
            return await cursor.fetchall()
    return await execute_with_retry(_get)

async def get_users_count(active_days=30) -> int:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            if active_days == 0:
                cursor = await db.execute("SELECT COUNT(*) FROM users")
            else:
                threshold = int(time.time()) - active_days * 86400
                cursor = await db.execute("SELECT COUNT(*) FROM users WHERE last_active > ?", (threshold,))
            row = await cursor.fetchone()
            return row[0] if row else 0
    return await execute_with_retry(_get)

async def set_user_agreed(user_id: int):
    async def _set():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET agreed = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
    await execute_with_retry(_set)

async def is_user_agreed(user_id: int) -> bool:
    async def _is():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT agreed FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row and row[0] == 1
    return await execute_with_retry(_is)

async def set_user_started(user_id: int):
    async def _set():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET has_started = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
    await execute_with_retry(_set)

async def increment_referral_count(inviter_id: int):
    async def _inc():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?", (inviter_id,))
            await db.commit()
    await execute_with_retry(_inc)

async def add_referral_earnings(inviter_id: int, amount: int):
    async def _add():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET referral_earnings = referral_earnings + ? WHERE user_id = ?", (amount, inviter_id))
            await db.commit()
    await execute_with_retry(_add)

async def increment_withdrawals_count(user_id: int):
    async def _inc():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET withdrawals_count = withdrawals_count + 1 WHERE user_id = ?", (user_id,))
            await db.commit()
    await execute_with_retry(_inc)

async def check_referral_bonus(user_id: int, bot):
    async def _check():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("BEGIN")
            cursor = await db.execute(
                "SELECT invited_by FROM users WHERE user_id = ? AND friend_played = 0",
                (user_id,)
            )
            row = await cursor.fetchone()
            if row and row[0] is not None:
                invited_by = row[0]
                await db.execute(
                    "UPDATE users SET friend_played = 1 WHERE user_id = ?",
                    (user_id,)
                )
                await db.execute(
                    "UPDATE users SET balance = balance + 30, bonus_total = bonus_total + 30, "
                    "bonus_balance = bonus_balance + 30 WHERE user_id IN (?, ?)",
                    (user_id, invited_by)
                )
                await db.commit()
                try:
                    await bot.send_message(user_id, "🎉 Поздравляем! Вы сыграли первую игру и получили 30 бонусных баллов!")
                    await bot.send_message(invited_by, "🎉 Ваш друг сыграл первую игру! Вы получаете 30 бонусных баллов!")
                except Exception:
                    pass
            else:
                await db.rollback()
    await execute_with_retry(_check)

async def get_active_tournament() -> Optional[Tuple[int, str, int, int]]:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            now = int(time.time())
            cursor = await db.execute(
                "SELECT id, name, prize_points, end_time FROM tournaments WHERE status='active' AND start_time <= ? AND end_time > ?",
                (now, now)
            )
            row = await cursor.fetchone()
            return row if row else None
    return await execute_with_retry(_get)

async def get_tournament_leaders(tournament_id: int, limit=10) -> List[tuple]:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT tp.user_id, u.username, tp.score FROM tournament_participants tp "
                "JOIN users u ON tp.user_id = u.user_id "
                "WHERE tp.tournament_id = ? ORDER BY tp.score DESC LIMIT ?",
                (tournament_id, limit)
            )
            return await cursor.fetchall()
    return await execute_with_retry(_get)

async def register_for_tournament(user_id: int, tournament_id: int):
    async def _reg():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO tournament_participants (tournament_id, user_id, registered) VALUES (?, ?, 1) "
                "ON CONFLICT(tournament_id, user_id) DO UPDATE SET registered = 1",
                (tournament_id, user_id)
            )
            await db.commit()
    await execute_with_retry(_reg)

async def is_registered_for_tournament(user_id: int, tournament_id: int) -> bool:
    async def _is():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT registered FROM tournament_participants WHERE tournament_id = ? AND user_id = ?",
                (tournament_id, user_id)
            )
            row = await cursor.fetchone()
            return row and row[0] == 1
    return await execute_with_retry(_is)

async def get_user_tournaments(user_id: int, offset: int = 0, limit: int = 5) -> List[tuple]:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT t.id, t.name, t.prize_points, t.start_time, t.end_time, tp.score, t.winner_id, t.winner_username "
                "FROM tournaments t JOIN tournament_participants tp ON t.id = tp.tournament_id "
                "WHERE tp.user_id = ? ORDER BY t.start_time DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset)
            )
            return await cursor.fetchall()
    return await execute_with_retry(_get)

async def count_user_tournaments(user_id: int) -> int:
    async def _count():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM tournament_participants WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0
    return await execute_with_retry(_count)

async def update_tournament_score(user_id: int, score_gain: int):
    async def _update():
        async with aiosqlite.connect(DB_NAME) as db:
            now = int(time.time())
            cursor = await db.execute(
                "SELECT id FROM tournaments WHERE status = 'active' AND start_time <= ? AND end_time > ?",
                (now, now)
            )
            tournament = await cursor.fetchone()
            if tournament:
                tournament_id = tournament[0]
                await db.execute(
                    "INSERT INTO tournament_participants (tournament_id, user_id, score) VALUES (?, ?, ?) "
                    "ON CONFLICT(tournament_id, user_id) DO UPDATE SET score = score + ?, last_update = ?",
                    (tournament_id, user_id, score_gain, score_gain, now)
                )
                await db.commit()
    await execute_with_retry(_update)

async def finish_tournament(tournament_id: int, bot):
    async def _finish():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT name, prize_points, winner_id FROM tournaments WHERE id = ? AND status = 'active'",
                (tournament_id,)
            )
            tournament = await cursor.fetchone()
            if not tournament or tournament[2] is not None:
                return
            cursor = await db.execute(
                "SELECT tp.user_id, u.username, tp.score FROM tournament_participants tp "
                "JOIN users u ON tp.user_id = u.user_id WHERE tp.tournament_id = ? ORDER BY tp.score DESC",
                (tournament_id,)
            )
            participants = await cursor.fetchall()
            if not participants:
                await db.execute("UPDATE tournaments SET status = 'finished' WHERE id = ?", (tournament_id,))
                await db.commit()
                return
            max_score = participants[0][2]
            top_users = [p for p in participants if p[2] == max_score]
            winner = random.choice(top_users)
            winner_id, winner_username = winner[0], winner[1]
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (tournament[1], winner_id))
            await db.execute(
                "UPDATE tournaments SET status = 'finished', winner_id = ?, winner_username = ? WHERE id = ?",
                (winner_id, winner_username, tournament_id)
            )
            await db.commit()
        try:
            await bot.send_message(winner_id, f"🏆 Поздравляем! Вы выиграли турнир «{tournament[0]}» и получили {tournament[1]} 💎!")
            from config import ADMIN_IDS
            for admin_id in ADMIN_IDS:
                await bot.send_message(admin_id, f"🏆 Турнир «{tournament[0]}» завершён. Победитель: {winner_username} (ID {winner_id}) – {tournament[1]} 💎.")
        except Exception as e:
            print(f"Ошибка при отправке уведомления: {e}")
    await execute_with_retry(_finish)

async def add_deposit(user_id: int, amount: int):
    async def _add():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT INTO deposits (user_id, amount) VALUES (?, ?)", (user_id, amount))
            await db.commit()
    await execute_with_retry(_add)

async def get_event_multiplier() -> float:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            now = int(time.time())
            cursor = await db.execute(
                "SELECT multiplier FROM events WHERE active = 1 AND start_date <= ? AND end_date > ?",
                (now, now)
            )
            row = await cursor.fetchone()
            return row[0] if row else 1.0
    return await execute_with_retry(_get)

async def log_agreement(user_id: int, ip_address: str = None, user_agent: str = None):
    async def _log():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT OR REPLACE INTO agreements (user_id, agreed_at, ip_address, user_agent) VALUES (?, ?, ?, ?)",
                (user_id, int(time.time()), ip_address, user_agent)
            )
            await db.execute("UPDATE users SET agreed = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
    await execute_with_retry(_log)

async def check_agreement(user_id: int) -> bool:
    return await is_user_agreed(user_id)

async def get_bot_stats() -> dict:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT MIN(created_at) FROM users")
            first_date = (await cursor.fetchone())[0] or int(time.time())
            days = (int(time.time()) - first_date) // 86400
            cursor = await db.execute("SELECT COUNT(*) FROM users")
            total_users = (await cursor.fetchone())[0]
            now = time.time()
            today_start = int(now - (now % 86400))
            cursor = await db.execute("SELECT COUNT(*) FROM users WHERE created_at >= ?", (today_start,))
            new_today = (await cursor.fetchone())[0]
            cursor = await db.execute("SELECT SUM(total_games) FROM users")
            total_games = (await cursor.fetchone())[0] or 0
            cursor = await db.execute("SELECT SUM(amount_points) FROM withdraw_requests WHERE status='completed'")
            total_paid = (await cursor.fetchone())[0] or 0
            return {"days": days, "total_users": total_users, "new_today": new_today, "total_games": total_games, "total_paid": total_paid}
    return await execute_with_retry(_get)

# ===== Крипто-транзакции =====
async def create_crypto_transaction(user_id: int, amount_rub: int, amount_points: int, payment_id: str, invoice_id: str):
    async def _create():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO crypto_transactions (user_id, amount_rub, amount_points, payment_id, invoice_id) VALUES (?, ?, ?, ?, ?)",
                (user_id, amount_rub, amount_points, payment_id, invoice_id)
            )
            await db.commit()
    await execute_with_retry(_create)

async def get_crypto_transaction(payment_id: str) -> Optional[Tuple[int, str]]:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT amount_points, status FROM crypto_transactions WHERE payment_id = ?",
                (payment_id,)
            )
            row = await cursor.fetchone()
            return (row[0], row[1]) if row else None
    return await execute_with_retry(_get)

async def get_crypto_transaction_full(payment_id: str) -> Optional[Tuple[int, str, str]]:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT amount_points, status, invoice_id FROM crypto_transactions WHERE payment_id = ?",
                (payment_id,)
            )
            row = await cursor.fetchone()
            return (row[0], row[1], row[2]) if row else None
    return await execute_with_retry(_get)

async def update_crypto_transaction_status(payment_id: str, status: str, confirmed_at: int = None):
    async def _update():
        async with aiosqlite.connect(DB_NAME) as db:
            if status == 'paid':
                cursor = await db.execute(
                    "UPDATE crypto_transactions SET status = ?, confirmed_at = ? WHERE payment_id = ? AND status = 'pending'",
                    (status, confirmed_at or int(time.time()), payment_id)
                )
                await db.commit()
                return cursor.rowcount > 0
            else:
                await db.execute(
                    "UPDATE crypto_transactions SET status = ? WHERE payment_id = ?",
                    (status, payment_id)
                )
                await db.commit()
                return True
    return await execute_with_retry(_update)

# ===== Заявки на вывод =====
async def create_withdraw_request(user_id: int, amount_points: int, amount_usdt: float, wallet_address: str):
    async def _create():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO withdraw_requests (user_id, amount_points, amount_usdt, wallet_address, status) VALUES (?, ?, ?, ?, 'pending')",
                (user_id, amount_points, amount_usdt, wallet_address)
            )
            await db.commit()
    await execute_with_retry(_create)

async def get_pending_withdraw_requests() -> List[tuple]:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT id, user_id, amount_points, amount_usdt, wallet_address FROM withdraw_requests WHERE status = 'pending' ORDER BY created_at ASC"
            )
            return await cursor.fetchall()
    return await execute_with_retry(_get)

async def get_all_withdraw_requests(offset: int = 0, limit: int = 5) -> List[tuple]:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT id, user_id, amount_points, amount_usdt, wallet_address, status, created_at, completed_at "
                "FROM withdraw_requests ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
            return await cursor.fetchall()
    return await execute_with_retry(_get)

async def count_withdraw_requests(status: str = None) -> int:
    async def _count():
        async with aiosqlite.connect(DB_NAME) as db:
            if status:
                cursor = await db.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status = ?", (status,))
            else:
                cursor = await db.execute("SELECT COUNT(*) FROM withdraw_requests")
            row = await cursor.fetchone()
            return row[0] if row else 0
    return await execute_with_retry(_count)

async def update_withdraw_request_status(request_id: int, status: str, completed_at: int = None):
    async def _update():
        async with aiosqlite.connect(DB_NAME) as db:
            if status == 'completed':
                await db.execute(
                    "UPDATE withdraw_requests SET status = ?, completed_at = ? WHERE id = ?",
                    (status, completed_at or int(time.time()), request_id)
                )
            else:
                await db.execute(
                    "UPDATE withdraw_requests SET status = ? WHERE id = ?",
                    (status, request_id)
                )
            await db.commit()
    await execute_with_retry(_update)

# ===== Статистика выводов и пополнений =====
async def get_withdraw_stats() -> dict:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM withdraw_requests")
            total_requests = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'completed'")
            completed_requests = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'rejected'")
            rejected_requests = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM withdraw_requests WHERE status = 'pending'")
            pending_requests = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COALESCE(SUM(amount_points), 0) FROM withdraw_requests WHERE status = 'completed'")
            completed_amount = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COALESCE(SUM(amount_usdt), 0) FROM withdraw_requests WHERE status = 'completed'")
            completed_amount_usdt = (await cursor.fetchone())[0]
            
            cursor = await db.execute(
                "SELECT AVG(completed_at - created_at) / 3600.0 FROM withdraw_requests WHERE status = 'completed' AND completed_at IS NOT NULL"
            )
            avg_processing_time = (await cursor.fetchone())[0] or 0
            
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
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM crypto_transactions")
            total_deposits = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM crypto_transactions WHERE status = 'paid'")
            successful = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM crypto_transactions WHERE status = 'pending'")
            pending = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM crypto_transactions WHERE status = 'failed'")
            failed = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COALESCE(SUM(amount_points), 0) FROM crypto_transactions WHERE status = 'paid'")
            total_amount = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COALESCE(AVG(amount_points), 0) FROM crypto_transactions WHERE status = 'paid'")
            avg_amount = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COALESCE(MAX(amount_points), 0) FROM crypto_transactions WHERE status = 'paid'")
            max_amount = (await cursor.fetchone())[0]
            
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
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM withdraw_requests WHERE user_id = ?", (user_id,))
            count = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COALESCE(SUM(amount_points), 0) FROM withdraw_requests WHERE user_id = ?", (user_id,))
            total = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM withdraw_requests WHERE user_id = ? AND status = 'completed'", (user_id,))
            completed = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COALESCE(SUM(amount_points), 0) FROM withdraw_requests WHERE user_id = ? AND status = 'completed'", (user_id,))
            completed_amount = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COUNT(*) FROM withdraw_requests WHERE user_id = ? AND status = 'pending'", (user_id,))
            pending = (await cursor.fetchone())[0]
            
        return {
            "count": count,
            "total": total,
            "completed": completed,
            "completed_amount": completed_amount,
            "pending": pending
        }
    return await execute_with_retry(_get)

async def get_user_deposit_stats(user_id: int) -> dict:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM crypto_transactions WHERE user_id = ? AND status = 'paid'", (user_id,))
            count = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COALESCE(SUM(amount_points), 0) FROM crypto_transactions WHERE user_id = ? AND status = 'paid'", (user_id,))
            total = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COALESCE(AVG(amount_points), 0) FROM crypto_transactions WHERE user_id = ? AND status = 'paid'", (user_id,))
            avg = (await cursor.fetchone())[0]
            
            cursor = await db.execute("SELECT COALESCE(MAX(amount_points), 0) FROM crypto_transactions WHERE user_id = ? AND status = 'paid'", (user_id,))
            max_val = (await cursor.fetchone())[0]
            
        return {
            "count": count,
            "total": total,
            "avg": avg,
            "max": max_val
        }
    return await execute_with_retry(_get)

# ===== Демо-режим =====
async def get_demo_games_played(user_id: int) -> int:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute("SELECT demo_games_played FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0
    return await execute_with_retry(_get)

async def increment_demo_games_played(user_id: int) -> bool:
    async def _inc():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "UPDATE users SET demo_games_played = demo_games_played + 1 WHERE user_id = ? AND demo_games_played < ?",
                (user_id, 5)
            )
            await db.commit()
            return cursor.rowcount > 0
    return await execute_with_retry(_inc)

async def reset_demo_games_played(user_id: int):
    async def _reset():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET demo_games_played = 0 WHERE user_id = ?", (user_id,))
            await db.commit()
    await execute_with_retry(_reset)

# ===== Защитные механизмы =====
async def get_daily_withdrawn(user_id: int) -> int:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            today_start = int(time.time()) - (int(time.time()) % 86400)
            cursor = await db.execute(
                "SELECT COALESCE(SUM(amount_points), 0) FROM withdraw_requests "
                "WHERE user_id = ? AND status='completed' AND completed_at >= ?",
                (user_id, today_start)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
    return await execute_with_retry(_get)

async def get_last_deposit_time(user_id: int) -> int:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT MAX(created_at) FROM deposits WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row and row[0] else 0
    return await execute_with_retry(_get)

async def get_pending_withdraw_count(user_id: int) -> int:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM withdraw_requests WHERE user_id = ? AND status = 'pending'",
                (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
    return await execute_with_retry(_get)

async def get_daily_total_withdrawn_rub() -> float:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            today_start = int(time.time()) - (int(time.time()) % 86400)
            usdt_total = await db.execute_fetchone(
                "SELECT COALESCE(SUM(amount_usdt), 0) FROM withdraw_requests "
                "WHERE status='pending' AND created_at >= ?",
                (today_start,)
            )
            usdt_total = usdt_total[0] if usdt_total else 0
            from config import USD_RATE
            return usdt_total * USD_RATE
    return await execute_with_retry(_get)

async def update_bonus_wagered(user_id: int, bet_amount: int, win: bool):
    async def _update():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET bonus_wagered = bonus_wagered + ? WHERE user_id = ?",
                (bet_amount, user_id)
            )
            await db.commit()
    await execute_with_retry(_update)

async def get_bonus_wagering_status(user_id: int) -> Tuple[int, int, bool]:
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT bonus_balance, bonus_wagered FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return 0, 0, True
            bonus_balance, bonus_wagered = row
            required_wagered = bonus_balance * BONUS_WAGER_MULTIPLIER
            is_cleared = bonus_balance == 0 or bonus_wagered >= required_wagered
            return bonus_balance, bonus_wagered, is_cleared
    return await execute_with_retry(_get)

# ===== Кэшбек =====
async def get_weekly_losses(user_id: int) -> int:
    """Возвращает сумму проигрышей пользователя за последние 7 дней."""
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            week_ago = int(time.time()) - 7 * 86400
            cursor = await db.execute(
                "SELECT COALESCE(SUM(bet_amount - win_amount), 0) FROM game_history "
                "WHERE user_id = ? AND played_at >= ? AND bet_amount > win_amount",
                (user_id, week_ago)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
    return await execute_with_retry(_get)

async def add_cashback(user_id: int, amount: int):
    """Начисляет кэшбек (бонусные баллы)."""
    async def _add():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET balance = balance + ?, bonus_total = bonus_total + ?, "
                "bonus_balance = bonus_balance + ? WHERE user_id = ?",
                (amount, amount, amount, user_id)
            )
            await db.commit()
    await execute_with_retry(_add)

async def get_last_cashback_time(user_id: int) -> int:
    """Возвращает время последнего начисления кэшбека."""
    async def _get():
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT last_cashback FROM users WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
    return await execute_with_retry(_get)

async def set_last_cashback_time(user_id: int, timestamp: int):
    """Устанавливает время последнего начисления кэшбека."""
    async def _set():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET last_cashback = ? WHERE user_id = ?",
                (timestamp, user_id)
            )
            await db.commit()
    await execute_with_retry(_set)

# ===== История игр =====
async def save_game_history(user_id: int, bet: int, win: int, game_type: str):
    """Сохраняет историю игры для расчёта кэшбека."""
    async def _save():
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "INSERT INTO game_history (user_id, game_type, bet_amount, win_amount, played_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, game_type, bet, win if win > 0 else 0, int(time.time()))
            )
            await db.commit()
    await execute_with_retry(_save)
#!/usr/bin/env python3
import asyncio
import logging
import os
import time
import json
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from config import MAIN_BOT_TOKEN
from database import create_db, init_db_pool, close_db_pool
from handlers.main_bot import (
    profile_router, payments_router, fallback_router, bot_info_router
)
from handlers.main_bot.cashback import router as cashback_router
from middlewares import UserStatusMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- HTTP сервер для API (синхронный, без asyncio) ----------
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

DB_NAME_FOR_API = "casino.db"

def get_balance_sync(user_id: int):
    """Синхронное получение баланса из SQLite (без asyncio)"""
    conn = sqlite3.connect(DB_NAME_FOR_API)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def update_balance_sync(user_id: int, new_balance: int):
    """Синхронное обновление баланса в SQLite"""
    conn = sqlite3.connect(DB_NAME_FOR_API)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    conn.close()

def update_stats_sync(user_id: int, win: bool):
    """Синхронное обновление статистики"""
    conn = sqlite3.connect(DB_NAME_FOR_API)
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
    """Синхронное сохранение истории игры"""
    conn = sqlite3.connect(DB_NAME_FOR_API)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO game_history (user_id, game_type, bet_amount, win_amount, played_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, game_type, bet, win_amount, int(time.time()))
    )
    conn.commit()
    conn.close()

class MainHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS, GET')
        self.end_headers()
    
    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        if self.path == '/api/get_balance':
            self._handle_get_balance()
        elif self.path == '/api/game_result':
            self._handle_game_result()
        else:
            self.send_response(404)
            self.end_headers()
    
    def _handle_get_balance(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            user_id = data.get('user_id')
            
            if not user_id:
                self._send_json({'success': False, 'error': 'user_id required'}, 400)
                return
            
            balance = get_balance_sync(int(user_id))
            
            self._send_json({
                'success': True,
                'balance': balance,
                'bonus_total': 0
            })
        except Exception as e:
            logger.error(f"Ошибка в get_balance: {e}")
            self._send_json({'success': False, 'error': str(e)}, 500)
    
    def _handle_game_result(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            user_id = data.get('user_id')
            game = data.get('game')
            bet = data.get('bet')
            win = data.get('win')
            win_amount = data.get('win_amount', 0)
            
            if not user_id or not game or bet is None:
                self._send_json({'success': False, 'error': 'Missing required fields'}, 400)
                return
            
            current_balance = get_balance_sync(int(user_id))
            
            if win:
                new_balance = current_balance + win_amount
            else:
                new_balance = current_balance - bet
            
            update_balance_sync(int(user_id), new_balance)
            update_stats_sync(int(user_id), win)
            save_game_history_sync(int(user_id), bet, win_amount if win else 0, game)
            
            self._send_json({
                'success': True,
                'new_balance': new_balance,
                'win': win,
                'win_amount': win_amount if win else 0
            })
        except Exception as e:
            logger.error(f"Ошибка в game_result: {e}")
            self._send_json({'success': False, 'error': str(e)}, 500)
    
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def log_message(self, format, *args):
        pass

def run_server():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), MainHandler)
    server.serve_forever()

# ---------- Telegram Bot ----------
bot = Bot(token=MAIN_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

dp.message.middleware(UserStatusMiddleware())

dp.include_router(profile_router)
dp.include_router(payments_router)
dp.include_router(bot_info_router)
dp.include_router(cashback_router)
dp.include_router(fallback_router)

@dp.errors()
async def global_error_handler(event: types.ErrorEvent):
    logger.error(f"Глобальная ошибка: {event.exception}", exc_info=True)
    return True

async def on_startup():
    await init_db_pool()
    await create_db()
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="myid", description="Мой Telegram ID"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    logger.info("База данных готова, команды установлены, бот запущен.")

async def main():
    # Запускаем HTTP сервер
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    await asyncio.sleep(1)
    
    await bot.delete_webhook()
    
    dp.startup.register(on_startup)
    
    await dp.start_polling(bot, allowed_updates=['message', 'callback_query'])

if __name__ == "__main__":
    asyncio.run(main())
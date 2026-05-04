#!/usr/bin/env python3
import asyncio
import logging
import os
import time
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from config import MAIN_BOT_TOKEN
from database import create_db, init_db_pool, close_db_pool, get_user, update_balance, update_stats, save_game_history
from handlers.main_bot import (
    profile_router, payments_router, fallback_router, bot_info_router
)
from handlers.main_bot.cashback import router as cashback_router
from handlers.main_bot.achievements import check_achievements
from middlewares import UserStatusMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Простой HTTP сервер для healthcheck и API ----------
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import json

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
            self.handle_get_balance()
        elif self.path == '/api/game_result':
            self.handle_game_result()
        else:
            self.send_response(404)
            self.end_headers()
    
    def handle_get_balance(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            user_id = data.get('user_id')
            
            logger.info(f"API get_balance called for user_id: {user_id}")
            
            if not user_id:
                self._send_json({'success': False, 'error': 'user_id required'}, 400)
                return
            
            # Выполняем синхронно
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            user_data = loop.run_until_complete(get_user(int(user_id), None))
            loop.close()
            
            balance = user_data[0]
            bonus_total = user_data[2] if len(user_data) > 2 else 0
            
            self._send_json({
                'success': True,
                'balance': balance,
                'bonus_total': bonus_total
            })
        except Exception as e:
            logger.error(f"Ошибка в get_balance: {e}")
            self._send_json({'success': False, 'error': str(e)}, 500)
    
    def handle_game_result(self):
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
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            user_data = loop.run_until_complete(get_user(int(user_id), None))
            current_balance = user_data[0]
            
            if win:
                new_balance = current_balance + win_amount
            else:
                new_balance = current_balance - bet
            
            loop.run_until_complete(update_balance(int(user_id), new_balance))
            loop.run_until_complete(update_stats(int(user_id), win=win))
            loop.run_until_complete(save_game_history(int(user_id), bet, win_amount if win else 0, game))
            loop.run_until_complete(check_achievements(int(user_id), None))
            loop.close()
            
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
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
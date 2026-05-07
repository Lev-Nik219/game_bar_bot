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
from datetime import datetime
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
FREE_BONUS_AMOUNT = 10
AD_COOLDOWN_SECONDS = 20

CRYPTOPAY_TOKEN = os.environ.get('CRYPTOPAY_TOKEN', '455143:AA35WjAeKxzuurvYbMCZewcqzQ7VmtAQbDZ')
CRYPTOPAY_API_URL = 'https://pay.crypt.bot/api'

PRICE_LIST = {250:20,500:35,750:50,1000:65}

REFERRAL_BONUS_INVITER = 100
REFERRAL_BONUS_INVITED = 25

DAILY_BONUS_BASE = 10
DAILY_BONUS_STREAK_MULTIPLIER = 1

CASHBACK_PERCENT = 5
CASHBACK_DAY = 6

ACHIEVEMENTS = {
    'first_game':{'name':'🎮 Первая игра','desc':'Сыграть первую игру','icon':'🎮','target':1},
    '10_games':{'name':'🎰 Игрок','desc':'Сыграть 10 игр','icon':'🎰','target':10},
    '50_games':{'name':'🎲 Завсегдатай','desc':'Сыграть 50 игр','icon':'🎲','target':50},
    '100_games':{'name':'🃏 Ветеран','desc':'Сыграть 100 игр','icon':'🃏','target':100},
    '500_games':{'name':'👑 Легенда','desc':'Сыграть 500 игр','icon':'👑','target':500},
    'first_win':{'name':'🍀 Первая победа','desc':'Одержать первую победу','icon':'🍀','target':1},
    '10_wins':{'name':'🏆 Победитель','desc':'Одержать 10 побед','icon':'🏆','target':10},
    '50_wins':{'name':'💪 Чемпион','desc':'Одержать 50 побед','icon':'💪','target':50},
    '100_wins':{'name':'🌟 Мастер','desc':'Одержать 100 побед','icon':'🌟','target':100},
    'big_win':{'name':'💰 Крупный выигрыш','desc':'Выиграть 500+ баллов за раз','icon':'💰','target':1},
    'balance_1000':{'name':'💎 Тысячник','desc':'Накопить 1000 баллов','icon':'💎','target':1},
    'balance_5000':{'name':'💵 Богач','desc':'Накопить 5000 баллов','icon':'💵','target':1},
    'depositor':{'name':'📥 Инвестор','desc':'Пополнить баланс','icon':'📥','target':1},
}

def execute_sqlite_with_retry(func, max_retries=5, delay=0.5):
    for attempt in range(max_retries):
        try: return func()
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and attempt < max_retries - 1: time.sleep(delay * (attempt + 1))
            else: raise
    raise Exception("SQLite still locked")

def get_balance_sync(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id=?",(uid,));r=c.fetchone();conn.close();return r[0] if r else 0
    return execute_sqlite_with_retry(_do)

def update_balance_sync(uid, bal):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("UPDATE users SET balance=? WHERE user_id=?",(bal,uid));conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def update_stats_sync(uid, win):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT total_games,wins FROM users WHERE user_id=?",(uid,));r=c.fetchone()
        if r: c.execute("UPDATE users SET total_games=?,wins=? WHERE user_id=?",(r[0]+1,r[1]+(1 if win else 0),uid))
        conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def get_user_stats_sync(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT balance,total_games,wins FROM users WHERE user_id=?",(uid,));r=c.fetchone();conn.close()
        return (r[0],r[1],r[2]) if r else (0,0,0)
    return execute_sqlite_with_retry(_do)

def save_game_history_sync(uid,bet,wa,game):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("INSERT INTO game_history(user_id,game_type,bet_amount,win_amount,played_at) VALUES(?,?,?,?,?)",(uid,game,bet,wa,int(time.time())));conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def check_achievements_sync(uid,bal,tg,w,wa=0):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS achievements(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,achievement_id TEXT NOT NULL,achieved_at INTEGER NOT NULL,UNIQUE(user_id,achievement_id))''')
        c.execute("SELECT achievement_id FROM achievements WHERE user_id=?",(uid,));existing={r[0] for r in c.fetchall()}
        checks={'first_game':tg>=1,'10_games':tg>=10,'50_games':tg>=50,'100_games':tg>=100,'500_games':tg>=500,'first_win':w>=1,'10_wins':w>=10,'50_wins':w>=50,'100_wins':w>=100,'big_win':wa>=500,'balance_1000':bal>=1000,'balance_5000':bal>=5000}
        new_achs=[];now=int(time.time())
        for aid,ach in checks.items():
            if ach and aid not in existing: c.execute("INSERT OR IGNORE INTO achievements(user_id,achievement_id,achieved_at) VALUES(?,?,?)",(uid,aid,now));new_achs.append(aid)
        conn.commit();conn.close();return new_achs
    return execute_sqlite_with_retry(_do)

def check_depositor_achievement(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS achievements(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,achievement_id TEXT NOT NULL,achieved_at INTEGER NOT NULL,UNIQUE(user_id,achievement_id))''')
        c.execute("INSERT OR IGNORE INTO achievements(user_id,achievement_id,achieved_at) VALUES(?,'depositor',?)",(uid,int(time.time())));conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def get_achievements_sync(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS achievements(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,achievement_id TEXT NOT NULL,achieved_at INTEGER NOT NULL,UNIQUE(user_id,achievement_id))''')
        c.execute("SELECT achievement_id,achieved_at FROM achievements WHERE user_id=? ORDER BY achieved_at DESC",(uid,));earned={r[0]:r[1] for r in c.fetchall()};conn.close();return earned
    return execute_sqlite_with_retry(_do)

def process_referral_sync(inviter_id, invited_id):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT invited_by FROM users WHERE user_id=?",(invited_id,));r=c.fetchone()
        if r and r[0] is not None: conn.close();return None
        c.execute("UPDATE users SET invited_by=? WHERE user_id=?",(inviter_id,invited_id))
        c.execute("SELECT balance FROM users WHERE user_id=?",(invited_id,));inv_bal=c.fetchone()[0]
        c.execute("UPDATE users SET balance=? WHERE user_id=?",(inv_bal+REFERRAL_BONUS_INVITED,invited_id))
        conn.commit();conn.close();return inviter_id
    return execute_sqlite_with_retry(_do)

def claim_referral_reward_sync(invited_id):
    """Начисляет бонус пригласившему после первой игры приглашённого"""
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT invited_by,referral_claimed FROM users WHERE user_id=?",(invited_id,));r=c.fetchone()
        if not r or not r[0]: conn.close();return None
        inviter_id=r[0];already=r[1] if len(r)>1 else 0
        if already: conn.close();return None
        c.execute("SELECT balance FROM users WHERE user_id=?",(inviter_id,));inv_bal=c.fetchone()[0]
        c.execute("UPDATE users SET balance=? WHERE user_id=?",(inv_bal+REFERRAL_BONUS_INVITER,inviter_id))
        c.execute("UPDATE users SET referral_claimed=1 WHERE user_id=?",(invited_id,))
        c.execute("UPDATE users SET referral_count=COALESCE(referral_count,0)+1 WHERE user_id=?",(inviter_id,))
        conn.commit();conn.close();return (inviter_id,inv_bal+REFERRAL_BONUS_INVITER)
    return execute_sqlite_with_retry(_do)

def get_referral_stats_sync(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE invited_by=?",(uid,));total=c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE invited_by=? AND total_games>0",(uid,));played=c.fetchone()[0]
        c.execute("SELECT user_id,username,total_games FROM users WHERE invited_by=? ORDER BY total_games DESC LIMIT 10",(uid,))
        friends=[{'user_id':r[0],'username':r[1] or f'ID{r[0]}','games':r[2]} for r in c.fetchall()];conn.close()
        return {'total':total,'played':played,'friends':friends}
    return execute_sqlite_with_retry(_do)

def get_admin_referral_stats_sync():
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE invited_by IS NOT NULL");total_refs=c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT invited_by) FROM users WHERE invited_by IS NOT NULL");active_refs=c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE referral_claimed=1");claimed=c.fetchone()[0]
        c.execute("SELECT u.user_id,u.username,u.referral_count,u.balance FROM users u WHERE u.referral_count>0 ORDER BY u.referral_count DESC LIMIT 20")
        top=[{'user_id':r[0],'username':r[1] or f'ID{r[0]}','count':r[2] or 0,'balance':r[3] or 0} for r in c.fetchall()]
        c.execute("SELECT COALESCE(SUM(referral_count),0) FROM users");total_ref_earnings=c.fetchone()[0]*REFERRAL_BONUS_INVITER
        conn.close()
        return {'total_referrals':total_refs,'active_referrers':active_refs,'claimed_rewards':claimed,'top_referrers':top,'total_earnings':total_ref_earnings}
    return execute_sqlite_with_retry(_do)

def claim_daily_bonus_sync(uid):
    now=int(time.time());today_start=now-(now%86400)
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        try: c.execute("ALTER TABLE users ADD COLUMN daily_bonus_last INTEGER DEFAULT 0")
        except: pass
        try: c.execute("ALTER TABLE users ADD COLUMN daily_bonus_streak INTEGER DEFAULT 0")
        except: pass
        c.execute("SELECT daily_bonus_last,daily_bonus_streak,balance FROM users WHERE user_id=?",(uid,));r=c.fetchone()
        if not r: conn.close();return None
        last,streak,bal=r[0] or 0,r[1] or 0,r[2]
        if last>=today_start: conn.close();return {'success':False,'error':'already_claimed','next':today_start+86400}
        yesterday=today_start-86400;new_streak=streak+1 if last>=yesterday else 1
        bonus=DAILY_BONUS_BASE+min(new_streak-1,7)*5
        new_bal=bal+bonus
        c.execute("UPDATE users SET daily_bonus_last=?,daily_bonus_streak=?,balance=? WHERE user_id=?",(now,new_streak,new_bal,uid))
        conn.commit();conn.close();return {'success':True,'bonus':bonus,'streak':new_streak,'new_balance':new_bal}
    return execute_sqlite_with_retry(_do)

def get_daily_bonus_status_sync(uid):
    now=int(time.time());today_start=now-(now%86400)
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT daily_bonus_last,daily_bonus_streak FROM users WHERE user_id=?",(uid,));r=c.fetchone()
        if not r: conn.close();return {'can_claim':True,'streak':0,'next_bonus':10}
        last,streak=r[0] or 0,r[1] or 0
        can=last<today_start;next_bonus=DAILY_BONUS_BASE+min(streak,7)*5
        conn.close();return {'can_claim':can,'streak':streak if last>=today_start-86400 else 0,'next_bonus':next_bonus}
    return execute_sqlite_with_retry(_do)

def get_last_ad_time_sync(uid):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT last_ad_watch FROM users WHERE user_id=?",(uid,));r=c.fetchone();conn.close();return r[0] if r else 0
    return execute_sqlite_with_retry(_do)

def set_last_ad_time_sync(uid, ts):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("UPDATE users SET last_ad_watch=? WHERE user_id=?",(ts,uid));conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def create_payment(user_id, amount_points, price_usdt, payment_id, invoice_id):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("INSERT INTO crypto_payments(user_id,amount_points,price_usdt,payment_id,invoice_id,status,created_at) VALUES(?,?,?,?,?,'pending',?)",(user_id,amount_points,price_usdt,payment_id,invoice_id,int(time.time())));conn.commit();conn.close()
    execute_sqlite_with_retry(_do)

def confirm_payment(payment_id):
    def _do():
        conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
        c.execute("SELECT user_id,amount_points,status FROM crypto_payments WHERE payment_id=?",(payment_id,));r=c.fetchone()
        if not r or r[2]!='pending': conn.close();return None
        uid,amount,_=r
        c.execute("UPDATE crypto_payments SET status='paid' WHERE payment_id=?",(payment_id,))
        c.execute("SELECT balance FROM users WHERE user_id=?",(uid,));bal=c.fetchone()[0]
        c.execute("UPDATE users SET balance=? WHERE user_id=?",(bal+amount,uid))
        conn.commit();conn.close();check_depositor_achievement(uid);return (uid,amount)
    return execute_sqlite_with_retry(_do, max_retries=10, delay=0.3)

def init_sqlite_db():
    conn=sqlite3.connect(DB_NAME);c=conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,balance INTEGER DEFAULT 0,total_games INTEGER DEFAULT 0,wins INTEGER DEFAULT 0,last_ad_watch INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS game_history(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,game_type TEXT NOT NULL,bet_amount INTEGER NOT NULL,win_amount INTEGER DEFAULT 0,played_at INTEGER NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS support_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,message TEXT NOT NULL,created_at INTEGER NOT NULL,is_read INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS crypto_payments(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,amount_points INTEGER NOT NULL,price_usdt REAL NOT NULL,payment_id TEXT UNIQUE NOT NULL,invoice_id TEXT,status TEXT DEFAULT 'pending',created_at INTEGER NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS achievements(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,achievement_id TEXT NOT NULL,achieved_at INTEGER NOT NULL,UNIQUE(user_id,achievement_id))''')
    for col,typ in [('display_name','TEXT'),('avatar_emoji',"TEXT DEFAULT '🦊'"),('invited_by','INTEGER DEFAULT NULL'),('referral_claimed','INTEGER DEFAULT 0'),('referral_count','INTEGER DEFAULT 0'),('last_cashback','INTEGER DEFAULT 0'),('daily_bonus_last','INTEGER DEFAULT 0'),('daily_bonus_streak','INTEGER DEFAULT 0')]:
        try: c.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
        except: pass
    conn.commit();conn.close()

bot=Bot(token=MAIN_BOT_TOKEN);storage=MemoryStorage();dp=Dispatcher(storage=storage)
dp.include_router(support_router);dp.include_router(admin_router);dp.include_router(user_router)

app=web.Application()
@web.middleware
async def cors_middleware(request,handler):
    if request.method=='OPTIONS':
        resp=web.Response();resp.headers['Access-Control-Allow-Origin']='*';resp.headers['Access-Control-Allow-Methods']='POST,GET,OPTIONS';resp.headers['Access-Control-Allow-Headers']='Content-Type,crypto-pay-api-sign';return resp
    resp=await handler(request);resp.headers['Access-Control-Allow-Origin']='*';return resp
app.middlewares.append(cors_middleware)

async def handle_get_balance(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        def _do():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            c.execute("SELECT balance FROM users WHERE user_id=?",(uid,));r=c.fetchone()
            if not r: c.execute("INSERT INTO users(user_id,balance,total_games,wins,avatar_emoji) VALUES(?,20,0,0,'🦊')",(uid,));conn.commit();conn.close();return 20
            conn.close();return r[0]
        bal=execute_sqlite_with_retry(_do);return web.json_response({'success':True,'balance':bal})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_get_profile(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        def _do():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            c.execute("SELECT balance,total_games,wins,display_name,avatar_emoji FROM users WHERE user_id=?",(uid,));r=c.fetchone()
            if not r: conn.close();return None
            bal,tg,w,dn,av=r[0],r[1],r[2],r[3] if len(r)>3 else None,r[4] if len(r)>4 else '🦊'
            c.execute("SELECT game_type,bet_amount,win_amount,played_at FROM game_history WHERE user_id=? ORDER BY played_at DESC LIMIT 10",(uid,));games=c.fetchall();conn.close()
            return (bal,tg,w,dn,av,games)
        result=execute_sqlite_with_retry(_do)
        if not result: return web.json_response({'success':False,'error':'User not found'},status=404)
        bal,tg,w,dn,av,games=result;losses=tg-w;wr=round(w/tg*100,1) if tg>0 else 0
        rg=[{'game':g[0],'bet':g[1],'win_amount':g[2],'result':'win' if g[2]>0 else 'lose','time':g[3]} for g in games]
        return web.json_response({'success':True,'profile':{'user_id':uid,'balance':bal,'total_games':tg,'wins':w,'losses':losses,'winrate':wr,'recent_games':rg,'display_name':dn,'avatar_emoji':av or '🦊'}})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_get_achievements(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        bal,tg,w=get_user_stats_sync(uid);earned=get_achievements_sync(uid)
        all_a=[]
        for aid,ad in ACHIEVEMENTS.items():
            prog=0
            if aid in['first_game','10_games','50_games','100_games','500_games']: prog=tg
            elif aid in['first_win','10_wins','50_wins','100_wins']: prog=w
            elif aid in['balance_1000','balance_5000']: prog=bal
            else: prog=1 if aid in earned else 0
            all_a.append({'id':aid,'name':ad['name'],'desc':ad['desc'],'icon':ad['icon'],'target':ad['target'],'progress':prog,'earned':aid in earned,'earned_at':earned.get(aid,0)})
        return web.json_response({'success':True,'achievements':all_a})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_save_profile(request):
    try:
        data=await request.json();uid=int(data.get('user_id'));dn=data.get('display_name','').strip();av=data.get('avatar_emoji','🦊')
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        if dn and len(dn)>30: return web.json_response({'success':False,'error':'Никнейм слишком длинный'},status=400)
        allowed=['🦊','🐺','🦁','🐯','🐻','🐼','🐨','🐰','🦄','🐲','🎃','🤖','👑','💀','👻']
        if av not in allowed: av='🦊'
        def _do(): conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor();c.execute("UPDATE users SET display_name=?,avatar_emoji=? WHERE user_id=?",(dn or None,av,uid));conn.commit();conn.close()
        execute_sqlite_with_retry(_do);return web.json_response({'success':True,'message':'Профиль сохранён!','display_name':dn,'avatar_emoji':av})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_game_result(request):
    try:
        data=await request.json();uid=int(data.get('user_id'));game=data.get('game');bet=data.get('bet');win=data.get('win');wa=data.get('win_amount',0)
        if not uid or not game or bet is None: return web.json_response({'success':False,'error':'Missing fields'},status=400)
        # Получаем количество игр ДО обновления
        tg_before = get_user_stats_sync(uid)[1]
        cur=get_balance_sync(uid);new=cur+wa if win else cur-bet
        update_balance_sync(uid,new);update_stats_sync(uid,win);save_game_history_sync(uid,bet,wa if win else 0,game)
        # Проверяем реферальный бонус после первой игры
        if tg_before == 0:
            claim_result = claim_referral_reward_sync(uid)
            if claim_result:
                try:
                    await bot.send_message(claim_result[0], f"🎉 Ваш друг сыграл первую игру!\n💰 Вы получили +{REFERRAL_BONUS_INVITER} 💎!")
                except:
                    pass
        bal,tg,w=get_user_stats_sync(uid);new_achs=check_achievements_sync(uid,new,tg,w,wa if win else 0)
        return web.json_response({'success':True,'new_balance':new,'win':win})
    except Exception as e:
        logger.error(f"game_result error: {e}")
        return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_referral_join(request):
    try:
        data=await request.json();invited=int(data.get('user_id'));inviter=int(data.get('inviter_id'))
        if not invited or not inviter: return web.json_response({'success':False,'error':'user_id and inviter_id required'},status=400)
        if invited==inviter: return web.json_response({'success':False,'error':'Cannot refer yourself'},status=400)
        result=process_referral_sync(inviter,invited)
        if result is None: return web.json_response({'success':False,'error':'Already referred'},status=200)
        return web.json_response({'success':True,'message':f'+{REFERRAL_BONUS_INVITED} баллов за переход!','bonus':REFERRAL_BONUS_INVITED})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_get_referral_stats(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        stats=get_referral_stats_sync(uid);stats['balance']=get_balance_sync(uid)
        return web.json_response({'success':True,'stats':stats})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_get_referral_link(request):
    try:
        data=await request.json();uid=data.get('user_id')
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        link=f"https://t.me/GamesAsino_bot/GamesAsino?startapp=ref_{uid}"
        return web.json_response({'success':True,'link':link,'user_id':uid})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_get_admin_referral_stats(request):
    try:
        data=await request.json();uid=int(data.get('user_id','0'))
        if uid not in ADMIN_IDS: return web.json_response({'success':False,'error':'Access denied'},status=403)
        stats=get_admin_referral_stats_sync()
        return web.json_response({'success':True,'stats':stats})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_daily_bonus(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        result=claim_daily_bonus_sync(uid)
        if not result: return web.json_response({'success':False,'error':'User not found'},status=404)
        if result.get('error')=='already_claimed': return web.json_response({'success':False,'error':'already_claimed','next':result['next']})
        return web.json_response({'success':True,'bonus':result['bonus'],'streak':result['streak'],'new_balance':result['new_balance']})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_daily_bonus_status(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        status=get_daily_bonus_status_sync(uid)
        return web.json_response({'success':True,'status':status})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_claim_ad_reward(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        last_ad=get_last_ad_time_sync(uid);now=int(time.time())
        if last_ad and now-last_ad<AD_COOLDOWN_SECONDS:
            remaining=AD_COOLDOWN_SECONDS-(now-last_ad)
            return web.json_response({'success':False,'error':'cooldown','remaining':remaining},status=200)
        cur=get_balance_sync(uid);new=cur+AD_REWARD_AMOUNT
        update_balance_sync(uid,new);set_last_ad_time_sync(uid,now)
        return web.json_response({'success':True,'new_balance':new,'reward':AD_REWARD_AMOUNT})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_claim_free_bonus(request):
    try:
        data=await request.json();uid=int(data.get('user_id'))
        if not uid: return web.json_response({'success':False,'error':'user_id required'},status=400)
        last_ad=get_last_ad_time_sync(uid);now=int(time.time())
        if last_ad and now-last_ad<AD_COOLDOWN_SECONDS:
            remaining=AD_COOLDOWN_SECONDS-(now-last_ad)
            return web.json_response({'success':False,'error':'cooldown','remaining':remaining},status=200)
        cur=get_balance_sync(uid);new=cur+FREE_BONUS_AMOUNT
        update_balance_sync(uid,new);set_last_ad_time_sync(uid,now)
        return web.json_response({'success':True,'new_balance':new,'reward':FREE_BONUS_AMOUNT})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_create_invoice(request):
    try:
        data=await request.json();uid=int(data.get('user_id'));amount_points=data.get('amount_points')
        if not uid or not amount_points: return web.json_response({'success':False,'error':'user_id and amount_points required'},status=400)
        amount_points=int(amount_points)
        if amount_points not in PRICE_LIST: return web.json_response({'success':False,'error':'Invalid amount'},status=400)
        price_usdt=PRICE_LIST[amount_points]
        async with aiohttp.ClientSession() as session:
            headers={'Crypto-Pay-API-Token':CRYPTOPAY_TOKEN,'Content-Type':'application/json'}
            payload={'asset':'USDT','amount':str(price_usdt),'description':f'Пополнение {amount_points} баллов для Game Bar Casino','payload':json.dumps({'user_id':uid,'amount_points':amount_points}),'allow_comments':False,'allow_anonymous':False}
            try:
                async with session.post(f'{CRYPTOPAY_API_URL}/createInvoice',json=payload,headers=headers) as resp: result=await resp.json()
            except Exception as e: return web.json_response({'success':False,'error':f'CryptoPay API error: {str(e)}'},status=500)
            if not result.get('ok'): return web.json_response({'success':False,'error':f'CryptoPay error: {result.get("error","unknown")}'},status=500)
            invoice=result['result'];payment_id=str(invoice['invoice_id']);invoice_url=invoice['pay_url']
            create_payment(uid,amount_points,price_usdt,payment_id,str(invoice['invoice_id']))
            return web.json_response({'success':True,'payment_id':payment_id,'invoice_url':invoice_url,'amount_points':amount_points,'price_usdt':price_usdt})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_check_payment(request):
    try:
        data=await request.json();payment_id=data.get('payment_id');uid=data.get('user_id')
        if not payment_id and uid:
            def _find():
                conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
                c.execute("SELECT payment_id,amount_points,status FROM crypto_payments WHERE user_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1",(int(uid),));r=c.fetchone();conn.close();return r
            row=execute_sqlite_with_retry(_find)
            if not row:
                def _find_paid():
                    conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
                    c.execute("SELECT payment_id,amount_points FROM crypto_payments WHERE user_id=? AND status='paid' ORDER BY created_at DESC LIMIT 1",(int(uid),));paid_row=c.fetchone();conn.close();return paid_row
                paid_row=execute_sqlite_with_retry(_find_paid)
                if paid_row:
                    new_balance=get_balance_sync(int(uid))
                    return web.json_response({'success':True,'status':'already_credited','message':f'✅ Баллы уже начислены! ({paid_row[1]} 💎)','new_balance':new_balance,'amount_points':paid_row[1]})
                return web.json_response({'success':True,'status':'no_pending','message':'Нет ожидающих платежей.'})
            payment_id=row[0]
        if not payment_id: return web.json_response({'success':False,'error':'payment_id required'},status=400)
        def _check_local():
            conn=sqlite3.connect(DB_NAME,timeout=10);conn.execute("PRAGMA busy_timeout=5000");c=conn.cursor()
            c.execute("SELECT user_id,amount_points,status FROM crypto_payments WHERE payment_id=?",(payment_id,));r=c.fetchone();conn.close();return r
        row=execute_sqlite_with_retry(_check_local)
        if row and row[2]=='paid':
            new_balance=get_balance_sync(row[0])
            return web.json_response({'success':True,'status':'paid','amount_points':row[1],'new_balance':new_balance,'message':f'✅ Начислено {row[1]} баллов!'})
        async with aiohttp.ClientSession() as session:
            headers={'Crypto-Pay-API-Token':CRYPTOPAY_TOKEN,'Content-Type':'application/json'}
            params={'invoice_ids':payment_id}
            try:
                async with session.get(f'{CRYPTOPAY_API_URL}/getInvoices',params=params,headers=headers,timeout=10) as resp: result=await resp.json()
            except Exception: return web.json_response({'success':True,'status':'api_error','message':'⏳ Ошибка связи с CryptoPay.'})
            if not result.get('ok') or not result['result']['items']: return web.json_response({'success':True,'status':'not_found','message':'❌ Счёт не найден.'})
            invoice=result['result']['items'][0]
            if invoice['status']=='paid':
                confirmed=confirm_payment(payment_id)
                if confirmed:
                    uid,amount=confirmed;new_balance=get_balance_sync(uid)
                    return web.json_response({'success':True,'status':'paid','user_id':uid,'amount_points':amount,'new_balance':new_balance,'message':f'✅ Начислено {amount} баллов!'})
                return web.json_response({'success':True,'status':'already_credited','message':'✅ Баллы уже начислены.'})
            return web.json_response({'success':True,'status':invoice['status'],'message':f'⏳ Статус: {invoice["status"]}.'})
    except Exception as e: return web.json_response({'success':False,'error':str(e)},status=500)

async def handle_crypto_webhook(request):
    try:
        body=await request.text();signature=request.headers.get('crypto-pay-api-sign','')
        secret=hashlib.sha256(CRYPTOPAY_TOKEN.encode()).digest()
        expected_signature=hmac.new(secret,body.encode(),hashlib.sha256).hexdigest()
        if signature!=expected_signature: return web.json_response({'error':'Invalid signature'},status=403)
        data=json.loads(body)
        if data.get('update_type')=='invoice_paid':
            invoice_id=str(data['payload']['invoice_id']);confirmed=confirm_payment(invoice_id)
            if confirmed:
                uid,amount=confirmed
                try: await bot.send_message(uid,f"✅ <b>Платёж подтверждён!</b>\n\n💰 Начислено: <b>{amount} 💎</b>\n💵 Сумма: <b>{PRICE_LIST.get(amount,'?')} USDT</b>\n\nСпасибо за пополнение! 🎉",parse_mode="HTML")
                except: pass
        return web.json_response({'success':True})
    except Exception as e: return web.json_response({'error':str(e)},status=500)

async def handle_get_price_list(request):
    return web.json_response({'success':True,'prices':{str(k):v for k,v in PRICE_LIST.items()}})

async def health(request): return web.json_response({'status':'ok'})

async def handle_webhook(request):
    update=types.Update(**await request.json());await dp.feed_update(bot,update);return web.Response()

app.router.add_post('/webhook',handle_webhook)
app.router.add_post('/api/get_balance',handle_get_balance)
app.router.add_post('/api/get_profile',handle_get_profile)
app.router.add_post('/api/get_achievements',handle_get_achievements)
app.router.add_post('/api/save_profile',handle_save_profile)
app.router.add_post('/api/game_result',handle_game_result)
app.router.add_post('/api/claim_ad_reward',handle_claim_ad_reward)
app.router.add_post('/api/claim_free_bonus',handle_claim_free_bonus)
app.router.add_post('/api/referral_join',handle_referral_join)
app.router.add_post('/api/get_referral_stats',handle_get_referral_stats)
app.router.add_post('/api/get_referral_link',handle_get_referral_link)
app.router.add_post('/api/get_admin_referral_stats',handle_get_admin_referral_stats)
app.router.add_post('/api/daily_bonus',handle_daily_bonus)
app.router.add_post('/api/daily_bonus_status',handle_daily_bonus_status)
app.router.add_post('/api/create_invoice',handle_create_invoice)
app.router.add_post('/api/check_payment',handle_check_payment)
app.router.add_post('/api/crypto_webhook',handle_crypto_webhook)
app.router.add_get('/api/get_price_list',handle_get_price_list)
app.router.add_get('/health',health);app.router.add_get('/',health)

async def on_startup():
    await init_db_pool();await create_db();init_sqlite_db()
    await bot.set_my_commands([BotCommand(command="start",description="Запустить бота"),BotCommand(command="myid",description="Мой Telegram ID"),BotCommand(command="admin",description="Админ-панель")])
    logger.info("Бот запущен")

async def on_shutdown(): await bot.session.close();await close_db_pool()

async def main():
    port=int(os.environ.get('PORT',10000));await on_startup()
    await bot.delete_webhook();await bot.set_webhook("https://game-bar-bot.onrender.com/webhook")
    runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'0.0.0.0',port);await site.start()
    logger.info(f"Сервер на порту {port}")
    try: await asyncio.Future()
    finally: await on_shutdown()

if __name__=="__main__": asyncio.run(main())
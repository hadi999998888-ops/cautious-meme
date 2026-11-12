# -*- coding: utf-8 -*-
"""Angelok Hub WebApp/API. Uses the same SQLite database as bot_easy.py."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from aiogram.types import LabeledPrice

from config import BOT_TOKEN, OPENROUTER_API_KEY, WEB_HOST, WEB_PORT

log = logging.getLogger("angelok.web")
BASE = Path(__file__).resolve().parent
DB_PATH = BASE / os.getenv("DB_FILENAME", "angelok_hub.db")
INDEX = BASE / "index.html"
AI_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
MAX_MESSAGE = 4000


def connect():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS web_profiles (
      user_id INTEGER PRIMARY KEY,
      username TEXT UNIQUE COLLATE NOCASE,
      display_name TEXT NOT NULL DEFAULT '',
      avatar TEXT NOT NULL DEFAULT '',
      privacy TEXT NOT NULL DEFAULT 'all',
      extra_chats INTEGER NOT NULL DEFAULT 0,
      verified INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS web_dialogs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_a INTEGER NOT NULL,
      user_b INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(user_a,user_b)
    );
    CREATE TABLE IF NOT EXISTS web_messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      dialog_id INTEGER NOT NULL,
      sender_id INTEGER NOT NULL,
      body TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_web_messages_dialog ON web_messages(dialog_id,id);
    CREATE TABLE IF NOT EXISTS web_purchases (
      id TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL,
      chats INTEGER NOT NULL,
      stars INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      telegram_charge_id TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      paid_at TEXT
    );
    """)
    # Existing bot database has users/friend_profiles tables.
    c.commit()
    return c


def validate_init_data(init_data: str):
    if not init_data or len(init_data) > 10000:
        raise web.HTTPUnauthorized(text="Откройте сайт через Telegram-бота.")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise web.HTTPUnauthorized(text="Не найдена подпись Telegram.")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise web.HTTPUnauthorized(text="Не удалось подтвердить Telegram-аккаунт.")
    try:
        auth_date = int(pairs.get("auth_date", "0"))
        user = json.loads(pairs["user"])
    except Exception:
        raise web.HTTPUnauthorized(text="Некорректные данные Telegram.")
    if time.time() - auth_date > 86400 or auth_date > time.time() + 60:
        raise web.HTTPUnauthorized(text="Сессия устарела. Перезапустите мини-приложение.")
    if not user.get("id"):
        raise web.HTTPUnauthorized(text="Не найден ID пользователя.")
    return user


@web.middleware
async def auth_middleware(request, handler):
    if request.path == "/" or request.path == "/health":
        return await handler(request)
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    request["tg_user"] = validate_init_data(init_data)
    return await handler(request)


def me_id(request):
    return int(request["tg_user"]["id"])


def ensure_user(c, tg):
    uid = int(tg["id"])
    first = (tg.get("first_name") or tg.get("username") or "Игрок")[:64]
    username_tg = tg.get("username")
    c.execute("""INSERT INTO users(user_id,username,first_name,registered_at,last_seen)
                 VALUES(?,?,?,?,CURRENT_TIMESTAMP)
                 ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
                 first_name=excluded.first_name,last_seen=CURRENT_TIMESTAMP""",
              (uid, username_tg, first, time.strftime("%Y-%m-%dT%H:%M:%S")))
    c.execute("INSERT OR IGNORE INTO web_profiles(user_id,display_name) VALUES(?,?)", (uid, first))
    c.commit()


def profile_json(c, uid):
    row = c.execute("""SELECT w.*, f.nickname, f.standoff_id, f.age, f.soft, f.about, f.visible
                       FROM web_profiles w LEFT JOIN friend_profiles f ON f.user_id=w.user_id
                       WHERE w.user_id=?""", (uid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["chat_limit"] = 2 + int(d.get("extra_chats") or 0)
    return d


def user_card(c, uid, viewer):
    row = c.execute("""SELECT w.user_id,w.username,w.display_name,w.avatar,w.verified,
                       f.nickname,f.standoff_id,f.age,f.soft,f.about
                       FROM web_profiles w JOIN friend_profiles f ON f.user_id=w.user_id
                       WHERE w.user_id=? AND f.visible=1""", (uid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    # Respect privacy setting: username is visible only when user allows it.
    if d["user_id"] != viewer:
        privacy = c.execute("SELECT privacy FROM web_profiles WHERE user_id=?", (uid,)).fetchone()
        if privacy and privacy["privacy"] == "hidden":
            d["username"] = None
    return d


async def index(_):
    if not INDEX.exists():
        raise web.HTTPNotFound(text="index.html не найден")
    return web.FileResponse(INDEX)


async def health(_):
    return web.json_response({"ok": True, "service": "Angelok Hub"})


async def api_me(request):
    tg = request["tg_user"]
    c = connect()
    try:
        ensure_user(c, tg)
        return web.json_response({"telegram": {"id": tg["id"], "first_name": tg.get("first_name","")},
                                  "profile": profile_json(c, int(tg["id"]))})
    finally:
        c.close()


async def api_profile(request):
    tg = request["tg_user"]; uid = int(tg["id"])
    data = await request.json()
    nickname = str(data.get("nickname","")).strip()
    game_id = re.sub(r"\s+", "", str(data.get("standoff_id","")))
    age = int(data.get("age", 0) or 0)
    soft = 1 if data.get("soft") in (1, True, "1", "yes") else 0
    about = str(data.get("about","")).strip()[:300]
    username = str(data.get("username","")).strip().lstrip("@").lower()
    display = str(data.get("display_name","")).strip()[:32] or nickname
    avatar = str(data.get("avatar",""))
    if not 2 <= len(nickname) <= 24 or not re.fullmatch(r"\d{4,15}", game_id) or not 7 <= age <= 99:
        raise web.HTTPBadRequest(text="Проверь ник, игровой ID и возраст.")
    if username and not re.fullmatch(r"[a-z0-9_]{4,20}", username):
        raise web.HTTPBadRequest(text="Username: 4–20 символов, латиница, цифры и _.")
    if avatar and (not avatar.startswith("data:image/") or len(avatar) > 1_500_000):
        raise web.HTTPBadRequest(text="Аватар должен быть изображением до 1 МБ.")
    c = connect()
    try:
        ensure_user(c, tg)
        if username:
            conflict = c.execute("SELECT user_id FROM web_profiles WHERE username=? COLLATE NOCASE AND user_id<>?",
                                 (username, uid)).fetchone()
            if conflict:
                raise web.HTTPConflict(text="Этот username уже занят.")
        c.execute("""UPDATE web_profiles SET username=?,display_name=?,avatar=? WHERE user_id=?""",
                  (username or None, display, avatar, uid))
        c.execute("""INSERT INTO friend_profiles(user_id,nickname,standoff_id,age,soft,visible,about,photo_id,created_at,updated_at)
                     VALUES(?,?,?,?,?,1,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                     ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname,standoff_id=excluded.standoff_id,
                     age=excluded.age,soft=excluded.soft,about=excluded.about,updated_at=CURRENT_TIMESTAMP""",
                  (uid,nickname,game_id,age,soft,about,None))
        c.commit()
        return web.json_response({"ok": True, "profile": profile_json(c, uid)})
    finally:
        c.close()


async def api_privacy(request):
    uid = me_id(request); data = await request.json()
    privacy = data.get("privacy")
    if privacy not in ("all", "hidden"):
        raise web.HTTPBadRequest(text="Некорректная настройка приватности.")
    c=connect()
    try:
        c.execute("UPDATE web_profiles SET privacy=? WHERE user_id=?", (privacy,uid)); c.commit()
        return web.json_response({"ok":True})
    finally: c.close()


async def api_search(request):
    uid=me_id(request); q=request.query.get("q","").strip().lstrip("@")[:32]
    c=connect()
    try:
        ensure_user(c, request["tg_user"])
        sql="""SELECT w.user_id,w.username,w.display_name,w.avatar,w.verified,
                      f.nickname,f.standoff_id,f.age,f.soft,f.about
               FROM web_profiles w JOIN friend_profiles f ON f.user_id=w.user_id
               WHERE w.user_id<>? AND f.visible=1
               AND NOT EXISTS (SELECT 1 FROM friend_blocks b WHERE
                 (b.blocker_id=? AND b.blocked_id=w.user_id) OR
                 (b.blocker_id=w.user_id AND b.blocked_id=?))"""
        params=[uid,uid,uid]
        if q:
            sql += " AND (w.username LIKE ? OR f.nickname LIKE ?)"
            params += [f"%{q}%",f"%{q}%"]
        sql += " ORDER BY w.verified DESC,f.updated_at DESC LIMIT 60"
        rows=c.execute(sql,params).fetchall()
        result=[]
        for row in rows:
            d=dict(row)
            if d["user_id"] != uid:
                pr=c.execute("SELECT privacy FROM web_profiles WHERE user_id=?", (d["user_id"],)).fetchone()
                if pr and pr["privacy"]=="hidden": d["username"]=None
            result.append(d)
        return web.json_response({"users":result})
    finally:c.close()


def pair(a,b): return (min(a,b),max(a,b))


def get_or_create_dialog(c,a,b):
    x,y=pair(a,b)
    c.execute("INSERT OR IGNORE INTO web_dialogs(user_a,user_b) VALUES(?,?)",(x,y))
    c.commit()
    return c.execute("SELECT * FROM web_dialogs WHERE user_a=? AND user_b=?",(x,y)).fetchone()


def chat_limit_ok(c,uid):
    p=c.execute("SELECT extra_chats FROM web_profiles WHERE user_id=?",(uid,)).fetchone()
    limit=2+(int(p["extra_chats"]) if p else 0)
    used=c.execute("SELECT COUNT(*) FROM web_dialogs WHERE user_a=? OR user_b=?",(uid,uid)).fetchone()[0]
    return used < limit, used, limit


async def api_chats(request):
    uid=me_id(request); c=connect()
    try:
        ensure_user(c,request["tg_user"])
        rows=c.execute("""SELECT d.id,d.user_a,d.user_b,d.created_at,
            (SELECT body FROM web_messages m WHERE m.dialog_id=d.id ORDER BY m.id DESC LIMIT 1) last_message,
            (SELECT created_at FROM web_messages m WHERE m.dialog_id=d.id ORDER BY m.id DESC LIMIT 1) last_at
            FROM web_dialogs d WHERE d.user_a=? OR d.user_b=? ORDER BY COALESCE(last_at,d.created_at) DESC""",(uid,uid)).fetchall()
        chats=[]
        for r in rows:
            peer=r["user_b"] if r["user_a"]==uid else r["user_a"]
            card=user_card(c,peer,uid)
            if card: chats.append({"dialog_id":r["id"],"peer":card,"last_message":r["last_message"] or "Начните общение","last_at":r["last_at"]})
        p=profile_json(c,uid)
        return web.json_response({"chats":chats,"used":len(chats),"limit":p["chat_limit"] if p else 2})
    finally:c.close()


async def api_open_chat(request):
    uid=me_id(request); peer=int(request.match_info["peer"])
    if peer==uid: raise web.HTTPBadRequest(text="Нельзя открыть чат с собой.")
    c=connect()
    try:
        ensure_user(c,request["tg_user"])
        if c.execute("SELECT 1 FROM friend_blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
                     (uid,peer,peer,uid)).fetchone():
            raise web.HTTPForbidden(text="Чат недоступен.")
        if not user_card(c,peer,uid): raise web.HTTPNotFound(text="Игрок не найден.")
        exists=c.execute("SELECT id FROM web_dialogs WHERE user_a=? AND user_b=?",pair(uid,peer)).fetchone()
        if not exists:
            ok,used,limit=chat_limit_ok(c,uid)
            if not ok: raise web.HTTPPaymentRequired(text=f"Лимит чатов исчерпан: {used}/{limit}. Откройте профиль → Подписки.")
            ok2,used2,limit2=chat_limit_ok(c,peer)
            if not ok2: raise web.HTTPConflict(text="У этого игрока временно достигнут лимит новых чатов.")
        d=get_or_create_dialog(c,uid,peer)
        return web.json_response({"dialog_id":d["id"],"peer":user_card(c,peer,uid)})
    finally:c.close()


async def api_messages(request):
    uid=me_id(request); peer=int(request.match_info["peer"]); c=connect()
    try:
        x,y=pair(uid,peer)
        d=c.execute("SELECT id FROM web_dialogs WHERE user_a=? AND user_b=?",(x,y)).fetchone()
        if not d: raise web.HTTPNotFound(text="Чат ещё не создан.")
        after=int(request.query.get("after","0"))
        rows=c.execute("SELECT id,sender_id,body,created_at FROM web_messages WHERE dialog_id=? AND id>? ORDER BY id LIMIT 100",
                       (d["id"],after)).fetchall()
        return web.json_response({"messages":[dict(r) for r in rows],"dialog_id":d["id"]})
    finally:c.close()


async def api_send_message(request):
    uid=me_id(request); peer=int(request.match_info["peer"]); data=await request.json()
    body=str(data.get("body","")).strip()
    if not body or len(body)>MAX_MESSAGE: raise web.HTTPBadRequest(text="Сообщение пустое или слишком длинное.")
    c=connect()
    try:
        x,y=pair(uid,peer)
        d=c.execute("SELECT id FROM web_dialogs WHERE user_a=? AND user_b=?",(x,y)).fetchone()
        if not d: raise web.HTTPNotFound(text="Чат не найден.")
        if c.execute("SELECT 1 FROM friend_blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
                     (uid,peer,peer,uid)).fetchone(): raise web.HTTPForbidden(text="Чат недоступен.")
        cur=c.execute("INSERT INTO web_messages(dialog_id,sender_id,body) VALUES(?,?,?)",(d["id"],uid,body))
        c.commit()
        row=c.execute("SELECT id,sender_id,body,created_at FROM web_messages WHERE id=?",(cur.lastrowid,)).fetchone()
        return web.json_response(dict(row))
    finally:c.close()


async def api_purchase(request):
    uid=me_id(request); data=await request.json()
    pack=data.get("pack")
    if pack not in ("5","10"): raise web.HTTPBadRequest(text="Неизвестный пакет.")
    chats=int(pack); stars=chats
    purchase_id=uuid.uuid4().hex
    payload=f"ah_limit:{purchase_id}:{uid}"
    c=connect()
    try:
        ensure_user(c,request["tg_user"])
        c.execute("INSERT INTO web_purchases(id,user_id,chats,stars) VALUES(?,?,?,?)",
                  (purchase_id,uid,chats,stars)); c.commit()
    finally:c.close()
    try:
        link=await request.app["bot"].create_invoice_link(
            title=f"Angelok Hub: +{chats} чатов",
            description=f"Дополнительный лимит на {chats} личных чатов.",
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"+{chats} чатов",amount=stars)]
        )
    except Exception:
        c=connect()
        try:c.execute("UPDATE web_purchases SET status='error' WHERE id=?",(purchase_id,));c.commit()
        finally:c.close()
        log.exception("Invoice link creation failed")
        raise web.HTTPBadGateway(text="Не удалось создать оплату. Попробуйте позже.")
    return web.json_response({"purchase_id":purchase_id,"invoice_url":link})


async def api_purchase_status(request):
    uid=me_id(request); pid=request.match_info["pid"]; c=connect()
    try:
        row=c.execute("SELECT status,chats,stars FROM web_purchases WHERE id=? AND user_id=?",(pid,uid)).fetchone()
        if not row: raise web.HTTPNotFound(text="Покупка не найдена.")
        p=profile_json(c,uid)
        return web.json_response({"status":row["status"],"chats":row["chats"],"stars":row["stars"],
                                  "profile":p})
    finally:c.close()


async def api_ai(request):
    uid=me_id(request); data=await request.json()
    prompt=str(data.get("message","")).strip()[:2000]
    if not prompt: raise web.HTTPBadRequest(text="Введите сообщение.")
    c=connect()
    try:
        ensure_user(c,request["tg_user"])
        history=c.execute("SELECT role,content FROM ai_history WHERE user_id=? ORDER BY id DESC LIMIT 10",(uid,)).fetchall()
    finally:c.close()
    messages=[{"role":"system","content":"Ты — дружелюбный помощник Angelok Hub. Отвечай по-русски, кратко и безопасно."}]
    messages += [{"role":r["role"],"content":r["content"]} for r in reversed(history)]
    messages.append({"role":"user","content":prompt})
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY.startswith("ВСТАВИТЬ"):
        return web.json_response({"answer":"ИИ временно недоступен: владелец ещё не настроил API-ключ."})
    import aiohttp as http
    async with http.ClientSession(timeout=http.ClientTimeout(total=60)) as s:
        async with s.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"},
            json={"model":AI_MODEL,"messages":messages,"max_tokens":1000}) as resp:
            raw=await resp.text()
            if resp.status>=400: raise web.HTTPBadGateway(text="ИИ временно не ответил.")
            obj=json.loads(raw); answer=obj["choices"][0]["message"].get("content") or "Не удалось получить ответ."
    c=connect()
    try:
        c.execute("INSERT INTO ai_history(user_id,role,content,created_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",(uid,"user",prompt))
        c.execute("INSERT INTO ai_history(user_id,role,content,created_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",(uid,"assistant",answer))
        c.commit()
    finally:c.close()
    return web.json_response({"answer":answer})


def create_app(bot):
    app=web.Application(middlewares=[auth_middleware],client_max_size=2*1024*1024)
    app["bot"]=bot
    app.router.add_get("/",index)
    app.router.add_get("/health",health)
    app.router.add_get("/api/me",api_me)
    app.router.add_post("/api/profile",api_profile)
    app.router.add_post("/api/privacy",api_privacy)
    app.router.add_get("/api/users",api_search)
    app.router.add_get("/api/chats",api_chats)
    app.router.add_post("/api/chats/{peer}/open",api_open_chat)
    app.router.add_get("/api/chats/{peer}/messages",api_messages)
    app.router.add_post("/api/chats/{peer}/messages",api_send_message)
    app.router.add_post("/api/purchase",api_purchase)
    app.router.add_get("/api/purchase/{pid}",api_purchase_status)
    app.router.add_post("/api/ai",api_ai)
    return app


async def start_web_server(bot):
    runner=web.AppRunner(create_app(bot),access_log=log)
    await runner.setup()
    site=web.TCPSite(runner,WEB_HOST,WEB_PORT)
    await site.start()
    log.info("Angelok Hub WebApp listening on %s:%s",WEB_HOST,WEB_PORT)
    return runner

import os
import sys
import asyncio
import json
import ssl
import uuid
import re
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime
from typing import Any, Optional, Union
import aiohttp
from aiohttp import web

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_BASE = os.getenv("MAX_API_BASE", "https://platform-api2.max.ru").rstrip("/")
TOKEN = os.getenv("MAX_BOT_TOKEN", "").strip()
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("MAX_WEBHOOK_SECRET", "").strip()
PORT = int(os.getenv("PORT", "8080"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/buro_bot")


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn

def init_db() -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    user_id BIGINT NOT NULL,
                    chat_id BIGINT,
                    user_name TEXT,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    place TEXT NOT NULL,
                    details TEXT,
                    photo_id TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS photo_id TEXT;")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS admin_codes (
                    code TEXT PRIMARY KEY,
                    used_by BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("INSERT INTO admin_codes (code) VALUES ('HACKATHON_ADMIN') ON CONFLICT DO NOTHING;")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    chat_id BIGINT,
                    user_name TEXT,
                    state TEXT,
                    state_data TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_admin BOOLEAN DEFAULT FALSE
                )
            """)
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;")
    print("bd ok")

def db_is_admin(user_id: int) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT is_admin FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return bool(row[0]) if row else False

def db_get_user(user_id: int) -> dict:
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                return {"user_id": user_id, "state": None, "data": {}, "chat_id": None, "user_name": None}
            data = {}
            if row["state_data"]:
                try:
                    data = json.loads(row["state_data"])
                except Exception:
                    data = {}
            return {
                "user_id": user_id,
                "state": row["state"],
                "data": data,
                "chat_id": row["chat_id"],
                "user_name": row["user_name"],
            }

def db_set_user(user_id: int, chat_id: Optional[int] = None, user_name: Optional[str] = None,
                state: Optional[str] = None, data: Optional[dict] = None) -> None:
    current = db_get_user(user_id)
    new_chat_id = chat_id if chat_id is not None else current.get("chat_id")
    new_user_name = user_name if user_name is not None else current.get("user_name")
    new_state = state if state is not None else current.get("state")
    new_data = data if data is not None else current.get("data", {})
    data_json = json.dumps(new_data, ensure_ascii=False)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, chat_id, user_name, state, state_data, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    chat_id = COALESCE(EXCLUDED.chat_id, users.chat_id),
                    user_name = COALESCE(EXCLUDED.user_name, users.user_name),
                    state = EXCLUDED.state,
                    state_data = EXCLUDED.state_data,
                    updated_at = CURRENT_TIMESTAMP
            """, (user_id, new_chat_id, new_user_name, new_state, data_json))

def db_clear_state(user_id: int) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users SET state = NULL, state_data = '{}', updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s
            """, (user_id,))

def db_create_item(item_type: str, user_id: int, chat_id: Optional[int], user_name: str,
                   title: str, category: str, place: str, details: str = "", photo_id: Optional[str] = None) -> str:
    item_id = str(uuid.uuid4())[:8]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO items (id, type, user_id, chat_id, user_name, title, category, place, details, photo_id, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
            """, (item_id, item_type, user_id, chat_id, user_name, title, category, place, details, photo_id))
    return item_id

def db_get_item(item_id: str) -> Optional[dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("SELECT * FROM items WHERE id = %s", (item_id,))
            row = cur.fetchone()
            return dict(row) if row else None

def db_get_user_items(user_id: int, status: str = "active") -> list[dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            cur.execute("""
                SELECT * FROM items WHERE user_id = %s AND status = %s
                ORDER BY created_at DESC
            """, (user_id, status))
            return [dict(r) for r in cur.fetchall()]

def db_get_active_items(item_type: str, limit: int = 10, category: Optional[str] = None) -> list[dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cur:
            if category:
                cur.execute("""
                    SELECT * FROM items WHERE type = %s AND status = 'active' AND category = %s
                    ORDER BY created_at DESC LIMIT %s
                """, (item_type, category, limit))
            else:
                cur.execute("""
                    SELECT * FROM items WHERE type = %s AND status = 'active'
                    ORDER BY created_at DESC LIMIT %s
                """, (item_type, limit))
            return [dict(r) for r in cur.fetchall()]

def db_resolve_item(item_id: str, user_id: int) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE items SET status = 'resolved'
                WHERE id = %s AND user_id = %s
            """, (item_id, user_id))
            return cur.rowcount > 0

def db_delete_item(item_id: str, user_id: int) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE items SET status = 'cancelled'
                WHERE id = %s AND user_id = %s
            """, (item_id, user_id))
            return cur.rowcount > 0

# фильтр на мат и спам
BAD_WORDS = [
    "спам", "реклама", "казино", "ставки", "оскорбление", "мат"
]

def check_text(text: str) -> tuple[bool, str]:
    if not text or not text.strip():
        return False, "Текст не может быть пустым."
    t = text.lower()
    for w in BAD_WORDS:
        if w in t:
            return False, "Текст содержит недопустимые слова. Пожалуйста, соблюдайте школьные правила."
    return True, ""


def extract_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", (text or "").lower())
    stop_words = {
        "в", "на", "с", "и", "под", "у", "около", "из", "за", "к", "по", "для",
        "от", "или", "что", "где", "как", "был", "была", "были", "это", "там"
    }
    return {w for w in words if len(w) >= 3 and w not in stop_words}

def find_matches(title: str, category: str, place: str, target_type: str,
                 exclude_user_id: Optional[int] = None) -> list[dict]:
    candidates = db_get_active_items(target_type, limit=50)
    q_tokens = extract_tokens(title)
    q_places = extract_tokens(place)
    matches = []

    for c in candidates:
        if exclude_user_id and c["user_id"] == exclude_user_id:
            continue

        score = 0
        if category and c["category"] == category:
            score += 4

        c_tokens = extract_tokens(c["title"])
        common_words = q_tokens.intersection(c_tokens)
        score += len(common_words) * 5

        for w1 in q_tokens:
            if w1 not in common_words and len(w1) >= 4:
                for w2 in c_tokens:
                    if w2 not in common_words and len(w2) >= 4 and w1[:4] == w2[:4]:
                        score += 3
                        break

        c_places = extract_tokens(c["place"])
        common_places = q_places.intersection(c_places)
        score += len(common_places) * 3

        q_nums = set(re.findall(r"\d+", place or ""))
        c_nums = set(re.findall(r"\d+", c["place"] or ""))
        if q_nums and c_nums and (q_nums & c_nums):
            score += 4

        if score >= 5:
            matches.append({"item": c, "score": score})

    matches.sort(key=lambda x: x["score"], reverse=True)
    return [m["item"] for m in matches[:3]]

# кнопки клавиатуры
def kb_admin() -> dict:
    return {
        "buttons": [
            [{"type": "callback", "text": "🗑 Удалить объявление", "payload": "admin_delete"},
             {"type": "callback", "text": "📢 Рассылка", "payload": "admin_broadcast"}],
            [{"type": "callback", "text": "🔑 Создать код доступа", "payload": "admin_generate_code"},
             {"type": "callback", "text": "📋 Список админов", "payload": "admin_list"}],
            [{"type": "callback", "text": "❌ Снять админа", "payload": "admin_revoke"},
             {"type": "callback", "text": "🔎 Последние 5 объявлений", "payload": "admin_recent"}],
            [{"type": "callback", "text": "📊 Статистика", "payload": "admin_stats"},
             {"type": "callback", "text": "⬅️ В главное меню", "payload": "menu_start"}]
        ]
    }

async def show_admin_panel(session: aiohttp.ClientSession, uid: int, chat_id: Optional[int]):
    if not db_is_admin(uid):
        return
    msg = "🛡 Вы в панели администратора.\n\nВыберите действие ниже:"
    await api_send(session, msg, kb_admin(), user_id=uid, chat_id=chat_id)

async def show_admin_stats(session: aiohttp.ClientSession, uid: int, chat_id: Optional[int]):
    if not db_is_admin(uid):
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            users_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM items WHERE status = 'active'")
            active_items = cur.fetchone()[0]
            cur.execute("SELECT type, COUNT(*) FROM items GROUP BY type")
            types_stats = cur.fetchall()

    stats_text = (
        "📊 СТАТИСТИКА\n\n"
        f"👥 Всего пользователей: {users_count}\n"
        f"📦 Активных объявлений: {active_items}\n\n"
        "Статистика по типам (всего за всё время):\n"
    )
    for t_name, count in types_stats:
        stats_text += f"• {t_name}: {count}\n"

    await api_send(session, stats_text, kb_admin(), user_id=uid, chat_id=chat_id)

CATEGORIES = [
    ("👟 Обувь и одежда", "cat_clothes"),
    ("📱 Электроника", "cat_electronics"),
    ("🔑 Ключи и пропуска", "cat_keys"),
    ("📚 Книги и канцелярия", "cat_books"),
    ("🎒 Рюкзаки и сумки", "cat_bags"),
    ("✨ Другое", "cat_other"),
]
CATEGORY_MAP = {slug: name for name, slug in CATEGORIES}

def kb_main(uid: Optional[int] = None) -> dict:
    buttons = [
        [{"type": "callback", "text": "🔍 Потерял вещь", "payload": "menu_lost"},
         {"type": "callback", "text": "📦 Нашёл вещь", "payload": "menu_found"}],
        [{"type": "callback", "text": "🗂 Витрина находок", "payload": "menu_catalog"},
         {"type": "callback", "text": "🔄 Шеринг", "payload": "menu_share"}],
        [{"type": "callback", "text": "📋 Мои объявления", "payload": "menu_my"},
         {"type": "callback", "text": "❓ Помощь", "payload": "menu_help"}],
    ]
    if uid and db_is_admin(uid):
        buttons.append([{"type": "callback", "text": "🛡 Админ-панель", "payload": "menu_admin"}])
    return {"buttons": buttons}

def kb_cancel() -> dict:
    return {
        "buttons": [
            [{"type": "callback", "text": "❌ Отмена", "payload": "cancel_action"}]
        ]
    }

def kb_skip_or_cancel() -> dict:
    return {
        "buttons": [
            [{"type": "callback", "text": "⏭ Пропустить", "payload": "skip_details"},
             {"type": "callback", "text": "❌ Отмена", "payload": "cancel_action"}]
        ]
    }

def kb_categories(flow_type: str) -> dict:
    buttons = []
    row = []
    for name, slug in CATEGORIES:
        row.append({"type": "callback", "text": name, "payload": f"cat_{flow_type}:{slug}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"type": "callback", "text": "❌ Отмена", "payload": "cancel_action"}])
    return {"buttons": buttons}

def kb_share_menu() -> dict:
    return {
        "buttons": [
            [{"type": "callback", "text": "📤 Поделиться", "payload": "share_offer"},
             {"type": "callback", "text": "👀 Доступно", "payload": "share_list"}],
            [{"type": "callback", "text": "🎒 Мои вещи", "payload": "share_my"},
             {"type": "callback", "text": "⬅️ В главное меню", "payload": "menu_start"}],
        ]
    }

def kb_catalog_filter() -> dict:
    buttons = []
    row = []
    for name, slug in CATEGORIES:
        row.append({"type": "callback", "text": name, "payload": f"filter_cat:{slug}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        {"type": "callback", "text": "🔄 Все категории", "payload": "menu_catalog"},
        {"type": "callback", "text": "⬅️ Главное меню", "payload": "menu_start"}
    ])
    return {"buttons": buttons}

def kb_item_actions(item_id: str) -> dict:
    return {
        "buttons": [
            [{"type": "callback", "text": "✅ Найдено / Закрыть", "payload": f"resolve:{item_id}"},
             {"type": "callback", "text": "❌ Снять заявку", "payload": f"delete:{item_id}"}]
        ]
    }

def kb_back() -> dict:
    return {"buttons": [[{"type": "callback", "text": "⬅️ В главное меню", "payload": "menu_start"}]]}

def get_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile="/app/russian_trusted_root_ca_pem.crt")
    return ctx

async def api_answer_callback(session: aiohttp.ClientSession, callback_id: str,
                              notification: Optional[str] = None) -> bool:
    if not callback_id:
        return False
    headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
    body: dict[str, Any] = {}
    if notification:
        body["notification"] = notification
    else:
        body["notification"] = "ОК"

    url = f"{API_BASE}/answers?callback_id={callback_id}"
    try:
        ssl_ctx = get_ssl_context()
        async with session.post(
            url,
            json=body,
            headers=headers,
            ssl=ssl_ctx,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            if r.status not in (200, 204):
                err = await r.text()
                print(f"[CALLBACK WARN] Status {r.status} on callback {callback_id}: {err}")
                return False
            return True
    except Exception as e:
        print(f"[CALLBACK ERROR] Exception on callback {callback_id}: {e}")
        return False

async def api_send(
    session: aiohttp.ClientSession,
    text: str,
    keyboard: Optional[dict] = None,
    user_id: Optional[int] = None,
    chat_id: Optional[int] = None,
    photo_id: Optional[str] = None
) -> dict:
    headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
    body: dict[str, Any] = {"text": text}
    atts = []
    if keyboard:
        atts.append({"type": "inline_keyboard", "payload": keyboard})
    if photo_id:
        atts.append({"type": "image", "payload": {"file_id": photo_id}})
    if atts:
        body["attachments"] = atts

    if chat_id is not None:
        url = f"{API_BASE}/messages?chat_id={chat_id}"
    elif user_id is not None:
        url = f"{API_BASE}/messages?user_id={user_id}"
    else:
        print("[API ERROR] Neither chat_id nor user_id provided")
        return {}

    try:
        ssl_ctx = get_ssl_context()
        async with session.post(
            url,
            json=body,
            headers=headers,
            ssl=ssl_ctx,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            data = await r.json()
            if r.status != 200:
                print(f"[API ERROR] Send error (status {r.status}): {data}")
            return data
    except Exception as e:
        print(f"[API ERROR] Exception in api_send: {e}")
        return {}

# тексты приветствия и справки
WELCOME = (
    "👋 Привет! Это школьный бот «Бюро находок и Шеринг».\n\n"
    "Здесь ты можешь:\n"
    "• 🔍 Подать заявку о потерянной вещи — бот автоматически найдёт совпадения!\n"
    "• 📦 Сообщить о находке и вернуть вещь хозяину.\n"
    "• 🗂 Посмотреть витрину всех найденных в школе вещей.\n"
    "• 🔄 Взять или одолжить зарядку, ручку или циркуль на урок через Шеринг.\n\n"
    "Выбери нужный раздел в меню ниже 👇"
)

HELP_TEXT = (
    "📖 ШКОЛЬНОЕ БЮРО НАХОДОК И ШЕРИНГ\n\n"
    "🔍 «Потерял вещь»:\n"
    "Опишите потерянный предмет. Бот сразу проверит базу находок, а если вещи "
    "ещё нет — будет непрерывно искать и оповестит вас, как только её сдадут!\n\n"
    "📦 «Нашёл вещь»:\n"
    "Сдали чужую вещь на вахту или в учительскую? Зарегистрируйте её тут. "
    "Бот автоматически найдёт владельца и отправит ему личное сообщение!\n\n"
    "🗂 «Витрина находок»:\n"
    "Список всех вещей, которые прямо сейчас лежат в школе (на вахте / в учительской).\n\n"
    "🔄 «Школьный шеринг»:\n"
    "Выручай одноклассников! Нужен циркуль на геометрию, маркер или зарядка? "
    "Посмотри доступное или поделись своим.\n\n"
    "📍 Основные пункты приёма находок в школе:\n"
    "• Вахта на 1 этаже\n"
    "• Кабинет дежурного администратора / учительская\n\n"
    "Команды: /start — главное меню, /cancel — отмена текущего действия."
)

async def handle_start(session: aiohttp.ClientSession, uid: int, chat_id: Optional[int], user_name: Optional[str]):
    db_clear_state(uid)
    db_set_user(uid, chat_id=chat_id, user_name=user_name, state=None, data={})
    await api_send(session, WELCOME, kb_main(uid), user_id=uid, chat_id=chat_id)

async def complete_lost_registration(session: aiohttp.ClientSession, uid: int, chat_id: Optional[int], data: dict):
    title = data.get("title", "")
    category = data.get("category", "cat_other")
    place = data.get("place", "")
    details = data.get("details", "")
    photo_id = data.get("photo_id")
    cat_name = CATEGORY_MAP.get(category, "Другое")

    user_info = db_get_user(uid)
    uname = user_info.get("user_name") or "Ученик"

    item_id = db_create_item(
        item_type="lost",
        user_id=uid,
        chat_id=chat_id,
        user_name=uname,
        title=title,
        category=category,
        place=place,
        details=details,
        photo_id=photo_id
    )
    db_clear_state(uid)

    conf_text = (
        f"✅ Заявка о пропаже #{item_id} зарегистрирована!\n\n"
        f"📌 Предмет: {title}\n"
        f"📂 Категория: {cat_name}\n"
        f"📍 Где потеряли: {place}\n"
    )
    if details:
        conf_text += f"📝 Приметы: {details}\n"

    await api_send(session, conf_text, kb_main(uid), user_id=uid, chat_id=chat_id, photo_id=photo_id)

    # ищем совпадения среди уже найденных вещей
    matches = find_matches(title, category, place, target_type="found")
    if matches:
        match_msg = "🔔 Внимание! В бюро находок уже есть похожие предметы:\n\n"
        for idx, m in enumerate(matches, 1):
            m_cat = CATEGORY_MAP.get(m["category"], "Вещь")
            match_msg += (
                f"{idx}. 📦 {m['title']} ({m_cat})\n"
                f"   📍 Куда сдано: {m['place']}\n"
            )
            if m.get("details"):
                match_msg += f"   📝 Приметы: {m['details']}\n"
            match_msg += f"   👤 Нашёл: {m['user_name']}\n"
            match_msg += f"   📅 Дата: {str(m['created_at'])[:16]}\n\n"
        match_msg += "👉 Если это ваша вещь, подойдите в указанное место или свяжитесь с нашедшим, чтобы забрать её!"
        await api_send(session, match_msg, kb_main(uid), user_id=uid, chat_id=chat_id)
    else:
        await api_send(
            session,
            "🔍 Заявка добавлена в активный поиск. Как только кто-то сообщит о похожей находке, бот моментально пришлёт вам уведомление!",
            kb_main(uid),
            user_id=uid,
            chat_id=chat_id
        )

async def complete_found_registration(session: aiohttp.ClientSession, uid: int, chat_id: Optional[int], data: dict):
    title = data.get("title", "")
    category = data.get("category", "cat_other")
    place = data.get("place", "")
    details = data.get("details", "")
    photo_id = data.get("photo_id")
    cat_name = CATEGORY_MAP.get(category, "Другое")

    user_info = db_get_user(uid)
    uname = user_info.get("user_name") or "Ученик"

    item_id = db_create_item(
        item_type="found",
        user_id=uid,
        chat_id=chat_id,
        user_name=uname,
        title=title,
        category=category,
        place=place,
        details=details,
        photo_id=photo_id
    )
    db_clear_state(uid)

    conf_text = (
        f"🎉 Спасибо за честность! Находка #{item_id} добавлена в базу.\n\n"
        f"📌 Предмет: {title}\n"
        f"📂 Категория: {cat_name}\n"
        f"📍 Где находится / куда передали: {place}\n"
    )
    if details:
        conf_text += f"📝 Особые приметы: {details}\n"

    await api_send(session, conf_text, kb_main(uid), user_id=uid, chat_id=chat_id, photo_id=photo_id)

    # уведомляем владельцев если нашли совпадение
    matches = find_matches(title, category, place, target_type="lost")
    if matches:
        notified_count = 0
        for m in matches:
            owner_uid = m["user_id"]
            owner_text = (
                f"🔔 ОТЛИЧНЫЕ НОВОСТИ! Возможно, нашлась ваша потерянная вещь!\n\n"
                f"Вы искали: «{m['title']}»\n\n"
                f"Только что зарегистрирована находка:\n"
                f"📦 «{title}» ({cat_name})\n"
                f"📍 Куда сдана / где забрать: {place}\n"
            )
            if details:
                owner_text += f"📝 Приметы: {details}\n"
            owner_text += f"👤 Нашёл: {uname}\n"
            owner_text += (
                f"\n👉 Пожалуйста, подойдите в указанное место или свяжитесь с нашедшим. "
                f"Если вещь вернулась к вам, закройте заявку в разделе «📋 Мои объявления»."
            )
            res = await api_send(session, owner_text, kb_main(owner_uid), user_id=owner_uid, photo_id=photo_id)
            if res:
                notified_count += 1

        if notified_count > 0:
            await api_send(
                session,
                f"💡 Мы нашли {notified_count} подходящих заявок о потере и уже отправили владельцам уведомления!",
                kb_main(uid),
                user_id=uid,
                chat_id=chat_id
            )

async def complete_share_registration(session: aiohttp.ClientSession, uid: int, chat_id: Optional[int], data: dict):
    title = data.get("title", "")
    time_info = data.get("time_info", "")
    place = data.get("place", "")

    user_info = db_get_user(uid)
    uname = user_info.get("user_name") or "Ученик"

    item_id = db_create_item(
        item_type="share",
        user_id=uid,
        chat_id=chat_id,
        user_name=uname,
        title=title,
        category="cat_other",
        place=f"{place} ({time_info})",
        details=f"Время: {time_info}"
    )
    db_clear_state(uid)

    conf_text = (
        f"✅ Вещь «{title}» успешно добавлена в шеринг!\n\n"
        f"⏱ На сколько: {time_info}\n"
        f"📍 Где забрать: {place}\n\n"
        f"Одноклассники увидят её в разделе «Доступно сейчас»."
    )
    await api_send(session, conf_text, kb_share_menu(), user_id=uid, chat_id=chat_id)

async def show_catalog(session: aiohttp.ClientSession, uid: int, chat_id: Optional[int], category: Optional[str] = None):
    cat_name = CATEGORY_MAP.get(category, "Все категории") if category else "Все категории"
    items = db_get_active_items(item_type="found", limit=10, category=category)

    if not items:
        msg = f"🗂 ВИТРИНА НАХОДОК ({cat_name})\n\nВ этой категории сейчас нет найденных вещей."
        await api_send(session, msg, kb_catalog_filter(), user_id=uid, chat_id=chat_id)
        return

    await api_send(session, f"🗂 ВИТРИНА ШКОЛЬНОГО БЮРО НАХОДОК ({cat_name})\nВещи, которые прямо сейчас ждут владельцев:", user_id=uid, chat_id=chat_id)
    
    for idx, item in enumerate(items, 1):
        c_name = CATEGORY_MAP.get(item["category"], "Вещь")
        msg = (
            f"📦 {item['title']} [{c_name}]\n"
            f"📍 Где забрать: {item['place']}\n"
        )
        if item.get("details"):
            msg += f"📝 Приметы: {item['details']}\n"
        msg += f"📅 Найдено: {str(item['created_at'])[:16]}"
        
        await api_send(session, msg, user_id=uid, chat_id=chat_id, photo_id=item.get("photo_id"))

    await api_send(session, "👉 Если вы узнали свою вещь, подойдите в указанное место (на вахту или в учительскую)!", kb_catalog_filter(), user_id=uid, chat_id=chat_id)

async def show_my_items(session: aiohttp.ClientSession, uid: int, chat_id: Optional[int]):
    items = db_get_user_items(uid, status="active")
    if not items:
        await api_send(
            session,
            "📋 У вас пока нет активных объявлений.\n\n"
            "Если вы что-то потеряли, нашли или хотите одолжить — воспользуйтесь главным меню!",
            kb_main(uid),
            user_id=uid,
            chat_id=chat_id
        )
        return

    await api_send(session, f"📋 Ваши активные объявления ({len(items)}):", user_id=uid, chat_id=chat_id)

    for it in items:
        t_icon = "🔍 Потеря" if it["type"] == "lost" else ("📦 Находка" if it["type"] == "found" else "🔄 Шеринг")
        c_name = CATEGORY_MAP.get(it["category"], "Вещь")
        text = (
            f"{t_icon} #{it['id']}: «{it['title']}»\n"
            f"📂 Категория: {c_name}\n"
            f"📍 Место: {it['place']}\n"
            f"📅 Создано: {str(it['created_at'])[:16]}"
        )
        await api_send(session, text, kb_item_actions(it["id"]), user_id=uid, chat_id=chat_id)

    await api_send(session, "Вы можете закрыть или удалить любую заявку кнопками выше 👆", kb_main(uid), user_id=uid, chat_id=chat_id)

async def show_sharing_list(session: aiohttp.ClientSession, uid: int, chat_id: Optional[int]):
    items = db_get_active_items(item_type="share", limit=15)
    if not items:
        await api_send(
            session,
            "🔄 В шеринге сейчас нет свободных вещей.\n\n"
            "Будьте первым — поделитесь ручкой, зарядкой или калькулятором на перемену!",
            kb_share_menu(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    msg = "🔄 ДОСТУПНО В ШКОЛЬНОМ ШЕРИНГЕ:\n\n"
    for idx, it in enumerate(items, 1):
        uname = it.get("user_name") or "Ученик"
        msg += (
            f"{idx}. ⚡ {it['title']}\n"
            f"   📍 Где и когда: {it['place']}\n"
            f"   👤 Предложил: {uname}\n\n"
        )
    msg += "👉 Найдите ученика в указанном кабинете, чтобы взять вещь на урок!"
    await api_send(session, msg, kb_share_menu(), user_id=uid, chat_id=chat_id)

async def show_my_shares(session: aiohttp.ClientSession, uid: int, chat_id: Optional[int]):
    all_my = db_get_user_items(uid, status="active")
    shares = [it for it in all_my if it["type"] == "share"]
    if not shares:
        await api_send(
            session,
            "🎒 Вы пока не делились вещами в шеринге.",
            kb_share_menu(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    for it in shares:
        text = f"🔄 Вещь: «{it['title']}»\n📍 Где: {it['place']}"
        await api_send(session, text, kb_item_actions(it["id"]), user_id=uid, chat_id=chat_id)

    await api_send(session, "Если вещь забрали или вернули, нажмите «✅ Найдено / Закрыть» выше 👆", kb_share_menu(), user_id=uid, chat_id=chat_id)

async def handle_message(session: aiohttp.ClientSession, update: dict):
    msg = update.get("message", {}) or {}
    body = msg.get("body", {}) or {}
    text = (body.get("text") or msg.get("text") or "").strip()

    attachments = body.get("attachments") or msg.get("attachments") or []
    photo_id = None
    for att in attachments:
        if att.get("type") in ("image", "photo"):
            payload = att.get("payload", {})
            photo_id = payload.get("file_id") or payload.get("id") or att.get("id")
            if photo_id:
                break

    user = update.get("user") or msg.get("sender") or {}
    uid = user.get("user_id")
    user_name = user.get("name") or user.get("first_name") or "Ученик"

    chat = update.get("recipient") or msg.get("recipient") or {}
    chat_id = chat.get("chat_id")

    if not uid:
        return

    u = db_get_user(uid)
    db_set_user(uid, chat_id=chat_id, user_name=user_name)

    print(f"[MSG] uid={uid} chat={chat_id} text='{text}' state={u['state']}")

    # Глобальные команды — /start, /help, /cancel, /admin
    if text in ("/start", "старт", "start"):
        await handle_start(session, uid, chat_id, user_name)
        return
    elif text in ("/help", "помощь", "help"):
        await api_send(session, HELP_TEXT, kb_main(uid), user_id=uid, chat_id=chat_id)
        return
    elif text in ("/cancel", "отмена", "cancel"):
        db_clear_state(uid)
        await api_send(session, "Действие отменено.", kb_main(uid), user_id=uid, chat_id=chat_id)
        return
    elif text == "/admin":
        if db_is_admin(uid):
            await show_admin_panel(session, uid, chat_id)
        return
    elif text.startswith("/admin "):
        code = text.split(" ", 1)[1].strip()
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT used_by FROM admin_codes WHERE code = %s", (code,))
                row = cur.fetchone()
                if not row:
                    await api_send(session, "❌ Неверный код администратора.", kb_main(uid), user_id=uid, chat_id=chat_id)
                elif row[0] is not None:
                    await api_send(session, "❌ Этот код уже был использован.", kb_main(uid), user_id=uid, chat_id=chat_id)
                else:
                    cur.execute("UPDATE admin_codes SET used_by = %s WHERE code = %s", (uid, code))
                    cur.execute("UPDATE users SET is_admin = TRUE WHERE user_id = %s", (uid,))
                    await api_send(session, "✅ Вы успешно стали администратором!", kb_main(uid), user_id=uid, chat_id=chat_id)
                    await show_admin_panel(session, uid, chat_id)
        return

    state = u.get("state")
    data = u.get("data", {})

    if not state:
        await api_send(session, "Выберите действие в меню 👇", kb_main(uid), user_id=uid, chat_id=chat_id)
        return

    # если текст есть — проверяем на стоп-слова
    if text:
        ok, err_msg = check_text(text)
        if not ok:
            await api_send(session, f"⚠️ {err_msg}\nПопробуйте написать по-другому:", kb_cancel(), user_id=uid, chat_id=chat_id)
            return

    # --- Шаги создания заявки: ПОТЕРЯ ---
    if state == "lost_title":
        data["title"] = text
        db_set_user(uid, state="lost_category", data=data)
        await api_send(session, f"Принято: «{text}».\nТеперь выберите категорию вещи:", kb_categories("lost"), user_id=uid, chat_id=chat_id)
        return

    elif state == "lost_place":
        data["place"] = text
        db_set_user(uid, state="lost_details", data=data)
        await api_send(
            session,
            "Опишите особые приметы (наклейки, цвет, царапины, брелок) или нажмите «Пропустить»:",
            kb_skip_or_cancel(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    elif state == "lost_details":
        data["details"] = text
        await complete_lost_registration(session, uid, chat_id, data)
        return

    elif state == "lost_photo":
        if photo_id:
            data["photo_id"] = photo_id
            await complete_lost_registration(session, uid, chat_id, data)
        elif text.lower() == "пропустить":
            await complete_lost_registration(session, uid, chat_id, data)
        else:
            await api_send(session, "Пожалуйста, отправьте фото или нажмите «Пропустить»:", kb_skip_or_cancel(), user_id=uid, chat_id=chat_id)
        return

    # --- Шаги создания заявки: НАХОДКА ---
    elif state == "found_title":
        data["title"] = text
        db_set_user(uid, state="found_category", data=data)
        await api_send(session, f"Принято: «{text}».\nВыберите категорию находки:", kb_categories("found"), user_id=uid, chat_id=chat_id)
        return

    elif state == "found_place":
        data["place"] = text
        db_set_user(uid, state="found_details", data=data)
        await api_send(
            session,
            "Опишите особые приметы вещи или нажмите «Пропустить»:",
            kb_skip_or_cancel(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    elif state == "found_details":
        data["details"] = text
        await complete_found_registration(session, uid, chat_id, data)
        return

    elif state == "found_photo":
        if photo_id:
            data["photo_id"] = photo_id
            await complete_found_registration(session, uid, chat_id, data)
        elif text.lower() == "пропустить":
            await complete_found_registration(session, uid, chat_id, data)
        else:
            await api_send(session, "Пожалуйста, отправьте фото или нажмите «Пропустить»:", kb_skip_or_cancel(), user_id=uid, chat_id=chat_id)
        return

    # --- Шаги создания заявки: ШЕРИНГ ---
    elif state == "share_title":
        data["title"] = text
        db_set_user(uid, state="share_time", data=data)
        await api_send(
            session,
            "На сколько времени вы готовы одолжить вещь? (например: «На 3 урок», «На всю смену», «На 15 минут»):",
            kb_cancel(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    elif state == "share_time":
        data["time_info"] = text
        db_set_user(uid, state="share_place", data=data)
        await api_send(
            session,
            "Где вас найти? (например: «Кабинет 302, 2 ряд», «Около учительской»):",
            kb_cancel(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    elif state == "share_place":
        data["place"] = text
        await complete_share_registration(session, uid, chat_id, data)
        return

    elif state == "admin_wait_delete":
        if db_is_admin(uid):
            item_id = text.strip()
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE items SET status = 'cancelled' WHERE id = %s", (item_id,))
                    if cur.rowcount > 0:
                        await api_send(session, f"✅ Объявление #{item_id} принудительно удалено!", kb_main(uid), user_id=uid, chat_id=chat_id)
                    else:
                        await api_send(session, f"❌ Объявление #{item_id} не найдено.", kb_main(uid), user_id=uid, chat_id=chat_id)
            db_clear_state(uid)
        return

    elif state == "admin_wait_revoke":
        if db_is_admin(uid):
            try:
                target_id = int(text.strip())
                if target_id == uid:
                    await api_send(session, "❌ Вы не можете снять админку с самого себя.", kb_main(uid), user_id=uid, chat_id=chat_id)
                else:
                    with get_db() as conn:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE users SET is_admin = FALSE WHERE user_id = %s RETURNING user_name", (target_id,))
                            if cur.rowcount > 0:
                                t_name = cur.fetchone()[0]
                                await api_send(session, f"✅ Пользователь {t_name} (ID: {target_id}) лишён прав администратора.", kb_main(uid), user_id=uid, chat_id=chat_id)
                                await api_send(session, "Ваши права администратора были отозваны.", kb_main(target_id), user_id=target_id)
                            else:
                                await api_send(session, f"❌ Пользователь с ID {target_id} не найден.", kb_main(uid), user_id=uid, chat_id=chat_id)
            except ValueError:
                await api_send(session, "❌ Неверный формат ID. Введите число.", kb_main(uid), user_id=uid, chat_id=chat_id)
            db_clear_state(uid)
        return

    elif state == "admin_wait_broadcast":
        if db_is_admin(uid):
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM users WHERE chat_id IS NOT NULL")
                    users = cur.fetchall()
            
            await api_send(session, f"📢 Начинаю рассылку для {len(users)} пользователей...", kb_main(uid), user_id=uid, chat_id=chat_id)
            db_clear_state(uid)
            
            success = 0
            for (u_id,) in users:
                res = await api_send(session, f"📢 СООБЩЕНИЕ ОТ АДМИНИСТРАТОРА:\n\n{text}", user_id=u_id)
                if res:
                    success += 1
                await asyncio.sleep(0.05) # лимит
            
            await api_send(session, f"✅ Рассылка завершена! Доставлено: {success}/{len(users)}", kb_main(uid), user_id=uid, chat_id=chat_id)
        return

    else:
        db_clear_state(uid)
        await api_send(session, "Выберите действие в меню 👇", kb_main(uid), user_id=uid, chat_id=chat_id)

async def handle_callback(session: aiohttp.ClientSession, update: dict):
    cb = update.get("callback") or update
    callback_id = (
        cb.get("callback_id")
        or cb.get("id")
        or update.get("callback_id")
        or update.get("id")
    )
    payload = cb.get("payload") or update.get("payload") or ""

    user = update.get("user") or cb.get("user") or update.get("message", {}).get("sender") or {}
    uid = user.get("user_id")
    user_name = user.get("name") or user.get("first_name") or "Ученик"

    chat = update.get("recipient") or cb.get("recipient") or update.get("message", {}).get("recipient") or {}
    chat_id = chat.get("chat_id")

    # подтверждаем нажатие
    if callback_id:
        await api_answer_callback(session, str(callback_id))

    print(f"[CB] uid={uid} payload='{payload}'")

    if not uid:
        return

    db_set_user(uid, chat_id=chat_id, user_name=user_name)
    u = db_get_user(uid)

    if payload in ("menu_start", "cancel_action"):
        await handle_start(session, uid, chat_id, user_name)
        return

    if payload == "menu_admin":
        await show_admin_panel(session, uid, chat_id)
        return
    elif payload == "admin_stats":
        await show_admin_stats(session, uid, chat_id)
        return
    elif payload == "admin_delete":
        if db_is_admin(uid):
            db_set_user(uid, state="admin_wait_delete", data={})
            await api_send(session, "Введите ID объявления (8 символов), которое нужно удалить:", kb_cancel(), user_id=uid, chat_id=chat_id)
        return
    elif payload == "admin_broadcast":
        if db_is_admin(uid):
            db_set_user(uid, state="admin_wait_broadcast", data={})
            await api_send(session, "Введите текст для рассылки всем пользователям:\n(Осторожно, сообщение получат все!)", kb_cancel(), user_id=uid, chat_id=chat_id)
        return
    elif payload == "admin_generate_code":
        if db_is_admin(uid):
            import random
            import string
            new_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO admin_codes (code) VALUES (%s)", (new_code,))
            await api_send(session, f"✅ Новый код доступа создан:\n\n{new_code}\n\nОтправьте этот код будущему администратору. Он должен будет написать боту команду:\n/admin {new_code}", kb_admin(), user_id=uid, chat_id=chat_id)
        return
    elif payload == "admin_list":
        if db_is_admin(uid):
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id, user_name FROM users WHERE is_admin = TRUE")
                    admins = cur.fetchall()
            msg = "📋 СПИСОК АДМИНИСТРАТОРОВ:\n\n"
            for a_id, a_name in admins:
                msg += f"• {a_name} (ID: {a_id})\n"
            await api_send(session, msg, kb_admin(), user_id=uid, chat_id=chat_id)
        return
    elif payload == "admin_revoke":
        if db_is_admin(uid):
            db_set_user(uid, state="admin_wait_revoke", data={})
            await api_send(session, "Введите ID пользователя, которого нужно лишить прав администратора:", kb_cancel(), user_id=uid, chat_id=chat_id)
        return
    elif payload == "admin_recent":
        if db_is_admin(uid):
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, type, category, title, user_name, status, created_at FROM items ORDER BY created_at DESC LIMIT 5")
                    items = cur.fetchall()
            msg = "🔎 ПОСЛЕДНИЕ 5 ОБЪЯВЛЕНИЙ:\n\n"
            for item in items:
                i_id, i_type, i_cat, i_title, i_author, i_status, i_date = item
                status_emoji = "✅" if i_status == "active" else "❌"
                msg += f"[{status_emoji}] #{i_id} | {i_type}\n{i_title}\nАвтор: {i_author}\n\n"
            if not items:
                msg += "Объявлений пока нет."
            await api_send(session, msg, kb_admin(), user_id=uid, chat_id=chat_id)
        return

    elif payload == "menu_lost":
        db_set_user(uid, state="lost_title", data={})
        await api_send(
            session,
            "🔍 Что именно вы потеряли? Напишите краткое название "
            "(например: «Синяя сменка Nike», «Электронный пропуск», «Ключи с брелоком»):",
            kb_cancel(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    elif payload == "menu_found":
        db_set_user(uid, state="found_title", data={})
        await api_send(
            session,
            "📦 Что вы нашли? Опишите кратко "
            "(например: «Связка ключей с котиком», «Школьный пиджак», «Пенал»):",
            kb_cancel(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    elif payload.startswith("cat_lost:"):
        cat_slug = payload.split(":", 1)[1]
        data = u.get("data", {})
        data["category"] = cat_slug
        db_set_user(uid, state="lost_place", data=data)
        await api_send(
            session,
            "Где и примерно когда вы потеряли вещь? (например: «Кабинет 204 на 3 уроке», «Улица около школы», «Дворик детского сада»):",
            kb_cancel(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    elif payload.startswith("cat_found:"):
        cat_slug = payload.split(":", 1)[1]
        data = u.get("data", {})
        data["category"] = cat_slug
        db_set_user(uid, state="found_place", data=data)
        await api_send(
            session,
            "Где нашли и КУДА СДАЛИ вещь? (Если забрали себе домой — напишите где нашли и как с вами связаться. Пример: «Нашёл у школы №5, забрал домой, писать в лс» или «Кабинет 305 у учителя»):",
            kb_cancel(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    elif payload == "skip_details":
        state = u.get("state")
        data = u.get("data", {})
        
        if state == "lost_details":
            data["details"] = ""
            await complete_lost_registration(session, uid, chat_id, data)
        elif state == "found_details":
            data["details"] = ""
            await complete_found_registration(session, uid, chat_id, data)
        else:
            await handle_start(session, uid, chat_id, user_name)
        return

    elif payload == "menu_catalog":
        await show_catalog(session, uid, chat_id, category=None)
        return

    elif payload.startswith("filter_cat:"):
        cat_slug = payload.split(":", 1)[1]
        await show_catalog(session, uid, chat_id, category=cat_slug)
        return

    elif payload == "menu_my":
        await show_my_items(session, uid, chat_id)
        return

    elif payload.startswith("resolve:"):
        item_id = payload.split(":", 1)[1]
        ok = db_resolve_item(item_id, uid)
        if ok:
            await api_send(session, f"✅ Заявка #{item_id} успешно закрыта! Рады, что вопрос решился 🎉", kb_main(uid), user_id=uid, chat_id=chat_id)
        else:
            await api_send(session, "Не удалось закрыть заявку (возможно, она уже закрыта).", kb_main(uid), user_id=uid, chat_id=chat_id)
        return

    elif payload.startswith("delete:"):
        item_id = payload.split(":", 1)[1]
        ok = db_delete_item(item_id, uid)
        if ok:
            await api_send(session, f"❌ Объявление #{item_id} снято с публикации.", kb_main(uid), user_id=uid, chat_id=chat_id)
        else:
            await api_send(session, "Объявление не найдено.", kb_main(uid), user_id=uid, chat_id=chat_id)
        return

    elif payload == "menu_share":
        await api_send(
            session,
            "🔄 ШКОЛЬНЫЙ ШЕРИНГ\n\n"
            "Взаимовыручка между учениками школы!\n"
            "Нужна зарядка, калькулятор на урок или циркуль на геометрию?\n"
            "Или вы готовы выручить других своей запасной вещью?",
            kb_share_menu(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    elif payload == "share_offer":
        db_set_user(uid, state="share_title", data={})
        await api_send(
            session,
            "📤 Что вы готовы одолжить? (например: «Зарядка Type-C», «Калькулятор Casio», «Циркуль», «Маркер»):",
            kb_cancel(),
            user_id=uid,
            chat_id=chat_id
        )
        return

    elif payload == "share_list":
        await show_sharing_list(session, uid, chat_id)
        return

    elif payload == "share_my":
        await show_my_shares(session, uid, chat_id)
        return

    elif payload == "menu_help":
        await api_send(session, HELP_TEXT, kb_main(uid), user_id=uid, chat_id=chat_id)
        return

    else:
        await handle_start(session, uid, chat_id, user_name)

async def dispatch_update(session: aiohttp.ClientSession, update: dict):
    update_type = update.get("update_type") or update.get("type")

    if update_type == "bot_started":
        user = update.get("user", {}) or {}
        recipient = update.get("recipient", {}) or {}
        uid = user.get("user_id")
        user_name = user.get("name") or user.get("first_name") or "Ученик"
        chat_id = recipient.get("chat_id")
        if uid:
            await handle_start(session, uid, chat_id, user_name)

    elif update_type in ("message_callback", "callback_created") or "callback" in update:
        await handle_callback(session, update)

    elif update_type in ("message_created", "message_sent") or "message" in update:
        await handle_message(session, update)

async def webhook_handler(request: web.Request) -> web.Response:
    if WEBHOOK_SECRET:
        req_secret = request.headers.get("X-Max-Bot-Api-Secret", "")
        if req_secret != WEBHOOK_SECRET:
            print("[WEBHOOK WARN] Unauthorized webhook request (secret mismatch)")
            return web.Response(status=403, text="Forbidden")

    try:
        data = await request.json()
    except Exception as e:
        print(f"[WEBHOOK ERROR] Invalid JSON: {e}")
        return web.Response(status=400, text="Bad JSON")

    session: aiohttp.ClientSession = request.app["session"]
    if isinstance(data, list):
        for item in data:
            asyncio.create_task(dispatch_update(session, item))
    elif isinstance(data, dict):
        asyncio.create_task(dispatch_update(session, data))

    return web.Response(status=200, text="OK")

async def health_check(request: web.Request) -> web.Response:
    return web.Response(status=200, text="Bot is healthy!")

async def run_webhook_server(session: aiohttp.ClientSession):
    app = web.Application()
    app["session"] = session
    
    # Регистрация путей для Mini App
    async def webapp_index(request):        return web.FileResponse(os.path.join(os.path.dirname(__file__), "webapp", "index.html"))
    
    app.router.add_get("/app", webapp_index)
    app.router.add_get("/app/", webapp_index)
    app.router.add_static("/app/static/", path=os.path.join(os.path.dirname(__file__), "webapp"), name="webapp")

    # API endpoints для мини-приложения
    def check_admin_code(request: web.Request) -> bool:
        code = request.headers.get("X-Admin-Code", "").strip()
        if not code:
            return False
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT used_by FROM admin_codes WHERE code = %s", (code,))
                row = cur.fetchone()
                if not row or row[0] is None:
                    return False
                cur.execute("SELECT is_admin FROM users WHERE user_id = %s", (row[0],))
                admin_row = cur.fetchone()
                return bool(admin_row and admin_row[0])

    async def api_admin_stats(request: web.Request) -> web.Response:
        if not check_admin_code(request):
            return web.json_response({"text": "Доступ запрещён."}, status=403)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                users_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM items WHERE status = 'active'")
                active_items = cur.fetchone()[0]
                cur.execute("SELECT type, COUNT(*) FROM items GROUP BY type")
                types_stats = cur.fetchall()

        stats_html = (
            f"<b>Статистика (Реальная):</b><br>"
            f"Пользователей: {users_count}<br>"
            f"Объявлений всего: {active_items}<br>"
        )
        for t_name, count in types_stats:
            stats_html += f"{t_name}: {count}<br>"
            
        return web.json_response({"text": stats_html})

    async def api_admin_recent(request: web.Request) -> web.Response:
        if not check_admin_code(request):
            return web.json_response({"text": "Доступ запрещён."}, status=403)
        with get_db() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT title, type FROM items ORDER BY id DESC LIMIT 5")
                recent = cur.fetchall()
        
        if not recent:
            return web.json_response({"text": "Нет объявлений."})
            
        res = "<b>Последние 5 объявлений:</b><br>"
        for i, it in enumerate(recent, 1):
            t_name = "Потерян" if it['type'] == 'lost' else "Найден"
            res += f"{i}. {it['title']} ({t_name})<br>"
        
        return web.json_response({"text": res})

    async def api_admin_list(request: web.Request) -> web.Response:
        if not check_admin_code(request):
            return web.json_response({"text": "Доступ запрещён."}, status=403)
        with get_db() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT user_name FROM users WHERE is_admin = TRUE")
                admins = cur.fetchall()
        
        if not admins:
            return web.json_response({"text": "Нет администраторов."})
            
        res = "<b>Администраторы:</b><br>"
        for a in admins:
            name = a['user_name'] or "Без имени"
            res += f"- @{name}<br>"
            
        return web.json_response({"text": res})

    app.router.add_get("/api/admin/stats", api_admin_stats)
    app.router.add_get("/api/admin/recent", api_admin_recent)
    app.router.add_get("/api/admin/list", api_admin_list)

    async def api_search(request: web.Request) -> web.Response:
        q = request.rel_url.query.get("q", "").strip()
        if not q:
            return web.json_response({"items": []})
        items = db_get_active_items("found", limit=20)
        q_tokens = extract_tokens(q)
        results = []
        for it in items:
            if q_tokens & extract_tokens(it["title"]):
                results.append({"title": it["title"], "place": it["place"]})
        return web.json_response({"items": results[:5]})

    async def api_add_item(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False}, status=400)
        title = body.get("title", "").strip()
        place = body.get("place", "").strip()
        details = body.get("details", "").strip()
        item_type = body.get("type", "found").strip()
        if item_type not in ("found", "lost"):
            item_type = "found"
        if not title or not place:
            return web.json_response({"ok": False}, status=400)
        item_id = db_create_item(item_type, 0, None, "webapp", title, "cat_other", place, details=details)
        return web.json_response({"ok": True, "id": item_id})

    async def api_gencode(request: web.Request) -> web.Response:
        if not check_admin_code(request):
            return web.json_response({"text": "Доступ запрещён."}, status=403)
        import random, string
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO admin_codes (code) VALUES (%s)", (code,))
        return web.json_response({"code": code})

    app.router.add_get("/app/api/admin/stats", api_admin_stats)
    app.router.add_get("/app/api/admin/recent", api_admin_recent)
    app.router.add_get("/app/api/admin/list", api_admin_list)
    app.router.add_get("/app/api/search", api_search)
    app.router.add_post("/app/api/items", api_add_item)
    async def api_clear_items(request: web.Request) -> web.Response:
        if not check_admin_code(request):
            return web.json_response({"ok": False, "text": "Доступ запрещён."}, status=403)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if body.get("confirm") != "УДАЛИТЬ":
            return web.json_response({"ok": False, "text": "Подтверждение не совпадает."}, status=400)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM items")
                count_before = cur.fetchone()[0]
                cur.execute("TRUNCATE TABLE items")
        return web.json_response({"ok": True, "text": f"Удалено записей: {count_before}"})

    app.router.add_post("/app/api/admin/gencode", api_gencode)
    app.router.add_post("/app/api/admin/clear", api_clear_items)

    app.router.add_post("/webhook", webhook_handler)
    app.router.add_get("/health", health_check)
    webhook_url = f"{WEBHOOK_BASE_URL}/webhook"
    print(f"[INIT] Registering webhook: {webhook_url}")
    ssl_ctx = get_ssl_context()
    sub_body: dict[str, Any] = {"url": webhook_url}
    if WEBHOOK_SECRET:
        sub_body["secret"] = WEBHOOK_SECRET

    async with session.post(
        f"{API_BASE}/subscriptions",
        json=sub_body,
        headers={"Authorization": TOKEN, "Content-Type": "application/json"},
        ssl=ssl_ctx
    ) as r:
        resp = await r.text()
        print(f"[INIT] Webhook registered. Status: {r.status}, Response: {resp}")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[SERVER] Webhook server listening on 0.0.0.0:{PORT}")

    while True:
        await asyncio.sleep(3600)

async def run_long_polling(session: aiohttp.ClientSession):
    ssl_ctx = get_ssl_context()

    try:
        async with session.delete(
            f"{API_BASE}/subscriptions",
            headers={"Authorization": TOKEN},
            ssl=ssl_ctx
        ) as r:
            print(f"[INIT] Webhook cleared for long polling: status {r.status}")
    except Exception as e:
        print(f"[INIT] Webhook cleanup notice: {e}")

    marker: Optional[int] = None
    print("polling started")

    while True:
        try:
            params: dict[str, Any] = {"timeout": 30}
            if marker is not None:
                params["marker"] = marker

            async with session.get(
                f"{API_BASE}/updates",
                params=params,
                headers={"Authorization": TOKEN},
                ssl=ssl_ctx,
                timeout=aiohttp.ClientTimeout(total=35)
            ) as r:
                if r.status != 200:
                    err_text = await r.text()
                    print(f"[POLL ERROR] Status {r.status}: {err_text}")
                    await asyncio.sleep(3)
                    continue

                data = await r.json()
                if "marker" in data and data["marker"] is not None:
                    marker = data["marker"]

                updates = data.get("updates", [])
                for update in updates:
                    try:
                        await dispatch_update(session, update)
                    except Exception as e:
                        print(f"[DISPATCH ERROR] Failed processing update: {e}")

        except asyncio.TimeoutError:
            continue
        except aiohttp.ClientError as e:
            print(f"[POLL CLIENT ERROR] {e}")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"[POLL ERROR] Unexpected: {e}")
            await asyncio.sleep(3)

async def main():
    init_db()

    ssl_ctx = get_ssl_context()
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{API_BASE}/me",
                headers={"Authorization": TOKEN},
                ssl=ssl_ctx,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                me = await r.json()
                if r.status == 200:
                    bot_name = me.get("name") or me.get("first_name") or "MAX Bot"
                    bot_user = me.get("username", "")
                    print(f"started as {bot_name}")
                else:
                    print(f"[INIT ERROR] Token rejected! Status: {r.status}, response: {me}")
                    return
        except Exception as e:
            print(f"[INIT ERROR] Could not connect to MAX API: {e}")
            return

        if WEBHOOK_BASE_URL:
            await run_webhook_server(session)
        else:
            await run_long_polling(session)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n[STOP] Bot stopped by user.")

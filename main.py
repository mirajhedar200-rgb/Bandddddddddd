import asyncio
import logging
import os
from datetime import datetime, timezone, date
from typing import Optional

import aiosqlite
from aiohttp import web
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Message, ReplyKeyboardMarkup, Update
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("ichancy_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
DB_PATH = os.getenv("DB_PATH", "ichancy_bot.db")
PORT = int(os.getenv("PORT", "10000"))

# On Render, RENDER_EXTERNAL_URL is provided automatically.
# WEBHOOK_URL can also be set manually if desired.
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
PUBLIC_URL = WEBHOOK_URL or RENDER_EXTERNAL_URL
WEBHOOK_PATH = "/telegram/webhook"


def get_webhook_secret():
    """Return one stable secret used by both set_webhook and the HTTP handler."""
    configured = os.getenv("WEBHOOK_SECRET", "").strip()
    if configured:
        return configured
    import hashlib
    return hashlib.sha256(BOT_TOKEN.encode()).hexdigest()[:32]


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS is required")

BOT: Optional[Bot] = None
DP = Dispatcher()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today():
    return date.today().isoformat()


async def db():
    c = await aiosqlite.connect(DB_PATH)
    c.row_factory = aiosqlite.Row
    await c.execute("PRAGMA journal_mode=WAL")
    await c.execute("PRAGMA synchronous=NORMAL")
    await c.execute("PRAGMA foreign_keys=ON")
    await c.execute("PRAGMA busy_timeout=10000")
    return c


DEFAULT = {
    "welcome": "🎰 أهلاً بك في Ichancy Bot\n\nاختر الخدمة من القائمة 👇",
    "terms": (
        "⚠️ شروط الاستخدام\n\n"
        "1️⃣ يمنع إنشاء أكثر من حساب للتحايل.\n"
        "2️⃣ يمنع التلاعب أو استغلال الثغرات.\n"
        "3️⃣ عمليات الشحن والسحب تتم بعد مراجعة الإدارة.\n"
        "4️⃣ الإدارة تستطيع إيقاف الحسابات المخالفة.\n"
        "5️⃣ حساب Ichancy هنا شكلي وداخلي فقط، ولا يتم إنشاء حساب حقيقي على موقع خارجي."
    ),
    "ref_reward": "1000",
    "daily_reward": "1000",
    "min_deposit": "1000",
    "min_withdraw": "15000",
    "min_i_deposit": "1000",
    "min_i_withdraw": "15000",
    "offers": "🎁 لا توجد عروض نشطة حالياً.",
    "fun": "🎮 قسم التسلية غير متاح حالياً.",
}


class S(StatesGroup):
    ich_user = State()
    ich_pass = State()
    dep_amount = State()
    dep_method = State()
    dep_ref = State()
    wd_amount = State()
    wd_method = State()
    wd_account = State()
    support = State()
    gift = State()

    admin_text = State()
    admin_user = State()
    admin_amount = State()
    admin_method = State()
    admin_reply = State()
    admin_gift = State()


async def init_db():
    c = await db()
    try:
        await c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            referrer_id INTEGER,
            balance INTEGER DEFAULT 0,
            ichancy_balance INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            accepted_terms INTEGER DEFAULT 0,
            created_at TEXT,
            last_seen TEXT
        );

        CREATE TABLE IF NOT EXISTS ichancy_accounts(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            password TEXT,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS ledger(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            wallet TEXT,
            delta INTEGER,
            reason TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS methods(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            name TEXT,
            details TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            wallet TEXT,
            amount INTEGER,
            method TEXT,
            account TEXT,
            reference TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            processed_at TEXT,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS channels(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE,
            title TEXT,
            username TEXT,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS gift_codes(
            code TEXT PRIMARY KEY,
            amount INTEGER,
            max_uses INTEGER DEFAULT 0,
            used_count INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS gift_used(
            user_id INTEGER,
            code TEXT,
            created_at TEXT,
            PRIMARY KEY(user_id, code)
        );

        CREATE TABLE IF NOT EXISTS daily_claims(
            user_id INTEGER,
            day TEXT,
            PRIMARY KEY(user_id, day)
        );

        CREATE TABLE IF NOT EXISTS support(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            status TEXT DEFAULT 'open',
            reply TEXT,
            created_at TEXT,
            replied_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_tx_status
        ON transactions(status);

        CREATE INDEX IF NOT EXISTS idx_ledger_user
        ON ledger(user_id);
        """)

        for k, v in DEFAULT.items():
            await c.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                (k, v)
            )

        await c.execute(
            "INSERT OR IGNORE INTO gift_codes(code,amount,max_uses) VALUES('WELCOME99',5000,0)"
        )
        await c.commit()
    finally:
        await c.close()


async def setting(k, default=""):
    c = await db()
    try:
        r = await (
            await c.execute("SELECT value FROM settings WHERE key=?", (k,))
        ).fetchone()
        return r["value"] if r else default
    finally:
        await c.close()


async def set_setting(k, v):
    c = await db()
    try:
        await c.execute(
            """
            INSERT INTO settings(key,value)
            VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (k, v)
        )
        await c.commit()
    finally:
        await c.close()


async def ensure_user(m: Message, ref=None):
    u = m.from_user
    c = await db()
    try:
        r = await (
            await c.execute("SELECT * FROM users WHERE id=?", (u.id,))
        ).fetchone()

        if r:
            await c.execute(
                """
                UPDATE users
                SET username=?, first_name=?, last_seen=?
                WHERE id=?
                """,
                (u.username, u.first_name, now(), u.id)
            )
            await c.commit()
            return dict(r)

        safe = None
        if (
            ref
            and ref != u.id
            and await (
                await c.execute("SELECT id FROM users WHERE id=?", (ref,))
            ).fetchone()
        ):
            safe = ref

        t = now()
        # FIX: original INSERT had 7 placeholders for 6 columns.
        await c.execute(
            """
            INSERT INTO users(
                id, username, first_name, referrer_id,
                balance, created_at, last_seen
            )
            VALUES(?,?,?,?,?,?,?)
            """,
            (u.id, u.username, u.first_name, safe, 15000, t, t)
        )

        await c.execute(
            """
            INSERT INTO ledger(user_id,wallet,delta,reason,created_at)
            VALUES(?,?,?,?,?)
            """,
            (u.id, "bot", 15000, "🎁 بونص التسجيل", t)
        )

        if safe:
            reward = int(await setting("ref_reward", "1000"))
            await c.execute(
                "UPDATE users SET balance=balance+? WHERE id=?",
                (reward, safe)
            )
            await c.execute(
                """
                INSERT INTO ledger(user_id,wallet,delta,reason,created_at)
                VALUES(?,?,?,?,?)
                """,
                (safe, "bot", reward, f"👥 إحالة المستخدم {u.id}", t)
            )

        await c.commit()
        r = await (
            await c.execute("SELECT * FROM users WHERE id=?", (u.id,))
        ).fetchone()
        return dict(r)
    finally:
        await c.close()


async def user(uid):
    c = await db()
    try:
        r = await (
            await c.execute("SELECT * FROM users WHERE id=?", (uid,))
        ).fetchone()
        return dict(r) if r else None
    finally:
        await c.close()


async def banned(uid):
    u = await user(uid)
    return bool(u and u["banned"])


async def change(uid, wallet, delta, reason):
    col = "balance" if wallet == "bot" else "ichancy_balance"
    c = await db()
    try:
        await c.execute("BEGIN IMMEDIATE")
        r = await (
            await c.execute(f"SELECT {col} FROM users WHERE id=?", (uid,))
        ).fetchone()
        if not r:
            raise ValueError("user not found")

        new = int(r[0]) + delta
        if new < 0:
            raise ValueError("insufficient")

        await c.execute(
            f"UPDATE users SET {col}=? WHERE id=?",
            (new, uid)
        )
        await c.execute(
            """
            INSERT INTO ledger(user_id,wallet,delta,reason,created_at)
            VALUES(?,?,?,?,?)
            """,
            (uid, wallet, delta, reason, now())
        )
        await c.commit()
        return new
    except Exception:
        await c.rollback()
        raise
    finally:
        await c.close()


async def methods(tp):
    c = await db()
    try:
        return [
            dict(x)
            for x in await (
                await c.execute(
                    "SELECT * FROM methods WHERE type=? AND active=1 ORDER BY id",
                    (tp,)
                )
            ).fetchall()
        ]
    finally:
        await c.close()


async def channels():
    c = await db()
    try:
        return [
            dict(x)
            for x in await (
                await c.execute(
                    "SELECT * FROM channels WHERE active=1 ORDER BY id"
                )
            ).fetchall()
        ]
    finally:
        await c.close()


async def tx_create(
    uid, tp, wallet, amount, method="", account="", reference=""
):
    c = await db()
    try:
        cur = await c.execute(
            """
            INSERT INTO transactions(
                user_id,type,wallet,amount,method,account,reference,
                status,created_at
            )
            VALUES(?,?,?,?,?,?,?,'pending',?)
            """,
            (uid, tp, wallet, amount, method, account, reference, now())
        )
        await c.commit()
        return cur.lastrowid
    finally:
        await c.close()


async def process_tx(tid, approve, note=""):
    c = await db()
    try:
        await c.execute("BEGIN IMMEDIATE")
        r = await (
            await c.execute(
                "SELECT * FROM transactions WHERE id=?", (tid,)
            )
        ).fetchone()

        if not r or r["status"] != "pending":
            await c.rollback()
            return None

        d = dict(r)
        status = "approved" if approve else "rejected"

        if approve and d["type"] == "withdraw":
            col = "balance" if d["wallet"] == "bot" else "ichancy_balance"
            r2 = await (
                await c.execute(
                    f"SELECT {col} FROM users WHERE id=?",
                    (d["user_id"],)
                )
            ).fetchone()

            if not r2 or int(r2[0]) < d["amount"]:
                await c.rollback()
                return "insufficient"

            await c.execute(
                f"UPDATE users SET {col}={col}-? WHERE id=?",
                (d["amount"], d["user_id"])
            )
            await c.execute(
                """
                INSERT INTO ledger(
                    user_id,wallet,delta,reason,created_at
                )
                VALUES(?,?,?,?,?)
                """,
                (
                    d["user_id"],
                    d["wallet"],
                    -d["amount"],
                    f"💸 قبول سحب #{tid}",
                    now()
                )
            )

        if approve and d["type"] == "deposit":
            col = "balance" if d["wallet"] == "bot" else "ichancy_balance"
            await c.execute(
                f"UPDATE users SET {col}={col}+? WHERE id=?",
                (d["amount"], d["user_id"])
            )
            await c.execute(
                """
                INSERT INTO ledger(
                    user_id,wallet,delta,reason,created_at
                )
                VALUES(?,?,?,?,?)
                """,
                (
                    d["user_id"],
                    d["wallet"],
                    d["amount"],
                    f"💳 قبول شحن #{tid}",
                    now()
                )
            )

        await c.execute(
            """
            UPDATE transactions
            SET status=?,processed_at=?,note=?
            WHERE id=?
            """,
            (status, now(), note, tid)
        )
        await c.commit()
        return d
    except Exception:
        await c.rollback()
        raise
    finally:
        await c.close()


def inline(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="👤 حساب Ichancy"),
                KeyboardButton(text="💰 محفظة البوت")
            ],
            [
                KeyboardButton(text="👥 الإحالات"),
                KeyboardButton(text="🎁 الهدية اليومية")
            ],
            [
                KeyboardButton(text="🎁 كود هدية"),
                KeyboardButton(text="📋 سجلاتي")
            ],
            [
                KeyboardButton(text="🎁 العروض"),
                KeyboardButton(text="💬 الدعم")
            ],
            [
                KeyboardButton(text="⚠️ الشروط"),
                KeyboardButton(text="▶️ Start")
            ]
        ],
        resize_keyboard=True,
        is_persistent=True
    )


def admin_kb():
    b = InlineKeyboardBuilder()
    items = [
        ("📊 الإحصائيات", "a:stats"),
        ("👥 مستخدم", "a:user"),
        ("💰 تعديل رصيد", "a:balance"),
        ("💳 طلبات الشحن", "a:deps"),
        ("💸 طلبات السحب", "a:wds"),
        ("➕ طرق الشحن", "a:adddep"),
        ("➕ طرق السحب", "a:addwd"),
        ("🗑 طرق الدفع", "a:methods"),
        ("📢 القنوات", "a:channels"),
        ("🎁 المكافآت", "a:rewards"),
        ("🎟 الأكواد", "a:gift"),
        ("📣 إذاعة", "a:broadcast"),
        ("💬 الدعم", "a:support"),
        ("⚙️ الإعدادات", "a:settings"),
    ]
    for text, data in items:
        b.button(text=text, callback_data=data)
    b.adjust(2)
    return b.as_markup()


async def check_sub(uid):
    if not BOT:
        return True

    for ch in await channels():
        try:
            mem = await BOT.get_chat_member(ch["chat_id"], uid)
            if mem.status not in ("member", "administrator", "creator"):
                return False
        except Exception:
            return False

    return True


async def sub_prompt(m):
    rows = []
    for ch in await channels():
        username = (ch["username"] or "").lstrip("@")
        url = f"https://t.me/{username}" if username else "https://t.me/"
        rows.append([
            InlineKeyboardButton(
                text=f"📢 {ch['title']}",
                url=url
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="✅ تحققت من الاشتراك",
            callback_data="sub:check"
        )
    ])

    await m.answer(
        "🔒 يجب الاشتراك بالقنوات المطلوبة أولاً:",
        reply_markup=inline(rows)
    )


async def guard(m):
    if await banned(m.from_user.id):
        await m.answer("🚫 حسابك موقوف.")
        return False

    if not await check_sub(m.from_user.id):
        await sub_prompt(m)
        return False

    return True


@DP.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()

    parts = (m.text or "").split(maxsplit=1)
    ref = (
        int(parts[1])
        if len(parts) > 1 and parts[1].isdigit()
        else None
    )

    u = await ensure_user(m, ref)

    if u["banned"]:
        return await m.answer("🚫 حسابك موقوف.")

    if not u["accepted_terms"]:
        return await m.answer(
            await setting("terms", DEFAULT["terms"]),
            reply_markup=inline([
                [
                    InlineKeyboardButton(
                        text="✅ أوافق وأتابع",
                        callback_data="terms"
                    )
                ]
            ])
        )

    if not await check_sub(m.from_user.id):
        return await sub_prompt(m)

    await m.answer(
        await setting("welcome", DEFAULT["welcome"]),
        reply_markup=main_kb()
    )


@DP.callback_query(F.data == "terms")
async def terms(c: CallbackQuery):
    cc = await db()
    try:
        await cc.execute(
            "UPDATE users SET accepted_terms=1 WHERE id=?",
            (c.from_user.id,)
        )
        await cc.commit()
    finally:
        await cc.close()

    await c.answer("تم القبول ✅")
    if await check_sub(c.from_user.id):
        await c.message.answer(
            "تم تفعيل حسابك ✅",
            reply_markup=main_kb()
        )
    else:
        await sub_prompt(c.message)


@DP.callback_query(F.data == "sub:check")
async def subcheck(c: CallbackQuery):
    if await check_sub(c.from_user.id):
        await c.answer("تم التحقق ✅")
        await c.message.answer(
            "تم تفعيل الوصول إلى البوت ✅",
            reply_markup=main_kb()
        )
    else:
        await c.answer(
            "لم تكتمل الاشتراكات",
            show_alert=True
        )


@DP.message(F.text == "▶️ Start")
async def restart(m: Message, state: FSMContext):
    await start(m, state)


@DP.message(F.text == "⚠️ الشروط")
async def terms_btn(m):
    if await guard(m):
        await m.answer(
            await setting("terms", DEFAULT["terms"])
        )


async def get_ich(uid):
    c = await db()
    try:
        r = await (
            await c.execute(
                "SELECT * FROM ichancy_accounts WHERE user_id=?",
                (uid,)
            )
        ).fetchone()
        return dict(r) if r else None
    finally:
        await c.close()


@DP.message(F.text == "👤 حساب Ichancy")
async def ich_menu(m):
    if not await guard(m):
        return

    a = await get_ich(m.from_user.id)
    rows = []

    if not a:
        rows.append([
            InlineKeyboardButton(
                text="➕ إنشاء حساب Ichancy",
                callback_data="ich:create"
            )
        ])
    else:
        rows += [
            [
                InlineKeyboardButton(
                    text="👤 بيانات الحساب",
                    callback_data="ich:data"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 رصيد Ichancy",
                    callback_data="ich:balance"
                )
            ]
        ]

    rows += [
        [
            InlineKeyboardButton(
                text="💳 شحن حساب Ichancy",
                callback_data="ich:dep"
            )
        ],
        [
            InlineKeyboardButton(
                text="💸 سحب من حساب Ichancy",
                callback_data="ich:wd"
            )
        ]
    ]

    await m.answer(
        "👤 حساب Ichancy",
        reply_markup=inline(rows)
    )


@DP.callback_query(F.data == "ich:create")
async def ich_create(c, state):
    await state.set_state(S.ich_user)
    await c.answer()
    await c.message.answer(
        "👤 أرسل اسم مستخدم Ichancy الشكلي:"
    )


@DP.message(S.ich_user)
async def ich_user(m, state):
    v = (m.text or "").strip()

    if not 3 <= len(v) <= 32:
        return await m.answer(
            "الاسم يجب أن يكون بين 3 و32 محرفاً."
        )

    await state.update_data(iu=v)
    await state.set_state(S.ich_pass)
    await m.answer("🔑 أرسل كلمة المرور:")


@DP.message(S.ich_pass)
async def ich_pass(m, state):
    v = (m.text or "").strip()
    d = await state.get_data()

    if not 4 <= len(v) <= 64:
        return await m.answer(
            "كلمة المرور يجب أن تكون بين 4 و64 محرفاً."
        )

    c = await db()
    try:
        await c.execute(
            """
            INSERT INTO ichancy_accounts(
                user_id,username,password,created_at,updated_at
            )
            VALUES(?,?,?,?,?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                username=excluded.username,
                password=excluded.password,
                updated_at=excluded.updated_at
            """,
            (
                m.from_user.id,
                d["iu"],
                v,
                now(),
                now()
            )
        )
        await c.commit()
    finally:
        await c.close()

    await state.clear()
    await m.answer(
        "✅ تم إنشاء حساب Ichancy بنجاح.",
        reply_markup=main_kb()
    )


@DP.callback_query(F.data == "ich:data")
async def ich_data(c):
    a = await get_ich(c.from_user.id)
    u = await user(c.from_user.id)

    if not a or not u:
        return await c.answer(
            "أنشئ حساب Ichancy أولاً",
            show_alert=True
        )

    await c.answer()
    await c.message.answer(
        f"👤 <b>حساب Ichancy</b>\n\n"
        f"اسم المستخدم: <code>{a['username']}</code>\n"
        f"كلمة المرور: <code>{a['password']}</code>\n"
        f"💰 الرصيد: <b>{u['ichancy_balance']:,} ل.س</b>"
    )


@DP.callback_query(F.data == "ich:balance")
async def ich_bal(c):
    u = await user(c.from_user.id)
    await c.answer()
    await c.message.answer(
        f"💰 رصيد Ichancy: <b>{u['ichancy_balance']:,} ل.س</b>"
    )


@DP.callback_query(F.data.in_({"ich:dep", "bot:dep"}))
async def dep_click(c, state):
    wallet = "ichancy" if c.data.startswith("ich") else "bot"
    key = (
        "min_i_deposit"
        if wallet == "ichancy"
        else "min_deposit"
    )

    await state.update_data(wallet=wallet)
    await state.set_state(S.dep_amount)
    await c.answer()
    await c.message.answer(
        f"💳 أدخل مبلغ الشحن بالليرة السورية\n"
        f"الحد الأدنى: "
        f"{int(await setting(key, '1000')):,}"
    )


@DP.message(S.dep_amount)
async def dep_amount(m, state):
    if not (m.text or "").isdigit():
        return await m.answer("أرسل رقماً فقط.")

    amount = int(m.text)
    d = await state.get_data()

    key = (
        "min_i_deposit"
        if d["wallet"] == "ichancy"
        else "min_deposit"
    )
    minimum = int(await setting(key, "1000"))

    if amount < minimum:
        return await m.answer(
            f"الحد الأدنى {minimum:,} ل.س"
        )

    ms = await methods("deposit")

    if not ms:
        await state.clear()
        return await m.answer(
            "❌ لا توجد طرق شحن مضافة حالياً. "
            "اطلب من الإدارة إضافة طريقة."
        )

    await state.update_data(amount=amount)
    await state.set_state(S.dep_method)

    await m.answer(
        "اختر طريقة الشحن:",
        reply_markup=inline([
            [
                InlineKeyboardButton(
                    text=x["name"],
                    callback_data=f"dep_method:{x['id']}"
                )
            ]
            for x in ms
        ])
    )


@DP.callback_query(F.data.startswith("dep_method:"))
async def dep_method(c, state):
    await state.update_data(
        method_id=int(c.data.split(":")[1])
    )

    d = await state.get_data()
    ms = await methods("deposit")
    x = next(
        (z for z in ms if z["id"] == d["method_id"]),
        None
    )

    if not x:
        await state.clear()
        return await c.answer(
            "طريقة الدفع غير متاحة",
            show_alert=True
        )

    await state.set_state(S.dep_ref)
    await c.answer()
    await c.message.answer(
        f"💳 الطريقة: <b>{x['name']}</b>\n\n"
        f"بيانات الشحن:\n"
        f"<code>{x['details']}</code>\n\n"
        f"أرسل رقم العملية/إيصال التحويل "
        f"أو اكتب وصف العملية:"
    )


@DP.message(S.dep_ref)
async def dep_ref(m, state):
    d = await state.get_data()
    ms = await methods("deposit")
    x = next(
        (z for z in ms if z["id"] == d["method_id"]),
        None
    )

    if not x:
        await state.clear()
        return await m.answer(
            "❌ طريقة الشحن لم تعد متاحة."
        )

    tid = await tx_create(
        m.from_user.id,
        "deposit",
        d["wallet"],
        d["amount"],
        x["name"],
        reference=(m.text or "")[:500]
    )

    await state.clear()
    await m.answer(
        f"✅ تم إنشاء طلب الشحن #{tid}\n"
        f"⏳ بانتظار مراجعة الإدارة.",
        reply_markup=main_kb()
    )

    await notify_admin(
        f"💳 طلب شحن جديد #{tid}\n"
        f"المستخدم: <code>{m.from_user.id}</code>\n"
        f"المحفظة: {d['wallet']}\n"
        f"المبلغ: {d['amount']:,} ل.س\n"
        f"الطريقة: {x['name']}\n"
        f"المرجع: {(m.text or '')[:500]}",
        tid
    )


@DP.callback_query(F.data.in_({"ich:wd", "bot:wd"}))
async def wd_click(c, state):
    wallet = "ichancy" if c.data.startswith("ich") else "bot"
    u = await user(c.from_user.id)

    await state.update_data(wallet=wallet)
    await state.set_state(S.wd_amount)
    await c.answer()

    await c.message.answer(
        f"💸 رصيدك الحالي: "
        f"{u['ichancy_balance' if wallet == 'ichancy' else 'balance']:,} ل.س\n\n"
        f"أدخل مبلغ السحب:"
    )


@DP.message(S.wd_amount)
async def wd_amount(m, state):
    if not (m.text or "").isdigit():
        return await m.answer("أرسل رقماً فقط.")

    amount = int(m.text)
    d = await state.get_data()

    key = (
        "min_i_withdraw"
        if d["wallet"] == "ichancy"
        else "min_withdraw"
    )
    minimum = int(await setting(key, "15000"))
    u = await user(m.from_user.id)
    bal = u[
        "ichancy_balance"
        if d["wallet"] == "ichancy"
        else "balance"
    ]

    if amount < minimum:
        return await m.answer(
            f"الحد الأدنى {minimum:,} ل.س"
        )

    if amount > bal:
        return await m.answer(
            "❌ رصيدك غير كافٍ."
        )

    ms = await methods("withdraw")

    if not ms:
        await state.clear()
        return await m.answer(
            "❌ لا توجد طرق سحب مضافة حالياً."
        )

    await state.update_data(amount=amount)
    await state.set_state(S.wd_method)

    await m.answer(
        "اختر طريقة السحب:",
        reply_markup=inline([
            [
                InlineKeyboardButton(
                    text=x["name"],
                    callback_data=f"wd_method:{x['id']}"
                )
            ]
            for x in ms
        ])
    )


@DP.callback_query(F.data.startswith("wd_method:"))
async def wd_method(c, state):
    await state.update_data(
        method_id=int(c.data.split(":")[1])
    )
    await state.set_state(S.wd_account)
    await c.answer()
    await c.message.answer(
        "أرسل رقم الحساب/رقم الهاتف/بيانات الاستلام "
        "التي تريد السحب إليها:"
    )


@DP.message(S.wd_account)
async def wd_account(m, state):
    d = await state.get_data()
    ms = await methods("withdraw")
    x = next(
        (z for z in ms if z["id"] == d["method_id"]),
        None
    )

    if not x:
        await state.clear()
        return await m.answer(
            "❌ طريقة السحب لم تعد متاحة."
        )

    tid = await tx_create(
        m.from_user.id,
        "withdraw",
        d["wallet"],
        d["amount"],
        x["name"],
        account=(m.text or "")[:500]
    )

    await state.clear()
    await m.answer(
        f"✅ تم إرسال طلب السحب #{tid}\n"
        f"⏳ بانتظار مراجعة الإدارة.",
        reply_markup=main_kb()
    )

    await notify_admin(
        f"💸 طلب سحب جديد #{tid}\n"
        f"المستخدم: <code>{m.from_user.id}</code>\n"
        f"المحفظة: {d['wallet']}\n"
        f"المبلغ: {d['amount']:,} ل.س\n"
        f"الطريقة: {x['name']}\n"
        f"الحساب: {(m.text or '')[:500]}",
        tid
    )


@DP.message(F.text == "💰 محفظة البوت")
async def wallet(m):
    if not await guard(m):
        return

    u = await user(m.from_user.id)
    await m.answer(
        f"💰 <b>محفظة البوت</b>\n\n"
        f"رصيدك: <b>{u['balance']:,} ل.س</b>",
        reply_markup=inline([
            [
                InlineKeyboardButton(
                    text="💳 شحن البوت",
                    callback_data="bot:dep"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💸 سحب من البوت",
                    callback_data="bot:wd"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 السجل",
                    callback_data="records"
                )
            ]
        ])
    )


async def send_records(target, uid):
    cc = await db()
    try:
        rows = await (
            await cc.execute(
                """
                SELECT * FROM ledger
                WHERE user_id=?
                ORDER BY id DESC LIMIT 15
                """,
                (uid,)
            )
        ).fetchall()
    finally:
        await cc.close()

    if not rows:
        text = "📋 <b>سجل العمليات</b>\n\nلا توجد عمليات."
    else:
        lines = []
        for r in rows:
            sign = "+" if r["delta"] >= 0 else ""
            lines.append(
                f"{r['created_at'][:19]} | "
                f"{r['wallet']} | "
                f"{sign}{r['delta']:,} | "
                f"{r['reason']}"
            )
        text = "📋 <b>سجل العمليات</b>\n\n" + "\n".join(lines)

    await target.answer(text)


@DP.callback_query(F.data == "records")
async def rec(c):
    await c.answer()
    await send_records(c.message, c.from_user.id)


@DP.message(F.text == "📋 سجلاتي")
async def rec_btn(m):
    if await guard(m):
        await send_records(m, m.from_user.id)


@DP.message(F.text == "👥 الإحالات")
async def refs(m):
    if not await guard(m):
        return

    cc = await db()
    try:
        n = (
            await (
                await cc.execute(
                    "SELECT COUNT(*) c FROM users WHERE referrer_id=?",
                    (m.from_user.id,)
                )
            ).fetchone()
        )["c"]
    finally:
        await cc.close()

    me = await BOT.get_me()

    await m.answer(
        f"👥 إحالاتك: <b>{n}</b>\n"
        f"🎁 مكافأة الإحالة: "
        f"<b>{int(await setting('ref_reward','1000')):,} ل.س</b>\n\n"
        f"🔗 رابطك:\n"
        f"<code>https://t.me/{me.username}?start={m.from_user.id}</code>"
    )


@DP.message(F.text == "🎁 الهدية اليومية")
async def daily(m):
    if not await guard(m):
        return

    c = await db()
    try:
        await c.execute("BEGIN IMMEDIATE")

        r = await (
            await c.execute(
                """
                SELECT 1 FROM daily_claims
                WHERE user_id=? AND day=?
                """,
                (m.from_user.id, today())
            )
        ).fetchone()

        if r:
            await c.rollback()
            return await m.answer(
                "🎁 أخذت هدية اليوم مسبقاً."
            )

        v = int(await setting("daily_reward", "1000"))

        await c.execute(
            "INSERT INTO daily_claims(user_id,day) VALUES(?,?)",
            (m.from_user.id, today())
        )
        await c.execute(
            "UPDATE users SET balance=balance+? WHERE id=?",
            (v, m.from_user.id)
        )
        await c.execute(
            """
            INSERT INTO ledger(
                user_id,wallet,delta,reason,created_at
            )
            VALUES(?,?,?,?,?)
            """,
            (
                m.from_user.id,
                "bot",
                v,
                "🎁 الهدية اليومية",
                now()
            )
        )
        await c.commit()
    except Exception:
        await c.rollback()
        raise
    finally:
        await c.close()

    await m.answer(
        f"🎁 تمت إضافة {v:,} ل.س إلى رصيدك."
    )


@DP.message(F.text == "🎁 كود هدية")
async def gift_start(m, state):
    if await guard(m):
        await state.set_state(S.gift)
        await m.answer("أرسل كود الهدية:")


@DP.message(S.gift)
async def gift(m, state):
    code = (m.text or "").strip().upper()
    c = await db()

    try:
        await c.execute("BEGIN IMMEDIATE")

        g = await (
            await c.execute(
                """
                SELECT * FROM gift_codes
                WHERE code=? AND active=1
                """,
                (code,)
            )
        ).fetchone()

        if not g:
            await c.rollback()
            return await m.answer(
                "❌ الكود غير صالح."
            )

        used = await (
            await c.execute(
                """
                SELECT 1 FROM gift_used
                WHERE user_id=? AND code=?
                """,
                (m.from_user.id, code)
            )
        ).fetchone()

        if used:
            await c.rollback()
            return await m.answer(
                "لقد استخدمت الكود سابقاً."
            )

        if g["max_uses"] > 0 and g["used_count"] >= g["max_uses"]:
            await c.rollback()
            return await m.answer(
                "انتهت مرات استخدام الكود."
            )

        await c.execute(
            """
            UPDATE gift_codes
            SET used_count=used_count+1
            WHERE code=?
            """,
            (code,)
        )

        await c.execute(
            "INSERT INTO gift_used VALUES(?,?,?)",
            (m.from_user.id, code, now())
        )

        await c.execute(
            "UPDATE users SET balance=balance+? WHERE id=?",
            (g["amount"], m.from_user.id)
        )

        await c.execute(
            """
            INSERT INTO ledger(
                user_id,wallet,delta,reason,created_at
            )
            VALUES(?,?,?,?,?)
            """,
            (
                m.from_user.id,
                "bot",
                g["amount"],
                f"🎁 كود {code}",
                now()
            )
        )

        await c.commit()

        await m.answer(
            f"✅ تمت إضافة {g['amount']:,} ل.س."
        )
    except Exception:
        await c.rollback()
        raise
    finally:
        await c.close()
        await state.clear()


@DP.message(F.text == "🎁 العروض")
async def offers(m):
    if await guard(m):
        await m.answer(
            await setting("offers", DEFAULT["offers"])
        )


@DP.message(F.text == "💬 الدعم")
async def support(m, state):
    if await guard(m):
        await state.set_state(S.support)
        await m.answer("💬 أرسل رسالتك للدعم:")


@DP.message(S.support)
async def support_receive(m, state):
    c = await db()
    try:
        cur = await c.execute(
            """
            INSERT INTO support(user_id,message,created_at)
            VALUES(?,?,?)
            """,
            (
                m.from_user.id,
                (m.text or "")[:4000],
                now()
            )
        )
        tid = cur.lastrowid
        await c.commit()
    finally:
        await c.close()

    await state.clear()
    await m.answer(
        f"✅ تم إرسال طلب الدعم #{tid}"
    )

    await notify_admin(
        f"🆘 دعم #{tid}\n"
        f"المستخدم: <code>{m.from_user.id}</code>\n"
        f"{(m.text or '')[:3000]}"
    )


async def notify_admin(text, tid=None):
    kb = (
        inline([
            [
                InlineKeyboardButton(
                    text="👁 فتح الطلب",
                    callback_data=f"tx:{tid}"
                )
            ]
        ])
        if tid
        else None
    )

    for a in ADMIN_IDS:
        try:
            await BOT.send_message(
                a,
                text,
                reply_markup=kb
            )
        except Exception:
            log.exception("Failed to notify admin %s", a)


def admin(uid):
    return uid in ADMIN_IDS


@DP.message(Command("admin"))
async def admin_cmd(m):
    if admin(m.from_user.id):
        await m.answer(
            "🛠 <b>لوحة تحكم Ichancy Bot</b>",
            reply_markup=admin_kb()
        )


@DP.callback_query(F.data == "a:stats")
async def a_stats(c):
    if not admin(c.from_user.id):
        return

    cc = await db()
    try:
        vals = []
        queries = [
            "SELECT COUNT(*) c FROM users",
            "SELECT COUNT(*) c FROM users WHERE banned=1",
            "SELECT COALESCE(SUM(balance),0) x FROM users",
            "SELECT COALESCE(SUM(ichancy_balance),0) x FROM users",
            "SELECT COUNT(*) c FROM transactions WHERE status='pending'"
        ]
        for q in queries:
            r = await (await cc.execute(q)).fetchone()
            vals.append(int(r[0]))
    finally:
        await cc.close()

    await c.answer()
    await c.message.answer(
        f"📊 المستخدمون: {vals[0]}\n"
        f"🚫 المحظورون: {vals[1]}\n"
        f"💰 أرصدة البوت: {vals[2]:,}\n"
        f"🎰 أرصدة Ichancy: {vals[3]:,}\n"
        f"⏳ طلبات معلقة: {vals[4]}"
    )


@DP.callback_query(F.data == "a:user")
async def a_user(c, state):
    if admin(c.from_user.id):
        await state.set_state(S.admin_user)
        await c.answer()
        await c.message.answer("أرسل ID المستخدم:")


@DP.message(S.admin_user)
async def a_user_msg(m, state):
    if not admin(m.from_user.id):
        return

    if not (m.text or "").isdigit():
        return await m.answer("أرسل ID رقمي.")

    u = await user(int(m.text))
    await state.clear()

    if not u:
        return await m.answer("المستخدم غير موجود.")

    await m.answer(
        f"👤 ID: <code>{u['id']}</code>\n"
        f"@{u['username'] or '—'}\n"
        f"💰 البوت: {u['balance']:,}\n"
        f"🎰 Ichancy: {u['ichancy_balance']:,}\n"
        f"🚫 محظور: {'نعم' if u['banned'] else 'لا'}",
        reply_markup=inline([
            [
                InlineKeyboardButton(
                    text="🚫 حظر",
                    callback_data=f"ban:{u['id']}"
                ),
                InlineKeyboardButton(
                    text="✅ فك الحظر",
                    callback_data=f"unban:{u['id']}"
                )
            ]
        ])
    )


@DP.callback_query(F.data.startswith("ban:"))
async def ban(c):
    if not admin(c.from_user.id):
        return

    uid = int(c.data.split(":")[1])
    cc = await db()
    try:
        await cc.execute(
            "UPDATE users SET banned=1 WHERE id=?",
            (uid,)
        )
        await cc.commit()
    finally:
        await cc.close()

    await c.answer("تم الحظر")


@DP.callback_query(F.data.startswith("unban:"))
async def unban(c):
    if not admin(c.from_user.id):
        return

    uid = int(c.data.split(":")[1])
    cc = await db()
    try:
        await cc.execute(
            "UPDATE users SET banned=0 WHERE id=?",
            (uid,)
        )
        await cc.commit()
    finally:
        await cc.close()

    await c.answer("تم فك الحظر")


@DP.callback_query(F.data == "a:balance")
async def a_balance(c, state):
    if admin(c.from_user.id):
        await state.set_state(S.admin_amount)
        await c.answer()
        await c.message.answer(
            "أرسل: USER_ID | AMOUNT | bot/ichancy | add/sub\n"
            "مثال: <code>12345 | 5000 | bot | add</code>"
        )


@DP.message(S.admin_amount)
async def a_balance_msg(m, state):
    if not admin(m.from_user.id):
        return

    p = [
        x.strip()
        for x in (m.text or "").split("|")
    ]

    if (
        len(p) != 4
        or not p[0].isdigit()
        or not p[1].lstrip("-").isdigit()
        or p[2] not in ("bot", "ichancy")
        or p[3] not in ("add", "sub")
    ):
        return await m.answer("صيغة غير صحيحة.")

    d = int(p[1]) * (1 if p[3] == "add" else -1)

    try:
        new = await change(
            int(p[0]),
            p[2],
            d,
            "🛠 تعديل إداري"
        )
        await m.answer(
            f"✅ تم تعديل الرصيد. الجديد: {new:,}"
        )
    except Exception:
        await m.answer(
            "❌ تعذر تعديل الرصيد: "
            "الرصيد غير كافٍ أو المستخدم غير موجود."
        )

    await state.clear()


@DP.callback_query(F.data.in_({"a:adddep", "a:addwd"}))
async def add_method(c, state):
    if not admin(c.from_user.id):
        return

    await state.update_data(
        mt="deposit" if c.data == "a:adddep" else "withdraw"
    )
    await state.set_state(S.admin_method)
    await c.answer()
    await c.message.answer(
        "أرسل: الاسم | تفاصيل الطريقة\n"
        "مثال: <code>سيريتل كاش | 09xxxxxxxx</code>"
    )


@DP.message(S.admin_method)
async def add_method_msg(m, state):
    if not admin(m.from_user.id):
        return

    p = [
        x.strip()
        for x in (m.text or "").split("|", 1)
    ]

    if len(p) != 2:
        return await m.answer(
            "الصيغة: الاسم | التفاصيل"
        )

    d = await state.get_data()
    cc = await db()
    try:
        await cc.execute(
            """
            INSERT INTO methods(
                type,name,details,created_at
            )
            VALUES(?,?,?,?)
            """,
            (d["mt"], p[0], p[1], now())
        )
        await cc.commit()
    finally:
        await cc.close()

    await state.clear()
    await m.answer("✅ تمت إضافة الطريقة.")


@DP.callback_query(F.data == "a:methods")
async def list_methods(c):
    if not admin(c.from_user.id):
        return

    ms = await methods("deposit") + await methods("withdraw")

    await c.answer()

    if not ms:
        return await c.message.answer(
            "لا توجد طرق."
        )

    await c.message.answer(
        "💳 <b>طرق الدفع</b>\n\n" +
        "\n".join(
            f"#{x['id']} | {x['type']} | "
            f"{x['name']} | {x['details']}"
            for x in ms
        )
    )


@DP.callback_query(F.data.in_({"a:deps", "a:wds"}))
async def tx_list(c):
    if not admin(c.from_user.id):
        return

    typ = (
        "deposit"
        if c.data == "a:deps"
        else "withdraw"
    )

    cc = await db()
    try:
        rows = [
            dict(x)
            for x in await (
                await cc.execute(
                    """
                    SELECT t.*,u.username
                    FROM transactions t
                    LEFT JOIN users u ON u.id=t.user_id
                    WHERE t.type=? AND t.status='pending'
                    ORDER BY t.id
                    """,
                    (typ,)
                )
            ).fetchall()
        ]
    finally:
        await cc.close()

    await c.answer()

    if not rows:
        return await c.message.answer(
            "لا توجد طلبات معلقة."
        )

    for x in rows:
        await c.message.answer(
            f"#{x['id']} | {x['type']} | {x['wallet']}\n"
            f"المستخدم: <code>{x['user_id']}</code>\n"
            f"المبلغ: <b>{x['amount']:,}</b>\n"
            f"الطريقة: {x['method']}\n"
            f"الحساب/المرجع: "
            f"{x['account'] or x['reference'] or '—'}",
            reply_markup=inline([
                [
                    InlineKeyboardButton(
                        text="✅ قبول",
                        callback_data=f"approve:{x['id']}"
                    ),
                    InlineKeyboardButton(
                        text="❌ رفض",
                        callback_data=f"reject:{x['id']}"
                    )
                ]
            ])
        )


@DP.callback_query(F.data.startswith("approve:"))
@DP.callback_query(F.data.startswith("reject:"))
async def tx_action(c):
    if not admin(c.from_user.id):
        return

    tid = int(c.data.split(":")[1])
    ok = c.data.startswith("approve:")

    r = await process_tx(tid, ok)

    if r == "insufficient":
        return await c.answer(
            "الرصيد غير كافٍ",
            show_alert=True
        )

    if not r:
        return await c.answer(
            "الطلب غير متاح",
            show_alert=True
        )

    await c.answer("تمت المعالجة")

    try:
        await c.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    try:
        await BOT.send_message(
            r["user_id"],
            f"{'✅ تم قبول' if ok else '❌ تم رفض'} "
            f"طلب {r['type']} #{tid}\n"
            f"المبلغ: {r['amount']:,} ل.س"
        )
    except Exception:
        pass


@DP.callback_query(F.data == "a:channels")
async def a_channels(c):
    if not admin(c.from_user.id):
        return

    cc = await db()
    try:
        rows = [
            dict(x)
            for x in await (
                await cc.execute(
                    "SELECT * FROM channels WHERE active=1"
                )
            ).fetchall()
        ]
    finally:
        await cc.close()

    await c.answer()

    text = "📢 القنوات الحالية:\n"

    if rows:
        text += "\n".join(
            f"#{x['id']} | {x['title']} | {x['chat_id']}"
            for x in rows
        )
    else:
        text += "لا توجد"

    text += (
        "\n\nلإضافة قناة استخدم:\n"
        "/addchannel CHAT_ID | TITLE | @username\n"
        "لحذف:\n/delchannel ID"
    )

    await c.message.answer(text)


@DP.message(Command("addchannel"))
async def addch(m):
    if not admin(m.from_user.id):
        return

    raw = (m.text or "").partition(" ")[2]
    p = [x.strip() for x in raw.split("|")]

    if len(p) < 2:
        return await m.answer(
            "/addchannel CHAT_ID | TITLE | @username"
        )

    cc = await db()
    try:
        await cc.execute(
            """
            INSERT OR REPLACE INTO channels(
                chat_id,title,username,active
            )
            VALUES(?,?,?,1)
            """,
            (
                p[0],
                p[1],
                p[2] if len(p) > 2 else ""
            )
        )
        await cc.commit()
    finally:
        await cc.close()

    await m.answer("✅ تمت إضافة القناة.")


@DP.message(Command("delchannel"))
async def delch(m):
    if not admin(m.from_user.id):
        return

    parts = (m.text or "").split()

    if len(parts) < 2 or not parts[-1].isdigit():
        return

    cc = await db()
    try:
        await cc.execute(
            "DELETE FROM channels WHERE id=?",
            (int(parts[-1]),)
        )
        await cc.commit()
    finally:
        await cc.close()

    await m.answer("✅ تم حذف القناة.")


@DP.callback_query(F.data == "a:gift")
async def a_gift(c, state):
    if admin(c.from_user.id):
        await state.set_state(S.admin_gift)
        await c.answer()
        await c.message.answer(
            "أرسل: CODE | AMOUNT | MAX_USES\n"
            "ضع 0 للاستخدام غير المحدود."
        )


@DP.message(S.admin_gift)
async def a_gift_msg(m, state):
    if not admin(m.from_user.id):
        return

    p = [
        x.strip()
        for x in (m.text or "").split("|")
    ]

    if (
        len(p) != 3
        or not p[1].isdigit()
        or not p[2].isdigit()
    ):
        return await m.answer(
            "صيغة غير صحيحة."
        )

    cc = await db()
    try:
        await cc.execute(
            """
            INSERT INTO gift_codes(
                code,amount,max_uses
            )
            VALUES(?,?,?)
            ON CONFLICT(code)
            DO UPDATE SET
                amount=excluded.amount,
                max_uses=excluded.max_uses,
                active=1
            """,
            (p[0].upper(), int(p[1]), int(p[2]))
        )
        await cc.commit()
    finally:
        await cc.close()

    await state.clear()
    await m.answer("✅ تم حفظ الكود.")


@DP.callback_query(F.data == "a:rewards")
async def rewards(c):
    if admin(c.from_user.id):
        await c.answer()
        await c.message.answer(
            f"🎁 مكافأة الإحالة: "
            f"{await setting('ref_reward')}\n"
            f"🎁 الهدية اليومية: "
            f"{await setting('daily_reward')}\n\n"
            "/set_referral 1000\n"
            "/set_daily 1000"
        )


@DP.message(Command("set_referral"))
async def setref(m):
    if not admin(m.from_user.id):
        return

    parts = (m.text or "").split(maxsplit=1)
    value = parts[1].strip() if len(parts) > 1 else "1000"

    if not value.isdigit():
        return await m.answer("أرسل رقماً صحيحاً.")

    await set_setting("ref_reward", value)
    await m.answer("✅ تم تحديث مكافأة الإحالة.")


@DP.message(Command("set_daily"))
async def setdaily(m):
    if not admin(m.from_user.id):
        return

    parts = (m.text or "").split(maxsplit=1)
    value = parts[1].strip() if len(parts) > 1 else "1000"

    if not value.isdigit():
        return await m.answer("أرسل رقماً صحيحاً.")

    await set_setting("daily_reward", value)
    await m.answer("✅ تم تحديث الهدية اليومية.")


@DP.callback_query(F.data == "a:settings")
async def settings(c):
    if admin(c.from_user.id):
        await c.answer()
        await c.message.answer(
            f"⚙️ الإعدادات\n\n"
            f"حد شحن البوت: {await setting('min_deposit')}\n"
            f"حد سحب البوت: {await setting('min_withdraw')}\n"
            f"حد شحن Ichancy: {await setting('min_i_deposit')}\n"
            f"حد سحب Ichancy: {await setting('min_i_withdraw')}\n\n"
            "/set_min_deposit 1000\n"
            "/set_min_withdraw 15000\n"
            "/set_min_i_deposit 1000\n"
            "/set_min_i_withdraw 15000\n"
            "/set_welcome النص\n"
            "/set_offers النص"
        )


async def numeric_setting_command(m, key):
    if not admin(m.from_user.id):
        return

    parts = (m.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        return await m.answer(
            "أرسل رقماً صحيحاً."
        )

    await set_setting(key, parts[1])
    await m.answer("✅ تم التحديث.")


@DP.message(Command("set_min_deposit"))
async def smd(m):
    await numeric_setting_command(m, "min_deposit")


@DP.message(Command("set_min_withdraw"))
async def smw(m):
    await numeric_setting_command(m, "min_withdraw")


@DP.message(Command("set_min_i_deposit"))
async def smid(m):
    await numeric_setting_command(m, "min_i_deposit")


@DP.message(Command("set_min_i_withdraw"))
async def smiw(m):
    await numeric_setting_command(m, "min_i_withdraw")


@DP.message(Command("set_welcome"))
async def sw(m):
    if admin(m.from_user.id):
        value = (m.text or "").partition(" ")[2]
        await set_setting("welcome", value)
        await m.answer("✅ تم تحديث رسالة الترحيب.")


@DP.message(Command("set_offers"))
async def so(m):
    if admin(m.from_user.id):
        value = (m.text or "").partition(" ")[2]
        await set_setting("offers", value)
        await m.answer("✅ تم تحديث العروض.")


@DP.callback_query(F.data == "a:broadcast")
async def broadcast(c, state):
    if admin(c.from_user.id):
        await state.set_state(S.admin_text)
        await c.answer()
        await c.message.answer(
            "📣 أرسل رسالة البث:"
        )


@DP.message(S.admin_text)
async def broadcast_msg(m, state):
    if not admin(m.from_user.id):
        return

    text = m.text or ""
    await state.clear()

    cc = await db()
    try:
        ids = [
            r[0]
            for r in await (
                await cc.execute(
                    "SELECT id FROM users WHERE banned=0"
                )
            ).fetchall()
        ]
    finally:
        await cc.close()

    sem = asyncio.Semaphore(20)
    ok = 0

    async def send(uid):
        nonlocal ok
        async with sem:
            try:
                await BOT.send_message(uid, text)
                ok += 1
            except Exception:
                pass
            await asyncio.sleep(0.05)

    await asyncio.gather(*(send(x) for x in ids))

    await m.answer(
        f"📣 تم الإرسال إلى {ok}/{len(ids)}"
    )


@DP.callback_query(F.data == "a:support")
async def a_support(c):
    if not admin(c.from_user.id):
        return

    cc = await db()
    try:
        rows = [
            dict(x)
            for x in await (
                await cc.execute(
                    """
                    SELECT * FROM support
                    WHERE status='open'
                    ORDER BY id
                    """
                )
            ).fetchall()
        ]
    finally:
        await cc.close()

    await c.answer()

    if not rows:
        return await c.message.answer(
            "لا توجد طلبات دعم."
        )

    for x in rows:
        await c.message.answer(
            f"🆘 #{x['id']} | "
            f"<code>{x['user_id']}</code>\n"
            f"{x['message']}",
            reply_markup=inline([
                [
                    InlineKeyboardButton(
                        text="💬 رد",
                        callback_data=f"sup:{x['id']}"
                    )
                ]
            ])
        )


@DP.callback_query(F.data.startswith("sup:"))
async def sup(c, state):
    if admin(c.from_user.id):
        await state.update_data(
            sid=int(c.data.split(":")[1])
        )
        await state.set_state(S.admin_reply)
        await c.answer()
        await c.message.answer(
            "أرسل الرد:"
        )


@DP.message(S.admin_reply)
async def sup_reply(m, state):
    if not admin(m.from_user.id):
        return

    d = await state.get_data()
    cc = await db()
    try:
        r = await (
            await cc.execute(
                "SELECT * FROM support WHERE id=?",
                (d["sid"],)
            )
        ).fetchone()

        if not r:
            await state.clear()
            return await m.answer(
                "❌ طلب الدعم غير موجود."
            )

        await cc.execute(
            """
            UPDATE support
            SET status='closed',reply=?,replied_at=?
            WHERE id=?
            """,
            (m.text or "", now(), d["sid"])
        )
        await cc.commit()
    finally:
        await cc.close()

    await state.clear()
    await m.answer("✅ تم الرد.")

    try:
        await BOT.send_message(
            r["user_id"],
            f"💬 رد الدعم على #{d['sid']}\n\n"
            f"{m.text or ''}"
        )
    except Exception:
        pass


@DP.callback_query(F.data.startswith("tx:"))
async def tx_open(c):
    if admin(c.from_user.id):
        await c.answer()
        await c.message.answer(
            "استخدم 📋 طلبات الشحن أو السحب "
            "من لوحة الإدارة لمعالجة الطلبات."
        )


async def health(req):
    return web.json_response({
        "status": "ok",
        "service": "ichancy-bot",
        "time": now()
    })


async def webhook_handler(request):
    # Telegram sends POST updates here.
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != get_webhook_secret():
        return web.Response(status=403, text="Forbidden")

    try:
        data = await request.json()
        update = Update.model_validate(data)
        await DP.feed_update(BOT, update)
        return web.Response(text="OK")
    except Exception:
        log.exception("Webhook update processing failed")
        return web.Response(status=500, text="Update failed")


async def create_server():
    app = web.Application()

    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    if PUBLIC_URL:
        app.router.add_post(
            WEBHOOK_PATH,
            webhook_handler
        )

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )
    await site.start()

    return runner


async def main():
    global BOT

    await init_db()

    BOT = Bot(
        BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
    )

    runner = await create_server()

    try:
        if PUBLIC_URL:
            secret = get_webhook_secret()

            webhook = PUBLIC_URL + WEBHOOK_PATH

            await BOT.set_webhook(
                url=webhook,
                secret_token=secret,
                drop_pending_updates=False,
                allowed_updates=DP.resolve_used_update_types()
            )

            log.info(
                "Ichancy Bot started in WEBHOOK mode. "
                "Admins=%s Webhook=%s",
                sorted(ADMIN_IDS),
                webhook
            )

            # Keep the Render Web Service alive.
            await asyncio.Event().wait()

        else:
            # Local fallback only. On Render PUBLIC_URL exists.
            await BOT.delete_webhook(
                drop_pending_updates=False
            )

            log.info(
                "Ichancy Bot started in POLLING mode. Admins=%s",
                sorted(ADMIN_IDS)
            )

            await DP.start_polling(
                BOT,
                allowed_updates=DP.resolve_used_update_types()
            )

    finally:
        try:
            if PUBLIC_URL:
                await BOT.delete_webhook(
                    drop_pending_updates=False
                )
        except Exception:
            pass

        await runner.cleanup()
        await BOT.session.close()


if __name__ == "__main__":
    asyncio.run(main())

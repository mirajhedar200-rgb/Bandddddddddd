import asyncio
import base64
import hashlib
import logging
import os
import re
from datetime import datetime, timezone, date
from typing import Optional

import aiosqlite
from aiohttp import web
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


# =========================================================
# SETTINGS
# =========================================================

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("ichancy_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

DB_PATH = os.getenv("DB_PATH", "ichancy_bot.db")
PORT = int(os.getenv("PORT", "10000"))

APP_SECRET = os.getenv("APP_SECRET", "").strip()

# Telegram channel for mandatory subscription
REQUIRED_CHANNEL = os.getenv(
    "REQUIRED_CHANNEL",
    "@Ban1D1",
).strip()

# Syrtel Cash information shown to users.
SYRTEL_CASH_NUMBER = os.getenv(
    "SYRTEL_CASH_NUMBER",
    "ضع رقم سيريتل كاش من Render",
).strip()

SYRTEL_CASH_NAME = os.getenv(
    "SYRTEL_CASH_NAME",
    "Syrtel Cash",
).strip()


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")

if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS is required")

if not APP_SECRET:
    raise RuntimeError(
        "APP_SECRET is required. Put a long random secret in Render."
    )


# =========================================================
# ENCRYPTION
# =========================================================

ENC_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(APP_SECRET.encode()).digest()
)

CIPHER = Fernet(ENC_KEY)

BOT: Optional[Bot] = None
DP = Dispatcher()


# =========================================================
# HELPERS
# =========================================================

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_utc() -> str:
    return date.today().isoformat()


def encrypt_secret(value: str) -> str:
    return CIPHER.encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return CIPHER.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return "[تعذر فك تشفير البيانات القديمة]"


def money(value: int) -> str:
    return f"{int(value):,}"


def clean_text(value: str, max_len: int = 4000) -> str:
    return (value or "").strip()[:max_len]


# =========================================================
# DATABASE
# =========================================================

async def db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(DB_PATH)

    conn.row_factory = aiosqlite.Row

    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=10000")

    return conn


DEFAULT_TERMS = """أهلاً بك في بوت إيشانسي ✨

قبل استخدام البوت يرجى الموافقة على شروط الاستخدام.

⚠️ الشروط:

1. يمنع إنشاء أكثر من حساب مستخدم لنفس الشخص.
2. يمنع استخدام بيانات وهمية أو التحايل على النظام.
3. يمنع مشاركة بيانات الحساب مع الآخرين.
4. يمنع استغلال الثغرات أو محاولة اختراق النظام.
5. يحق للإدارة إيقاف الحسابات المخالفة.
6. المستخدم مسؤول عن البيانات التي يدخلها.
7. بيانات الدخول المحفوظة يتم تشفيرها.
8. طلبات السحب تخضع للمراجعة قبل التنفيذ.
9. يجب إدخال بيانات السحب بشكل صحيح.

باستخدام البوت فأنت توافق على هذه الشروط.
"""


DEFAULT_SETTINGS = {
    "bot_name": "إيشانسي",
    "welcome_text": (
        "🌟 أهلاً بك في بوت إيشانسي\n\n"
        "اختر الخدمة التي تريدها من القائمة 👇"
    ),
    "terms_text": DEFAULT_TERMS,
    "referral_reward_points": "1000",
    "daily_gift_points": "1000",
    "offers_text": "لا توجد عروض نشطة حالياً 🎁",
    "entertainment_text": "قسم التسلية غير متاح حالياً.",
    "minimum_withdraw": "10000",
    "minimum_deposit": "1000",
}


async def init_db() -> None:

    conn = await db()

    try:

        await conn.executescript(
            """

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,

                referrer_id INTEGER,

                balance_points INTEGER NOT NULL DEFAULT 0,

                banned INTEGER NOT NULL DEFAULT 0,

                accepted_terms INTEGER NOT NULL DEFAULT 0,

                welcome_bonus_claimed INTEGER NOT NULL DEFAULT 0,

                created_at TEXT NOT NULL,

                last_seen_at TEXT NOT NULL,

                FOREIGN KEY (referrer_id)
                    REFERENCES users(id)
            );


            CREATE TABLE IF NOT EXISTS external_accounts (
                user_id INTEGER PRIMARY KEY,

                login_enc TEXT NOT NULL,

                password_enc TEXT NOT NULL,

                created_at TEXT NOT NULL,

                updated_at TEXT NOT NULL,

                FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                delta_points INTEGER NOT NULL,

                reason TEXT NOT NULL,

                created_at TEXT NOT NULL,

                FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS gift_codes (
                code TEXT PRIMARY KEY,

                points INTEGER NOT NULL,

                max_uses INTEGER NOT NULL DEFAULT 1,

                used_count INTEGER NOT NULL DEFAULT 0,

                active INTEGER NOT NULL DEFAULT 1,

                expires_at TEXT
            );


            CREATE TABLE IF NOT EXISTS gift_redemptions (
                user_id INTEGER NOT NULL,

                code TEXT NOT NULL,

                redeemed_at TEXT NOT NULL,

                PRIMARY KEY(user_id, code),

                FOREIGN KEY(user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE,

                FOREIGN KEY(code)
                    REFERENCES gift_codes(code)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS daily_claims (
                user_id INTEGER NOT NULL,

                claim_date TEXT NOT NULL,

                PRIMARY KEY(user_id, claim_date),

                FOREIGN KEY(user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                message_text TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'open',

                admin_reply TEXT,

                created_at TEXT NOT NULL,

                replied_at TEXT,

                FOREIGN KEY(user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS deposit_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                amount INTEGER NOT NULL,

                method TEXT NOT NULL,

                reference TEXT,

                status TEXT NOT NULL DEFAULT 'pending',

                admin_note TEXT,

                created_at TEXT NOT NULL,

                processed_at TEXT,

                FOREIGN KEY(user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                amount INTEGER NOT NULL,

                method TEXT NOT NULL,

                account_number TEXT NOT NULL,

                account_name TEXT,

                status TEXT NOT NULL DEFAULT 'pending',

                admin_note TEXT,

                created_at TEXT NOT NULL,

                processed_at TEXT,

                FOREIGN KEY(user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,

                value TEXT NOT NULL
            );


            CREATE INDEX IF NOT EXISTS idx_users_referrer
            ON users(referrer_id);


            CREATE INDEX IF NOT EXISTS idx_ledger_user
            ON ledger(user_id);


            CREATE INDEX IF NOT EXISTS idx_support_status
            ON support_tickets(status);


            CREATE INDEX IF NOT EXISTS idx_deposit_status
            ON deposit_requests(status);


            CREATE INDEX IF NOT EXISTS idx_withdrawal_status
            ON withdrawal_requests(status);

            """
        )

        # Old DB migration
        try:
            await conn.execute(
                """
                ALTER TABLE users
                ADD COLUMN welcome_bonus_claimed
                INTEGER NOT NULL DEFAULT 0
                """
            )
        except Exception:
            pass

        for key, value in DEFAULT_SETTINGS.items():

            await conn.execute(
                """
                INSERT OR IGNORE INTO settings(key, value)
                VALUES(?, ?)
                """,
                (key, value),
            )

        await conn.execute(
            """
            INSERT OR IGNORE INTO gift_codes(
                code,
                points,
                max_uses,
                used_count,
                active
            )
            VALUES(?, ?, ?, 0, 1)
            """,
            ("BANDA99", 5000, 0),
        )

        await conn.commit()

    finally:
        await conn.close()


# =========================================================
# SETTINGS
# =========================================================

async def get_setting(key: str, default: str = "") -> str:

    conn = await db()

    try:

        cur = await conn.execute(
            "SELECT value FROM settings WHERE key=?",
            (key,),
        )

        row = await cur.fetchone()

        return row["value"] if row else default

    finally:
        await conn.close()


async def set_setting(key: str, value: str) -> None:

    conn = await db()

    try:

        await conn.execute(
            """
            INSERT INTO settings(key, value)
            VALUES(?, ?)

            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )

        await conn.commit()

    finally:
        await conn.close()


# =========================================================
# USERS
# =========================================================

async def ensure_user(
    message: Message,
    referrer_id: Optional[int] = None,
) -> dict:

    user = message.from_user

    conn = await db()

    try:

        cur = await conn.execute(
            "SELECT * FROM users WHERE id=?",
            (user.id,),
        )

        row = await cur.fetchone()

        if row:

            await conn.execute(
                """
                UPDATE users

                SET username=?,
                    first_name=?,
                    last_seen_at=?

                WHERE id=?
                """,
                (
                    user.username,
                    user.first_name,
                    now_iso(),
                    user.id,
                ),
            )

            await conn.commit()

            result = dict(row)

            result["__new_user"] = False

            return result

        safe_ref = None

        if referrer_id and referrer_id != user.id:

            cur = await conn.execute(
                "SELECT id FROM users WHERE id=?",
                (referrer_id,),
            )

            if await cur.fetchone():
                safe_ref = referrer_id

        welcome_bonus = 15000

        created = now_iso()

        await conn.execute(
            """
            INSERT INTO users(
                id,
                username,
                first_name,
                referrer_id,
                balance_points,
                banned,
                accepted_terms,
                welcome_bonus_claimed,
                created_at,
                last_seen_at
            )

            VALUES(
                ?, ?, ?, ?, ?, 0, 0, 1, ?, ?
            )
            """,
            (
                user.id,
                user.username,
                user.first_name,
                safe_ref,
                welcome_bonus,
                created,
                created,
            ),
        )

        await conn.execute(
            """
            INSERT INTO ledger(
                user_id,
                delta_points,
                reason,
                created_at
            )
            VALUES(?, ?, ?, ?)
            """,
            (
                user.id,
                welcome_bonus,
                "🎁 بونص ترحيبي",
                created,
            ),
        )

        await conn.commit()

        # Referral reward
        if safe_ref:

            reward = int(
                await get_setting(
                    "referral_reward_points",
                    "1000",
                )
            )

            await conn.execute(
                """
                UPDATE users

                SET balance_points =
                    balance_points + ?

                WHERE id=?
                """,
                (reward, safe_ref),
            )

            await conn.execute(
                """
                INSERT INTO ledger(
                    user_id,
                    delta_points,
                    reason,
                    created_at
                )
                VALUES(?, ?, ?, ?)
                """,
                (
                    safe_ref,
                    reward,
                    f"إحالة المستخدم {user.id}",
                    now_iso(),
                ),
            )

            await conn.commit()

        cur = await conn.execute(
            "SELECT * FROM users WHERE id=?",
            (user.id,),
        )

        created_row = await cur.fetchone()

        result = dict(created_row)

        result["__new_user"] = True

        return result

    finally:
        await conn.close()


async def get_user(user_id: int) -> Optional[dict]:

    conn = await db()

    try:

        cur = await conn.execute(
            "SELECT * FROM users WHERE id=?",
            (user_id,),
        )

        row = await cur.fetchone()

        return dict(row) if row else None

    finally:
        await conn.close()


async def is_banned(user_id: int) -> bool:

    user = await get_user(user_id)

    return bool(user and user["banned"])


async def set_terms_accepted(user_id: int):

    conn = await db()

    try:

        await conn.execute(
            """
            UPDATE users

            SET accepted_terms=1

            WHERE id=?
            """,
            (user_id,),
        )

        await conn.commit()

    finally:
        await conn.close()


# =========================================================
# BALANCE
# =========================================================

async def change_balance(
    user_id: int,
    delta: int,
    reason: str,
) -> int:

    conn = await db()

    try:

        await conn.execute("BEGIN IMMEDIATE")

        cur = await conn.execute(
            """
            SELECT balance_points
            FROM users
            WHERE id=?
            """,
            (user_id,),
        )

        row = await cur.fetchone()

        if not row:
            raise ValueError("User not found")

        old_balance = int(row["balance_points"])

        new_balance = old_balance + delta

        if new_balance < 0:
            raise ValueError("Insufficient balance")

        await conn.execute(
            """
            UPDATE users

            SET balance_points=?

            WHERE id=?
            """,
            (
                new_balance,
                user_id,
            ),
        )

        await conn.execute(
            """
            INSERT INTO ledger(
                user_id,
                delta_points,
                reason,
                created_at
            )
            VALUES(?, ?, ?, ?)
            """,
            (
                user_id,
                delta,
                reason,
                now_iso(),
            ),
        )

        await conn.commit()

        return new_balance

    except Exception:

        await conn.rollback()

        raise

    finally:
        await conn.close()


# =========================================================
# ICHANCY ACCOUNT
# =========================================================

async def get_account(
    user_id: int,
) -> Optional[dict]:

    conn = await db()

    try:

        cur = await conn.execute(
            """
            SELECT *
            FROM external_accounts

            WHERE user_id=?
            """,
            (user_id,),
        )

        row = await cur.fetchone()

        return dict(row) if row else None

    finally:
        await conn.close()


async def save_account(
    user_id: int,
    login_name: str,
    password: str,
) -> None:

    conn = await db()

    try:

        await conn.execute(
            """
            INSERT INTO external_accounts(
                user_id,
                login_enc,
                password_enc,
                created_at,
                updated_at
            )

            VALUES(?, ?, ?, ?, ?)

            ON CONFLICT(user_id)

            DO UPDATE SET

                login_enc=excluded.login_enc,

                password_enc=excluded.password_enc,

                updated_at=excluded.updated_at
            """,
            (
                user_id,
                encrypt_secret(login_name),
                encrypt_secret(password),
                now_iso(),
                now_iso(),
            ),
        )

        await conn.commit()

    finally:
        await conn.close()


# =========================================================
# CHANNEL SUBSCRIPTION
# =========================================================

async def check_channel_subscription(
    user_id: int,
) -> bool:

    if not BOT:
        return False

    channel = REQUIRED_CHANNEL

    try:

        member = await BOT.get_chat_member(
            chat_id=channel,
            user_id=user_id,
        )

        return member.status in {
            "creator",
            "administrator",
            "member",
        }

    except Exception as exc:

        logger.warning(
            "Channel subscription check failed: %s",
            exc,
        )

        return False


def subscription_keyboard():

    channel_username = REQUIRED_CHANNEL.replace("@", "")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 الاشتراك بالقناة",
                    url=f"https://t.me/{channel_username}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ تحقّق من الاشتراك",
                    callback_data="check_subscription",
                )
            ],
        ]
    )


async def require_subscription(
    message: Message,
) -> bool:

    if await check_channel_subscription(
        message.from_user.id
    ):
        return True

    await message.answer(
        "🔒 <b>الاشتراك إجباري</b>\n\n"
        "لاستخدام البوت يجب أولاً الاشتراك في القناة التالية:\n\n"
        f"📢 {REQUIRED_CHANNEL}\n\n"
        "بعد الاشتراك اضغط «تحقّق من الاشتراك».",
        reply_markup=subscription_keyboard(),
    )

    return False


@DP.callback_query(F.data == "check_subscription")
async def check_subscription_callback(
    callback: CallbackQuery,
):

    if await check_channel_subscription(
        callback.from_user.id
    ):

        await callback.answer(
            "تم التحقق بنجاح ✅",
            show_alert=True,
        )

        await callback.message.answer(
            "🎉 تم تفعيل وصولك إلى البوت.",
            reply_markup=main_keyboard(),
        )

    else:

        await callback.answer(
            "لم يتم العثور على اشتراكك بالقناة.",
            show_alert=True,
        )


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[

            [
                KeyboardButton(text="👤 حسابي"),
                KeyboardButton(text="💰 رصيدي"),
            ],

            [
                KeyboardButton(text="💳 شحن"),
                KeyboardButton(text="💸 سحب"),
            ],

            [
                KeyboardButton(text="💵 الإحالات"),
                KeyboardButton(text="🔄 السجلات"),
            ],

            [
                KeyboardButton(text="🎁 كود هدية"),
                KeyboardButton(text="🎁 الهدية اليومية"),
            ],

            [
                KeyboardButton(text="🎁 العروض النشطة"),
                KeyboardButton(text="💬 الدعم"),
            ],

            [
                KeyboardButton(text="🆔 ID"),
                KeyboardButton(text="⚠️ شروط الاستخدام"),
            ],

            [
                KeyboardButton(text="🎮 للتسلية"),
            ],

        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_keyboard():

    builder = InlineKeyboardBuilder()

    builder.button(
        text="📊 الإحصائيات",
        callback_data="adm:stats",
    )

    builder.button(
        text="👤 بحث مستخدم",
        callback_data="adm:user",
    )

    builder.button(
        text="🚫 حظر مستخدم",
        callback_data="adm:ban",
    )

    builder.button(
        text="✅ فك الحظر",
        callback_data="adm:unban",
    )

    builder.button(
        text="💰 تعديل الرصيد",
        callback_data="adm:balance",
    )

    builder.button(
        text="💳 طلبات الشحن",
        callback_data="adm:deposits",
    )

    builder.button(
        text="💸 طلبات السحب",
        callback_data="adm:withdrawals",
    )

    builder.button(
        text="📣 بث رسالة",
        callback_data="adm:broadcast",
    )

    builder.button(
        text="🎁 إدارة الأكواد",
        callback_data="adm:gift",
    )

    builder.button(
        text="💬 طلبات الدعم",
        callback_data="adm:support",
    )

    builder.button(
        text="⚙️ الإعدادات",
        callback_data="adm:settings",
    )

    builder.adjust(2)

    return builder.as_markup()


def account_create_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ إنشاء حساب إيشانسي",
                    callback_data="account:create",
                )
            ]
        ]
    )


# =========================================================
# STATES
# =========================================================

class AccountStates(StatesGroup):

    waiting_login = State()

    waiting_password = State()


class SupportStates(StatesGroup):

    waiting_message = State()


class GiftStates(StatesGroup):

    waiting_code = State()


class DepositStates(StatesGroup):

    waiting_amount = State()

    waiting_reference = State()


class WithdrawalStates(StatesGroup):

    waiting_amount = State()

    waiting_number = State()

    waiting_name = State()


class AdminStates(StatesGroup):

    waiting_user_id = State()

    waiting_balance_user = State()

    waiting_balance_amount = State()

    waiting_broadcast = State()

    waiting_gift = State()

    waiting_support_reply = State()

    waiting_withdrawal_note = State()

    waiting_deposit_note = State()


# =========================================================
# SAFETY
# =========================================================

async def ensure_not_banned(
    message: Message,
) -> bool:

    if await is_banned(
        message.from_user.id
    ):

        await message.answer(
            "🚫 هذا الحساب موقوف.\n"
            "تواصل مع الإدارة."
        )

        return False

    return True


async def access_ok(
    message: Message,
) -> bool:

    if not await ensure_not_banned(message):
        return False

    return await require_subscription(message)


# =========================================================
# START
# =========================================================

async def show_main_menu(
    message: Message,
):

    welcome = await get_setting(
        "welcome_text",
        DEFAULT_SETTINGS["welcome_text"],
    )

    await message.answer(
        welcome,
        reply_markup=main_keyboard(),
    )


async def show_terms(
    message: Message,
):

    text = await get_setting(
        "terms_text",
        DEFAULT_TERMS,
    )

    user = await get_user(
        message.from_user.id
    )

    if user and user["accepted_terms"]:

        await message.answer(
            text,
            reply_markup=main_keyboard(),
        )

    else:

        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ أوافق وأتابع",
                            callback_data="terms:accept",
                        )
                    ]
                ]
            ),
        )


async def bot_start(
    message: Message,
    state: FSMContext,
    ref_arg: Optional[str] = None,
):

    await state.clear()

    referrer_id = None

    if ref_arg and ref_arg.isdigit():

        referrer_id = int(ref_arg)

    user = await ensure_user(
        message,
        referrer_id,
    )

    if user["banned"]:

        await message.answer(
            "🚫 هذا الحساب موقوف."
        )

        return

    # Mandatory subscription FIRST
    if not await require_subscription(message):
        return

    if user.get("__new_user"):

        await message.answer(
            "🎉 <b>أهلاً بك!</b>\n\n"
            "🎁 تمت إضافة <b>15,000 ل.س</b> "
            "كبونص ترحيبي.\n\n"
            f"💰 رصيدك: "
            f"<b>{money(user['balance_points'])} ل.س</b>"
        )

    if not user["accepted_terms"]:

        await show_terms(message)

        return

    await show_main_menu(message)


@DP.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
):

    parts = (
        message.text or ""
    ).split(
        maxsplit=1
    )

    ref_arg = (
        parts[1]
        if len(parts) > 1
        else None
    )

    await bot_start(
        message,
        state,
        ref_arg,
    )


# =========================================================
# TERMS
# =========================================================

@DP.callback_query(F.data == "terms:accept")
async def terms_accept(
    callback: CallbackQuery,
):

    if not await check_channel_subscription(
        callback.from_user.id
    ):

        await callback.answer(
            "يجب الاشتراك بالقناة أولاً.",
            show_alert=True,
        )

        return

    await set_terms_accepted(
        callback.from_user.id
    )

    await callback.answer(
        "تم قبول الشروط ✅"
    )

    await callback.message.answer(
        "✅ تم تفعيل حسابك.",
        reply_markup=main_keyboard(),
    )


# =========================================================
# ACCOUNT
# =========================================================

@DP.message(F.text == "👤 حسابي")
async def account_menu(
    message: Message,
):

    if not await access_ok(message):
        return

    account = await get_account(
        message.from_user.id
    )

    user = await get_user(
        message.from_user.id
    )

    if not account:

        await message.answer(
            "👤 <b>حساب إيشانسي</b>\n\n"
            "لم تقم بإنشاء حسابك بعد.",
            reply_markup=account_create_keyboard(),
        )

        return

    login_name = decrypt_secret(
        account["login_enc"]
    )

    password = decrypt_secret(
        account["password_enc"]
    )

    await message.answer(
        "👤 <b>معلومات حساب إيشانسي</b>\n\n"
        f"👤 اسم المستخدم:\n"
        f"<code>{login_name}</code>\n\n"
        f"🔑 كلمة المرور:\n"
        f"<code>{password}</code>\n\n"
        f"🆔 ID:\n"
        f"<code>{user['id']}</code>\n\n"
        f"💰 رصيد البوت:\n"
        f"<b>{money(user['balance_points'])} ل.س</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ تعديل بيانات الحساب",
                        callback_data="account:edit",
                    )
                ]
            ]
        ),
    )


@DP.callback_query(
    F.data.in_(
        [
            "account:create",
            "account:edit",
        ]
    )
)
async def account_create(
    callback: CallbackQuery,
    state: FSMContext,
):

    await state.set_state(
        AccountStates.waiting_login
    )

    await callback.answer()

    await callback.message.answer(
        "👤 أرسل اسم مستخدم إيشانسي:"
    )


@DP.message(AccountStates.waiting_login)
async def account_login(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    value = (
        message.text or ""
    ).strip()

    if not 3 <= len(value) <= 64:

        await message.answer(
            "اسم المستخدم يجب أن يكون بين "
            "3 و64 محرفاً."
        )

        return

    await state.update_data(
        login=value
    )

    await state.set_state(
        AccountStates.waiting_password
    )

    await message.answer(
        "🔑 أرسل كلمة مرور إيشانسي:"
    )


@DP.message(AccountStates.waiting_password)
async def account_password(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    value = (
        message.text or ""
    ).strip()

    if not 4 <= len(value) <= 128:

        await message.answer(
            "كلمة المرور يجب أن تكون بين "
            "4 و128 محرفاً."
        )

        return

    data = await state.get_data()

    await save_account(
        message.from_user.id,
        data["login"],
        value,
    )

    await state.clear()

    user = await get_user(
        message.from_user.id
    )

    await message.answer(
        "✅ <b>تم حفظ حساب إيشانسي</b>\n\n"
        f"👤 المستخدم: <code>{data['login']}</code>\n"
        f"🔑 كلمة المرور: <code>{value}</code>\n"
        f"🆔 ID: <code>{user['id']}</code>\n\n"
        f"💰 رصيدك: "
        f"<b>{money(user['balance_points'])} ل.س</b>",
        reply_markup=main_keyboard(),
    )


# =========================================================
# BALANCE
# =========================================================

@DP.message(F.text == "💰 رصيدي")
async def balance(
    message: Message,
):

    if not await access_ok(message):
        return

    user = await get_user(
        message.from_user.id
    )

    await message.answer(
        "💰 <b>رصيدك</b>\n\n"
        f"الرصيد الحالي:\n"
        f"<b>{money(user['balance_points'])} ل.س</b>"
    )


# =========================================================
# DEPOSIT
# =========================================================

def deposit_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 Syrtel Cash",
                    callback_data="deposit:syrtel",
                )
            ]
        ]
    )


@DP.message(F.text == "💳 شحن")
async def deposit_start(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    minimum = int(
        await get_setting(
            "minimum_deposit",
            "1000",
        )
    )

    await state.update_data(
        method="Syrtel Cash"
    )

    await state.set_state(
        DepositStates.waiting_amount
    )

    await message.answer(
        "💳 <b>شحن الرصيد</b>\n\n"
        "اختر طريقة الشحن ثم أرسل المبلغ.\n\n"
        f"الحد الأدنى: "
        f"<b>{money(minimum)} ل.س</b>"
    )


@DP.message(DepositStates.waiting_amount)
async def deposit_amount(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    text = (
        message.text or ""
    ).replace(",", "").strip()

    if not text.isdigit():

        await message.answer(
            "❌ أرسل المبلغ بالأرقام فقط."
        )

        return

    amount = int(text)

    minimum = int(
        await get_setting(
            "minimum_deposit",
            "1000",
        )
    )

    if amount < minimum:

        await message.answer(
            f"❌ الحد الأدنى للشحن "
            f"{money(minimum)} ل.س."
        )

        return

    await state.update_data(
        amount=amount
    )

    await state.set_state(
        DepositStates.waiting_reference
    )

    await message.answer(
        "📱 الآن أرسل رقم العملية / رقم التحويل "
        "أو أي إثبات متاح للشحن.\n\n"
        "سيتم إرسال الطلب للإدارة للمراجعة."
    )


@DP.message(DepositStates.waiting_reference)
async def deposit_reference(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    data = await state.get_data()

    amount = int(data["amount"])

    reference = clean_text(
        message.text or "",
        500,
    )

    conn = await db()

    try:

        cur = await conn.execute(
            """
            INSERT INTO deposit_requests(
                user_id,
                amount,
                method,
                reference,
                status,
                created_at
            )
            VALUES(?, ?, ?, ?, 'pending', ?)
            """,
            (
                message.from_user.id,
                amount,
                "Syrtel Cash",
                reference,
                now_iso(),
            ),
        )

        request_id = cur.lastrowid

        await conn.commit()

    finally:
        await conn.close()

    await state.clear()

    await message.answer(
        "✅ <b>تم إرسال طلب الشحن</b>\n\n"
        f"رقم الطلب: <code>#{request_id}</code>\n"
        f"المبلغ: <b>{money(amount)} ل.س</b>\n"
        "الحالة: ⏳ قيد المراجعة"
    )

    for admin_id in ADMIN_IDS:

        try:

            await BOT.send_message(
                admin_id,
                "💳 <b>طلب شحن جديد</b>\n\n"
                f"الطلب: <code>#{request_id}</code>\n"
                f"المستخدم: <code>{message.from_user.id}</code>\n"
                f"المبلغ: <b>{money(amount)} ل.س</b>\n"
                f"الطريقة: Syrtel Cash\n"
                f"الإثبات/المرجع:\n"
                f"<code>{reference}</code>",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ قبول",
                                callback_data=f"dep:approve:{request_id}",
                            ),
                            InlineKeyboardButton(
                                text="❌ رفض",
                                callback_data=f"dep:reject:{request_id}",
                            ),
                        ]
                    ]
                ),
            )

        except Exception:

            logger.exception(
                "Failed to notify admin"
            )


# =========================================================
# WITHDRAW
# =========================================================

@DP.message(F.text == "💸 سحب")
async def withdrawal_start(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    user = await get_user(
        message.from_user.id
    )

    minimum = int(
        await get_setting(
            "minimum_withdraw",
            "10000",
        )
    )

    await state.set_state(
        WithdrawalStates.waiting_amount
    )

    await message.answer(
        "💸 <b>طلب سحب</b>\n\n"
        f"رصيدك الحالي: "
        f"<b>{money(user['balance_points'])} ل.س</b>\n\n"
        f"الحد الأدنى للسحب: "
        f"<b>{money(minimum)} ل.س</b>\n\n"
        "أرسل المبلغ الذي تريد سحبه:"
    )


@DP.message(WithdrawalStates.waiting_amount)
async def withdrawal_amount(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    text = (
        message.text or ""
    ).replace(",", "").strip()

    if not text.isdigit():

        await message.answer(
            "❌ أرسل المبلغ بالأرقام فقط."
        )

        return

    amount = int(text)

    minimum = int(
        await get_setting(
            "minimum_withdraw",
            "10000",
        )
    )

    user = await get_user(
        message.from_user.id
    )

    if amount < minimum:

        await message.answer(
            f"❌ الحد الأدنى للسحب "
            f"{money(minimum)} ل.س."
        )

        return

    if amount > int(
        user["balance_points"]
    ):

        await message.answer(
            "❌ المبلغ أكبر من رصيدك."
        )

        return

    await state.update_data(
        amount=amount
    )

    await state.set_state(
        WithdrawalStates.waiting_number
    )

    await message.answer(
        "📱 أرسل رقم <b>Syrtel Cash</b> "
        "الذي تريد استلام السحب عليه:"
    )


@DP.message(WithdrawalStates.waiting_number)
async def withdrawal_number(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    number = (
        message.text or ""
    ).strip()

    if len(number) < 7:

        await message.answer(
            "❌ أدخل رقم Syrtel Cash صحيحاً."
        )

        return

    await state.update_data(
        account_number=number
    )

    await state.set_state(
        WithdrawalStates.waiting_name
    )

    await message.answer(
        "👤 أرسل اسم صاحب رقم Syrtel Cash:"
    )


@DP.message(WithdrawalStates.waiting_name)
async def withdrawal_name(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    data = await state.get_data()

    amount = int(data["amount"])

    user = await get_user(
        message.from_user.id
    )

    if amount > int(
        user["balance_points"]
    ):

        await state.clear()

        await message.answer(
            "❌ لم يعد رصيدك كافياً."
        )

        return

    account_name = clean_text(
        message.text or "",
        200,
    )

    # Reserve balance immediately.
    try:

        await change_balance(
            message.from_user.id,
            -amount,
            f"💸 حجز مبلغ طلب سحب",
        )

    except ValueError:

        await state.clear()

        await message.answer(
            "❌ تعذر حجز المبلغ من رصيدك."
        )

        return

    conn = await db()

    try:

        cur = await conn.execute(
            """
            INSERT INTO withdrawal_requests(
                user_id,
                amount,
                method,
                account_number,
                account_name,
                status,
                created_at
            )
            VALUES(
                ?, ?, ?, ?, ?, 'pending', ?
            )
            """,
            (
                message.from_user.id,
                amount,
                "Syrtel Cash",
                data["account_number"],
                account_name,
                now_iso(),
            ),
        )

        request_id = cur.lastrowid

        await conn.commit()

    finally:
        await conn.close()

    await state.clear()

    await message.answer(
        "✅ <b>تم إرسال طلب السحب</b>\n\n"
        f"رقم الطلب: <code>#{request_id}</code>\n"
        f"المبلغ: <b>{money(amount)} ل.س</b>\n"
        "الطريقة: Syrtel Cash\n"
        "الحالة: ⏳ قيد المراجعة\n\n"
        "تم حجز المبلغ من رصيدك مؤقتاً حتى تتم معالجة الطلب."
    )

    for admin_id in ADMIN_IDS:

        try:

            await BOT.send_message(
                admin_id,
                "💸 <b>طلب سحب جديد</b>\n\n"
                f"الطلب: <code>#{request_id}</code>\n"
                f"المستخدم: <code>{message.from_user.id}</code>\n"
                f"المبلغ: <b>{money(amount)} ل.س</b>\n"
                "الطريقة: Syrtel Cash\n"
                f"رقم التحويل: <code>{data['account_number']}</code>\n"
                f"اسم صاحب الحساب: {account_name}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="✅ تنفيذ السحب",
                                callback_data=f"wd:approve:{request_id}",
                            ),
                            InlineKeyboardButton(
                                text="❌ رفض وإرجاع الرصيد",
                                callback_data=f"wd:reject:{request_id}",
                            ),
                        ]
                    ]
                ),
            )

        except Exception:

            logger.exception(
                "Failed to notify admin"
            )


# =========================================================
# WITHDRAW / DEPOSIT ADMIN ACTIONS
# =========================================================

async def get_deposit(
    request_id: int,
) -> Optional[dict]:

    conn = await db()

    try:

        cur = await conn.execute(
            """
            SELECT *
            FROM deposit_requests
            WHERE id=?
            """,
            (request_id,),
        )

        row = await cur.fetchone()

        return dict(row) if row else None

    finally:
        await conn.close()


async def get_withdrawal(
    request_id: int,
) -> Optional[dict]:

    conn = await db()

    try:

        cur = await conn.execute(
            """
            SELECT *
            FROM withdrawal_requests
            WHERE id=?
            """,
            (request_id,),
        )

        row = await cur.fetchone()

        return dict(row) if row else None

    finally:
        await conn.close()


@DP.callback_query(
    F.data.startswith("dep:")
)
async def deposit_admin_action(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    parts = callback.data.split(":")

    action = parts[1]

    request_id = int(parts[2])

    request = await get_deposit(
        request_id
    )

    if not request:

        await callback.answer(
            "الطلب غير موجود.",
            show_alert=True,
        )

        return

    if request["status"] != "pending":

        await callback.answer(
            "تمت معالجة الطلب مسبقاً.",
            show_alert=True,
        )

        return

    conn = await db()

    try:

        if action == "approve":

            await conn.execute(
                """
                UPDATE deposit_requests

                SET status='approved',
                    processed_at=?

                WHERE id=?
                """,
                (
                    now_iso(),
                    request_id,
                ),
            )

            await conn.commit()

            await change_balance(
                int(request["user_id"]),
                int(request["amount"]),
                f"💳 شحن طلب #{request_id}",
            )

            await BOT.send_message(
                int(request["user_id"]),
                "✅ <b>تم قبول طلب الشحن</b>\n\n"
                f"الطلب: #{request_id}\n"
                f"المبلغ: "
                f"<b>{money(request['amount'])} ل.س</b>",
            )

            await callback.message.edit_reply_markup(
                reply_markup=None
            )

            await callback.answer(
                "تم قبول الشحن ✅"
            )

        else:

            await conn.execute(
                """
                UPDATE deposit_requests

                SET status='rejected',
                    processed_at=?

                WHERE id=?
                """,
                (
                    now_iso(),
                    request_id,
                ),
            )

            await conn.commit()

            await BOT.send_message(
                int(request["user_id"]),
                "❌ <b>تم رفض طلب الشحن</b>\n\n"
                f"رقم الطلب: #{request_id}",
            )

            await callback.message.edit_reply_markup(
                reply_markup=None
            )

            await callback.answer(
                "تم رفض الشحن."
            )

    finally:

        await conn.close()


@DP.callback_query(
    F.data.startswith("wd:")
)
async def withdrawal_admin_action(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    parts = callback.data.split(":")

    action = parts[1]

    request_id = int(parts[2])

    request = await get_withdrawal(
        request_id
    )

    if not request:

        await callback.answer(
            "الطلب غير موجود.",
            show_alert=True,
        )

        return

    if request["status"] != "pending":

        await callback.answer(
            "تمت معالجة الطلب مسبقاً.",
            show_alert=True,
        )

        return

    conn = await db()

    try:

        if action == "approve":

            await conn.execute(
                """
                UPDATE withdrawal_requests

                SET status='approved',
                    processed_at=?

                WHERE id=?
                """,
                (
                    now_iso(),
                    request_id,
                ),
            )

            await conn.commit()

            await BOT.send_message(
                int(request["user_id"]),
                "✅ <b>تم تنفيذ طلب السحب</b>\n\n"
                f"رقم الطلب: #{request_id}\n"
                f"المبلغ: "
                f"<b>{money(request['amount'])} ل.س</b>\n"
                "الطريقة: Syrtel Cash",
            )

            await callback.message.edit_reply_markup(
                reply_markup=None
            )

            await callback.answer(
                "تم تنفيذ السحب ✅"
            )

        else:

            # Return reserved amount
            await change_balance(
                int(request["user_id"]),
                int(request["amount"]),
                f"↩️ إرجاع مبلغ السحب #{request_id}",
            )

            await conn.execute(
                """
                UPDATE withdrawal_requests

                SET status='rejected',
                    processed_at=?

                WHERE id=?
                """,
                (
                    now_iso(),
                    request_id,
                ),
            )

            await conn.commit()

            await BOT.send_message(
                int(request["user_id"]),
                "❌ <b>تم رفض طلب السحب</b>\n\n"
                f"رقم الطلب: #{request_id}\n"
                f"تم إرجاع "
                f"<b>{money(request['amount'])} ل.س</b> "
                "إلى رصيدك.",
            )

            await callback.message.edit_reply_markup(
                reply_markup=None
            )

            await callback.answer(
                "تم الرفض وإرجاع الرصيد."
            )

    finally:

        await conn.close()


# =========================================================
# ID
# =========================================================

@DP.message(F.text == "🆔 ID")
async def show_id(
    message: Message,
):

    if not await access_ok(message):
        return

    await message.answer(
        f"🆔 ID الخاص بك:\n"
        f"<code>{message.from_user.id}</code>"
    )


# =========================================================
# REFERRALS
# =========================================================

@DP.message(F.text == "💵 الإحالات")
async def referrals(
    message: Message,
):

    if not await access_ok(message):
        return

    conn = await db()

    try:

        cur = await conn.execute(
            """
            SELECT COUNT(*) c

            FROM users

            WHERE referrer_id=?
            AND banned=0
            """,
            (message.from_user.id,),
        )

        count = int(
            (await cur.fetchone())["c"]
        )

    finally:

        await conn.close()

    me = await BOT.get_me()

    link = (
        f"https://t.me/"
        f"{me.username}"
        f"?start={message.from_user.id}"
    )

    reward = await get_setting(
        "referral_reward_points",
        "1000",
    )

    await message.answer(
        "💵 <b>الإحالات</b>\n\n"
        f"👥 إحالاتك: <b>{count}</b>\n"
        f"🎁 المكافأة: "
        f"<b>{money(int(reward))} ل.س</b>\n\n"
        f"🔗 رابطك:\n"
        f"<code>{link}</code>"
    )


# =========================================================
# RECORDS
# =========================================================

@DP.message(F.text == "🔄 السجلات")
async def records(
    message: Message,
):

    if not await access_ok(message):
        return

    conn = await db()

    try:

        cur = await conn.execute(
            """
            SELECT *

            FROM ledger

            WHERE user_id=?

            ORDER BY id DESC

            LIMIT 20
            """,
            (message.from_user.id,),
        )

        rows = await cur.fetchall()

    finally:

        await conn.close()

    if not rows:

        await message.answer(
            "لا توجد عمليات حتى الآن."
        )

        return

    lines = [
        "📋 <b>سجلات الحساب</b>\n"
    ]

    for row in rows:

        sign = (
            "+"
            if row["delta_points"] >= 0
            else ""
        )

        lines.append(
            f"{row['created_at'][:19]}\n"
            f"{sign}{money(row['delta_points'])} ل.س\n"
            f"{row['reason']}\n"
        )

    await message.answer(
        "\n".join(lines)
    )


# =========================================================
# GIFT
# =========================================================

@DP.message(F.text == "🎁 كود هدية")
async def gift_start(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    await state.set_state(
        GiftStates.waiting_code
    )

    await message.answer(
        "🎁 أرسل كود الهدية:"
    )


@DP.message(GiftStates.waiting_code)
async def gift_redeem(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    code = (
        message.text or ""
    ).strip().upper()

    conn = await db()

    try:

        await conn.execute(
            "BEGIN IMMEDIATE"
        )

        cur = await conn.execute(
            """
            SELECT *

            FROM gift_codes

            WHERE code=?
            AND active=1
            """,
            (code,),
        )

        gift = await cur.fetchone()

        if not gift:

            await conn.rollback()

            await message.answer(
                "❌ الكود غير صالح."
            )

            return

        cur = await conn.execute(
            """
            SELECT 1

            FROM gift_redemptions

            WHERE user_id=?
            AND code=?
            """,
            (
                message.from_user.id,
                code,
            ),
        )

        if await cur.fetchone():

            await conn.rollback()

            await message.answer(
                "❌ استخدمت هذا الكود مسبقاً."
            )

            return

        max_uses = int(
            gift["max_uses"]
        )

        used = int(
            gift["used_count"]
        )

        if max_uses > 0 and used >= max_uses:

            await conn.rollback()

            await message.answer(
                "❌ انتهت مرات استخدام الكود."
            )

            return

        points = int(
            gift["points"]
        )

        await conn.execute(
            """
            UPDATE gift_codes

            SET used_count=used_count+1

            WHERE code=?
            """,
            (code,),
        )

        await conn.execute(
            """
            INSERT INTO gift_redemptions(
                user_id,
                code,
                redeemed_at
            )
            VALUES(?, ?, ?)
            """,
            (
                message.from_user.id,
                code,
                now_iso(),
            ),
        )

        await conn.execute(
            """
            UPDATE users

            SET balance_points =
                balance_points + ?

            WHERE id=?
            """,
            (
                points,
                message.from_user.id,
            ),
        )

        await conn.execute(
            """
            INSERT INTO ledger(
                user_id,
                delta_points,
                reason,
                created_at
            )
            VALUES(?, ?, ?, ?)
            """,
            (
                message.from_user.id,
                points,
                f"🎁 كود {code}",
                now_iso(),
            ),
        )

        await conn.commit()

        await message.answer(
            f"✅ تمت إضافة "
            f"<b>{money(points)} ل.س</b> "
            "إلى رصيدك."
        )

    except Exception:

        await conn.rollback()

        raise

    finally:

        await conn.close()

        await state.clear()


# =========================================================
# DAILY GIFT
# =========================================================

@DP.message(F.text == "🎁 الهدية اليومية")
async def daily_gift(
    message: Message,
):

    if not await access_ok(message):
        return

    reward = int(
        await get_setting(
            "daily_gift_points",
            "1000",
        )
    )

    day = today_utc()

    conn = await db()

    try:

        await conn.execute(
            "BEGIN IMMEDIATE"
        )

        cur = await conn.execute(
            """
            SELECT 1

            FROM daily_claims

            WHERE user_id=?
            AND claim_date=?
            """,
            (
                message.from_user.id,
                day,
            ),
        )

        if await cur.fetchone():

            await conn.rollback()

            await message.answer(
                "🎁 استلمت هدية اليوم مسبقاً."
            )

            return

        await conn.execute(
            """
            INSERT INTO daily_claims(
                user_id,
                claim_date
            )
            VALUES(?, ?)
            """,
            (
                message.from_user.id,
                day,
            ),
        )

        await conn.execute(
            """
            UPDATE users

            SET balance_points =
                balance_points + ?

            WHERE id=?
            """,
            (
                reward,
                message.from_user.id,
            ),
        )

        await conn.execute(
            """
            INSERT INTO ledger(
                user_id,
                delta_points,
                reason,
                created_at
            )
            VALUES(?, ?, ?, ?)
            """,
            (
                message.from_user.id,
                reward,
                "🎁 الهدية اليومية",
                now_iso(),
            ),
        )

        await conn.commit()

        await message.answer(
            f"🎁 تمت إضافة "
            f"<b>{money(reward)} ل.س</b>"
        )

    except Exception:

        await conn.rollback()

        raise

    finally:

        await conn.close()


# =========================================================
# SUPPORT
# =========================================================

@DP.message(F.text == "💬 الدعم")
async def support_start(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    await state.set_state(
        SupportStates.waiting_message
    )

    await message.answer(
        "💬 أرسل رسالتك للدعم:"
    )


@DP.message(SupportStates.waiting_message)
async def support_receive(
    message: Message,
    state: FSMContext,
):

    if not await access_ok(message):
        return

    conn = await db()

    try:

        cur = await conn.execute(
            """
            INSERT INTO support_tickets(
                user_id,
                message_text,
                status,
                created_at
            )
            VALUES(?, ?, 'open', ?)
            """,
            (
                message.from_user.id,
                clean_text(
                    message.text or ""
                ),
                now_iso(),
            ),
        )

        ticket_id = cur.lastrowid

        await conn.commit()

    finally:

        await conn.close()

    await state.clear()

    await message.answer(
        "✅ تم إرسال رسالتك للدعم.\n"
        f"رقم الطلب: <code>#{ticket_id}</code>"
    )

    for admin_id in ADMIN_IDS:

        try:

            await BOT.send_message(
                admin_id,
                "🆘 <b>طلب دعم جديد</b>\n\n"
                f"#{ticket_id}\n"
                f"المستخدم: "
                f"<code>{message.from_user.id}</code>\n\n"
                f"{message.text[:3500]}",
            )

        except Exception:

            logger.exception(
                "Support notification failed"
            )


# =========================================================
# OFFERS / TERMS / ENTERTAINMENT
# =========================================================

@DP.message(F.text == "🎁 العروض النشطة")
async def offers(
    message: Message,
):

    if not await access_ok(message):
        return

    text = await get_setting(
        "offers_text",
        DEFAULT_SETTINGS["offers_text"],
    )

    await message.answer(text)


@DP.message(F.text == "🎮 للتسلية")
async def entertainment(
    message: Message,
):

    if not await access_ok(message):
        return

    text = await get_setting(
        "entertainment_text",
        DEFAULT_SETTINGS["entertainment_text"],
    )

    await message.answer(text)


@DP.message(F.text == "⚠️ شروط الاستخدام")
async def terms(
    message: Message,
):

    if not await access_ok(message):
        return

    await show_terms(message)


# =========================================================
# ADMIN
# =========================================================

def is_admin(user_id: int) -> bool:

    return user_id in ADMIN_IDS


@DP.message(Command("admin"))
async def admin_command(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    await message.answer(
        "🛠 <b>لوحة تحكم الإدارة</b>\n\n"
        "اختر العملية:",
        reply_markup=admin_keyboard(),
    )


# =========================================================
# ADMIN STATS
# =========================================================

@DP.callback_query(F.data == "adm:stats")
async def admin_stats(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    conn = await db()

    try:

        cur = await conn.execute(
            "SELECT COUNT(*) c FROM users"
        )

        users = int(
            (await cur.fetchone())["c"]
        )

        cur = await conn.execute(
            """
            SELECT COUNT(*)
            c

            FROM users

            WHERE banned=1
            """
        )

        banned = int(
            (await cur.fetchone())["c"]
        )

        cur = await conn.execute(
            """
            SELECT COALESCE(
                SUM(balance_points),
                0
            ) total

            FROM users
            """
        )

        balance_total = int(
            (await cur.fetchone())["total"]
        )

        cur = await conn.execute(
            """
            SELECT COUNT(*)
            c

            FROM external_accounts
            """
        )

        accounts = int(
            (await cur.fetchone())["c"]
        )

        cur = await conn.execute(
            """
            SELECT COUNT(*)
            c

            FROM deposit_requests

            WHERE status='pending'
            """
        )

        deposits = int(
            (await cur.fetchone())["c"]
        )

        cur = await conn.execute(
            """
            SELECT COUNT(*)
            c

            FROM withdrawal_requests

            WHERE status='pending'
            """
        )

        withdrawals = int(
            (await cur.fetchone())["c"]
        )

    finally:

        await conn.close()

    await callback.message.answer(
        "📊 <b>إحصائيات البوت</b>\n\n"
        f"👥 المستخدمون: <b>{users}</b>\n"
        f"🚫 المحظورون: <b>{banned}</b>\n"
        f"👤 حسابات إيشانسي: <b>{accounts}</b>\n"
        f"💰 مجموع الأرصدة: "
        f"<b>{money(balance_total)} ل.س</b>\n"
        f"💳 شحنات معلقة: <b>{deposits}</b>\n"
        f"💸 سحوبات معلقة: <b>{withdrawals}</b>"
    )

    await callback.answer()


# =========================================================
# ADMIN BALANCE
# =========================================================

@DP.callback_query(F.data == "adm:balance")
async def admin_balance(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    await state.set_state(
        AdminStates.waiting_balance_user
    )

    await callback.message.answer(
        "💰 أرسل ID المستخدم الذي تريد تعديل رصيده:"
    )

    await callback.answer()


@DP.message(AdminStates.waiting_balance_user)
async def admin_balance_user(
    message: Message,
    state: FSMContext,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    if not (
        message.text
        and message.text.isdigit()
    ):

        await message.answer(
            "أرسل ID رقمي."
        )

        return

    uid = int(message.text)

    user = await get_user(uid)

    if not user:

        await message.answer(
            "المستخدم غير موجود."
        )

        return

    await state.update_data(
        balance_user=uid
    )

    await state.set_state(
        AdminStates.waiting_balance_amount
    )

    await message.answer(
        "أرسل قيمة التعديل.\n\n"
        "مثال:\n"
        "<code>+50000</code>\n"
        "أو\n"
        "<code>-10000</code>"
    )


@DP.message(AdminStates.waiting_balance_amount)
async def admin_balance_amount(
    message: Message,
    state: FSMContext,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    value = (
        message.text or ""
    ).strip()

    if not re.fullmatch(
        r"[+-]?\d+",
        value,
    ):

        await message.answer(
            "صيغة غير صحيحة."
        )

        return

    data = await state.get_data()

    uid = int(
        data["balance_user"]
    )

    delta = int(value)

    try:

        new_balance = await change_balance(
            uid,
            delta,
            "تعديل من الإدارة",
        )

    except ValueError as exc:

        await message.answer(
            f"❌ {exc}"
        )

        return

    await state.clear()

    await message.answer(
        "✅ تم تعديل الرصيد.\n\n"
        f"المستخدم: <code>{uid}</code>\n"
        f"التعديل: <b>{delta:+,} ل.س</b>\n"
        f"الرصيد الجديد: "
        f"<b>{money(new_balance)} ل.س</b>"
    )

    try:

        await BOT.send_message(
            uid,
            "💰 <b>تم تعديل رصيدك من الإدارة</b>\n\n"
            f"التعديل: {delta:+,} ل.س\n"
            f"الرصيد الجديد: "
            f"<b>{money(new_balance)} ل.س</b>",
        )

    except Exception:

        pass


# =========================================================
# ADMIN USER SEARCH / BAN
# =========================================================

@DP.callback_query(
    F.data.in_(
        [
            "adm:user",
            "adm:ban",
            "adm:unban",
        ]
    )
)
async def admin_user_action(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    action = callback.data.split(":")[1]

    await state.update_data(
        action=action
    )

    await state.set_state(
        AdminStates.waiting_user_id
    )

    if action == "user":

        text = "👤 أرسل ID المستخدم للبحث:"

    elif action == "ban":

        text = "🚫 أرسل ID المستخدم للحظر:"

    else:

        text = "✅ أرسل ID المستخدم لفك الحظر:"

    await callback.message.answer(text)

    await callback.answer()


@DP.message(AdminStates.waiting_user_id)
async def admin_user_action_message(
    message: Message,
    state: FSMContext,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    if not (
        message.text
        and message.text.isdigit()
    ):

        await message.answer(
            "أرسل ID رقمي."
        )

        return

    uid = int(message.text)

    data = await state.get_data()

    action = data.get(
        "action",
        "user",
    )

    await state.clear()

    if action == "ban":

        conn = await db()

        try:

            cur = await conn.execute(
                """
                UPDATE users

                SET banned=1

                WHERE id=?
                """,
                (uid,),
            )

            await conn.commit()

            ok = cur.rowcount > 0

        finally:

            await conn.close()

        await message.answer(
            "✅ تم الحظر."
            if ok
            else "المستخدم غير موجود."
        )

        return

    if action == "unban":

        conn = await db()

        try:

            cur = await conn.execute(
                """
                UPDATE users

                SET banned=0

                WHERE id=?
                """,
                (uid,),
            )

            await conn.commit()

            ok = cur.rowcount > 0

        finally:

            await conn.close()

        await message.answer(
            "✅ تم فك الحظر."
            if ok
            else "المستخدم غير موجود."
        )

        return

    user = await get_user(uid)

    if not user:

        await message.answer(
            "المستخدم غير موجود."
        )

        return

    account = await get_account(uid)

    await message.answer(
        "👤 <b>بيانات المستخدم</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 الاسم: {user['first_name'] or '—'}\n"
        f"Username: @{user['username'] or '—'}\n"
        f"💰 الرصيد: "
        f"<b>{money(user['balance_points'])} ل.س</b>\n"
        f"🚫 محظور: "
        f"{'نعم' if user['banned'] else 'لا'}\n"
        f"👤 حساب إيشانسي: "
        f"{'موجود' if account else 'غير موجود'}"
    )


# =========================================================
# ADMIN DEPOSITS
# =========================================================

@DP.callback_query(F.data == "adm:deposits")
async def admin_deposits(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    conn = await db()

    try:

        cur = await conn.execute(
            """
            SELECT *

            FROM deposit_requests

            WHERE status='pending'

            ORDER BY id ASC

            LIMIT 30
            """
        )

        rows = await cur.fetchall()

    finally:

        await conn.close()

    if not rows:

        await callback.message.answer(
            "💳 لا توجد طلبات شحن معلقة."
        )

        await callback.answer()

        return

    for row in rows:

        await callback.message.answer(
            "💳 <b>طلب شحن</b>\n\n"
            f"الطلب: #{row['id']}\n"
            f"المستخدم: "
            f"<code>{row['user_id']}</code>\n"
            f"المبلغ: "
            f"<b>{money(row['amount'])} ل.س</b>\n"
            f"الطريقة: {row['method']}\n"
            f"المرجع: "
            f"<code>{row['reference'] or '—'}</code>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ قبول",
                            callback_data=f"dep:approve:{row['id']}",
                        ),
                        InlineKeyboardButton(
                            text="❌ رفض",
                            callback_data=f"dep:reject:{row['id']}",
                        ),
                    ]
                ]
            ),
        )

    await callback.answer()


# =========================================================
# ADMIN WITHDRAWALS
# =========================================================

@DP.callback_query(F.data == "adm:withdrawals")
async def admin_withdrawals(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    conn = await db()

    try:

        cur = await conn.execute(
            """
            SELECT *

            FROM withdrawal_requests

            WHERE status='pending'

            ORDER BY id ASC

            LIMIT 30
            """
        )

        rows = await cur.fetchall()

    finally:

        await conn.close()

    if not rows:

        await callback.message.answer(
            "💸 لا توجد طلبات سحب معلقة."
        )

        await callback.answer()

        return

    for row in rows:

        await callback.message.answer(
            "💸 <b>طلب سحب</b>\n\n"
            f"الطلب: #{row['id']}\n"
            f"المستخدم: "
            f"<code>{row['user_id']}</code>\n"
            f"المبلغ: "
            f"<b>{money(row['amount'])} ل.س</b>\n"
            f"الطريقة: {row['method']}\n"
            f"الرقم: "
            f"<code>{row['account_number']}</code>\n"
            f"اسم صاحب الحساب: "
            f"{row['account_name'] or '—'}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ تنفيذ",
                            callback_data=f"wd:approve:{row['id']}",
                        ),
                        InlineKeyboardButton(
                            text="❌ رفض",
                            callback_data=f"wd:reject:{row['id']}",
                        ),
                    ]
                ]
            ),
        )

    await callback.answer()


# =========================================================
# ADMIN BROADCAST
# =========================================================

@DP.callback_query(F.data == "adm:broadcast")
async def admin_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    await state.set_state(
        AdminStates.waiting_broadcast
    )

    await callback.message.answer(
        "📣 أرسل الرسالة التي تريد بثها:"
    )

    await callback.answer()


@DP.message(AdminStates.waiting_broadcast)
async def admin_broadcast_send(
    message: Message,
    state: FSMContext,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    text = message.text or ""

    await state.clear()

    conn = await db()

    try:

        cur = await conn.execute(
            """
            SELECT id

            FROM users

            WHERE banned=0
            """
        )

        ids = [
            int(row["id"])
            for row in await cur.fetchall()
        ]

    finally:

        await conn.close()

    semaphore = asyncio.Semaphore(20)

    success = 0

    async def send_one(uid):

        nonlocal success

        async with semaphore:

            try:

                await BOT.send_message(
                    uid,
                    text,
                )

                success += 1

            except Exception:

                pass

            await asyncio.sleep(
                0.05
            )

    await asyncio.gather(
        *(
            send_one(uid)
            for uid in ids
        )
    )

    await message.answer(
        f"📣 انتهى البث.\n\n"
        f"نجح: <b>{success}</b>\n"
        f"الإجمالي: <b>{len(ids)}</b>"
    )


# =========================================================
# ADMIN GIFTS
# =========================================================

@DP.callback_query(F.data == "adm:gift")
async def admin_gift(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    await state.set_state(
        AdminStates.waiting_gift
    )

    await callback.message.answer(
        "🎁 أرسل الكود بالشكل:\n\n"
        "<code>CODE|POINTS|MAX_USES</code>\n\n"
        "مثال:\n"
        "<code>VIP100|10000|100</code>\n\n"
        "ضع 0 لعدد غير محدود."
    )

    await callback.answer()


@DP.message(AdminStates.waiting_gift)
async def admin_gift_create(
    message: Message,
    state: FSMContext,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    parts = [
        p.strip()
        for p in (
            message.text or ""
        ).split("|")
    ]

    if (
        len(parts) != 3
        or not parts[0]
        or not parts[1].isdigit()
        or not parts[2].isdigit()
    ):

        await message.answer(
            "❌ الصيغة غير صحيحة."
        )

        return

    code = parts[0].upper()

    points = int(parts[1])

    max_uses = int(parts[2])

    conn = await db()

    try:

        await conn.execute(
            """
            INSERT INTO gift_codes(
                code,
                points,
                max_uses,
                used_count,
                active
            )
            VALUES(?, ?, ?, 0, 1)

            ON CONFLICT(code)

            DO UPDATE SET

                points=excluded.points,

                max_uses=excluded.max_uses,

                active=1
            """,
            (
                code,
                points,
                max_uses,
            ),
        )

        await conn.commit()

    finally:

        await conn.close()

    await state.clear()

    await message.answer(
        "✅ تم إنشاء الكود.\n\n"
        f"الكود: <code>{code}</code>\n"
        f"القيمة: "
        f"<b>{money(points)} ل.س</b>\n"
        f"الاستخدامات: "
        f"<b>{max_uses or 'غير محدود'}</b>"
    )


# =========================================================
# ADMIN SUPPORT
# =========================================================

@DP.callback_query(F.data == "adm:support")
async def admin_support(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    conn = await db()

    try:

        cur = await conn.execute(
            """
            SELECT *

            FROM support_tickets

            WHERE status='open'

            ORDER BY id ASC

            LIMIT 20
            """
        )

        rows = await cur.fetchall()

    finally:

        await conn.close()

    if not rows:

        await callback.message.answer(
            "💬 لا توجد طلبات دعم."
        )

        await callback.answer()

        return

    for row in rows:

        await callback.message.answer(
            "🆘 <b>طلب دعم</b>\n\n"
            f"#{row['id']}\n"
            f"المستخدم: "
            f"<code>{row['user_id']}</code>\n\n"
            f"{row['message_text']}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💬 الرد",
                            callback_data=f"ticket:{row['id']}",
                        )
                    ]
                ]
            ),
        )

    await callback.answer()


@DP.callback_query(
    F.data.startswith("ticket:")
)
async def admin_ticket(
    callback: CallbackQuery,
    state: FSMContext,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    ticket_id = int(
        callback.data.split(":")[1]
    )

    await state.update_data(
        ticket_id=ticket_id
    )

    await state.set_state(
        AdminStates.waiting_support_reply
    )

    await callback.message.answer(
        f"💬 أرسل الرد على الطلب #{ticket_id}:"
    )

    await callback.answer()


@DP.message(
    AdminStates.waiting_support_reply
)
async def admin_ticket_reply(
    message: Message,
    state: FSMContext,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    data = await state.get_data()

    ticket_id = int(
        data["ticket_id"]
    )

    reply = clean_text(
        message.text or ""
    )

    conn = await db()

    try:

        cur = await conn.execute(
            """
            SELECT *

            FROM support_tickets

            WHERE id=?
            """,
            (ticket_id,),
        )

        ticket = await cur.fetchone()

        if not ticket:

            await state.clear()

            await message.answer(
                "الطلب غير موجود."
            )

            return

        await conn.execute(
            """
            UPDATE support_tickets

            SET status='closed',
                admin_reply=?,
                replied_at=?

            WHERE id=?
            """,
            (
                reply,
                now_iso(),
                ticket_id,
            ),
        )

        await conn.commit()

    finally:

        await conn.close()

    await state.clear()

    try:

        await BOT.send_message(
            int(ticket["user_id"]),
            f"💬 <b>رد الدعم</b>\n\n"
            f"{reply}",
        )

    except Exception:

        pass

    await message.answer(
        "✅ تم إرسال الرد."
    )


# =========================================================
# ADMIN SETTINGS
# =========================================================

@DP.callback_query(F.data == "adm:settings")
async def admin_settings(
    callback: CallbackQuery,
):

    if not is_admin(
        callback.from_user.id
    ):
        return

    minimum_deposit = await get_setting(
        "minimum_deposit",
        "1000",
    )

    minimum_withdraw = await get_setting(
        "minimum_withdraw",
        "10000",
    )

    referral = await get_setting(
        "referral_reward_points",
        "1000",
    )

    daily = await get_setting(
        "daily_gift_points",
        "1000",
    )

    await callback.message.answer(
        "⚙️ <b>إعدادات البوت</b>\n\n"
        f"💳 الحد الأدنى للشحن: "
        f"{money(int(minimum_deposit))} ل.س\n"
        f"💸 الحد الأدنى للسحب: "
        f"{money(int(minimum_withdraw))} ل.س\n"
        f"👥 مكافأة الإحالة: "
        f"{money(int(referral))} ل.س\n"
        f"🎁 الهدية اليومية: "
        f"{money(int(daily))} ل.س\n\n"
        "الأوامر:\n"
        "/set_deposit_min 1000\n"
        "/set_withdraw_min 10000\n"
        "/set_referral 1000\n"
        "/set_daily 1000\n"
        "/set_welcome النص\n"
        "/set_offers النص\n"
        "/set_terms النص"
    )

    await callback.answer()


# =========================================================
# ADMIN COMMANDS
# =========================================================

@DP.message(Command("set_deposit_min"))
async def set_deposit_min(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    parts = (
        message.text or ""
    ).split(
        maxsplit=1
    )

    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        await message.answer(
            "استخدم:\n"
            "/set_deposit_min 1000"
        )

        return

    await set_setting(
        "minimum_deposit",
        parts[1],
    )

    await message.answer(
        "✅ تم تحديث الحد الأدنى للشحن."
    )


@DP.message(Command("set_withdraw_min"))
async def set_withdraw_min(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    parts = (
        message.text or ""
    ).split(
        maxsplit=1
    )

    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        await message.answer(
            "استخدم:\n"
            "/set_withdraw_min 10000"
        )

        return

    await set_setting(
        "minimum_withdraw",
        parts[1],
    )

    await message.answer(
        "✅ تم تحديث الحد الأدنى للسحب."
    )


@DP.message(Command("set_referral"))
async def set_referral(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    parts = (
        message.text or ""
    ).split(
        maxsplit=1
    )

    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        await message.answer(
            "/set_referral 1000"
        )

        return

    await set_setting(
        "referral_reward_points",
        parts[1],
    )

    await message.answer(
        "✅ تم تحديث مكافأة الإحالة."
    )


@DP.message(Command("set_daily"))
async def set_daily(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    parts = (
        message.text or ""
    ).split(
        maxsplit=1
    )

    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        await message.answer(
            "/set_daily 1000"
        )

        return

    await set_setting(
        "daily_gift_points",
        parts[1],
    )

    await message.answer(
        "✅ تم تحديث الهدية اليومية."
    )


@DP.message(Command("set_welcome"))
async def set_welcome(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    text = (
        message.text or ""
    ).partition(" ")[2].strip()

    if not text:

        await message.answer(
            "/set_welcome النص"
        )

        return

    await set_setting(
        "welcome_text",
        text,
    )

    await message.answer(
        "✅ تم تحديث الترحيب."
    )


@DP.message(Command("set_offers"))
async def set_offers(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    text = (
        message.text or ""
    ).partition(" ")[2].strip()

    if not text:

        await message.answer(
            "/set_offers النص"
        )

        return

    await set_setting(
        "offers_text",
        text,
    )

    await message.answer(
        "✅ تم تحديث العروض."
    )


@DP.message(Command("set_terms"))
async def set_terms(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    text = (
        message.text or ""
    ).partition(" ")[2].strip()

    if not text:

        await message.answer(
            "/set_terms النص"
        )

        return

    await set_setting(
        "terms_text",
        text,
    )

    await message.answer(
        "✅ تم تحديث الشروط."
    )


@DP.message(Command("ban"))
async def ban_user(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    parts = (
        message.text or ""
    ).split(
        maxsplit=1
    )

    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        await message.answer(
            "/ban USER_ID"
        )

        return

    uid = int(parts[1])

    conn = await db()

    try:

        cur = await conn.execute(
            """
            UPDATE users

            SET banned=1

            WHERE id=?
            """,
            (uid,),
        )

        await conn.commit()

        ok = cur.rowcount > 0

    finally:

        await conn.close()

    await message.answer(
        "✅ تم الحظر."
        if ok
        else "المستخدم غير موجود."
    )


@DP.message(Command("unban"))
async def unban_user(
    message: Message,
):

    if not is_admin(
        message.from_user.id
    ):
        return

    parts = (
        message.text or ""
    ).split(
        maxsplit=1
    )

    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        await message.answer(
            "/unban USER_ID"
        )

        return

    uid = int(parts[1])

    conn = await db()

    try:

        cur = await conn.execute(
            """
            UPDATE users

            SET banned=0

            WHERE id=?
            """,
            (uid,),
        )

        await conn.commit()

        ok = cur.rowcount > 0

    finally:

        await conn.close()

    await message.answer(
        "✅ تم فك الحظر."
        if ok
        else "المستخدم غير موجود."
    )


# =========================================================
# HEALTH SERVER
# =========================================================

async def health(
    _request,
):

    return web.json_response(
        {
            "status": "ok",
            "service": "ichancy-bot",
            "time": now_iso(),
        }
    )


async def run_health_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health,
    )

    app.router.add_get(
        "/health",
        health,
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT,
    )

    await site.start()

    logger.info(
        "Health server running on %s",
        PORT,
    )

    return runner


# =========================================================
# MAIN
# =========================================================

async def main():

    global BOT

    await init_db()

    BOT = Bot(
        BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        ),
    )

    # Important:
    # Only ONE instance of this bot may run.
    await BOT.delete_webhook(
        drop_pending_updates=False
    )

    runner = await run_health_server()

    logger.info(
        "Ichancy bot started."
    )

    logger.info(
        "Admins: %s",
        sorted(ADMIN_IDS),
    )

    logger.info(
        "Required channel: %s",
        REQUIRED_CHANNEL,
    )

    try:

        await DP.start_polling(
            BOT,
            allowed_updates=DP.resolve_used_update_types(),
        )

    finally:

        await runner.cleanup()

        await BOT.session.close()


if __name__ == "__main__":

    asyncio.run(main())

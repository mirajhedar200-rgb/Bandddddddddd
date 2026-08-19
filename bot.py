import os
import asyncio
import logging
from decimal import Decimal, InvalidOperation
from aiohttp import web

import asyncpg
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramConflictError


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

ADMIN_ID = int(os.getenv("ADMIN_ID", "6697338101"))

SYRIATEL_CASH = os.getenv(
    "SYRIATEL_CASH",
    "77178326"
)

REFERRAL_REWARD = Decimal(
    os.getenv("REFERRAL_REWARD", "1000")
)

MIN_WITHDRAW = Decimal(
    os.getenv("MIN_WITHDRAW", "15000")
)

PORT = int(
    os.getenv("PORT", "10000")
)


if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN غير موجود في Environment Variables"
    )

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL غير موجود في Environment Variables"
    )


# =========================================================
# BOT
# =========================================================

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

db_pool = None

user_states = {}


# =========================================================
# DATABASE
# =========================================================

SCHEMA = """

CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,

    balance NUMERIC(18,2)
        NOT NULL DEFAULT 0,

    referrals INTEGER
        NOT NULL DEFAULT 0,

    referred_by BIGINT,

    referral_paid BOOLEAN
        NOT NULL DEFAULT FALSE,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW()
);


CREATE TABLE IF NOT EXISTS mandatory_channels (

    id BIGSERIAL PRIMARY KEY,

    chat_id TEXT NOT NULL UNIQUE,

    title TEXT NOT NULL,

    invite_link TEXT NOT NULL,

    enabled BOOLEAN
        NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW()
);


CREATE TABLE IF NOT EXISTS transactions (

    id BIGSERIAL PRIMARY KEY,

    user_id BIGINT NOT NULL,

    type TEXT NOT NULL,

    amount NUMERIC(18,2)
        NOT NULL DEFAULT 0,

    status TEXT
        NOT NULL DEFAULT 'pending',

    method TEXT,

    details TEXT,

    created_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMPTZ
        NOT NULL DEFAULT NOW()
);


CREATE INDEX IF NOT EXISTS
transactions_user_idx
ON transactions(user_id);


CREATE INDEX IF NOT EXISTS
transactions_status_idx
ON transactions(status);

"""


async def init_database():

    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
    )

    async with db_pool.acquire() as conn:

        await conn.execute(SCHEMA)


# =========================================================
# HELPERS
# =========================================================

def money(value):

    return Decimal(
        str(value)
    ).quantize(
        Decimal("0.01")
    )


def main_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="👤 معلومات الحساب",
                    callback_data="account"
                ),

                InlineKeyboardButton(
                    text="💳 شحن الرصيد",
                    callback_data="deposit"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💸 سحب الرصيد",
                    callback_data="withdraw"
                ),

                InlineKeyboardButton(
                    text="👥 الإحالات",
                    callback_data="referrals"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📜 سجل العمليات",
                    callback_data="transactions"
                )
            ]
        ]
    )


def back_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 الرئيسية",
                    callback_data="home"
                )
            ]
        ]
    )


def admin_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="📊 الإحصائيات",
                    callback_data="admin_stats"
                )
            ],

            [
                InlineKeyboardButton(
                    text="💳 طلبات الشحن",
                    callback_data="admin_deposits"
                ),

                InlineKeyboardButton(
                    text="💸 طلبات السحب",
                    callback_data="admin_withdraws"
                )
            ],

            [
                InlineKeyboardButton(
                    text="👥 المستخدمون",
                    callback_data="admin_users"
                ),

                InlineKeyboardButton(
                    text="💰 تعديل الرصيد",
                    callback_data="admin_balance"
                )
            ],

            [
                InlineKeyboardButton(
                    text="📢 الاشتراك الإجباري",
                    callback_data="admin_channels"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🔙 الرئيسية",
                    callback_data="home"
                )
            ]
        ]
    )


# =========================================================
# USERS
# =========================================================

async def ensure_user(
    message: Message,
    referral_id=None
):

    user_id = message.from_user.id

    async with db_pool.acquire() as conn:

        existing = await conn.fetchrow(
            """
            SELECT id
            FROM users
            WHERE id=$1
            """,
            user_id
        )

        if existing:

            await conn.execute(
                """
                UPDATE users
                SET
                    username=$2,
                    first_name=$3,
                    updated_at=NOW()
                WHERE id=$1
                """,
                user_id,
                message.from_user.username,
                message.from_user.first_name
            )

            return

        valid_referral = None

        if (
            referral_id
            and referral_id != user_id
        ):

            exists = await conn.fetchval(
                """
                SELECT id
                FROM users
                WHERE id=$1
                """,
                referral_id
            )

            if exists:

                valid_referral = referral_id

        await conn.execute(
            """
            INSERT INTO users(
                id,
                username,
                first_name,
                referred_by
            )

            VALUES($1,$2,$3,$4)
            """,
            user_id,
            message.from_user.username,
            message.from_user.first_name,
            valid_referral
        )


async def get_user(user_id):

    async with db_pool.acquire() as conn:

        return await conn.fetchrow(
            """
            SELECT *
            FROM users
            WHERE id=$1
            """,
            user_id
        )


# =========================================================
# MANDATORY SUBSCRIPTION
# =========================================================

async def get_channels():

    async with db_pool.acquire() as conn:

        return await conn.fetch(
            """
            SELECT *
            FROM mandatory_channels
            WHERE enabled=TRUE
            ORDER BY id
            """
        )


async def check_subscription(user_id):

    channels = await get_channels()

    missing = []

    for channel in channels:

        try:

            member = await bot.get_chat_member(
                channel["chat_id"],
                user_id
            )

            if member.status not in (
                "member",
                "administrator",
                "creator"
            ):

                missing.append(channel)

        except Exception:

            missing.append(channel)

    return len(missing) == 0, missing


def subscription_keyboard(channels):

    buttons = []

    for channel in channels:

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"📢 {channel['title']}",
                    url=channel["invite_link"]
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="✅ تحقق من الاشتراك",
                callback_data="check_subscription"
            )
        ]
    )

    return InlineKeyboardMarkup(
        inline_keyboard=buttons
    )


async def require_subscription_message(
    message
):

    ok, missing = await check_subscription(
        message.from_user.id
    )

    if ok:

        return True

    await message.answer(
        "🔒 <b>الاشتراك الإجباري</b>\n\n"
        "يجب الاشتراك بالقنوات التالية أولاً:",
        reply_markup=subscription_keyboard(
            missing
        ),
        parse_mode="HTML"
    )

    return False


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message):

    referral_id = None

    parts = (
        message.text or ""
    ).split(maxsplit=1)

    if (
        len(parts) == 2
        and parts[1].isdigit()
    ):

        referral_id = int(
            parts[1]
        )

    await ensure_user(
        message,
        referral_id
    )

    if not await require_subscription_message(
        message
    ):

        return

    await reward_referral(
        message.from_user.id
    )

    await message.answer(
        "🏠 <b>القائمة الرئيسية</b>\n\n"
        "مرحباً بك 👋\n"
        "اختر الخدمة:",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )


# =========================================================
# REFERRALS
# =========================================================

async def reward_referral(user_id):

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            user = await conn.fetchrow(
                """
                SELECT
                    referred_by,
                    referral_paid
                FROM users
                WHERE id=$1
                FOR UPDATE
                """,
                user_id
            )

            if not user:
                return

            if (
                not user["referred_by"]
                or user["referral_paid"]
            ):
                return

            referrer = await conn.fetchrow(
                """
                SELECT id
                FROM users
                WHERE id=$1
                FOR UPDATE
                """,
                user["referred_by"]
            )

            if not referrer:
                return

            await conn.execute(
                """
                UPDATE users
                SET
                    balance=balance+$2,
                    referrals=referrals+1,
                    updated_at=NOW()
                WHERE id=$1
                """,
                referrer["id"],
                REFERRAL_REWARD
            )

            await conn.execute(
                """
                UPDATE users
                SET
                    referral_paid=TRUE,
                    updated_at=NOW()
                WHERE id=$1
                """,
                user_id
            )

            await conn.execute(
                """
                INSERT INTO transactions(
                    user_id,
                    type,
                    amount,
                    status,
                    method,
                    details
                )

                VALUES(
                    $1,
                    'referral',
                    $2,
                    'approved',
                    'referral',
                    'Referral reward'
                )
                """,
                referrer["id"],
                REFERRAL_REWARD
            )


# =========================================================
# HOME
# =========================================================

@dp.callback_query(
    F.data == "home"
)
async def home_callback(callback):

    await callback.message.edit_text(
        "🏠 <b>القائمة الرئيسية</b>\n\n"
        "اختر الخدمة:",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# CHECK SUB
# =========================================================

@dp.callback_query(
    F.data == "check_subscription"
)
async def check_subscription_callback(
    callback
):

    ok, missing = await check_subscription(
        callback.from_user.id
    )

    if not ok:

        await callback.answer(
            "❌ لم تشترك بكل القنوات.",
            show_alert=True
        )

        return

    await reward_referral(
        callback.from_user.id
    )

    await callback.message.edit_text(
        "✅ تم التحقق من الاشتراك.\n\n"
        "🏠 <b>القائمة الرئيسية</b>",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ACCOUNT
# =========================================================

@dp.callback_query(
    F.data == "account"
)
async def account_callback(callback):

    user = await get_user(
        callback.from_user.id
    )

    me = await bot.get_me()

    referral_link = (
        f"https://t.me/{me.username}"
        f"?start={callback.from_user.id}"
    )

    text = (
        "👤 <b>معلومات الحساب</b>\n\n"

        f"🆔 ID:\n"
        f"<code>{user['id']}</code>\n\n"

        f"💰 الرصيد:\n"
        f"<b>{money(user['balance'])} ل.س</b>\n\n"

        f"👥 الإحالات:\n"
        f"<b>{user['referrals']}</b>\n\n"

        "🔗 رابط الإحالة:\n"
        f"<code>{referral_link}</code>"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="💳 شحن",
                    callback_data="deposit"
                ),

                InlineKeyboardButton(
                    text="💸 سحب",
                    callback_data="withdraw"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🔙 رجوع",
                    callback_data="home"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# DEPOSIT
# =========================================================

@dp.callback_query(
    F.data == "deposit"
)
async def deposit_callback(callback):

    text = (
        "💳 <b>شحن الرصيد</b>\n\n"

        "طريقة الشحن:\n"
        "📱 سيريتل كاش\n\n"

        "رقم التحويل:\n"
        f"<code>{SYRIATEL_CASH}</code>\n\n"

        "قم بالتحويل ثم أرسل طلب الشحن "
        "مع رقم العملية."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="🧾 إرسال طلب شحن",
                    callback_data="deposit_request"
                )
            ],

            [
                InlineKeyboardButton(
                    text="🔙 رجوع",
                    callback_data="account"
                )
            ]
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(
    F.data == "deposit_request"
)
async def deposit_request(callback):

    user_states[
        callback.from_user.id
    ] = "deposit"

    await callback.message.answer(
        "✍️ أرسل طلب الشحن بهذا الشكل:\n\n"
        "<code>"
        "شحن 25000\n"
        "رقم العملية: 123456\n"
        "رقم المحول: 09xxxxxxxx"
        "</code>\n\n"
        "أو أرسل صورة الإيصال "
        "مع كتابة المبلغ في الوصف.",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# WITHDRAW
# =========================================================

@dp.callback_query(
    F.data == "withdraw"
)
async def withdraw_callback(callback):

    user = await get_user(
        callback.from_user.id
    )

    await callback.message.edit_text(
        "💸 <b>سحب الرصيد</b>\n\n"

        f"رصيدك:\n"
        f"<b>{money(user['balance'])} ل.س</b>\n\n"

        f"الحد الأدنى:\n"
        f"<b>{money(MIN_WITHDRAW)} ل.س</b>\n\n"

        "أرسل:\n"
        "<code>"
        "سحب 15000\n"
        "رقم سيريتل كاش: 09xxxxxxxx"
        "</code>",
        reply_markup=back_keyboard(),
        parse_mode="HTML"
    )

    user_states[
        callback.from_user.id
    ] = "withdraw"

    await callback.answer()


# =========================================================
# TRANSACTIONS
# =========================================================

@dp.callback_query(
    F.data == "transactions"
)
async def transactions_callback(callback):

    async with db_pool.acquire() as conn:

        rows = await conn.fetch(
            """
            SELECT
                id,
                type,
                amount,
                status
            FROM transactions
            WHERE user_id=$1
            ORDER BY id DESC
            LIMIT 20
            """,
            callback.from_user.id
        )

    if not rows:

        text = (
            "📜 <b>سجل العمليات</b>\n\n"
            "لا توجد عمليات."
        )

    else:

        names = {
            "deposit": "💳 شحن",
            "withdraw": "💸 سحب",
            "referral": "👥 إحالة"
        }

        statuses = {
            "pending": "⏳",
            "approved": "✅",
            "rejected": "❌"
        }

        lines = [
            "📜 <b>سجل العمليات</b>\n"
        ]

        for row in rows:

            lines.append(
                f"#{row['id']} — "
                f"{names.get(row['type'], row['type'])} — "
                f"{money(row['amount'])} ل.س — "
                f"{statuses.get(row['status'], '❔')}"
            )

        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=back_keyboard(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# REFERRALS
# =========================================================

@dp.callback_query(
    F.data == "referrals"
)
async def referrals_callback(callback):

    user = await get_user(
        callback.from_user.id
    )

    me = await bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start={callback.from_user.id}"
    )

    await callback.message.edit_text(
        "👥 <b>الإحالات</b>\n\n"

        f"عدد الإحالات: "
        f"<b>{user['referrals']}</b>\n\n"

        f"مكافأة الإحالة: "
        f"<b>{money(REFERRAL_REWARD)} ل.س</b>\n\n"

        "🔗 رابطك:\n"
        f"<code>{link}</code>",
        reply_markup=back_keyboard(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# USER INPUT
# =========================================================

def parse_amount(text, command):

    lines = text.strip().splitlines()

    first = lines[0].split()

    if len(first) < 2:
        return None

    if first[0].lower() != command:
        return None

    try:

        amount = Decimal(
            first[1]
            .replace(",", "")
            .replace("،", "")
        )

        if amount <= 0:
            return None

        return amount

    except InvalidOperation:

        return None


@dp.message(F.text)
async def text_handler(message):

    user_id = message.from_user.id

    state = user_states.get(
        user_id
    )

    if state == "deposit":

        amount = parse_amount(
            message.text,
            "شحن"
        )

        if amount is None:

            await message.answer(
                "❌ الصيغة غير صحيحة.\n\n"
                "<code>"
                "شحن 25000\n"
                "رقم العملية: 123456"
                "</code>",
                parse_mode="HTML"
            )

            return

        user_states.pop(
            user_id,
            None
        )

        async with db_pool.acquire() as conn:

            transaction_id = await conn.fetchval(
                """
                INSERT INTO transactions(
                    user_id,
                    type,
                    amount,
                    status,
                    method,
                    details
                )

                VALUES(
                    $1,
                    'deposit',
                    $2,
                    'pending',
                    'Syriatel Cash',
                    $3
                )

                RETURNING id
                """,
                user_id,
                amount,
                message.text
            )

        await message.answer(
            "✅ <b>تم إرسال طلب الشحن</b>\n\n"
            f"رقم الطلب: "
            f"<b>#{transaction_id}</b>\n"
            f"المبلغ: "
            f"<b>{money(amount)} ل.س</b>\n\n"
            "بانتظار مراجعة الأدمن.",
            reply_markup=main_keyboard(),
            parse_mode="HTML"
        )

        await notify_admin(
            transaction_id
        )

        return


    if state == "withdraw":

        amount = parse_amount(
            message.text,
            "سحب"
        )

        if amount is None:

            await message.answer(
                "❌ الصيغة غير صحيحة."
            )

            return

        if amount < MIN_WITHDRAW:

            await message.answer(
                "❌ الحد الأدنى للسحب "
                f"{money(MIN_WITHDRAW)} ل.س"
            )

            return

        async with db_pool.acquire() as conn:

            async with conn.transaction():

                balance = await conn.fetchval(
                    """
                    SELECT balance
                    FROM users
                    WHERE id=$1
                    FOR UPDATE
                    """,
                    user_id
                )

                balance = Decimal(
                    str(balance)
                )

                if balance < amount:

                    await message.answer(
                        "❌ رصيدك غير كافٍ."
                    )

                    return

                await conn.execute(
                    """
                    UPDATE users
                    SET
                        balance=balance-$2,
                        updated_at=NOW()
                    WHERE id=$1
                    """,
                    user_id,
                    amount
                )

                transaction_id = await conn.fetchval(
                    """
                    INSERT INTO transactions(
                        user_id,
                        type,
                        amount,
                        status,
                        method,
                        details
                    )

                    VALUES(
                        $1,
                        'withdraw',
                        $2,
                        'pending',
                        'Syriatel Cash',
                        $3
                    )

                    RETURNING id
                    """,
                    user_id,
                    amount,
                    message.text
                )

        user_states.pop(
            user_id,
            None
        )

        await message.answer(
            "✅ <b>تم إرسال طلب السحب</b>\n\n"
            f"رقم الطلب: "
            f"<b>#{transaction_id}</b>\n"
            f"المبلغ: "
            f"<b>{money(amount)} ل.س</b>\n\n"
            "بانتظار مراجعة الأدمن.",
            reply_markup=main_keyboard(),
            parse_mode="HTML"
        )

        await notify_admin(
            transaction_id
        )


# =========================================================
# ADMIN
# =========================================================

@dp.message(Command("admin"))
async def admin_command(message):

    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "🛠 <b>لوحة التحكم</b>\n\n"
        "أهلاً بك في لوحة الإدارة.",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(
    F.data == "admin_stats"
)
async def admin_stats(callback):

    if callback.from_user.id != ADMIN_ID:
        return

    async with db_pool.acquire() as conn:

        users = await conn.fetchval(
            "SELECT COUNT(*) FROM users"
        )

        balance = await conn.fetchval(
            """
            SELECT COALESCE(
                SUM(balance),
                0
            )
            FROM users
            """
        )

        deposits = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM transactions
            WHERE
                type='deposit'
                AND status='pending'
            """
        )

        withdrawals = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM transactions
            WHERE
                type='withdraw'
                AND status='pending'
            """
        )

    await callback.message.edit_text(
        "📊 <b>الإحصائيات</b>\n\n"

        f"👥 المستخدمون: <b>{users}</b>\n\n"

        f"💰 مجموع الأرصدة: "
        f"<b>{money(balance)} ل.س</b>\n\n"

        f"💳 شحنات معلقة: "
        f"<b>{deposits}</b>\n\n"

        f"💸 سحوبات معلقة: "
        f"<b>{withdrawals}</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ADMIN USERS
# =========================================================

@dp.callback_query(
    F.data == "admin_users"
)
async def admin_users(callback):

    if callback.from_user.id != ADMIN_ID:
        return

    async with db_pool.acquire() as conn:

        rows = await conn.fetch(
            """
            SELECT
                id,
                username,
                balance
            FROM users
            ORDER BY id DESC
            LIMIT 20
            """
        )

    lines = [
        "👥 <b>آخر المستخدمين</b>\n"
    ]

    for row in rows:

        username = (
            f"@{row['username']}"
            if row["username"]
            else "-"
        )

        lines.append(
            f"<code>{row['id']}</code> "
            f"{username}\n"
            f"💰 {money(row['balance'])} ل.س"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ADMIN BALANCE
# =========================================================

@dp.callback_query(
    F.data == "admin_balance"
)
async def admin_balance(callback):

    if callback.from_user.id != ADMIN_ID:
        return

    user_states[
        callback.from_user.id
    ] = "admin_balance"

    await callback.message.answer(
        "💰 <b>تعديل الرصيد</b>\n\n"
        "أرسل:\n\n"
        "<code>USER_ID +5000</code>\n\n"
        "أو:\n"
        "<code>USER_ID -5000</code>",
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# ADMIN BALANCE INPUT
# =========================================================

async def process_admin_balance(message):

    parts = message.text.split()

    if len(parts) != 2:

        await message.answer(
            "❌ الصيغة خاطئة."
        )

        return

    try:

        user_id = int(parts[0])
        amount = Decimal(parts[1])

    except Exception:

        await message.answer(
            "❌ بيانات غير صحيحة."
        )

        return

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            current = await conn.fetchval(
                """
                SELECT balance
                FROM users
                WHERE id=$1
                FOR UPDATE
                """,
                user_id
            )

            if current is None:

                await message.answer(
                    "❌ المستخدم غير موجود."
                )

                return

            current = Decimal(
                str(current)
            )

            new_balance = (
                current + amount
            )

            if new_balance < 0:

                await message.answer(
                    "❌ لا يمكن أن يصبح "
                    "الرصيد سالباً."
                )

                return

            await conn.execute(
                """
                UPDATE users
                SET
                    balance=$2,
                    updated_at=NOW()
                WHERE id=$1
                """,
                user_id,
                new_balance
            )

    user_states.pop(
        ADMIN_ID,
        None
    )

    await message.answer(
        "✅ تم تعديل الرصيد.\n\n"
        f"المستخدم: <code>{user_id}</code>\n"
        f"الرصيد الجديد: "
        f"<b>{money(new_balance)} ل.س</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )


# =========================================================
# ADMIN CHANNELS
# =========================================================

@dp.callback_query(
    F.data == "admin_channels"
)
async def admin_channels(callback):

    if callback.from_user.id != ADMIN_ID:
        return

    channels = await get_channels()

    buttons = []

    for channel in channels:

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 حذف {channel['title']}",
                    callback_data=(
                        f"delete_channel:{channel['id']}"
                    )
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="➕ إضافة قناة",
                callback_data="add_channel"
            )
        ]
    )

    buttons.append(
        [
            InlineKeyboardButton(
                text="🔙 لوحة الأدمن",
                callback_data="admin_home"
            )
        ]
    )

    text = (
        "📢 <b>الاشتراك الإجباري</b>\n\n"
    )

    if not channels:

        text += "لا توجد قنوات مضافة."

    else:

        for channel in channels:

            text += (
                f"• {channel['title']}\n"
                f"<code>{channel['chat_id']}</code>\n\n"
            )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        ),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(
    F.data == "add_channel"
)
async def add_channel(callback):

    if callback.from_user.id != ADMIN_ID:
        return

    user_states[
        ADMIN_ID
    ] = "add_channel"

    await callback.message.answer(
        "📢 <b>إضافة قناة</b>\n\n"
        "أرسل:\n\n"
        "<code>"
        "@channel | اسم القناة | https://t.me/channel"
        "</code>\n\n"
        "يجب أن يكون البوت مشرفاً في القناة.",
        parse_mode="HTML"
    )

    await callback.answer()


async def process_add_channel(message):

    parts = [
        x.strip()
        for x in message.text.split("|")
    ]

    if len(parts) != 3:

        await message.answer(
            "❌ الصيغة خاطئة."
        )

        return

    chat_id, title, invite_link = parts

    async with db_pool.acquire() as conn:

        await conn.execute(
            """
            INSERT INTO mandatory_channels(
                chat_id,
                title,
                invite_link
            )

            VALUES($1,$2,$3)
            ON CONFLICT(chat_id)
            DO UPDATE SET
                title=EXCLUDED.title,
                invite_link=EXCLUDED.invite_link,
                enabled=TRUE
            """,
            chat_id,
            title,
            invite_link
        )

    user_states.pop(
        ADMIN_ID,
        None
    )

    await message.answer(
        "✅ تمت إضافة القناة.",
        reply_markup=admin_keyboard()
    )


@dp.callback_query(
    F.data.startswith("delete_channel:")
)
async def delete_channel(callback):

    if callback.from_user.id != ADMIN_ID:
        return

    channel_id = int(
        callback.data.split(":")[1]
    )

    async with db_pool.acquire() as conn:

        await conn.execute(
            """
            DELETE FROM mandatory_channels
            WHERE id=$1
            """,
            channel_id
        )

    await callback.answer(
        "✅ تم حذف القناة."
    )

    await admin_channels(
        callback
    )


# =========================================================
# ADMIN HOME
# =========================================================

@dp.callback_query(
    F.data == "admin_home"
)
async def admin_home(callback):

    if callback.from_user.id != ADMIN_ID:
        return

    await callback.message.edit_text(
        "🛠 <b>لوحة التحكم</b>",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )

    await callback.answer()


# =========================================================
# TRANSACTION ADMIN
# =========================================================

def transaction_keyboard(transaction_id):

    return InlineKeyboardMarkup(
        inline_keyboard=[

            [
                InlineKeyboardButton(
                    text="✅ قبول",
                    callback_data=(
                        f"approve:{transaction_id}"
                    )
                ),

                InlineKeyboardButton(
                    text="❌ رفض",
                    callback_data=(
                        f"reject:{transaction_id}"
                    )
                )
            ]
        ]
    )


async def notify_admin(transaction_id):

    async with db_pool.acquire() as conn:

        row = await conn.fetchrow(
            """
            SELECT *
            FROM transactions
            WHERE id=$1
            """,
            transaction_id
        )

    if not row:
        return

    await bot.send_message(
        ADMIN_ID,

        "🔔 <b>طلب جديد</b>\n\n"

        f"🧾 الطلب: "
        f"<b>#{row['id']}</b>\n"

        f"👤 المستخدم: "
        f"<code>{row['user_id']}</code>\n"

        f"📌 النوع: "
        f"<b>{row['type']}</b>\n"

        f"💰 المبلغ: "
        f"<b>{money(row['amount'])} ل.س</b>\n\n"

        f"📝 التفاصيل:\n"
        f"{row['details'] or '-'}",

        reply_markup=transaction_keyboard(
            transaction_id
        ),

        parse_mode="HTML"
    )


# =========================================================
# APPROVE
# =========================================================

@dp.callback_query(
    F.data.startswith("approve:")
)
async def approve(callback):

    if callback.from_user.id != ADMIN_ID:
        return

    transaction_id = int(
        callback.data.split(":")[1]
    )

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            row = await conn.fetchrow(
                """
                SELECT *
                FROM transactions
                WHERE id=$1
                FOR UPDATE
                """,
                transaction_id
            )

            if not row:
                return

            if row["status"] != "pending":

                await callback.answer(
                    "تمت معالجة الطلب مسبقاً.",
                    show_alert=True
                )

                return

            if row["type"] == "deposit":

                await conn.execute(
                    """
                    UPDATE users
                    SET
                        balance=balance+$2,
                        updated_at=NOW()
                    WHERE id=$1
                    """,
                    row["user_id"],
                    row["amount"]
                )

            await conn.execute(
                """
                UPDATE transactions
                SET
                    status='approved',
                    updated_at=NOW()
                WHERE id=$1
                """,
                transaction_id
            )

    await callback.message.edit_text(
        f"✅ تم قبول الطلب #{transaction_id}.",
        reply_markup=admin_keyboard()
    )

    await callback.answer(
        "تم القبول."
    )

    try:

        await bot.send_message(
            row["user_id"],
            "✅ <b>تم قبول طلبك</b>\n\n"
            f"رقم الطلب: #{transaction_id}\n"
            f"المبلغ: {money(row['amount'])} ل.س",
            parse_mode="HTML"
        )

    except Exception:
        pass


# =========================================================
# REJECT
# =========================================================

@dp.callback_query(
    F.data.startswith("reject:")
)
async def reject(callback):

    if callback.from_user.id != ADMIN_ID:
        return

    transaction_id = int(
        callback.data.split(":")[1]
    )

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            row = await conn.fetchrow(
                """
                SELECT *
                FROM transactions
                WHERE id=$1
                FOR UPDATE
                """,
                transaction_id
            )

            if not row:
                return

            if row["status"] != "pending":

                await callback.answer(
                    "تمت معالجة الطلب مسبقاً.",
                    show_alert=True
                )

                return

            if row["type"] == "withdraw":

                await conn.execute(
                    """
                    UPDATE users
                    SET
                        balance=balance+$2,
                        updated_at=NOW()
                    WHERE id=$1
                    """,
                    row["user_id"],
                    row["amount"]
                )

            await conn.execute(
                """
                UPDATE transactions
                SET
                    status='rejected',
                    updated_at=NOW()
                WHERE id=$1
                """,
                transaction_id
            )

    await callback.message.edit_text(
        f"❌ تم رفض الطلب #{transaction_id}.",
        reply_markup=admin_keyboard()
    )

    await callback.answer(
        "تم الرفض."
    )

    try:

        await bot.send_message(
            row["user_id"],
            "❌ <b>تم رفض طلبك</b>\n\n"
            f"رقم الطلب: #{transaction_id}",
            parse_mode="HTML"
        )

    except Exception:
        pass


# =========================================================
# PENDING LIST
# =========================================================

async def show_pending(
    callback,
    transaction_type
):

    if callback.from_user.id != ADMIN_ID:
        return

    async with db_pool.acquire() as conn:

        row = await conn.fetchrow(
            """
            SELECT *
            FROM transactions
            WHERE
                type=$1
                AND status='pending'
            ORDER BY id ASC
            LIMIT 1
            """,
            transaction_type
        )

    if not row:

        await callback.message.edit_text(
            "لا توجد طلبات معلقة.",
            reply_markup=admin_keyboard()
        )

        await callback.answer()

        return

    await callback.message.edit_text(
        "📋 <b>طلب معلق</b>\n\n"

        f"🧾 #{row['id']}\n"
        f"👤 <code>{row['user_id']}</code>\n"
        f"💰 {money(row['amount'])} ل.س\n\n"
        f"📝 {row['details'] or '-'}",

        reply_markup=transaction_keyboard(
            row["id"]
        ),

        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(
    F.data == "admin_deposits"
)
async def admin_deposits(callback):

    await show_pending(
        callback,
        "deposit"
    )


@dp.callback_query(
    F.data == "admin_withdraws"
)
async def admin_withdraws(callback):

    await show_pending(
        callback,
        "withdraw"
    )


# =========================================================
# STATE ROUTER FOR ADMIN
# =========================================================

@dp.message(
    F.from_user.id == ADMIN_ID,
    F.text
)
async def admin_state_handler(message):

    state = user_states.get(
        ADMIN_ID
    )

    if state == "admin_balance":

        await process_admin_balance(
            message
        )

    elif state == "add_channel":

        await process_add_channel(
            message
        )


# =========================================================
# PHOTO RECEIPT
# =========================================================

@dp.message(F.photo)
async def photo_handler(message):

    state = user_states.get(
        message.from_user.id
    )

    if state != "deposit":
        return

    caption = (
        message.caption
        or "إيصال شحن"
    )

    async with db_pool.acquire() as conn:

        transaction_id = await conn.fetchval(
            """
            INSERT INTO transactions(
                user_id,
                type,
                amount,
                status,
                method,
                details
            )

            VALUES(
                $1,
                'deposit',
                0,
                'pending',
                'Syriatel Cash',
                $2
            )

            RETURNING id
            """,
            message.from_user.id,
            caption
        )

    user_states.pop(
        message.from_user.id,
        None
    )

    await message.answer(
        "✅ تم استلام الإيصال.\n\n"
        f"رقم الطلب: #{transaction_id}",
        reply_markup=main_keyboard()
    )

    await bot.send_photo(
        ADMIN_ID,
        message.photo[-1].file_id,
        caption=(
            "🧾 <b>إيصال شحن</b>\n\n"
            f"الطلب: #{transaction_id}\n"
            f"المستخدم: "
            f"<code>{message.from_user.id}</code>\n\n"
            f"{caption}"
        ),
        reply_markup=transaction_keyboard(
            transaction_id
        ),
        parse_mode="HTML"
    )


# =========================================================
# HEALTH SERVER
# =========================================================

async def health(request):

    return web.Response(
        text="OK"
    )


async def start_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health
    )

    app.router.add_get(
        "/health",
        health
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


# =========================================================
# MAIN
# =========================================================

async def main():

    await init_database()

    runner = await start_server()

    try:

        await bot.delete_webhook(
            drop_pending_updates=True
        )

        me = await bot.get_me()

        logging.info(
            "Bot started: @%s",
            me.username
        )

        await dp.start_polling(
            bot,
            allowed_updates=(
                dp.resolve_used_update_types()
            )
        )

    except TelegramConflictError:

        logging.error(
            "يوجد Bot instance آخر يعمل بنفس التوكن."
        )

        raise

    finally:

        await runner.cleanup()

        if db_pool:

            await db_pool.close()

        await bot.session.close()


if __name__ == "__main__":

    asyncio.run(main())

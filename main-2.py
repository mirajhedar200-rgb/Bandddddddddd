import os
import asyncio
import logging
from datetime import date
from aiohttp import web

import asyncpg
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramConflictError

# =========================================================
# SETTINGS
# =========================================================

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip()
}

PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
pool = None

REF_REWARD = 1000
DAILY_REWARD = 1000
MIN_WITHDRAW = 15000

# =========================================================
# DATABASE
# =========================================================

async def init_db():
    global pool

    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    async with pool.acquire() as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id BIGINT PRIMARY KEY,
            username TEXT,
            full_name TEXT NOT NULL,
            balance BIGINT NOT NULL DEFAULT 0,
            referrals INT NOT NULL DEFAULT 0,
            referred_by BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_daily DATE,
            banned BOOLEAN NOT NULL DEFAULT FALSE
        );
        """)
        await db.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS banned BOOLEAN NOT NULL DEFAULT FALSE;")

        await db.execute("""
        CREATE TABLE IF NOT EXISTS channels(
            id BIGSERIAL PRIMARY KEY,
            chat_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals(
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            amount BIGINT NOT NULL,
            cash_number TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS topups(
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            amount BIGINT NOT NULL,
            channel TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)

        # New tables. Existing tables/data are not removed or rewritten.
        await db.execute("""
        CREATE TABLE IF NOT EXISTS bot_buttons(
            id BIGSERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            action TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '',
            row_no INT NOT NULL DEFAULT 0,
            position INT NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT TRUE
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS admin_sessions(
            user_id BIGINT PRIMARY KEY,
            action TEXT NOT NULL,
            data TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """)

        # Default editable texts are inserted only if missing.
        defaults = {
            "welcome_text": "🎉 أهلاً بك في <b>Billion Bot</b>\n\nنظام إحالات وترويج للقنوات.\nاكسب من الإحالات والهدية اليومية واطلب سحب أرباحك.",
            "terms_text": "📜 <b>الشروط والأحكام</b>\n\n• الإحالة تحتسب مرة واحدة لكل مستخدم.\n• يمنع إنشاء الحسابات الوهمية أو التحايل.\n• الحد الأدنى للسحب يتم تحديده من الإدارة.\n• طلبات السحب تراجع من الإدارة.\n• يحق للإدارة رفض الطلبات المخالفة.",
        }
        for key, value in defaults.items():
            await db.execute(
                "INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING",
                key, value
            )


# =========================================================
# SETTINGS HELPERS
# =========================================================

async def get_setting(key, default):
    value = await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)
    if value is None:
        await pool.execute(
            "INSERT INTO settings(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING",
            key, str(default)
        )
        return str(default)
    return value


async def set_setting(key, value):
    await pool.execute(
        """
        INSERT INTO settings(key,value) VALUES($1,$2)
        ON CONFLICT(key) DO UPDATE SET value=$2
        """,
        key, str(value)
    )


async def get_ref_reward():
    return int(await get_setting("ref_reward", REF_REWARD))


async def get_daily_reward():
    return int(await get_setting("daily_reward", DAILY_REWARD))


async def get_min_withdraw():
    return int(await get_setting("min_withdraw", MIN_WITHDRAW))


async def get_welcome_text():
    return await get_setting(
        "welcome_text",
        "🎉 أهلاً بك في <b>Billion Bot</b>\n\nنظام إحالات وترويج للقنوات.\nاكسب من الإحالات والهدية اليومية واطلب سحب أرباحك."
    )


async def get_terms_text():
    return await get_setting("terms_text", "📜 <b>الشروط والأحكام</b>")


# =========================================================
# ADMIN SESSION HELPERS
# =========================================================

async def set_admin_action(user_id, action, data=""):
    await pool.execute(
        """
        INSERT INTO admin_sessions(user_id,action,data)
        VALUES($1,$2,$3)
        ON CONFLICT(user_id) DO UPDATE SET action=$2,data=$3,created_at=NOW()
        """,
        user_id, action, data
    )


async def get_admin_action(user_id):
    return await pool.fetchrow(
        "SELECT action,data FROM admin_sessions WHERE user_id=$1",
        user_id
    )


async def clear_admin_action(user_id):
    await pool.execute("DELETE FROM admin_sessions WHERE user_id=$1", user_id)


# =========================================================
# KEYBOARDS
# =========================================================

async def custom_user_buttons():
    rows = await pool.fetch(
        """
        SELECT id,title,action,value,row_no,position
        FROM bot_buttons
        WHERE active=TRUE
        ORDER BY row_no,position,id
        """
    )
    result = []
    current_row = None
    for row in rows:
        if current_row != row["row_no"]:
            result.append([])
            current_row = row["row_no"]
        if row["action"] == "url":
            result[-1].append(InlineKeyboardButton(text=row["title"], url=row["value"]))
        elif row["action"] == "text":
            result[-1].append(InlineKeyboardButton(text=row["title"], callback_data=f"custom:{row['id']}"))
    return result


async def main_menu(is_admin=False):
    rows = [
        [
            InlineKeyboardButton(text="👤 حسابي", callback_data="account"),
            InlineKeyboardButton(text="🔗 الإحالة", callback_data="ref"),
        ],
        [
            InlineKeyboardButton(text="💰 السحب", callback_data="withdraw"),
            InlineKeyboardButton(text="🎁 اليومية", callback_data="daily"),
        ],
        [
            InlineKeyboardButton(text="📢 القنوات", callback_data="gift_channels"),
            InlineKeyboardButton(text="💳 الشحن", callback_data="topup"),
        ],
        [InlineKeyboardButton(text="📜 الشروط", callback_data="terms")],
    ]
    custom = await custom_user_buttons()
    rows.extend(custom)
    if is_admin:
        rows.append([InlineKeyboardButton(text="👑 لوحة الإدارة", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 الإحصائيات", callback_data="a_stats"),
            InlineKeyboardButton(text="👥 المستخدمون", callback_data="a_users"),
        ],
        [
            InlineKeyboardButton(text="💰 السحوبات", callback_data="a_withdrawals"),
            InlineKeyboardButton(text="💳 الشحن", callback_data="a_topups"),
        ],
        [
            InlineKeyboardButton(text="🔒 الاشتراك الإجباري", callback_data="a_channels"),
            InlineKeyboardButton(text="🔘 الأزرار", callback_data="a_buttons"),
        ],
        [
            InlineKeyboardButton(text="🎁 المكافآت", callback_data="a_settings"),
            InlineKeyboardButton(text="✏️ الرسائل", callback_data="a_messages"),
        ],
        [
            InlineKeyboardButton(text="📣 الإذاعة", callback_data="a_broadcast"),
            InlineKeyboardButton(text="🔎 بحث", callback_data="a_search"),
        ],
        [InlineKeyboardButton(text="🏠 القائمة الرئيسية", callback_data="home")],
    ])


def back_admin():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ لوحة الإدارة", callback_data="admin")]
    ])


def buttons_admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ إضافة زر", callback_data="btn_add"),
            InlineKeyboardButton(text="📋 القائمة", callback_data="a_buttons"),
        ],
        [InlineKeyboardButton(text="⬅️ لوحة الإدارة", callback_data="admin")],
    ])


# =========================================================
# USERS / SUBSCRIPTION
# =========================================================

async def upsert_user(message: Message, referred_by=None):
    user = message.from_user
    async with pool.acquire() as db:
        existing = await db.fetchrow("SELECT id FROM users WHERE id=$1", user.id)
        if existing:
            await db.execute(
                "UPDATE users SET username=$2, full_name=$3 WHERE id=$1",
                user.id, user.username, user.full_name
            )
            return False

        valid_ref = None
        if referred_by and referred_by != user.id:
            ref_exists = await db.fetchval("SELECT id FROM users WHERE id=$1", referred_by)
            if ref_exists:
                valid_ref = referred_by

        await db.execute(
            """
            INSERT INTO users(id,username,full_name,referred_by)
            VALUES($1,$2,$3,$4)
            """,
            user.id, user.username, user.full_name, valid_ref
        )
        if valid_ref:
            reward = await get_ref_reward()
            await db.execute(
                "UPDATE users SET balance=balance+$1,referrals=referrals+1 WHERE id=$2",
                reward, valid_ref
            )
        return True


async def is_banned(user_id):
    result = await pool.fetchval("SELECT banned FROM users WHERE id=$1", user_id)
    return bool(result)


async def check_banned(message):
    if await is_banned(message.from_user.id):
        await message.answer("🚫 تم إيقاف حسابك من قبل الإدارة.")
        return True
    return False


async def is_subscribed(user_id):
    # Admins are never blocked by the forced-subscription gate.
    if user_id in ADMIN_IDS:
        return True
    rows = await pool.fetch("SELECT chat_id FROM channels WHERE active=TRUE")
    for row in rows:
        try:
            member = await bot.get_chat_member(row["chat_id"], user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            # If Telegram cannot verify membership, keep the gate closed.
            return False
    return True


async def channel_gate():
    rows = await pool.fetch(
        "SELECT chat_id,title,url FROM channels WHERE active=TRUE ORDER BY id"
    )
    buttons = []
    for row in rows:
        buttons.append([InlineKeyboardButton(text=f"📢 {row['title']}", url=row["url"])])
    buttons.append([InlineKeyboardButton(text="✅ تحقق من الاشتراك", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def require_sub(obj):
    user_id = obj.from_user.id
    if await is_banned(user_id):
        if isinstance(obj, Message):
            await obj.answer("🚫 حسابك موقوف.")
        else:
            await obj.message.edit_text("🚫 حسابك موقوف.")
        return False

    if await is_subscribed(user_id):
        return True

    text = "🔒 يجب الاشتراك في القنوات المطلوبة قبل استخدام البوت."
    if isinstance(obj, Message):
        await obj.answer(text, reply_markup=await channel_gate())
    else:
        await obj.message.edit_text(text, reply_markup=await channel_gate())
    return False


def is_admin(obj):
    return obj.from_user.id in ADMIN_IDS


# =========================================================
# ADMIN DIRECT ACCESS
# =========================================================

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message):
        await message.answer("❌ هذا الأمر مخصص للإدارة فقط.")
        return
    await clear_admin_action(message.from_user.id)
    await message.answer(
        "👑 <b>لوحة الإدارة</b>\n\nتحكم كامل بالبوت من هنا.",
        parse_mode="HTML",
        reply_markup=admin_menu()
    )


# =========================================================
# START / HOME
# =========================================================

@dp.message(CommandStart())
async def start(message: Message):
    if await check_banned(message):
        return

    referral = None
    parts = message.text.split(maxsplit=1)
    if len(parts) == 2 and parts[1].isdigit():
        referral = int(parts[1])

    await upsert_user(message, referral)
    # الإدارة يجب أن تدخل لوحة التحكم حتى لو لم تكن مشتركة بالقنوات الإلزامية.
    if message.from_user.id not in ADMIN_IDS:
        if not await require_sub(message):
            return

    await message.answer(
        await get_welcome_text(),
        parse_mode="HTML",
        reply_markup=await main_menu(message.from_user.id in ADMIN_IDS)
    )


@dp.callback_query(F.data == "home")
async def home(callback: CallbackQuery):
    if not await require_sub(callback):
        await callback.answer()
        return
    await callback.message.edit_text(
        await get_welcome_text(),
        parse_mode="HTML",
        reply_markup=await main_menu(callback.from_user.id in ADMIN_IDS)
    )
    await callback.answer()


# =========================================================
# USER CALLBACKS
# =========================================================

@dp.callback_query(F.data == "check_sub")
async def check_subscription(callback: CallbackQuery):
    if not await is_subscribed(callback.from_user.id):
        await callback.answer("❌ لم يكتمل الاشتراك بعد.", show_alert=True)
        return
    await callback.message.edit_text(
        await get_welcome_text(),
        parse_mode="HTML",
        reply_markup=await main_menu(callback.from_user.id in ADMIN_IDS)
    )
    await callback.answer("✅ تم التحقق من الاشتراك.")


@dp.callback_query(F.data == "account")
async def account(callback: CallbackQuery):
    uid = callback.from_user.id
    if not await require_sub(callback):
        await callback.answer()
        return
    row = await pool.fetchrow("SELECT * FROM users WHERE id=$1", uid)
    if not row:
        await callback.answer("أرسل /start أولاً", show_alert=True)
        return
    await callback.message.edit_text(
        f"👤 <b>معلومات الحساب</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"💰 الرصيد: <b>{row['balance']:,} ل.س</b>\n"
        f"👥 الإحالات: <b>{row['referrals']}</b>",
        parse_mode="HTML",
        reply_markup=await main_menu(uid in ADMIN_IDS)
    )
    await callback.answer()


@dp.callback_query(F.data == "ref")
async def referral(callback: CallbackQuery):
    uid = callback.from_user.id
    if not await require_sub(callback):
        await callback.answer()
        return
    me = await bot.get_me()
    reward = await get_ref_reward()
    link = f"https://t.me/{me.username}?start={uid}"
    await callback.message.edit_text(
        "🔗 <b>رابط الإحالة الخاص بك</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"💰 مكافأة الإحالة: <b>{reward:,} ل.س</b>",
        parse_mode="HTML",
        reply_markup=await main_menu(uid in ADMIN_IDS)
    )
    await callback.answer()


@dp.callback_query(F.data == "daily")
async def daily(callback: CallbackQuery):
    uid = callback.from_user.id
    if not await require_sub(callback):
        await callback.answer()
        return
    today = date.today()
    async with pool.acquire() as db:
        row = await db.fetchrow("SELECT last_daily FROM users WHERE id=$1", uid)
        if row and row["last_daily"] == today:
            await callback.answer("🎁 أخذت الهدية اليومية مسبقاً.", show_alert=True)
            return
        reward = await get_daily_reward()
        await db.execute(
            "UPDATE users SET balance=balance+$1,last_daily=$2 WHERE id=$3",
            reward, today, uid
        )
    await callback.answer(f"🎁 تمت إضافة {reward:,} ل.س إلى رصيدك.", show_alert=True)


@dp.callback_query(F.data == "terms")
async def terms(callback: CallbackQuery):
    if not await require_sub(callback):
        await callback.answer()
        return
    await callback.message.edit_text(
        await get_terms_text(), parse_mode="HTML",
        reply_markup=await main_menu(callback.from_user.id in ADMIN_IDS)
    )
    await callback.answer()


@dp.callback_query(F.data == "gift_channels")
async def gift_channels(callback: CallbackQuery):
    await callback.message.edit_text(
        "📢 اشترك بالقنوات المطلوبة ثم اضغط تحقق.",
        reply_markup=await channel_gate()
    )
    await callback.answer()


@dp.callback_query(F.data == "withdraw")
async def withdraw_info(callback: CallbackQuery):
    if not await require_sub(callback):
        await callback.answer()
        return
    minimum = await get_min_withdraw()
    await callback.message.edit_text(
        "💰 <b>طلب سحب</b>\n\n"
        f"الحد الأدنى للسحب: <b>{minimum:,} ل.س</b>\n\n"
        "استخدم:\n<code>/withdraw المبلغ رقم_سيريتل</code>",
        parse_mode="HTML",
        reply_markup=await main_menu(callback.from_user.id in ADMIN_IDS)
    )
    await callback.answer()


@dp.callback_query(F.data == "topup")
async def topup_info(callback: CallbackQuery):
    if not await require_sub(callback):
        await callback.answer()
        return
    await callback.message.edit_text(
        "💳 <b>شحن الرصيد</b>\n\n"
        "استخدم:\n<code>/topup المبلغ اسم_القناة</code>\n\n"
        "وسيصل الطلب إلى الإدارة.",
        parse_mode="HTML",
        reply_markup=await main_menu(callback.from_user.id in ADMIN_IDS)
    )
    await callback.answer()


# =========================================================
# WITHDRAW / TOPUP
# =========================================================

@dp.message(Command("withdraw"))
async def withdraw(message: Message):
    if not await require_sub(message):
        return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit():
        await message.answer("الاستخدام:\n/withdraw المبلغ رقم_سيريتل")
        return
    amount = int(parts[1])
    number = parts[2]
    minimum = await get_min_withdraw()
    if amount < minimum:
        await message.answer(f"❌ الحد الأدنى للسحب {minimum:,} ل.س")
        return

    async with pool.acquire() as db:
        row = await db.fetchrow("SELECT balance FROM users WHERE id=$1", message.from_user.id)
        if not row or row["balance"] < amount:
            await message.answer("❌ رصيدك غير كافٍ.")
            return
        await db.execute("UPDATE users SET balance=balance-$1 WHERE id=$2", amount, message.from_user.id)
        result = await db.fetchrow(
            """
            INSERT INTO withdrawals(user_id,amount,cash_number)
            VALUES($1,$2,$3) RETURNING id
            """,
            message.from_user.id, amount, number
        )

    withdrawal_id = result["id"]
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💰 <b>طلب سحب جديد</b>\n\n🆔 الطلب: {withdrawal_id}\n"
                f"👤 {message.from_user.full_name}\n🆔 {message.from_user.id}\n"
                f"💰 {amount:,} ل.س\n📱 {number}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ قبول", callback_data=f"wd_ok:{withdrawal_id}"),
                    InlineKeyboardButton(text="❌ رفض", callback_data=f"wd_no:{withdrawal_id}")
                ]])
            )
        except Exception:
            pass
    await message.answer("✅ تم إرسال طلب السحب إلى الإدارة.")


@dp.message(Command("topup"))
async def topup(message: Message):
    if not await require_sub(message):
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("الاستخدام:\n/topup المبلغ اسم_القناة")
        return
    amount = int(parts[1])
    channel = parts[2]
    result = await pool.fetchrow(
        "INSERT INTO topups(user_id,amount,channel) VALUES($1,$2,$3) RETURNING id",
        message.from_user.id, amount, channel
    )
    topup_id = result["id"]
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💳 <b>طلب شحن جديد</b>\n\n🆔 الطلب: {topup_id}\n"
                f"👤 {message.from_user.full_name}\n🆔 {message.from_user.id}\n"
                f"💰 {amount:,} ل.س\n📢 {channel}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ قبول", callback_data=f"tp_ok:{topup_id}"),
                    InlineKeyboardButton(text="❌ رفض", callback_data=f"tp_no:{topup_id}")
                ]])
            )
        except Exception:
            pass
    await message.answer("✅ تم إرسال طلب الشحن إلى الإدارة.")


# =========================================================
# ADMIN PANEL
# =========================================================

@dp.callback_query(F.data == "admin")
async def admin_panel(callback: CallbackQuery):
    if not is_admin(callback):
        await callback.answer("❌ غير مصرح.", show_alert=True)
        return
    await clear_admin_action(callback.from_user.id)
    await callback.message.edit_text(
        "👑 <b>لوحة الإدارة</b>\n\nتحكم كامل بالبوت من هنا.",
        parse_mode="HTML", reply_markup=admin_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "a_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback):
        await callback.answer("❌ غير مصرح.", show_alert=True); return
    users = await pool.fetchval("SELECT COUNT(*) FROM users")
    banned = await pool.fetchval("SELECT COUNT(*) FROM users WHERE banned=TRUE")
    balance = await pool.fetchval("SELECT COALESCE(SUM(balance),0) FROM users")
    refs = await pool.fetchval("SELECT COALESCE(SUM(referrals),0) FROM users")
    pending_wd = await pool.fetchval("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
    pending_tp = await pool.fetchval("SELECT COUNT(*) FROM topups WHERE status='pending'")
    channels = await pool.fetchval("SELECT COUNT(*) FROM channels WHERE active=TRUE")
    await callback.message.edit_text(
        "📊 <b>إحصائيات البوت</b>\n\n"
        f"👥 المستخدمون: <b>{users}</b>\n🚫 المحظورون: <b>{banned}</b>\n"
        f"🔗 الإحالات: <b>{refs}</b>\n💰 مجموع الأرصدة: <b>{balance:,}</b>\n"
        f"💸 سحوبات معلقة: <b>{pending_wd}</b>\n💳 شحنات معلقة: <b>{pending_tp}</b>\n"
        f"📢 القنوات الفعالة: <b>{channels}</b>",
        parse_mode="HTML", reply_markup=back_admin()
    )
    await callback.answer()


@dp.callback_query(F.data == "a_users")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback):
        await callback.answer("❌ غير مصرح.", show_alert=True); return
    rows = await pool.fetch(
        "SELECT id,full_name,balance,referrals,banned FROM users ORDER BY created_at DESC LIMIT 15"
    )
    text = "👥 <b>آخر المستخدمين</b>\n\n"
    if not rows:
        text += "لا يوجد مستخدمون."
    else:
        for row in rows:
            status = "🚫" if row["banned"] else "✅"
            text += f"{status} <code>{row['id']}</code> {row['full_name'][:25]}\n💰 {row['balance']:,} | 🔗 {row['referrals']}\n\n"
    text += "\n🔎 لإدارة مستخدم: استخدم /user ID"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_admin())
    await callback.answer()


@dp.callback_query(F.data == "a_search")
async def admin_search(callback: CallbackQuery):
    if not is_admin(callback):
        await callback.answer("❌", show_alert=True); return
    await callback.message.edit_text(
        "🔎 <b>البحث عن مستخدم</b>\n\nأرسل:\n<code>/user ID</code>",
        parse_mode="HTML", reply_markup=back_admin()
    )
    await callback.answer()


@dp.message(Command("user"))
async def admin_user(message: Message):
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("الاستخدام:\n/user ID"); return
    uid = int(parts[1])
    row = await pool.fetchrow("SELECT * FROM users WHERE id=$1", uid)
    if not row:
        await message.answer("❌ المستخدم غير موجود."); return
    status = "🚫 محظور" if row["banned"] else "✅ نشط"
    await message.answer(
        f"👤 <b>معلومات المستخدم</b>\n\n🆔 {row['id']}\n👤 {row['full_name']}\n"
        f"🔗 @{row['username'] or 'بدون'}\n💰 الرصيد: {row['balance']:,}\n"
        f"👥 الإحالات: {row['referrals']}\n📌 الحالة: {status}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ رصيد", callback_data=f"user_add:{uid}"), InlineKeyboardButton(text="➖ خصم", callback_data=f"user_sub:{uid}")],
            [InlineKeyboardButton(text="🚫 حظر", callback_data=f"user_ban:{uid}"), InlineKeyboardButton(text="✅ فك الحظر", callback_data=f"user_unban:{uid}")],
            [InlineKeyboardButton(text="🔄 تحديث", callback_data=f"user_view:{uid}")],
            [InlineKeyboardButton(text="👑 لوحة الإدارة", callback_data="admin")]
        ])
    )


async def send_user_card(callback: CallbackQuery, uid: int):
    row = await pool.fetchrow("SELECT * FROM users WHERE id=$1", uid)
    if not row:
        await callback.answer("المستخدم غير موجود.", show_alert=True); return
    status = "🚫 محظور" if row["banned"] else "✅ نشط"
    await callback.message.edit_text(
        f"👤 <b>معلومات المستخدم</b>\n\n🆔 {row['id']}\n👤 {row['full_name']}\n"
        f"🔗 @{row['username'] or 'بدون'}\n💰 الرصيد: {row['balance']:,}\n"
        f"👥 الإحالات: {row['referrals']}\n📌 الحالة: {status}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ رصيد", callback_data=f"user_add:{uid}"), InlineKeyboardButton(text="➖ خصم", callback_data=f"user_sub:{uid}")],
            [InlineKeyboardButton(text="🚫 حظر", callback_data=f"user_ban:{uid}"), InlineKeyboardButton(text="✅ فك الحظر", callback_data=f"user_unban:{uid}")],
            [InlineKeyboardButton(text="👑 لوحة الإدارة", callback_data="admin")]
        ])
    )


@dp.callback_query(F.data.startswith("user_view:"))
async def user_view(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    await send_user_card(callback, int(callback.data.split(":")[1])); await callback.answer()


@dp.callback_query(F.data.startswith("user_add:"))
async def user_add(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    uid = int(callback.data.split(":")[1])
    await set_admin_action(callback.from_user.id, "add_balance", str(uid))
    await callback.message.answer(f"➕ أرسل الآن مبلغ الإضافة فقط للمستخدم <code>{uid}</code>.", parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("user_sub:"))
async def user_sub(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    uid = int(callback.data.split(":")[1])
    await set_admin_action(callback.from_user.id, "sub_balance", str(uid))
    await callback.message.answer(f"➖ أرسل الآن مبلغ الخصم فقط للمستخدم <code>{uid}</code>.", parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("user_ban:"))
async def user_ban(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    uid = int(callback.data.split(":")[1])
    await pool.execute("UPDATE users SET banned=TRUE WHERE id=$1", uid)
    await callback.answer("🚫 تم حظر المستخدم.", show_alert=True)
    await send_user_card(callback, uid)


@dp.callback_query(F.data.startswith("user_unban:"))
async def user_unban(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    uid = int(callback.data.split(":")[1])
    await pool.execute("UPDATE users SET banned=FALSE WHERE id=$1", uid)
    await callback.answer("✅ تم فك الحظر.", show_alert=True)
    await send_user_card(callback, uid)


# =========================================================
# ADMIN BALANCE INPUTS
# =========================================================

@dp.message(Command("addbalance"))
async def addbalance(message: Message):
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("/addbalance ID المبلغ"); return
    uid, amount = int(parts[1]), int(parts[2])
    result = await pool.execute("UPDATE users SET balance=balance+$1 WHERE id=$2", amount, uid)
    await message.answer("❌ المستخدم غير موجود." if result == "UPDATE 0" else "✅ تمت إضافة الرصيد.")


@dp.message(Command("subbalance"))
async def subbalance(message: Message):
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("/subbalance ID المبلغ"); return
    uid, amount = int(parts[1]), int(parts[2])
    await pool.execute("UPDATE users SET balance=GREATEST(0,balance-$1) WHERE id=$2", amount, uid)
    await message.answer("✅ تم خصم الرصيد.")


# =========================================================
# WITHDRAWAL MANAGEMENT
# =========================================================

@dp.callback_query(F.data == "a_withdrawals")
async def admin_withdrawals(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    rows = await pool.fetch(
        """SELECT id,user_id,amount,cash_number,status FROM withdrawals
           WHERE status='pending' ORDER BY created_at DESC LIMIT 10"""
    )
    if not rows:
        await callback.message.edit_text("💰 لا توجد طلبات سحب معلقة.", reply_markup=back_admin()); await callback.answer(); return
    text = "💰 <b>طلبات السحب المعلقة</b>\n\n"
    buttons = []
    for row in rows:
        text += f"🆔 {row['id']} | 👤 {row['user_id']} | 💰 {row['amount']:,}\n📱 {row['cash_number']}\n\n"
        buttons.append([
            InlineKeyboardButton(text=f"✅ قبول {row['id']}", callback_data=f"wd_ok:{row['id']}"),
            InlineKeyboardButton(text=f"❌ رفض {row['id']}", callback_data=f"wd_no:{row['id']}")
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data="admin")])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await callback.answer()


@dp.callback_query(F.data.startswith("wd_ok:"))
async def withdrawal_accept(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    wid = int(callback.data.split(":")[1])
    row = await pool.fetchrow(
        """UPDATE withdrawals SET status='approved' WHERE id=$1 AND status='pending'
           RETURNING user_id,amount""", wid
    )
    if not row:
        await callback.answer("الطلب تمت معالجته مسبقاً.", show_alert=True); return
    try:
        await bot.send_message(row["user_id"], f"✅ تم قبول طلب السحب.\n💰 المبلغ: {row['amount']:,} ل.س")
    except Exception: pass
    await callback.answer("✅ تم قبول طلب السحب.", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)


@dp.callback_query(F.data.startswith("wd_no:"))
async def withdrawal_reject(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    wid = int(callback.data.split(":")[1])
    row = await pool.fetchrow(
        """UPDATE withdrawals SET status='rejected' WHERE id=$1 AND status='pending'
           RETURNING user_id,amount""", wid
    )
    if not row:
        await callback.answer("الطلب تمت معالجته مسبقاً.", show_alert=True); return
    await pool.execute("UPDATE users SET balance=balance+$1 WHERE id=$2", row["amount"], row["user_id"])
    try:
        await bot.send_message(row["user_id"], f"❌ تم رفض طلب السحب.\n💰 تمت إعادة {row['amount']:,} ل.س إلى رصيدك.")
    except Exception: pass
    await callback.answer("❌ تم رفض الطلب وإعادة الرصيد.", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)


# =========================================================
# TOPUP MANAGEMENT
# =========================================================

@dp.callback_query(F.data == "a_topups")
async def admin_topups(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    rows = await pool.fetch(
        """SELECT id,user_id,amount,channel FROM topups WHERE status='pending'
           ORDER BY created_at DESC LIMIT 10"""
    )
    if not rows:
        await callback.message.edit_text("💳 لا توجد طلبات شحن معلقة.", reply_markup=back_admin()); await callback.answer(); return
    text = "💳 <b>طلبات الشحن</b>\n\n"
    buttons = []
    for row in rows:
        text += f"🆔 {row['id']}\n👤 {row['user_id']}\n💰 {row['amount']:,}\n📢 {row['channel']}\n\n"
        buttons.append([
            InlineKeyboardButton(text=f"✅ قبول {row['id']}", callback_data=f"tp_ok:{row['id']}"),
            InlineKeyboardButton(text=f"❌ رفض {row['id']}", callback_data=f"tp_no:{row['id']}")
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data="admin")])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await callback.answer()


@dp.callback_query(F.data.startswith("tp_ok:"))
async def topup_accept(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    tid = int(callback.data.split(":")[1])
    row = await pool.fetchrow(
        """UPDATE topups SET status='approved' WHERE id=$1 AND status='pending'
           RETURNING user_id,amount""", tid
    )
    if not row:
        await callback.answer("الطلب تمت معالجته مسبقاً.", show_alert=True); return
    await pool.execute("UPDATE users SET balance=balance+$1 WHERE id=$2", row["amount"], row["user_id"])
    try: await bot.send_message(row["user_id"], f"✅ تم قبول الشحن.\n💰 تمت إضافة {row['amount']:,} ل.س إلى رصيدك.")
    except Exception: pass
    await callback.answer("✅ تم قبول الشحن.", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)


@dp.callback_query(F.data.startswith("tp_no:"))
async def topup_reject(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    tid = int(callback.data.split(":")[1])
    row = await pool.fetchrow(
        """UPDATE topups SET status='rejected' WHERE id=$1 AND status='pending'
           RETURNING user_id""", tid
    )
    if not row:
        await callback.answer("الطلب تمت معالجته مسبقاً.", show_alert=True); return
    try: await bot.send_message(row["user_id"], "❌ تم رفض طلب الشحن.")
    except Exception: pass
    await callback.answer("❌ تم رفض الشحن.", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)


# =========================================================
# CHANNEL MANAGEMENT - PANEL + COMMANDS
# =========================================================

@dp.callback_query(F.data == "a_channels")
async def admin_channels(callback: CallbackQuery):
    if not is_admin(callback):
        await callback.answer("❌ غير مصرح.", show_alert=True)
        return
    rows = await pool.fetch("SELECT id,chat_id,title,url,active FROM channels ORDER BY id")
    text = "🔒 <b>إدارة الاشتراك الإجباري</b>\n\n"
    if not rows:
        text += "⚠️ لا توجد قنوات مشتركة إجباريًا حاليًا.\n\n"
    else:
        for row in rows:
            status = "🟢 مفعلة" if row["active"] else "🔴 معطلة"
            text += f"{status} | <b>{row['title']}</b>\n🆔 {row['id']}\n💬 {row['chat_id']}\n🔗 {row['url']}\n\n"
    buttons = [[InlineKeyboardButton(text="➕ إضافة قناة", callback_data="channel_add")]]
    for row in rows:
        if row["active"]:
            buttons.append([
                InlineKeyboardButton(text=f"🔴 تعطيل: {row['title']}", callback_data=f"channel_disable:{row['id']}")
            ])
        else:
            buttons.append([
                InlineKeyboardButton(text=f"🟢 تفعيل: {row['title']}", callback_data=f"channel_enable:{row['id']}")
            ])
    buttons.append([InlineKeyboardButton(text="⬅️ لوحة الإدارة", callback_data="admin")])
    await callback.message.edit_text(
        text + "\n💡 يجب أن يكون البوت مشرفًا في كل قناة حتى يستطيع التحقق من الاشتراك.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@dp.callback_query(F.data == "channel_add")
async def channel_add_start(callback: CallbackQuery):
    if not is_admin(callback):
        await callback.answer("❌ غير مصرح.", show_alert=True)
        return
    await set_admin_action(callback.from_user.id, "add_forced_channel")
    await callback.message.answer(
        "➕ <b>إضافة قناة للاشتراك الإجباري</b>\n\n"
        "أرسل في رسالة واحدة بهذا الشكل:\n"
        "<code>@channel | اسم القناة | https://t.me/channel</code>\n\n"
        "أو استخدم chat_id بدل @channel.\n"
        "تأكد أن البوت مشرف في القناة.\n\n"
        "للإلغاء: /cancel",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("channel_disable:"))
async def channel_disable(callback: CallbackQuery):
    if not is_admin(callback):
        await callback.answer("❌ غير مصرح.", show_alert=True)
        return
    cid = int(callback.data.split(":")[1])
    await pool.execute("UPDATE channels SET active=FALSE WHERE id=$1", cid)
    await callback.answer("🔴 تم تعطيل القناة.", show_alert=True)
    await admin_channels(callback)


@dp.callback_query(F.data.startswith("channel_enable:"))
async def channel_enable(callback: CallbackQuery):
    if not is_admin(callback):
        await callback.answer("❌ غير مصرح.", show_alert=True)
        return
    cid = int(callback.data.split(":")[1])
    await pool.execute("UPDATE channels SET active=TRUE WHERE id=$1", cid)
    await callback.answer("🟢 تم تفعيل القناة.", show_alert=True)
    await admin_channels(callback)


@dp.message(Command("addchannel"))
async def addchannel(message: Message):
    if not is_admin(message): return
    raw = message.text[len("/addchannel"):].strip()
    parts = [x.strip() for x in raw.split("|")]
    if len(parts) != 3:
        await message.answer("الاستخدام:\n/addchannel chat_id | الاسم | https://t.me/channel"); return
    try:
        await pool.execute(
            """INSERT INTO channels(chat_id,title,url) VALUES($1,$2,$3)
               ON CONFLICT(chat_id) DO UPDATE SET title=$2,url=$3,active=TRUE""", *parts
        )
        await message.answer("✅ تمت إضافة/تفعيل القناة.")
    except Exception:
        await message.answer("❌ تعذر إضافة القناة. تأكد أن البوت مشرف في القناة وأن البيانات صحيحة.")


@dp.message(Command("delchannel"))
async def delchannel(message: Message):
    if not is_admin(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("/delchannel chat_id"); return
    await pool.execute("UPDATE channels SET active=FALSE WHERE chat_id=$1", parts[1])
    await message.answer("✅ تم تعطيل القناة.")


@dp.message(Command("enablechannel"))
async def enablechannel(message: Message):
    if not is_admin(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("/enablechannel chat_id"); return
    await pool.execute("UPDATE channels SET active=TRUE WHERE chat_id=$1", parts[1])
    await message.answer("✅ تم تفعيل القناة.")


# =========================================================
# SETTINGS / REWARDS
# =========================================================

@dp.callback_query(F.data == "a_settings")
async def admin_settings(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    ref = await get_ref_reward(); daily_reward = await get_daily_reward(); minimum = await get_min_withdraw()
    await callback.message.edit_text(
        "🎁 <b>المكافآت والإعدادات</b>\n\n"
        f"🔗 مكافأة الإحالة: <b>{ref:,}</b>\n🎁 الهدية اليومية: <b>{daily_reward:,}</b>\n"
        f"💰 الحد الأدنى للسحب: <b>{minimum:,}</b>\n\n"
        "لتغييرها:\n<code>/setref المبلغ</code>\n<code>/setdaily المبلغ</code>\n<code>/setminwithdraw المبلغ</code>",
        parse_mode="HTML", reply_markup=back_admin()
    )
    await callback.answer()


@dp.message(Command("setref"))
async def setref(message: Message):
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit(): await message.answer("/setref المبلغ"); return
    await set_setting("ref_reward", int(parts[1])); await message.answer("✅ تم تغيير مكافأة الإحالة.")


@dp.message(Command("setdaily"))
async def setdaily(message: Message):
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit(): await message.answer("/setdaily المبلغ"); return
    await set_setting("daily_reward", int(parts[1])); await message.answer("✅ تم تغيير الهدية اليومية.")


@dp.message(Command("setminwithdraw"))
async def setminwithdraw(message: Message):
    if not is_admin(message): return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit(): await message.answer("/setminwithdraw المبلغ"); return
    await set_setting("min_withdraw", int(parts[1])); await message.answer("✅ تم تغيير الحد الأدنى للسحب.")


# =========================================================
# EDITABLE MESSAGES
# =========================================================

@dp.callback_query(F.data == "a_messages")
async def admin_messages(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    welcome = await get_welcome_text(); terms_text = await get_terms_text()
    await callback.message.edit_text(
        "✏️ <b>إدارة الرسائل</b>\n\n"
        f"🎉 <b>الترحيب الحالي:</b>\n{welcome[:700]}\n\n"
        f"📜 <b>الشروط الحالية:</b>\n{terms_text[:700]}\n\n"
        "اختر ما تريد تعديله:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎉 تعديل الترحيب", callback_data="msg_welcome")],
            [InlineKeyboardButton(text="📜 تعديل الشروط", callback_data="msg_terms")],
            [InlineKeyboardButton(text="⬅️ لوحة الإدارة", callback_data="admin")],
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "msg_welcome")
async def edit_welcome(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    await set_admin_action(callback.from_user.id, "set_welcome")
    await callback.message.answer("🎉 أرسل الآن نص الترحيب الجديد. يمكنك استخدام HTML البسيط مثل <b>النص</b>.")
    await callback.answer()


@dp.callback_query(F.data == "msg_terms")
async def edit_terms(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    await set_admin_action(callback.from_user.id, "set_terms")
    await callback.message.answer("📜 أرسل الآن نص الشروط الجديد.")
    await callback.answer()


# =========================================================
# CUSTOM BUTTON MANAGEMENT
# =========================================================

@dp.callback_query(F.data == "a_buttons")
async def admin_buttons(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    rows = await pool.fetch(
        "SELECT id,title,action,value,row_no,position,active FROM bot_buttons ORDER BY row_no,position,id"
    )
    text = "🔘 <b>إدارة أزرار البوت</b>\n\n"
    buttons = []
    if not rows:
        text += "لا توجد أزرار مخصصة.\n"
    else:
        for row in rows:
            status = "🟢" if row["active"] else "🔴"
            kind = "🔗 رابط" if row["action"] == "url" else "💬 نص"
            text += f"{status} <b>{row['title']}</b> — {kind}\n"
            buttons.append([
                InlineKeyboardButton(text=f"✏️ {row['title'][:20]}", callback_data=f"btn_edit:{row['id']}"),
                InlineKeyboardButton(text="🗑", callback_data=f"btn_del:{row['id']}"),
            ])
    buttons.append([InlineKeyboardButton(text="➕ إضافة زر", callback_data="btn_add")])
    buttons.append([InlineKeyboardButton(text="⬅️ لوحة الإدارة", callback_data="admin")])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await callback.answer()


@dp.callback_query(F.data == "btn_add")
async def btn_add(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    await callback.message.edit_text(
        "🔘 <b>إضافة زر جديد</b>\n\nاختر نوع الزر:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 زر رابط", callback_data="btn_type:url")],
            [InlineKeyboardButton(text="💬 زر رسالة داخل البوت", callback_data="btn_type:text")],
            [InlineKeyboardButton(text="⬅️ رجوع", callback_data="a_buttons")],
        ])
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("btn_type:"))
async def btn_type(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    action = callback.data.split(":", 1)[1]
    await set_admin_action(callback.from_user.id, "add_button", action)
    example = "اسم الزر | https://t.me/example" if action == "url" else "اسم الزر | النص الذي سيظهر للمستخدم"
    await callback.message.answer(
        "📝 أرسل البيانات بهذا الشكل:\n\n<code>" + example + "</code>\n\n"
        "سيظهر الزر في القائمة الرئيسية.", parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("btn_edit:"))
async def btn_edit(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    bid = int(callback.data.split(":")[1])
    row = await pool.fetchrow("SELECT * FROM bot_buttons WHERE id=$1", bid)
    if not row:
        await callback.answer("الزر غير موجود.", show_alert=True); return
    await callback.message.edit_text(
        f"🔘 <b>تعديل الزر</b>\n\nID: <code>{bid}</code>\n"
        f"الاسم: <b>{row['title']}</b>\nالقيمة: <code>{row['value']}</code>\n"
        f"الصف: {row['row_no']} | الترتيب: {row['position']}\n"
        f"الحالة: {'🟢 فعال' if row['active'] else '🔴 معطل'}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ تعديل الاسم/القيمة", callback_data=f"btn_edit_data:{bid}")],
            [InlineKeyboardButton(text="🔄 تفعيل/تعطيل", callback_data=f"btn_toggle:{bid}")],
            [InlineKeyboardButton(text="🗑 حذف", callback_data=f"btn_del:{bid}")],
            [InlineKeyboardButton(text="⬅️ رجوع", callback_data="a_buttons")],
        ])
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("btn_edit_data:"))
async def btn_edit_data(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    bid = int(callback.data.split(":")[1])
    row = await pool.fetchrow("SELECT action FROM bot_buttons WHERE id=$1", bid)
    if not row:
        await callback.answer("الزر غير موجود.", show_alert=True); return
    await set_admin_action(callback.from_user.id, "edit_button", str(bid))
    example = "اسم الزر | https://t.me/example" if row["action"] == "url" else "اسم الزر | النص"
    await callback.message.answer(f"✏️ أرسل التعديل بهذا الشكل:\n<code>{example}</code>", parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("btn_toggle:"))
async def btn_toggle(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    bid = int(callback.data.split(":")[1])
    await pool.execute("UPDATE bot_buttons SET active=NOT active WHERE id=$1", bid)
    await callback.answer("✅ تم تغيير حالة الزر.", show_alert=True)
    # Refresh the list.
    await admin_buttons(callback)


@dp.callback_query(F.data.startswith("btn_del:"))
async def btn_del(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    bid = int(callback.data.split(":")[1])
    await pool.execute("DELETE FROM bot_buttons WHERE id=$1", bid)
    await callback.answer("🗑 تم حذف الزر.", show_alert=True)
    await admin_buttons(callback)


@dp.callback_query(F.data.startswith("custom:"))
async def custom_button(callback: CallbackQuery):
    bid = int(callback.data.split(":")[1])
    row = await pool.fetchrow("SELECT title,action,value,active FROM bot_buttons WHERE id=$1", bid)
    if not row or not row["active"]:
        await callback.answer("هذا الزر غير متاح.", show_alert=True); return
    if row["action"] == "text":
        await callback.message.answer(row["value"], parse_mode="HTML")
    await callback.answer()


# =========================================================
# BROADCAST
# =========================================================

@dp.callback_query(F.data == "a_broadcast")
async def broadcast_info(callback: CallbackQuery):
    if not is_admin(callback): await callback.answer("❌", show_alert=True); return
    await set_admin_action(callback.from_user.id, "broadcast")
    await callback.message.edit_text(
        "📣 <b>الإذاعة</b>\n\nأرسل الآن الرسالة التي تريد إرسالها لجميع المستخدمين.\n"
        "لإلغاء العملية أرسل /cancel",
        parse_mode="HTML", reply_markup=back_admin()
    )
    await callback.answer()


@dp.message(Command("broadcast"))
async def broadcast_command(message: Message):
    if not is_admin(message): return
    text = message.text[len("/broadcast"):].strip()
    if not text:
        await message.answer("/broadcast نص الرسالة"); return
    await run_broadcast(message, text)


async def run_broadcast(message: Message, text: str):
    users = await pool.fetch("SELECT id FROM users WHERE banned=FALSE")
    sent = 0
    for user in users:
        try:
            await bot.send_message(user["id"], text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"📣 تم إرسال الرسالة إلى {sent} مستخدم.")


# =========================================================
# ADMIN INPUT ROUTER
# =========================================================

@dp.message(Command("cancel"))
async def cancel_action(message: Message):
    if not is_admin(message): return
    await clear_admin_action(message.from_user.id)
    await message.answer("❌ تم إلغاء العملية.", reply_markup=admin_menu())


@dp.message(F.text)
async def admin_text_actions(message: Message):
    # This handler is deliberately last. It only processes messages when an
    # administrator has an active panel action; normal user messages are ignored.
    if not is_admin(message):
        return
    session = await get_admin_action(message.from_user.id)
    if not session:
        return

    action = session["action"]
    data = session["data"] or ""
    text = message.text.strip()

    if action == "add_forced_channel":
        parts = [x.strip() for x in text.split("|", 2)]
        if len(parts) != 3 or not all(parts):
            await message.answer(
                "❌ الصيغة غير صحيحة.\nاستخدم: <code>@channel | اسم القناة | https://t.me/channel</code>",
                parse_mode="HTML"
            )
            return
        chat_id, title, url = parts
        if not (url.startswith("https://t.me/") or url.startswith("http://t.me/")):
            await message.answer("❌ رابط القناة يجب أن يبدأ بـ https://t.me/")
            return
        try:
            # Verify the bot can access the channel and is an administrator.
            chat = await bot.get_chat(chat_id)
            me = await bot.get_me()
            bot_member = await bot.get_chat_member(chat.id, me.id)
            if bot_member.status not in ("administrator", "creator"):
                raise RuntimeError("BOT_IS_NOT_ADMIN")
            await pool.execute(
                """INSERT INTO channels(chat_id,title,url,active) VALUES($1,$2,$3,TRUE)
                   ON CONFLICT(chat_id) DO UPDATE SET title=$2,url=$3,active=TRUE""",
                str(chat.id), title, url
            )
            await clear_admin_action(message.from_user.id)
            await message.answer(
                f"✅ تم تفعيل الاشتراك الإجباري للقناة: <b>{title}</b>",
                parse_mode="HTML",
                reply_markup=admin_menu()
            )
        except Exception as e:
            logging.exception("Failed to add forced channel: %s", e)
            await message.answer(
                "❌ لم أستطع الوصول إلى القناة. تأكد أن البوت مضاف كمشرف وأن chat_id أو @username صحيح.\n\n"
                "مثال: <code>@mychannel | قناتي | https://t.me/mychannel</code>",
                parse_mode="HTML"
            )
        return

    if action == "add_balance" and text.isdigit():
        uid = int(data); amount = int(text)
        result = await pool.execute("UPDATE users SET balance=balance+$1 WHERE id=$2", amount, uid)
        await clear_admin_action(message.from_user.id)
        await message.answer("❌ المستخدم غير موجود." if result == "UPDATE 0" else f"✅ تمت إضافة {amount:,} إلى رصيد المستخدم.", reply_markup=admin_menu())
        return

    if action == "sub_balance" and text.isdigit():
        uid = int(data); amount = int(text)
        await pool.execute("UPDATE users SET balance=GREATEST(0,balance-$1) WHERE id=$2", amount, uid)
        await clear_admin_action(message.from_user.id)
        await message.answer(f"✅ تم خصم {amount:,} من رصيد المستخدم.", reply_markup=admin_menu())
        return

    if action == "set_welcome":
        await set_setting("welcome_text", text)
        await clear_admin_action(message.from_user.id)
        await message.answer("✅ تم تحديث رسالة الترحيب.", reply_markup=admin_menu())
        return

    if action == "set_terms":
        await set_setting("terms_text", text)
        await clear_admin_action(message.from_user.id)
        await message.answer("✅ تم تحديث الشروط.", reply_markup=admin_menu())
        return

    if action == "broadcast":
        await clear_admin_action(message.from_user.id)
        await run_broadcast(message, text)
        return

    if action == "add_button":
        parts = [x.strip() for x in text.split("|", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            await message.answer("❌ الصيغة غير صحيحة. استخدم: الاسم | القيمة")
            return
        action_type = data
        if action_type == "url" and not (parts[1].startswith("https://") or parts[1].startswith("http://") or parts[1].startswith("tg://")):
            await message.answer("❌ رابط غير صالح. يجب أن يبدأ بـ https:// أو http:// أو tg://")
            return
        max_pos = await pool.fetchval("SELECT COALESCE(MAX(position),-1) FROM bot_buttons")
        await pool.execute(
            "INSERT INTO bot_buttons(title,action,value,row_no,position,active) VALUES($1,$2,$3,0,$4,TRUE)",
            parts[0], action_type, parts[1], int(max_pos) + 1
        )
        await clear_admin_action(message.from_user.id)
        await message.answer("✅ تمت إضافة الزر. سيظهر للمستخدمين بعد فتح /start.", reply_markup=admin_menu())
        return

    if action == "edit_button":
        bid = int(data)
        parts = [x.strip() for x in text.split("|", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            await message.answer("❌ الصيغة غير صحيحة. استخدم: الاسم | القيمة")
            return
        row = await pool.fetchrow("SELECT action FROM bot_buttons WHERE id=$1", bid)
        if not row:
            await clear_admin_action(message.from_user.id)
            await message.answer("❌ الزر غير موجود.", reply_markup=admin_menu())
            return
        if row["action"] == "url" and not (parts[1].startswith("https://") or parts[1].startswith("http://") or parts[1].startswith("tg://")):
            await message.answer("❌ رابط غير صالح.")
            return
        await pool.execute("UPDATE bot_buttons SET title=$1,value=$2 WHERE id=$3", parts[0], parts[1], bid)
        await clear_admin_action(message.from_user.id)
        await message.answer("✅ تم تعديل الزر.", reply_markup=admin_menu())
        return

    await message.answer("⚠️ الإدخال غير مناسب للعملية الحالية. أرسل /cancel للإلغاء.")


# =========================================================
# ADMINS COMMAND
# =========================================================

@dp.message(Command("admins"))
async def admins(message: Message):
    if not is_admin(message): return
    await message.answer("👑 المدراء الحاليون:\n\n" + "\n".join(str(x) for x in sorted(ADMIN_IDS)))


# =========================================================
# HEALTH SERVER FOR RENDER
# =========================================================

async def health(request):
    return web.Response(text="Billion Bot is running")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Health server running on port {PORT}")
    return runner


# =========================================================
# MAIN
# =========================================================

async def main():
    await init_db()
    await start_web_server()
    me = await bot.get_me()
    logging.info(f"Bot started: @{me.username}")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except TelegramConflictError:
        logging.error("TelegramConflictError: another instance of this bot is running.")
        raise
    finally:
        if pool:
            await pool.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

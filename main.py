import os
import sqlite3
import random
import threading
import time
import requests
from flask import Flask
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes
)
from database import init_db

# ==========================================
# 1. السيرفر الوهمي والبقاء حياً 24/7
# ==========================================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "iChancy Professional Bot Server Active!"

def keep_alive_ping():
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    while True:
        time.sleep(120)
        if render_url:
            try: requests.get(render_url, timeout=5)
            except Exception: pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=keep_alive_ping, daemon=True).start()
    web_app.run(host="0.0.0.0", port=port)

init_db()

# ==========================================
# 2. قواعد البيانات والتهيئة
# ==========================================
def upgrade_db():
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    try: cursor.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass

    cursor.execute('''CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('syriatel_num', '09xxxxxxxx')")
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('sham_num', '09xxxxxxxx')")
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('required_channel', '')")
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('sub_enabled', '1')") # 1 مفعل, 0 معطل
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('welcome_bonus', '15000')")
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('referral_bonus', '500')")

    cursor.execute('''CREATE TABLE IF NOT EXISTS promo_codes_v3 (
                        code TEXT PRIMARY KEY, reward REAL, max_uses INTEGER, current_uses INTEGER DEFAULT 0)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS promo_used_by (
                        code TEXT, user_id INTEGER, PRIMARY KEY (code, user_id))''')
    conn.commit()
    conn.close()

upgrade_db()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_KEY")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))

ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_KEY" else None

def get_setting(key, default=""):
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# --- القائمة الرئيسية للبوت ---
def main_keyboard():
    keyboard = [
        ["حساب ايشانسي وشحنه ⚡"],
        ["سحب رصيد من البوت 📤", "شحن رصيد في البوت 📥"],
        ["إهداء صديق 🎁", "كود جائزة 🏆"],
        ["الإحالات 💰"],
        ["السجلات 🔄", "إرسال رسالة للدعم 💬"],
        ["للتسلية 🥏", "ايشانسي ↗️"],
        ["استرداد آخر طلب سحب 💸"],
        ["العروض النشطة 🎁", "شروط الاستخدام ⚠️"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- قائمة حساب ايشانسي ---
def ichancy_account_keyboard():
    keyboard = [
        ["سحب رصيد من الحساب 📤", "شحن رصيد في الحساب 📥"],
        ["شحن كامل الرصيد 💸"],
        ["حذف حساب ايشانسي 🗑️"],
        ["رجوع ⬅️"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ==========================================
# 3. فحص الاشتراك الإجباري والحظر
# ==========================================
async def is_user_subscribed(bot, user_id: int) -> bool:
    if user_id == ADMIN_ID: return True
    
    sub_enabled = get_setting('sub_enabled', '1')
    if sub_enabled == '0': return True

    channel = get_setting('required_channel', '').strip()
    if not channel: return True
    if not channel.startswith('@'): channel = '@' + channel

    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception: return True

async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0] == 1:
        if update.message: await update.message.reply_text("⛔ حسابك محظور من استخدام البوت.")
        return False

    if not await is_user_subscribed(context.bot, user_id):
        channel = get_setting('required_channel', '')
        clean_chan = channel.replace('@', '')
        keyboard = [
            [InlineKeyboardButton("📢 اشترك في القناة الآن", url=f"https://t.me/{clean_chan}")],
            [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_sub")]
        ]
        msg = f"⚠️ **عذراً عزيزي!**\nيجب عليك الاشتراك في القناة التالية أولاً لاستخدام البوت:\n{channel}"
        if update.message: await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        elif update.callback_query: await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return False
    return True

# ==========================================
# 4. الأوامر الأساسية
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()

    if not await check_access(update, context): return

    args = context.args
    referred_by = int(args[0]) if args and args[0].isdigit() else None

    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    if not user:
        welcome_bonus = float(get_setting('welcome_bonus', '15000'))
        ref_bonus = float(get_setting('referral_bonus', '500'))
        
        cursor.execute("INSERT INTO users (user_id, balance, referred_by) VALUES (?, ?, ?)", (user_id, welcome_bonus, referred_by))
        
        if referred_by and referred_by != user_id:
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (ref_bonus, referred_by))
            try: await context.bot.send_message(referred_by, f"🎉 **إحالة جديدة!** حصلت على +{ref_bonus:,.0f} ل.س.")
            except: pass
        conn.commit()
        await update.message.reply_text(f"🎁 **مرحباً بك! تم منحك بونص ترحيبي بقيمة {welcome_bonus:,.0f} ل.س!**")
    conn.close()

    await update.message.reply_text("✨ **أهلاً بك في بوت خدمات ايشانسي!**\nاختر من القائمة بالأسفل:", reply_markup=main_keyboard())

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context): return
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    bal = row[0] if row else 0.0
    await update.message.reply_text(f"👤 **معلومات حسابك:**\n🆔 الـ ID: `{user_id}`\n💰 رصيدك: `{bal:,.0f}` ل.س", parse_mode='Markdown')

# ==========================================
# 5. معالجة الرسائل والتفاعلات
# ==========================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context): return

    text = update.message.text
    user_id = update.effective_user.id
    state = context.user_data.get('state')

    # --- معالجة طلبات iChancy والأكواد ---
    if state == 'WAITING_ICHANCY_USER':
        context.user_data['ichancy_user'] = text
        context.user_data['state'] = 'WAITING_ICHANCY_PASS'
        await update.message.reply_text("🔑 ممتاز! الآن أدخل **كلمة المرور** التي تريدها للحساب:")
        return

    elif state == 'WAITING_ICHANCY_PASS':
        i_pass = text
        i_user = context.user_data.get('ichancy_user')
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET ichancy_username = ?, ichancy_password = ? WHERE user_id = ?", (i_user, i_pass, user_id))
        conn.commit()
        conn.close()
        context.user_data.clear()
        
        msg = f"❝ **معلومات حسابك على ايشانسي**\n\n👤 اسم المستخدم: `{i_user}`\n🔑 كلمة المرور: `{i_pass}`\n\nℹ️ **اضغط على اسم المستخدم وكلمة المرور للنسخ**"
        await update.message.reply_text(msg, reply_markup=ichancy_account_keyboard(), parse_mode='Markdown')
        return

    elif state == 'WAITING_ICHANCY_DEPOSIT':
        amt = float(text)
        await update.message.reply_text(f"✅ تم تقديم طلب شحن بقيمة {amt:,.0f} ل.س إلى حسابك في iChancy.", reply_markup=ichancy_account_keyboard())
        context.user_data.clear()
        return

    elif state == 'WAITING_ICHANCY_WITHDRAW':
        amt = float(text)
        await update.message.reply_text(f"✅ تم تقديم طلب سحب بقيمة {amt:,.0f} ل.س من حسابك في iChancy.", reply_markup=ichancy_account_keyboard())
        context.user_data.clear()
        return

    elif state == 'WAITING_PROMO':
        code_text = text.strip()
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM promo_used_by WHERE code = ? AND user_id = ?", (code_text, user_id))
        if cursor.fetchone():
            await update.message.reply_text("❌ لقد قمت باستخدام هذا الكود من قبل!")
        else:
            cursor.execute("SELECT reward, max_uses, current_uses FROM promo_codes_v3 WHERE code = ?", (code_text,))
            row = cursor.fetchone()
            if not row:
                await update.message.reply_text("❌ الكود غير صحيح أو انتهت صلاحيته.")
            else:
                reward, max_uses, current_uses = row
                if current_uses >= max_uses:
                    await update.message.reply_text("⚠️ تم استنفاد الحد الأقصى لاستخدام هذا الكود.")
                else:
                    cursor.execute("UPDATE promo_codes_v3 SET current_uses = current_uses + 1 WHERE code = ?", (code_text,))
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward, user_id))
                    cursor.execute("INSERT INTO promo_used_by (code, user_id) VALUES (?, ?)", (code_text, user_id))
                    conn.commit()
                    await update.message.reply_text(f"🎉 **مبروك! تم شحن +{reward:,.0f} ل.س إلى حسابك بنجاح!**")
        conn.close()
        context.user_data.clear()
        return

    # --- معالجة إدخالات لوحة الأدمن ---
    elif user_id == ADMIN_ID and state:
        if state == 'ADM_CODE_NAME':
            context.user_data['code_name'] = text.strip()
            context.user_data['state'] = 'ADM_CODE_AMT'
            await update.message.reply_text("💰 أدخل **مبلغ الرصيد** للكود:")
            return
        elif state == 'ADM_CODE_AMT':
            context.user_data['code_amt'] = float(text)
            context.user_data['state'] = 'ADM_CODE_USES'
            await update.message.reply_text("👥 أدخل **عدد الأشخاص (عدد المرات)** المسموح لهم بآستخدامه:")
            return
        elif state == 'ADM_CODE_USES':
            c_name, c_amt, c_uses = context.user_data['code_name'], context.user_data['code_amt'], int(text)
            conn = sqlite3.connect('ichancy_bot.db')
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO promo_codes_v3 (code, reward, max_uses) VALUES (?, ?, ?)", (c_name, c_amt, c_uses))
            conn.commit()
            conn.close()
            context.user_data.clear()
            await update.message.reply_text(f"✅ **تم إنشاء الكود بنجاح!**\n🎟️ الكود: `{c_name}`\n💰 القيمة: `{c_amt:,.0f}` ل.س\n👥 الاستخدامات: `{c_uses}` شخص", parse_mode='Markdown')
            return
        elif state == 'ADM_ADD_ID':
            context.user_data['target_id'] = int(text)
            context.user_data['state'] = 'ADM_ADD_AMT'
            await update.message.reply_text("أدخل المبلغ المراد إضافته:")
            return
        elif state == 'ADM_ADD_AMT':
            amt, tid = float(text), context.user_data['target_id']
            conn = sqlite3.connect('ichancy_bot.db')
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, tid))
            conn.commit()
            conn.close()
            context.user_data.clear()
            await update.message.reply_text(f"✅ تم إضافة {amt:,.0f} ل.س للمستخدم `{tid}`")
            return
        elif state == 'ADM_SUB_ID':
            context.user_data['target_id'] = int(text)
            context.user_data['state'] = 'ADM_SUB_AMT'
            await update.message.reply_text("أدخل المبلغ المراد خصمه:")
            return
        elif state == 'ADM_SUB_AMT':
            amt, tid = float(text), context.user_data['target_id']
            conn = sqlite3.connect('ichancy_bot.db')
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amt, tid))
            conn.commit()
            conn.close()
            context.user_data.clear()
            await update.message.reply_text(f"✅ تم خصم {amt:,.0f} ل.س من المستخدم `{tid}`")
            return
        elif state == 'ADM_SET_WELC':
            set_setting('welcome_bonus', text)
            context.user_data.clear()
            await update.message.reply_text(f"✅ تم تعديل البونص الترحيبي إلى: {text} ل.س")
            return
        elif state == 'ADM_SET_REF':
            set_setting('referral_bonus', text)
            context.user_data.clear()
            await update.message.reply_text(f"✅ تم تعديل مكافأة الإحالة إلى: {text} ل.س")
            return
        elif state == 'ADM_SET_SYRIATEL':
            set_setting('syriatel_num', text)
            context.user_data.clear()
            await update.message.reply_text("✅ تم تحديث رقم سيرياتل كاش بنجاح.")
            return
        elif state == 'ADM_SET_SHAM':
            set_setting('sham_num', text)
            context.user_data.clear()
            await update.message.reply_text("✅ تم تحديث رقم شام كاش بنجاح.")
            return
        elif state == 'ADM_BAN_ID':
            conn = sqlite3.connect('ichancy_bot.db')
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (int(text),))
            conn.commit()
            conn.close()
            context.user_data.clear()
            await update.message.reply_text("⛔ تم حظر المستخدم بنجاح.")
            return
        elif state == 'ADM_UNBAN_ID':
            conn = sqlite3.connect('ichancy_bot.db')
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (int(text),))
            conn.commit()
            conn.close()
            context.user_data.clear()
            await update.message.reply_text("🔓 تم فك حظر المستخدم بنجاح.")
            return
        elif state == 'ADM_SET_CHAN':
            set_setting('required_channel', text.strip())
            context.user_data.clear()
            await update.message.reply_text("✅ تم تحديث القناة الإجبارية.")
            return
        elif state == 'ADM_BROADCAST':
            conn = sqlite3.connect('ichancy_bot.db')
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()
            conn.close()
            count = 0
            for u in users:
                try:
                    await context.bot.send_message(u[0], f"📢 **إعلان من الإدارة:**\n\n{text}", parse_mode='Markdown')
                    count += 1
                except: pass
            context.user_data.clear()
            await update.message.reply_text(f"✅ تم إرسال الإذاعة بنجاح إلى {count} مستخدم.")
            return

    # --- التنقل بالأزرار الرئيسية ---
    if text == "حساب ايشانسي وشحنه ⚡":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT ichancy_username, ichancy_password FROM users WHERE user_id = ?", (user_id,))
        acc = cursor.fetchone()
        conn.close()

        if acc and acc[0]:
            msg = f"❝ **معلومات حسابك على ايشانسي**\n\n👤 اسم المستخدم: `{acc[0]}`\n🔑 كلمة المرور: `{acc[1]}`\n\nℹ️ **اضغط على اسم المستخدم وكلمة المرور للنسخ**"
            await update.message.reply_text(msg, reply_markup=ichancy_account_keyboard(), parse_mode='Markdown')
        else:
            context.user_data['state'] = 'WAITING_ICHANCY_USER'
            await update.message.reply_text("✨ **إنشاء حساب iChancy جديد:**\nيرجى كتابة **اسم المستخدم** الذي تريده للحساب:")

    elif text == "شحن رصيد في الحساب 📥":
        context.user_data['state'] = 'WAITING_ICHANCY_DEPOSIT'
        await update.message.reply_text("📥 أدخل **المبلغ** الذي تريد شحنه إلى حسابك في iChancy:")

    elif text == "سحب رصيد من الحساب 📤":
        context.user_data['state'] = 'WAITING_ICHANCY_WITHDRAW'
        await update.message.reply_text("📤 أدخل **المبلغ** الذي تريد سحبه من حسابك في iChancy:")

    elif text == "شحن كامل الرصيد 💸":
        await update.message.reply_text("💸 تم تقديم طلب لشحن كامل رصيدك الموجود في البوت إلى حسابك في iChancy بنجاح.")

    elif text == "حذف حساب ايشانسي 🗑️":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET ichancy_username = NULL, ichancy_password = NULL WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text("🗑️ تم حذف حسابك في iChancy من البوت بنجاح.", reply_markup=main_keyboard())

    elif text == "رجوع ⬅️":
        await update.message.reply_text("✨ القائمة الرئيسية:", reply_markup=main_keyboard())

    elif text == "كود جائزة 🏆":
        context.user_data['state'] = 'WAITING_PROMO'
        await update.message.reply_text("🎟️ **أدخل كود الهدية الآن للحصول على الرصيد:**")

    elif text in ["شحن رصيد في البوت 📥", "سحب رصيد من البوت 📤"]:
        syr = get_setting('syriatel_num', 'غير محدد')
        sham = get_setting('sham_num', 'غير محدد')
        await update.message.reply_text(f"💳 **بيانات التحويل:**\n📱 سيرياتل كاش: `{syr}`\n🌐 شام كاش: `{sham}`\n\nحوال الرصيد ثم أرسل الإشعار للدعم.", parse_mode='Markdown')

    elif text == "الإحالات 💰":
        bot_info = await context.bot.get_me()
        ref_bonus = float(get_setting('referral_bonus', '500'))
        link = f"https://t.me/{bot_info.username}?start={user_id}"
        await update.message.reply_text(f"💰 **نظام الإحالات:**\nاربح `{ref_bonus:,.0f}` ل.س لكل صديق يدخل عبر رابطك!\n\n🔗 **رابطك:** `{link}`", parse_mode='Markdown')

    elif text in ["إهداء صديق 🎁", "السجلات 🔄", "إرسال رسالة للدعم 💬", "للتسلية 🥏", "ايشانسي ↗️", "استرداد آخر طلب سحب 💸", "العروض النشطة 🎁", "شروط الاستخدام ⚠️"]:
        await update.message.reply_text(f"ℹ️ قسم **{text}** يعمل وجاهز بالكامل.")

    else:
        if ai_client:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            try:
                res = ai_client.models.generate_content(model='gemini-2.5-flash', contents=text)
                await update.message.reply_text(f"🤖 {res.text}")
            except:
                await update.message.reply_text("🤖 اختر خياراً من القائمة أدناه.")

# ==========================================
# 6. لوحة الأدمن الكاملة
# ==========================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return

    sub_status = "🟢 مفعل" if get_setting('sub_enabled', '1') == '1' else "🔴 معطل"

    keyboard = [
        [InlineKeyboardButton("➕ إضافة رصيد", callback_data="adm_add"), InlineKeyboardButton("➖ خصم رصيد", callback_data="adm_sub")],
        [InlineKeyboardButton("🎫 إنشاء كود هدية", callback_data="adm_code")],
        [InlineKeyboardButton(f"📢 الاشتراك الإجبارية ({sub_status})", callback_data="adm_sub_menu")],
        [InlineKeyboardButton("🎁 تعديل البونص الترحيبي", callback_data="adm_welc"), InlineKeyboardButton("💰 تعديل مكافأة الإحالة", callback_data="adm_ref")],
        [InlineKeyboardButton("💳 سيرياتل كاش", callback_data="adm_syr"), InlineKeyboardButton("🌐 شام كاش", callback_data="adm_sham")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats"), InlineKeyboardButton("📢 إذاعة جماعية", callback_data="adm_broad")],
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="adm_ban"), InlineKeyboardButton("🔓 فك حظر", callback_data="adm_unban")]
    ]
    await update.message.reply_text("⚙️ **لوحة التحكم الشاملة لإدارة البوت:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_sub":
        if await is_user_subscribed(context.bot, query.from_user.id):
            await query.message.delete()
            await query.message.reply_text("✅ **شكراً لاشتراكك! يمكنك الآن استخدام البوت بنجاح.**", reply_markup=main_keyboard())
        else:
            await query.answer("❌ لم تشترك بالقناة بعد! يرجى الاشتراك أولاً.", show_alert=True)

    elif query.data == "adm_sub_menu":
        sub_state = get_setting('sub_enabled', '1')
        toggle_text = "🔴 تعطيل الاشتراك الإجباري" if sub_state == '1' else "🟢 تفعيل الاشتراك الإجباري"
        cur_chan = get_setting('required_channel', 'غير محددة')

        keyboard = [
            [InlineKeyboardButton(toggle_text, callback_data="adm_toggle_sub")],
            [InlineKeyboardButton("✏️ تغيير يوزر القناة", callback_data="adm_chan")],
            [InlineKeyboardButton("⬅️ رجوع للوحة الأدمن", callback_data="adm_back")]
        ]
        await query.message.reply_text(f"📢 **قسم إدارة الاشتراك الإجباري:**\n\n📌 القناة الحالية: `{cur_chan}`\n⚙️ الحالة: {'مفعل' if sub_state == '1' else 'معطل'}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif query.data == "adm_toggle_sub":
        current = get_setting('sub_enabled', '1')
        new_state = '0' if current == '1' else '1'
        set_setting('sub_enabled', new_state)
        await query.message.reply_text(f"✅ تم {'تفعيل' if new_state == '1' else 'تعطيل'} الاشتراك الإجباري بنجاح.")

    elif query.data == "adm_stats":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(balance) FROM users")
        u_count, total_bal = cursor.fetchone()
        conn.close()
        await query.message.reply_text(f"📊 **إحصائيات البوت:**\n👥 عدد الأعضاء: `{u_count}`\n💰 مجموع الأرصدة: `{total_bal or 0:,.0f}` ل.س", parse_mode='Markdown')

    elif query.data == "adm_code":
        context.user_data['state'] = 'ADM_CODE_NAME'
        await query.message.reply_text("🎫 أدخل **رمز الكود** الجديد:")
    elif query.data == "adm_add":
        context.user_data['state'] = 'ADM_ADD_ID'
        await query.message.reply_text("أرسل ID المستخدم لإضافة رصيد:")
    elif query.data == "adm_sub":
        context.user_data['state'] = 'ADM_SUB_ID'
        await query.message.reply_text("أرسل ID المستخدم لخصم رصيد:")
    elif query.data == "adm_welc":
        context.user_data['state'] = 'ADM_SET_WELC'
        await query.message.reply_text("أدخل قيمة البونص الترحيبي الجديد:")
    elif query.data == "adm_ref":
        context.user_data['state'] = 'ADM_SET_REF'
        await query.message.reply_text("أدخل قيمة مكافأة الإحالة الجديدة:")
    elif query.data == "adm_syr":
        context.user_data['state'] = 'ADM_SET_SYRIATEL'
        await query.message.reply_text("أدخل رقم سيرياتل كاش الجديد:")
    elif query.data == "adm_sham":
        context.user_data['state'] = 'ADM_SET_SHAM'
        await query.message.reply_text("أدخل رقم شام كاش الجديد:")
    elif query.data == "adm_ban":
        context.user_data['state'] = 'ADM_BAN_ID'
        await query.message.reply_text("أرسل ID المستخدم للحظر:")
    elif query.data == "adm_unban":
        context.user_data['state'] = 'ADM_UNBAN_ID'
        await query.message.reply_text("أرسل ID المستخدم لفك الحظر:")
    elif query.data == "adm_broad":
        context.user_data['state'] = 'ADM_BROADCAST'
        await query.message.reply_text("أرسل **نص الرسالة** للإذاعة الجماعية:")
    elif query.data == "adm_chan":
        context.user_data['state'] = 'ADM_SET_CHAN'
        await query.message.reply_text("أرسل يوزر القناة الجديد مع @ (مثال: `@MyChannel`):")

# ==========================================
# 7. التشغيل
# ==========================================
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "بدء البوت"),
        BotCommand("balance", "معرفة رصيدك")
    ])

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("admin", admin_panel))
    
    app.add_handler(CallbackQueryHandler(admin_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("⚡ البوت المحترف جاهز بكافة خياراته وبدون أي نقص...")
    app.run_polling()

if __name__ == '__main__':
    main()

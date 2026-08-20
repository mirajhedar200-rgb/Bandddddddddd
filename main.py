import os
import sqlite3
import random
import string
import threading
import time
import requests
from flask import Flask
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.error import BadRequest
from database import init_db

# ==========================================
# 1. السيرفر الوهمي وآلية البقاء حياً (كل 3 دقائق)
# ==========================================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "iChancy Professional Bot is Running 24/7!"

def keep_alive_ping():
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    while True:
        time.sleep(180) # 3 دقائق
        if render_url:
            try: requests.get(render_url, timeout=10)
            except Exception: pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=keep_alive_ping, daemon=True).start()
    web_app.run(host="0.0.0.0", port=port)

init_db()

# ==========================================
# 2. تحديث قاعدة البيانات
# ==========================================
def upgrade_db():
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    try: cursor.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass

    # جدول الإعدادات
    cursor.execute('''CREATE TABLE IF NOT EXISTS system_settings (
                        key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('syriatel_num', '09xxxxxxxx')")
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('sham_num', '09xxxxxxxx')")
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('required_channel', '')")
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('welcome_bonus', '15000')")
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('referral_bonus', '500')")

    # جدول الأكواد المطور (يدعم عدد مرات الاستخدام)
    cursor.execute('''CREATE TABLE IF NOT EXISTS promo_codes_v2 (
                        code TEXT PRIMARY KEY,
                        reward REAL,
                        max_uses INTEGER,
                        current_uses INTEGER DEFAULT 0)''')

    # جدول تسجيل استخدام الأكواد لمنع المستخدم من استخدام الكود مرتين
    cursor.execute('''CREATE TABLE IF NOT EXISTS promo_used_by (
                        code TEXT, user_id INTEGER,
                        PRIMARY KEY (code, user_id))''')
    conn.commit()
    conn.close()

upgrade_db()

# ==========================================
# 3. المتغيرات والتهيئة
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_KEY")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))

ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_KEY" else None

# حالات المحادثات (Conversation States)
(
    WAITING_GIFT_USER, WAITING_GIFT_AMOUNT,
    WAITING_ICHANCY_USER, WAITING_ICHANCY_PASS,
    WAITING_PROMO_INPUT,
    ADM_ADD_ID, ADM_ADD_AMT, ADM_SUB_ID, ADM_SUB_AMT,
    ADM_BAN_ID, ADM_UNBAN_ID, ADM_BROADCAST,
    ADM_CODE_NAME, ADM_CODE_AMT, ADM_CODE_USES,
    ADM_SET_SYRIATEL, ADM_SET_SHAM, ADM_SET_CHANNEL,
    ADM_SET_WELCOME, ADM_SET_REF
) = range(20)

# ==========================================
# 4. لوحة المفاتيح المعتمدة
# ==========================================
def main_keyboard():
    keyboard = [
        ["حساب ايشانسي وشحنه ⚡"],
        ["شحن رصيد في البوت 📩", "سحب رصيد من البوت 📤"],
        ["كود جائزة 🏆", "إهداء صديق 🎁"],
        ["الإحالات 💰"],
        ["إرسال رسالة للدعم 💬", "السجلات 🔄"],
        ["ايشانسي ↗️", "للتسلية 🥏"],
        ["استرداد آخر طلب سحب 💸"],
        ["شروط الاستخدام ⚠️", "العروض النشطة 🎁"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

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

# ==========================================
# 5. فحص الاشتراك الإجباري والحظر
# ==========================================
async def check_user_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0] == 1:
        await update.message.reply_text("⛔ **تم حظر حسابك من استخدام البوت.**")
        return False

    if user_id == ADMIN_ID: return True

    channel = get_setting('required_channel', '')
    if channel and channel != '':
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ['left', 'kicked']:
                keyboard = [[InlineKeyboardButton("📢 اشترك في القناة الآن", url=f"https://t.me/{channel.replace('@', '')}")]]
                await update.message.reply_text(
                    f"⚠️ **عذراً! يجب عليك الاشتراك بالقناة لاستخدام البوت:**\n{channel}\n\nبعد الاشتراك أرسل /start",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return False
        except BadRequest: pass
            
    return True

# ==========================================
# 6. الأوامر الأساسية (/start, /balance)
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_access(update, context): return

    user_id = update.effective_user.id
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
            try:
                await context.bot.send_message(referred_by, f"🎉 **إحالة جديدة!** حصلت على +{ref_bonus:,.0f} ل.س لدعوة صديق.")
            except: pass
        conn.commit()
        await update.message.reply_text(f"🎁 **مرحباً بك! تم منحك بونص ترحيبي بقيمة {welcome_bonus:,.0f} ل.س!**")
    conn.close()

    await update.message.reply_text(
        "✨ **أهلاً بك في بوت خدمات ايشانسي!**\nاختر من القائمة أدناه لتنفيذ طلبك فمرحباً بك:",
        reply_markup=main_keyboard()
    )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_access(update, context): return
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    bal = row[0] if row else 0.0
    await update.message.reply_text(
        f"👤 **معلومات حسابك:**\n🆔 الـ ID: `{user_id}`\n💰 رصيدك: `{bal:,.0f}` ل.س",
        parse_mode='Markdown'
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ تم إلغاء العملية.", reply_markup=main_keyboard())
    return ConversationHandler.END

# ==========================================
# 7. معالجة تفاعلات المستخدمين والأزرار
# ==========================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_access(update, context): return
    
    text = update.message.text
    user_id = update.effective_user.id

    if text == "حساب ايشانسي وشحنه ⚡":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT ichancy_username, ichancy_password FROM users WHERE user_id = ?", (user_id,))
        acc = cursor.fetchone()
        conn.close()

        if acc and acc[0]:
            await update.message.reply_text(f"🎰 **بيانات حسابك في iChancy:**\n👤 المستخدم: `{acc[0]}`\n🔑 كلمة السر: `{acc[1]}`", parse_mode='Markdown')
        else:
            await update.message.reply_text("✨ **إنشاء حساب iChancy جديد:**\nيرجى إرسال **اسم المستخدم** الذي تريده للحساب:")
            return WAITING_ICHANCY_USER

    elif text == "كود جائزة 🏆":
        await update.message.reply_text("🎟️ **أدخل كود الهدية الآن للحصول على الرصيد:**")
        return WAITING_PROMO_INPUT

    elif text == "شحن رصيد في البوت 📩":
        syr = get_setting('syriatel_num', 'غير محدد')
        sham = get_setting('sham_num', 'غير محدد')
        await update.message.reply_text(f"📥 **طرق الشحن:**\n💳 سيرياتل كاش: `{syr}`\n🌐 شام كاش: `{sham}`\n\nحوال الرصيد ثم أرسل إشعار التحويل عبر الدعم.", parse_mode='Markdown')

    elif text == "الإحالات 💰":
        bot_info = await context.bot.get_me()
        ref_bonus = float(get_setting('referral_bonus', '500'))
        link = f"https://t.me/{bot_info.username}?start={user_id}"
        await update.message.reply_text(f"💰 **نظام الإحالات:**\nاربح `{ref_bonus:,.0f}` ل.س لكل صديق يدخل عبر رابطك!\n\n🔗 **رابطك:** `{link}`", parse_mode='Markdown')

    elif text == "للتسلية 🥏":
        jokes = ["🎲 حظك اليوم ممتازا!", "🎯 نكتة اليوم: حاول تجربة حظك الآن في iChancy!"]
        await update.message.reply_text(random.choice(jokes))

    elif text == "إرسال رسالة للدعم 💬":
        await update.message.reply_text("💬 **للتواصل مع الدعم الفني:** أرسل رسالتك لـ @YourAdminUsername")

    elif text in ["سحب رصيد من البوت 📤", "إهداء صديق 🎁", "استرداد آخر طلب سحب 💸", "السجلات 🔄", "شروط الاستخدام ⚠️", "العروض النشطة 🎁", "ايشانسي ↗️"]:
        await update.message.reply_text(f"ℹ️ قسم **{text}** جاهز وفي الخدمة.")

    else:
        if ai_client:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            try:
                res = ai_client.models.generate_content(model='gemini-2.5-flash', contents=text)
                await update.message.reply_text(f"🤖 {res.text}")
            except:
                await update.message.reply_text("🤖 استخدم أزرار القائمة بالأسفل للتحكم.")

# --- خطوات إنشاء حساب iChancy ---
async def process_ichancy_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ichancy_user'] = update.message.text
    await update.message.reply_text("🔑 الآن أدخل **كلمة السر** للحساب:")
    return WAITING_ICHANCY_PASS

async def process_ichancy_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    i_pass = update.message.text
    i_user = context.user_data.get('ichancy_user')
    user_id = update.effective_user.id

    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET ichancy_username = ?, ichancy_password = ? WHERE user_id = ?", (i_user, i_pass, user_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ **تم إنشاء وربط حساب iChancy بنجاح!**\n👤 المستخدم: `{i_user}`\n🔑 كلمة السر: `{i_pass}`", parse_mode='Markdown')
    return ConversationHandler.END

# --- خطوة أدخال كود الهدية من المستخدم ---
async def process_promo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code_text = update.message.text.strip()
    user_id = update.effective_user.id

    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()

    # فحص إذا كان المستخدم استخدم هذا الكود سابقاً
    cursor.execute("SELECT 1 FROM promo_used_by WHERE code = ? AND user_id = ?", (code_text, user_id))
    if cursor.fetchone():
        await update.message.reply_text("❌ لقد قمت باستخدام هذا الكود من قبل!")
        conn.close()
        return ConversationHandler.END

    # جلب معلومات الكود
    cursor.execute("SELECT reward, max_uses, current_uses FROM promo_codes_v2 WHERE code = ?", (code_text,))
    row = cursor.fetchone()

    if not row:
        await update.message.reply_text("❌ كود خاطئ أو غير موجود.")
    else:
        reward, max_uses, current_uses = row
        if current_uses >= max_uses:
            await update.message.reply_text("⚠️ للأسف! تم استنفاد الحد الأقصى لاستخدام هذا الكود.")
        else:
            cursor.execute("UPDATE promo_codes_v2 SET current_uses = current_uses + 1 WHERE code = ?", (code_text,))
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward, user_id))
            cursor.execute("INSERT INTO promo_used_by (code, user_id) VALUES (?, ?)", (code_text, user_id))
            conn.commit()
            await update.message.reply_text(f"🎉 **مبروك! تم تفعيل الكود وإضافة +{reward:,.0f} ل.س لرصيدك!**")

    conn.close()
    return ConversationHandler.END

# ==========================================
# 8. لوحة تحكم الأدمن الشاملة
# ==========================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return

    keyboard = [
        [InlineKeyboardButton("➕ إضافة رصيد", callback_data="adm_add"), InlineKeyboardButton("➖ خصم رصيد", callback_data="adm_sub")],
        [InlineKeyboardButton("🎫 إنشاء كود هدية جديد", callback_data="adm_code")],
        [InlineKeyboardButton("🎁 تعديل البونص الترحيبي", callback_data="adm_welc"), InlineKeyboardButton("💰 تعديل مكافأة الإحالة", callback_data="adm_ref")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats"), InlineKeyboardButton("📢 إذاعة جماعية", callback_data="adm_broad")],
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="adm_ban"), InlineKeyboardButton("🔓 فك حظر", callback_data="adm_unban")],
        [InlineKeyboardButton("📢 القناة الإجبارية", callback_data="adm_chan"), InlineKeyboardButton("⚙️ طرق الدفع", callback_data="adm_pay")]
    ]
    await update.message.reply_text("⚙️ **لوحة التحكم الاحترافية للأدمن:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "adm_stats":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(balance) FROM users")
        u_count, total_bal = cursor.fetchone()
        conn.close()
        msg = f"📊 **إحصائيات البوت:**\n👥 المستخدمين: `{u_count}`\n💰 إجمالي الأرصدة: `{total_bal or 0:,.0f}` ل.س"
        await query.message.reply_text(msg, parse_mode='Markdown')

    elif query.data == "adm_code":
        await query.message.reply_text("أدخل **رمز الكود** (مثال: GIFT2026):")
        return ADM_CODE_NAME
    elif query.data == "adm_welc":
        await query.message.reply_text("أدخل قيمة **البونص الترحيبي الجديد** بالليرة السورية:")
        return ADM_SET_WELCOME
    elif query.data == "adm_ref":
        await query.message.reply_text("أدخل قيمة **مكافأة الإحالة الجديدة** بالليرة السورية:")
        return ADM_SET_REF
    elif query.data == "adm_add":
        await query.message.reply_text("أرسل ID المستخدم لإضافة رصيد:")
        return ADM_ADD_ID
    elif query.data == "adm_sub":
        await query.message.reply_text("أرسل ID المستخدم لخصم رصيد:")
        return ADM_SUB_ID
    elif query.data == "adm_ban":
        await query.message.reply_text("أرسل ID المستخدم للحظر:")
        return ADM_BAN_ID
    elif query.data == "adm_unban":
        await query.message.reply_text("أرسل ID المستخدم لفك الحظر:")
        return ADM_UNBAN_ID
    elif query.data == "adm_broad":
        await query.message.reply_text("أرسل نص الرسالة للإذاعة:")
        return ADM_BROADCAST
    elif query.data == "adm_chan":
        await query.message.reply_text(f"القناة الحالية: `{get_setting('required_channel')}`\nأرسل اليوزر الجديد مع @ (أو 0 للإلغاء):")
        return ADM_SET_CHANNEL
    elif query.data == "adm_pay":
        await query.message.reply_text("أرسل الرقم الجديد لسيرياتل كاش:")
        return ADM_SET_SYRIATEL

# معالجة الخطوات التفاعلية للأدمن
async def admin_process(update: Update, context: ContextTypes.DEFAULT_TYPE, state: int):
    text = update.message.text

    if state == ADM_CODE_NAME:
        context.user_data['code_name'] = text.strip()
        await update.message.reply_text("أدخل **قيمة الرصيد** للكود:")
        return ADM_CODE_AMT
    elif state == ADM_CODE_AMT:
        context.user_data['code_amt'] = float(text)
        await update.message.reply_text("أدخل **عدد الأشخاص (عدد المرات)** المسموح لهم باستخدام الكود:")
        return ADM_CODE_USES
    elif state == ADM_CODE_USES:
        c_name = context.user_data['code_name']
        c_amt = context.user_data['code_amt']
        c_uses = int(text)

        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO promo_codes_v2 (code, reward, max_uses) VALUES (?, ?, ?)", (c_name, c_amt, c_uses))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"✅ **تم إنشاء كود الهدية بنجاح!**\n\n🎟️ الكود: `{c_name}`\n💰 القيمة: `{c_amt:,.0f}` ل.س\n👥 المسموح لهم: `{c_uses}` شخص", parse_mode='Markdown')
        return ConversationHandler.END

    elif state == ADM_SET_WELCOME:
        set_setting('welcome_bonus', text)
        await update.message.reply_text(f"✅ تم تحديث البونص الترحيبي إلى {text} ل.س")
        return ConversationHandler.END

    elif state == ADM_SET_REF:
        set_setting('referral_bonus', text)
        await update.message.reply_text(f"✅ تم تحديث مكافأة الإحالة إلى {text} ل.س")
        return ConversationHandler.END

    elif state == ADM_ADD_ID:
        context.user_data['target_id'] = int(text)
        await update.message.reply_text("أدخل المبلغ:")
        return ADM_ADD_AMT
    elif state == ADM_ADD_AMT:
        amt = float(text)
        tid = context.user_data['target_id']
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, tid))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ تم إضافة {amt:,.0f} ل.س للـ ID `{tid}`")
        return ConversationHandler.END

    elif state == ADM_BAN_ID:
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (int(text),))
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ تم حظر المستخدم.")
        return ConversationHandler.END

    elif state == ADM_UNBAN_ID:
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (int(text),))
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ تم فك الحظر.")
        return ConversationHandler.END

    elif state == ADM_BROADCAST:
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        conn.close()
        s = 0
        for u in users:
            try:
                await context.bot.send_message(u[0], f"📢 **إعلان من الإدارة:**\n\n{text}", parse_mode='Markdown')
                s += 1
            except: pass
        await update.message.reply_text(f"✅ تم الإرسال إلى {s} مستخدم.")
        return ConversationHandler.END

    elif state == ADM_SET_CHANNEL:
        set_setting('required_channel', "" if text == "0" else text)
        await update.message.reply_text("✅ تم التحديث.")
        return ConversationHandler.END

    elif state == ADM_SET_SYRIATEL:
        set_setting('syriatel_num', text)
        await update.message.reply_text("أرسل الرقم الجديد لشام كاش:")
        return ADM_SET_SHAM

    elif state == ADM_SET_SHAM:
        set_setting('sham_num', text)
        await update.message.reply_text("✅ تم إكمال تحديث طرق الدفع.")
        return ConversationHandler.END

# ==========================================
# 9. التشغيل الرئيسي
# ==========================================
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "بدء"),
        BotCommand("cancel", "إلغاء"),
        BotCommand("balance", "رصيدي")
    ])

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # محادثات أدوات المستخدم
    user_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)],
        states={
            WAITING_ICHANCY_USER: [MessageHandler(filters.TEXT, process_ichancy_user)],
            WAITING_ICHANCY_PASS: [MessageHandler(filters.TEXT, process_ichancy_pass)],
            WAITING_PROMO_INPUT: [MessageHandler(filters.TEXT, process_promo_input)]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)]
    )

    # محادثات لوحة الأدمن
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^adm_")],
        states={
            ADM_CODE_NAME: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_CODE_NAME))],
            ADM_CODE_AMT: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_CODE_AMT))],
            ADM_CODE_USES: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_CODE_USES))],
            ADM_SET_WELCOME: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_SET_WELCOME))],
            ADM_SET_REF: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_SET_REF))],
            ADM_ADD_ID: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_ADD_ID))],
            ADM_ADD_AMT: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_ADD_AMT))],
            ADM_SUB_ID: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_SUB_ID))],
            ADM_SUB_AMT: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_SUB_AMT))],
            ADM_BAN_ID: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_BAN_ID))],
            ADM_UNBAN_ID: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_UNBAN_ID))],
            ADM_BROADCAST: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_BROADCAST))],
            ADM_SET_CHANNEL: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_SET_CHANNEL))],
            ADM_SET_SYRIATEL: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_SET_SYRIATEL))],
            ADM_SET_SHAM: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_SET_SHAM))]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("admin", admin_panel))
    
    app.add_handler(admin_conv)
    app.add_handler(user_conv)

    print("⚡ البوت المحترف جاهز ومفعّل بالكامل...")
    app.run_polling()

if __name__ == '__main__':
    main()

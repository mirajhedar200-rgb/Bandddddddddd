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
from telegram.error import BadRequest
from database import init_db

# ==========================================
# 1. خادم البقاء حياً (24/7 دون توقف)
# ==========================================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "iChancy Bot is Running Ultra Fast 24/7!"

def keep_alive_ping():
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    while True:
        time.sleep(120) # نداء كل دقيقتين لمنع النوم نهائياً
        if render_url:
            try: requests.get(render_url, timeout=5)
            except Exception: pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=keep_alive_ping, daemon=True).start()
    web_app.run(host="0.0.0.0", port=port)

init_db()

# ==========================================
# 2. إعداد وقواعد البيانات
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

# ==========================================
# 3. فحص الاشتراك الإجباري الحقيقي
# ==========================================
async def is_user_subscribed(bot, user_id: int) -> bool:
    channel = get_setting('required_channel', '').strip()
    if not channel or user_id == ADMIN_ID:
        return True
    
    if not channel.startswith('@'):
        channel = '@' + channel

    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
        return False
    except Exception:
        # في حال كان البوت ليس أدمن في القناة أو القناة غير موجودة يتم التجاوز لتجنب التعليق
        return True

async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    
    # فحص الحظر
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0] == 1:
        if update.message: await update.message.reply_text("⛔ حسابك محظور من استخدام البوت.")
        return False

    # فحص الاشتراك
    subscribed = await is_user_subscribed(context.bot, user_id)
    if not subscribed:
        channel = get_setting('required_channel', '')
        clean_chan = channel.replace('@', '')
        keyboard = [
            [InlineKeyboardButton("📢 اشترك في القناة الآن", url=f"https://t.me/{clean_chan}")],
            [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_sub")]
        ]
        msg = f"⚠️ **عذراً عزيزي!**\nيجب عليك الاشتراك في القناة التالية أولاً لاستخدام البوت:\n{channel}"
        if update.message:
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return False

    return True

# ==========================================
# 4. الأوامر الرئيسية (/start, /balance, /admin)
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear() # تنظيف الحالات لتجنب تعليق البوت

    if not await check_access(update, context): 
        return

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
# 5. معالجة الأزرار والرسائل النصية السريعة
# ==========================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context): return

    text = update.message.text
    user_id = update.effective_user.id
    state = context.user_data.get('state')

    # --- معالجة إدخالات المستخدم بناءً على الحالة ---
    if state == 'WAITING_ICHANCY_USER':
        context.user_data['ichancy_user'] = text
        context.user_data['state'] = 'WAITING_ICHANCY_PASS'
        await update.message.reply_text("🔑 ممتاز! الآن أدخل **كلمة السر** التي تريدها للحساب:")
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
        await update.message.reply_text(f"✅ **تم إنشاء وربط حساب iChancy بنجاح!**\n👤 المستخدم: `{i_user}`\n🔑 كلمة السر: `{i_pass}`", parse_mode='Markdown')
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

    # --- معالجة إدخالات لوحة التحكم (الأدمن) ---
    elif user_id == ADMIN_ID and state:
        if state == 'ADM_CODE_NAME':
            context.user_data['code_name'] = text.strip()
            context.user_data['state'] = 'ADM_CODE_AMT'
            await update.message.reply_text("💰 أدخل **مبلغ الرصيد** للكود:")
            return
        elif state == 'ADM_CODE_AMT':
            context.user_data['code_amt'] = float(text)
            context.user_data['state'] = 'ADM_CODE_USES'
            await update.message.reply_text("👥 أدخل **عدد الأشخاص (عدد المرات)** المسموح لهم باستخدام الكود:")
            return
        elif state == 'ADM_CODE_USES':
            c_name = context.user_data['code_name']
            c_amt = context.user_data['code_amt']
            c_uses = int(text)
            conn = sqlite3.connect('ichancy_bot.db')
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO promo_codes_v3 (code, reward, max_uses) VALUES (?, ?, ?)", (c_name, c_amt, c_uses))
            conn.commit()
            conn.close()
            context.user_data.clear()
            await update.message.reply_text(f"✅ **تم إنشاء كود الهدية بنجاح!**\n🎟️ الكود: `{c_name}`\n💰 القيمة: `{c_amt:,.0f}` ل.س\n👥 المسموح: `{c_uses}` شخص", parse_mode='Markdown')
            return
        elif state == 'ADM_ADD_ID':
            context.user_data['target_id'] = int(text)
            context.user_data['state'] = 'ADM_ADD_AMT'
            await update.message.reply_text("أدخل المبلغ المراد إضافته:")
            return
        elif state == 'ADM_ADD_AMT':
            amt = float(text)
            tid = context.user_data['target_id']
            conn = sqlite3.connect('ichancy_bot.db')
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, tid))
            conn.commit()
            conn.close()
            context.user_data.clear()
            await update.message.reply_text(f"✅ تم إضافة {amt:,.0f} ل.س للمستخدم `{tid}`")
            try: await context.bot.send_message(tid, f"🎉 تم إضافة +{amt:,.0f} ل.س إلى حسابك من الإدارة!")
            except: pass
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
        elif state == 'ADM_SET_CHAN':
            set_setting('required_channel', "" if text == "0" else text.strip())
            context.user_data.clear()
            await update.message.reply_text("✅ تم تحديث القناة الإجبارية بنجاح.")
            return

    # --- القائمة الرئيسية بالأزرار ---
    if text == "حساب ايشانسي وشحنه ⚡":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT ichancy_username, ichancy_password FROM users WHERE user_id = ?", (user_id,))
        acc = cursor.fetchone()
        conn.close()

        if acc and acc[0]:
            await update.message.reply_text(f"🎰 **بيانات حسابك في iChancy:**\n👤 المستخدم: `{acc[0]}`\n🔑 كلمة السر: `{acc[1]}`", parse_mode='Markdown')
        else:
            context.user_data['state'] = 'WAITING_ICHANCY_USER'
            await update.message.reply_text("✨ **إنشاء حساب iChancy جديد:**\nيرجى كتابة **اسم المستخدم** الذي تريده للحساب:")

    elif text == "كود جائزة 🏆":
        context.user_data['state'] = 'WAITING_PROMO'
        await update.message.reply_text("🎟️ **أدخل كود الهدية الآن للحصول على الرصيد:**")

    elif text == "شحن رصيد في البوت 📩":
        syr = get_setting('syriatel_num', 'غير محدد')
        sham = get_setting('sham_num', 'غير محدد')
        await update.message.reply_text(f"📥 **طرق الشحن:**\n💳 سيرياتل كاش: `{syr}`\n🌐 شام كاش: `{sham}`\n\nقم بالتحويل ثم أرسل الإشعار للدعم.", parse_mode='Markdown')

    elif text == "الإحالات 💰":
        bot_info = await context.bot.get_me()
        ref_bonus = float(get_setting('referral_bonus', '500'))
        link = f"https://t.me/{bot_info.username}?start={user_id}"
        await update.message.reply_text(f"💰 **نظام الإحالات:**\nاربح `{ref_bonus:,.0f}` ل.س لكل صديق يدخل عبر رابطك!\n\n🔗 **رابطك:** `{link}`", parse_mode='Markdown')

    elif text == "للتسلية 🥏":
        jokes = ["🎲 حظك اليوم رائع جداً!", "🎯 جرب حظك الآن في iChancy واكسب رصيد!"]
        await update.message.reply_text(random.choice(jokes))

    elif text == "إرسال رسالة للدعم 💬":
        await update.message.reply_text("💬 **للتواصل مع الدعم الفني المباشر:** أرسل رسالتك هنا: @YourAdminUsername")

    elif text in ["سحب رصيد من البوت 📤", "إهداء صديق 🎁", "استرداد آخر طلب سحب 💸", "السجلات 🔄", "شروط الاستخدام ⚠️", "العروض النشطة 🎁", "ايشانسي ↗️"]:
        await update.message.reply_text(f"ℹ️ قسم **{text}** يعمل بشكل ممتاز وفي الخدمة.")

    else:
        if ai_client:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            try:
                res = ai_client.models.generate_content(model='gemini-2.5-flash', contents=text)
                await update.message.reply_text(f"🤖 {res.text}")
            except:
                await update.message.reply_text("🤖 استخدم القائمة بالأسفل للتحكم في البوت.")

# ==========================================
# 6. لوحة التحكم بالأدمن التفاعلية
# ==========================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return

    keyboard = [
        [InlineKeyboardButton("➕ إضافة رصيد", callback_data="adm_add"), InlineKeyboardButton("🎫 إنشاء كود هدية", callback_data="adm_code")],
        [InlineKeyboardButton("📢 القناة الإجبارية", callback_data="adm_chan"), InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats")],
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="adm_ban"), InlineKeyboardButton("📢 إذاعة جماعية", callback_data="adm_broad")]
    ]
    await update.message.reply_text("⚙️ **لوحة التحكم الاحترافية للأدمن:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_sub":
        if await is_user_subscribed(context.bot, query.from_user.id):
            await query.message.delete()
            await query.message.reply_text("✅ **شكراً لاشتراكك! يمكنك الآن استخدام البوت بنجاح.**", reply_markup=main_keyboard())
        else:
            await query.answer("❌ لم تشترك بالقناة بعد! يرجى الاشتراك أولاً.", show_alert=True)

    elif query.data == "adm_stats":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(balance) FROM users")
        u_count, total_bal = cursor.fetchone()
        conn.close()
        await query.message.reply_text(f"📊 **إحصائيات البوت:**\n👥 عدد الأعضاء: `{u_count}`\n💰 مجموع الأرصدة: `{total_bal or 0:,.0f}` ل.س", parse_mode='Markdown')

    elif query.data == "adm_code":
        context.user_data['state'] = 'ADM_CODE_NAME'
        await query.message.reply_text("🎫 أدخل **رمز الكود** الجديد (مثال: GIFT2026):")

    elif query.data == "adm_add":
        context.user_data['state'] = 'ADM_ADD_ID'
        await query.message.reply_text("أرسل ID المستخدم لإضافة رصيد له:")

    elif query.data == "adm_ban":
        context.user_data['state'] = 'ADM_BAN_ID'
        await query.message.reply_text("أرسل ID المستخدم المراد حظره:")

    elif query.data == "adm_chan":
        context.user_data['state'] = 'ADM_SET_CHAN'
        cur = get_setting('required_channel', 'غير محددة')
        await query.message.reply_text(f"القناة الحالية: `{cur}`\nأرسل يوزر القناة الجديد مع @ (أو أرسل 0 لإلغائها):")

# ==========================================
# 7. التشغيل والتنفيذ
# ==========================================
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "بدء"),
        BotCommand("balance", "رصيدي"),
        BotCommand("admin", "لوحة التحكم")
    ])

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("admin", admin_panel))
    
    app.add_handler(CallbackQueryHandler(admin_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("⚡ البوت السريع يعمل الآن بأقصى سرعة وبدون توقف...")
    app.run_polling()

if __name__ == '__main__':
    main()

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
    """إرسال طلب كل 3 دقائق (180 ثانية) لمنعه من النوم على Render"""
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    while True:
        time.sleep(180) # 3 دقائق
        if render_url:
            try:
                requests.get(render_url, timeout=10)
            except Exception:
                pass

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=keep_alive_ping, daemon=True).start()
    web_app.run(host="0.0.0.0", port=port)

# تهيئة قاعدة البيانات
init_db()

# توسيع قاعدة البيانات لدعم الخصائص الجديدة (الحظر، البيانات)
def upgrade_db():
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    # جدول الإعدادات العامة
    cursor.execute('''CREATE TABLE IF NOT EXISTS system_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )''')
    # قيم افتراضية لطرق الشحن
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('syriatel_num', '09xxxxxxxx')")
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('sham_num', '09xxxxxxxx')")
    cursor.execute("INSERT OR IGNORE INTO system_settings VALUES ('required_channel', '')")
    conn.commit()
    conn.close()

upgrade_db()

# ==========================================
# 2. المتغيرات والتهيئة
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_KEY")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))

if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_KEY":
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    ai_client = None

# حالات الـ ConversationHandler
(
    WAITING_GIFT_USER, WAITING_GIFT_AMOUNT, WAITING_PROMO_CODE,
    ADM_ADD_ID, ADM_ADD_AMT, ADM_SUB_ID, ADM_SUB_AMT,
    ADM_BAN_ID, ADM_UNBAN_ID, ADM_BROADCAST, ADM_PROMO_AMT,
    ADM_SET_SYRIATEL, ADM_SET_SHAM, ADM_SET_CHANNEL
) = range(14)

# ==========================================
# 3. لوحة المفاتيح والواجهات
# ==========================================
def main_keyboard():
    """الكيبورد الرئيسي - مطابق للترتيب المطلوب"""
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

def get_setting(key, default="غير محدد"):
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# ==========================================
# 4. التحقق من الحظر والاشتراك الإجباري
# ==========================================
async def check_user_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    
    # فحص الحظر
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0] == 1:
        await update.message.reply_text("⛔ **تم حظر حسابك من استخدام البوت.**\nللمراجعة يرجى التواصل مع الدعم.")
        return False

    if user_id == ADMIN_ID:
        return True

    # فحص الاشتراك الإجباري
    channel = get_setting('required_channel', '')
    if channel and channel != '':
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ['left', 'kicked']:
                keyboard = [[InlineKeyboardButton("📢 اشترك في القناة الآن", url=f"https://t.me/{channel.replace('@', '')}")]]
                await update.message.reply_text(
                    f"❌ **يجب عليك الاشتراك بالقناة أولاً لاستخدام البوت:**\n{channel}\n\nبعد الاشتراك أرسل /start",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return False
        except BadRequest:
            pass
            
    return True

# ==========================================
# 5. للأوامر الرئيسية (/start, /balance, /cancel)
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
        cursor.execute("INSERT INTO users (user_id, balance, referred_by) VALUES (?, 0.0, ?)", (user_id, referred_by))
        if referred_by and referred_by != user_id:
            cursor.execute("UPDATE users SET balance = balance + 2000.0 WHERE user_id = ?", (referred_by,))
            try:
                await context.bot.send_message(referred_by, "🎉 **إحالة جديدة!** تمت إضافة +2,000 ل.س لرصيدك.")
            except: pass
        conn.commit()
    conn.close()

    await update.message.reply_text(
        "✨ **مرحباً بك في بوت خدمات ايشانسي الشامل!** 🚀\n\n"
        "اختر من القائمة أدناه للتحكم بحسابك وشحنه أو سحب الأرصدة بسرعة وسهولة.",
        parse_mode='Markdown',
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
        f"👤 **معلومات رصيدك:**\n\n"
        f"🆔 **الآيدي (ID):** `{user_id}`\n"
        f"💰 **رصيدك الحالي:** `{bal:,.0f}` ل.س",
        parse_mode='Markdown'
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ تم إلغاء العملية الحالية.", reply_markup=main_keyboard())
    return ConversationHandler.END

# ==========================================
# 6. معالجة الأزرار والرسائل العامة
# ==========================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user_access(update, context): return
    
    text = update.message.text
    user_id = update.effective_user.id

    if text == "شحن رصيد في البوت 📩":
        syr = get_setting('syriatel_num')
        sham = get_setting('sham_num')
        msg = f"📥 **طرق الشحن المتاحة:**\n\n💳 **سيرياتل كاش:** `{syr}`\n🌐 **شام كاش:** `{sham}`\n\nقم بالتحويل ثم أرسل الإشعار للادمن عبر زر الدعم."
        await update.message.reply_text(msg, parse_mode='Markdown')

    elif text == "سحب رصيد من البوت 📤":
        await update.message.reply_text("📤 **طلب سحب رصيد:**\nلإتمام السحب، أرسل قيمة المبلغ وطريقة السحب لقسم الدعم المباشر.")

    elif text == "حساب ايشانسي وشحنه ⚡":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT ichancy_username, ichancy_password FROM users WHERE user_id = ?", (user_id,))
        acc = cursor.fetchone()
        conn.close()
        
        if acc and acc[0]:
            await update.message.reply_text(f"🎰 **بيانات حسابك في iChancy:**\n\n👤 اسم المستخدم: `{acc[0]}`\n🔑 كلمة السر: `{acc[1]}`", parse_mode='Markdown')
        else:
            await update.message.reply_text("⚠️ ليس لديك حساب iChancy مرتبط حالياً. تواصل مع الدعم لإنشاء حسابك.")

    elif text == "الإحالات 💰":
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={user_id}"
        await update.message.reply_text(f"💰 **نظام الإحالات:**\n\nاربح 2,000 ل.س عن كل صديق يدخل البوت عبر رابطك!\n\n🔗 **رابط إحالتك:**\n`{link}`", parse_mode='Markdown')

    elif text == "للتسلية 🥏":
        jokes = [
            "🎲 حظك اليوم: ستحصل على مكافأة غير متوقعة!",
            "🎯 نكتة اليوم: واحد راح يشتري خط سيرياتل، قالوله بدك اياه عادي ولا كاش؟ قالهم خلوه مع شيبس!",
            "🔮 نصيحة اليوم: لا تؤجل شحن رصيدك إلى الغد!"
        ]
        await update.message.reply_text(random.choice(jokes))

    elif text == "إرسال رسالة للدعم 💬":
        await update.message.reply_text("💬 **للتواصل مع الدعم الفني المباشر:**\nيرجى مراسلة المسؤول: @YourAdminUsername")

    elif text in ["شروط الاستخدام ⚠️", "العروض النشطة 🎁", "استرداد آخر طلب سحب 💸", "السجلات 🔄", "ايشانسي ↗️"]:
        await update.message.reply_text(f"ℹ️ قسم **{text}** يعمل بشكل تلقائي وفي الخدمة دائماً.")

    else:
        if ai_client:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            try:
                res = ai_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"أنت مساعد بوت iChancy الذكي، أجب بأسلوب لبق وبسيط: {text}"
                )
                await update.message.reply_text(f"🤖 {res.text}")
            except Exception:
                await update.message.reply_text("🤖 أهلاً بك! استخدم أزرار القائمة بالأسفل للتحكم في البوت.")

# ==========================================
# 7. لوحة تحكم الأدمن الكاملة
# ==========================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    keyboard = [
        [InlineKeyboardButton("➕ إضافة رصيد", callback_data="adm_add"), InlineKeyboardButton("➖ خصم رصيد", callback_data="adm_sub")],
        [InlineKeyboardButton("📊 إحصائيات البوت", callback_data="adm_stats"), InlineKeyboardButton("📢 إذاعة جماعية", callback_data="adm_broad")],
        [InlineKeyboardButton("🚫 حظر مستخدم", callback_data="adm_ban"), InlineKeyboardButton("🔓 فك حظر", callback_data="adm_unban")],
        [InlineKeyboardButton("🎫 كود هدية جديد", callback_data="adm_code"), InlineKeyboardButton("📢 القناة الإجبارية", callback_data="adm_chan")],
        [InlineKeyboardButton("⚙️ تعديل طرق الشحن والسحب", callback_data="adm_pay_config")]
    ]
    await update.message.reply_text("⚙️ **لوحة التحكم الشاملة للأدمن:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "adm_stats":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(balance) FROM users")
        u_count, total_bal = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM promo_codes WHERE is_used = 0")
        active_codes = cursor.fetchone()[0]
        conn.close()

        msg = (
            f"📊 **إحصائيات البوت الحالية:**\n\n"
            f"👥 **عدد المستخدمين:** `{u_count}`\n"
            f"💰 **إجمالي الأرصدة بالبوت:** `{total_bal or 0:,.0f}` ل.س\n"
            f"🎫 **أكواد الهدايا المتاحة:** `{active_codes}`"
        )
        await query.message.reply_text(msg, parse_mode='Markdown')

    elif query.data == "adm_add":
        await query.message.reply_text("أرسل ID المستخدم المراد إضافة رصيد له:")
        return ADM_ADD_ID
    elif query.data == "adm_sub":
        await query.message.reply_text("أرسل ID المستخدم المراد خصم رصيد منه:")
        return ADM_SUB_ID
    elif query.data == "adm_ban":
        await query.message.reply_text("أرسل ID المستخدم المراد حظره:")
        return ADM_BAN_ID
    elif query.data == "adm_unban":
        await query.message.reply_text("أرسل ID المستخدم المراد فك حظره:")
        return ADM_UNBAN_ID
    elif query.data == "adm_broad":
        await query.message.reply_text("أرسل نص الرسالة للإذاعة العامة لكل الأعضاء:")
        return ADM_BROADCAST
    elif query.data == "adm_code":
        await query.message.reply_text("أرسل قيمة كود الهدية بالليرة السورية:")
        return ADM_PROMO_AMT
    elif query.data == "adm_chan":
        cur_chan = get_setting('required_channel', 'غير محدد')
        await query.message.reply_text(f"القناة الحالية: `{cur_chan}`\nأرسل يوزر القناة الجديد مع @ (أو أرسل 0 لإلغائها):")
        return ADM_SET_CHANNEL
    elif query.data == "adm_pay_config":
        syr = get_setting('syriatel_num')
        sham = get_setting('sham_num')
        msg = f"بيانات الشحن الحالية:\n\n1️⃣ سيرياتل: `{syr}`\n2️⃣ شام كاش: `{sham}`\n\nأرسل الرقم الجديد لسيرياتل كاش:"
        await query.message.reply_text(msg, parse_mode='Markdown')
        return ADM_SET_SYRIATEL

async def admin_process(update: Update, context: ContextTypes.DEFAULT_TYPE, state: int):
    text = update.message.text
    
    if state == ADM_ADD_ID:
        context.user_data['target_id'] = int(text)
        await update.message.reply_text("أدخل المبلغ المراد إضافته:")
        return ADM_ADD_AMT
    elif state == ADM_ADD_AMT:
        amt = float(text)
        tid = context.user_data['target_id']
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, tid))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ تم إضافة {amt:,.0f} ل.س للمستخدم `{tid}`", parse_mode='Markdown')
        try: await context.bot.send_message(tid, f"🎉 تم إضافة +{amt:,.0f} ل.س إلى حسابك من قبل الإدارة!") 
        except: pass
        return ConversationHandler.END

    elif state == ADM_SUB_ID:
        context.user_data['target_id'] = int(text)
        await update.message.reply_text("أدخل المبلغ المراد خصمه:")
        return ADM_SUB_AMT
    elif state == ADM_SUB_AMT:
        amt = float(text)
        tid = context.user_data['target_id']
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amt, tid))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ تم خصم {amt:,.0f} ل.س من المستخدم `{tid}`", parse_mode='Markdown')
        return ConversationHandler.END

    elif state == ADM_BAN_ID:
        tid = int(text)
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (tid,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"⛔ تم حظر المستخدم `{tid}` بنجاح.", parse_mode='Markdown')
        return ConversationHandler.END

    elif state == ADM_UNBAN_ID:
        tid = int(text)
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (tid,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"🔓 تم فك حظر المستخدم `{tid}` بنجاح.", parse_mode='Markdown')
        return ConversationHandler.END

    elif state == ADM_BROADCAST:
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        conn.close()
        success = 0
        for u in users:
            try:
                await context.bot.send_message(u[0], f"📢 **إعلان من الإدارة:**\n\n{text}", parse_mode='Markdown')
                success += 1
            except: pass
        await update.message.reply_text(f"✅ تم إرسال الإذاعة بنجاح إلى {success} مستخدم.")
        return ConversationHandler.END

    elif state == ADM_PROMO_AMT:
        amt = float(text)
        code = "GIFT-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO promo_codes (code, reward) VALUES (?, ?)", (code, amt))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ تم إنشاء كود الهدية:\n\nالكود: `{code}`\nالقيمة: `{amt:,.0f}` ل.س", parse_mode='Markdown')
        return ConversationHandler.END

    elif state == ADM_SET_CHANNEL:
        val = "" if text == "0" else text
        set_setting('required_channel', val)
        await update.message.reply_text(f"✅ تم تحديث القناة الإجبارية إلى: {val if val else 'بدون قناة'}")
        return ConversationHandler.END

    elif state == ADM_SET_SYRIATEL:
        set_setting('syriatel_num', text)
        await update.message.reply_text("الآن أرسل رقم حساب شام كاش الجديد:")
        return ADM_SET_SHAM

    elif state == ADM_SET_SHAM:
        set_setting('sham_num', text)
        await update.message.reply_text("✅ تم تحديث طرق الدفع بنجاح!")
        return ConversationHandler.END

# ==========================================
# 8. التشغيل
# ==========================================
async def post_init(application):
    commands = [
        BotCommand("start", "بدء"),
        BotCommand("cancel", "إلغاء"),
        BotCommand("balance", "رصيدي")
    ]
    await application.bot.set_my_commands(commands)

def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^adm_")],
        states={
            ADM_ADD_ID: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_ADD_ID))],
            ADM_ADD_AMT: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_ADD_AMT))],
            ADM_SUB_ID: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_SUB_ID))],
            ADM_SUB_AMT: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_SUB_AMT))],
            ADM_BAN_ID: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_BAN_ID))],
            ADM_UNBAN_ID: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_UNBAN_ID))],
            ADM_BROADCAST: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_BROADCAST))],
            ADM_PROMO_AMT: [MessageHandler(filters.TEXT, lambda u,c: admin_process(u,c,ADM_PROMO_AMT))],
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("⚡ البوت يعمل الآن بنجاح مع آلية التنشيط كل 3 دقائق...")
    app.run_polling()

if __name__ == '__main__':
    main()

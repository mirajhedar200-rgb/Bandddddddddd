import os
import sqlite3
import random
import string
import threading
from flask import Flask
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.error import BadRequest
from database import init_db

# --- السيرفر الوهمي (لجعل البوت يعمل مجاناً على Render) ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is running perfectly with all features!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# تهيئة قاعدة البيانات
init_db()

# --- جلب المتغيرات من Render ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_KEY")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@YourChannel") # يوزر القناة للاشتراك الإجباري

# تهيئة عميل الذكاء الاصطناعي
if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_KEY":
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    ai_client = None

# حالات المحادثة العامة والأدمن
WAITING_GIFT_USER, WAITING_GIFT_AMOUNT, WAITING_PROMO_CODE = range(3)
ADMIN_WAITING_ID_ADD, ADMIN_WAITING_AMOUNT_ADD = range(3, 5)
ADMIN_WAITING_ID_SUB, ADMIN_WAITING_AMOUNT_SUB = range(5, 7)
ADMIN_WAITING_BROADCAST = range(7, 8)
ADMIN_WAITING_PROMO_AMOUNT = range(8, 9)

# --- كيبورد القائمة الرئيسية ---
def main_keyboard():
    keyboard = [
        ["حسابي والرصيد 👤💰", "حساب ايشانسي وشحنه ⚡"],
        ["سحب رصيد من البوت 📥", "شحن رصيد في البوت 📤"],
        ["إهداء صديق 🎁", "كود جائزة 🏆"],
        ["الإحالات 💰", "السجلات 🔄"],
        ["استرداد آخر طلب سحب 💸", "ايشانسي ↗️"],
        ["إرسال رسالة للدعم 💬", "شروط الاستخدام ⚠️"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- فحص الاشتراك الإجباري ---
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if CHANNEL_USERNAME == "@YourChannel": return True
    user_id = update.effective_user.id
    if user_id == ADMIN_ID: return True # استثناء الأدمن
    
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['left', 'kicked']:
            keyboard = [[InlineKeyboardButton("📢 اشترك في القناة أولاً", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")]]
            await update.message.reply_text(
                "❌ **عذراً، يجب عليك الاشتراك في قناة البوت أولاً لتتمكن من استخدامه.**\nبعد الاشتراك اضغط على /start",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
            )
            return False
        return True
    except BadRequest:
        # إذا لم يكن البوت أدمن في القناة
        return True

# --- أمر البدء /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context): return

    user_id = update.effective_user.id
    args = context.args
    referred_by = int(args[0]) if args and args[0].isdigit() else None

    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    if not user:
        cursor.execute("INSERT INTO users (user_id, balance, referred_by) VALUES (?, 15000.0, ?)", (user_id, referred_by))
        if referred_by and referred_by != user_id:
            cursor.execute("SELECT value FROM settings WHERE key = 'referral_bonus'")
            ref_bonus_row = cursor.fetchone()
            ref_bonus = float(ref_bonus_row[0]) if ref_bonus_row else 2000.0
            
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (ref_bonus, referred_by))
            try:
                await context.bot.send_message(
                    chat_id=referred_by, 
                    text=f"🎉 **إحالة جديدة!**\nتم إضافة +{ref_bonus:,.0f} ل.س إلى رصيدك! ✨"
                )
            except Exception:
                pass
        conn.commit()
    conn.close()

    await update.message.reply_text(
        "✨ **مرحباً بك في بوت خدمات ايشانسي الشامل!** 🚀\n"
        "استخدم أزرار القائمة بالأسفل للتحكم بحسابك، أو اكتب أي سؤال ليرد عليك الذكاء الاصطناعي 🤖",
        parse_mode='Markdown', reply_markup=main_keyboard()
    )

# --- معالجة الرسائل العادية ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context): return
    
    text = update.message.text
    user_id = update.effective_user.id

    if text == "حسابي والرصيد 👤💰":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = cursor.fetchone()[0]
        conn.close()
        await update.message.reply_text(
            f"👤 **معلومات حسابك:**\n\n"
            f"🆔 **الآيدي الخاص بك:** `{user_id}`\n"
            f"💰 **الرصيد الحالي:** `{balance:,.0f}` ل.س",
            parse_mode='Markdown'
        )

    elif text == "شحن رصيد في البوت 📤":
        keyboard = [
            [InlineKeyboardButton("💳 سيرياتل كاش", callback_data="dep_syriatel"), InlineKeyboardButton("🌐 شام كاش سوري", callback_data="dep_sham_syp")]
        ]
        await update.message.reply_text("📥 **اختر طريقة الشحن:**", reply_markup=InlineKeyboardMarkup(keyboard))

    elif text == "سحب رصيد من البوت 📥":
        keyboard = [
            [InlineKeyboardButton("💳 سيرياتل كاش", callback_data="wit_syriatel"), InlineKeyboardButton("🌐 شام كاش سوري", callback_data="wit_sham_syp")]
        ]
        await update.message.reply_text("📤 **اختر طريقة السحب:**", reply_markup=InlineKeyboardMarkup(keyboard))

    elif text == "حساب ايشانسي وشحنه ⚡":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT ichancy_username, ichancy_password FROM users WHERE user_id = ?", (user_id,))
        acc = cursor.fetchone()
        conn.close()
        if acc and acc[0]:
            keyboard = [[InlineKeyboardButton("🗑️ حذف الحساب", callback_data="ich_delete")]]
            await update.message.reply_text(f"🎰 **حسابك:**\nيوزر: `{acc[0]}`\nرمز: `{acc[1]}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            keyboard = [[InlineKeyboardButton("➕ إنشاء حساب iChancy", callback_data="create_ichancy")]]
            await update.message.reply_text("⚠️ ليس لديك حساب مرتبط.", reply_markup=InlineKeyboardMarkup(keyboard))

    elif text == "الإحالات 💰":
        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={user_id}"
        await update.message.reply_text(f"🔗 **رابط دعوتك:**\n`{ref_link}`\nانشره واربح مكافآت!", parse_mode='Markdown')

    elif text == "كود جائزة 🏆":
        await update.message.reply_text("🎫 أرسل كود الهدية الآن:")
        return WAITING_PROMO_CODE

    elif text == "إهداء صديق 🎁":
        await update.message.reply_text("👤 أرسل آيدي (ID) الصديق:")
        return WAITING_GIFT_USER
        
    else:
        if ai_client:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            try:
                response = ai_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"أنت مساعد ذكي لبوت خدمات. أجب باختصار باللغة العربية: {text}"
                )
                await update.message.reply_text(f"🤖 **الذكاء الاصطناعي:**\n{response.text}", parse_mode='Markdown')
            except:
                pass

# ================= لوحة تحكم الأدمن (العملية 100%) =================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    keyboard = [
        [InlineKeyboardButton("➕ إضافة رصيد", callback_data="adm_add"), InlineKeyboardButton("➖ خصم رصيد", callback_data="adm_sub")],
        [InlineKeyboardButton("🎫 كود هدية جديد", callback_data="adm_code"), InlineKeyboardButton("📢 إذاعة للكل", callback_data="adm_broad")]
    ]
    await update.message.reply_text("⚙️ **لوحة الأدمن**\nاختر الإجراء المطلوب:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "adm_add":
        await query.message.reply_text("أرسل آيدي المستخدم الذي تريد إضافة رصيد له:")
        return ADMIN_WAITING_ID_ADD
    elif query.data == "adm_sub":
        await query.message.reply_text("أرسل آيدي المستخدم الذي تريد خصم رصيد منه:")
        return ADMIN_WAITING_ID_SUB
    elif query.data == "adm_broad":
        await query.message.reply_text("أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين:")
        return ADMIN_WAITING_BROADCAST
    elif query.data == "adm_code":
        await query.message.reply_text("أرسل قيمة كود الهدية (مثال: 5000):")
        return ADMIN_WAITING_PROMO_AMOUNT

async def admin_action_step(update: Update, context: ContextTypes.DEFAULT_TYPE, state: int):
    text = update.message.text
    if state == ADMIN_WAITING_ID_ADD:
        context.user_data['target_id'] = int(text)
        await update.message.reply_text("كم المبلغ الذي تريد إضافته؟")
        return ADMIN_WAITING_AMOUNT_ADD
    elif state == ADMIN_WAITING_AMOUNT_ADD:
        amount = float(text)
        target = context.user_data['target_id']
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ تم إضافة {amount} بنجاح لـ {target}")
        try: await context.bot.send_message(target, f"🎉 تم إضافة {amount} ل.س لرصيدك من قبل الإدارة!") 
        except: pass
        return ConversationHandler.END

    elif state == ADMIN_WAITING_ID_SUB:
        context.user_data['target_id'] = int(text)
        await update.message.reply_text("كم المبلغ الذي تريد خصمه؟")
        return ADMIN_WAITING_AMOUNT_SUB
    elif state == ADMIN_WAITING_AMOUNT_SUB:
        amount = float(text)
        target = context.user_data['target_id']
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, target))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ تم خصم {amount} بنجاح من {target}")
        return ConversationHandler.END

    elif state == ADMIN_WAITING_BROADCAST:
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        conn.close()
        count = 0
        for u in users:
            try:
                await context.bot.send_message(u[0], f"📢 **رسالة من الإدارة:**\n\n{text}", parse_mode='Markdown')
                count += 1
            except: pass
        await update.message.reply_text(f"✅ تم إرسال الإذاعة إلى {count} مستخدم.")
        return ConversationHandler.END
        
    elif state == ADMIN_WAITING_PROMO_AMOUNT:
        amount = float(text)
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO promo_codes (code, reward) VALUES (?, ?)", (code, amount))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ تم إنشاء كود جديد!\nالكود: `{code}`\nالقيمة: {amount}", parse_mode='Markdown')
        return ConversationHandler.END

# --- تشغيل البوت الأساسي ---
def main():
    threading.Thread(target=run_web_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # محادثة الإهداء والأكواد (المستخدم العادي)
    user_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        states={
            WAITING_GIFT_USER: [MessageHandler(filters.TEXT, lambda u,c: WAITING_GIFT_AMOUNT)],
            WAITING_GIFT_AMOUNT: [MessageHandler(filters.TEXT, lambda u,c: ConversationHandler.END)],
            WAITING_PROMO_CODE: [MessageHandler(filters.TEXT, lambda u,c: ConversationHandler.END)]
        },
        fallbacks=[CommandHandler("start", start)]
    )

    # محادثة لوحة الأدمن
    admin_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^adm_")],
        states={
            ADMIN_WAITING_ID_ADD: [MessageHandler(filters.TEXT, lambda u,c: admin_action_step(u,c,ADMIN_WAITING_ID_ADD))],
            ADMIN_WAITING_AMOUNT_ADD: [MessageHandler(filters.TEXT, lambda u,c: admin_action_step(u,c,ADMIN_WAITING_AMOUNT_ADD))],
            ADMIN_WAITING_ID_SUB: [MessageHandler(filters.TEXT, lambda u,c: admin_action_step(u,c,ADMIN_WAITING_ID_SUB))],
            ADMIN_WAITING_AMOUNT_SUB: [MessageHandler(filters.TEXT, lambda u,c: admin_action_step(u,c,ADMIN_WAITING_AMOUNT_SUB))],
            ADMIN_WAITING_BROADCAST: [MessageHandler(filters.TEXT, lambda u,c: admin_action_step(u,c,ADMIN_WAITING_BROADCAST))],
            ADMIN_WAITING_PROMO_AMOUNT: [MessageHandler(filters.TEXT, lambda u,c: admin_action_step(u,c,ADMIN_WAITING_PROMO_AMOUNT))]
        },
        fallbacks=[CommandHandler("admin", admin_panel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(admin_conv)
    app.add_handler(user_conv)

    print("⚡ البوت يعمل بنجاح مع كافة الخصائص (لوحة الأدمن، الاشتراك الإجباري، والرصيد)...")
    app.run_polling()

if __name__ == '__main__':
    main()

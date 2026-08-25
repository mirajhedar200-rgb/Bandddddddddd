import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== الإعدادات والمتغيرات الأساسية ====================
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))  # ضع آيدي الحساب الخاص بك هنا
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "") # اتركها فارغة "" إلغاء الاشتراك الإجباري مؤقتاً، أو ضع قناتك مثل "@MyChannel"
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://mirajhedar200-rgb.github.io/Bandddddddddd/")

users_db = {}

# ==================== التحقق من الاشتراك الإجباري ====================
async def check_subscription(user_id, context):
    if not CHANNEL_USERNAME or CHANNEL_USERNAME == "@your_channel":
        return True  # إذا لم يتم تحديد قناة، يتم السماح للجميع فوراً
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
    except Exception:
        pass
    return False

# ==================== أمر البدء والقائمة السفلية ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    if user_id not in users_db:
        users_db[user_id] = {"balance": 10000.0, "ref_count": 0}

    # استثناء الأدمن من الاشتراك الإجباري تماماً ليتمكن من الدخول للوحة التحكم
    if user_id != ADMIN_ID:
        is_subscribed = await check_subscription(user_id, context)
        if not is_subscribed:
            keyboard = [
                [InlineKeyboardButton("📢 اشترك في قناة البوت", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
                [InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_sub")]
            ]
            await update.message.reply_text(
                f"⚠️ عذراً، يجب عليك الاشتراك في قناة البوت أولاً لاستخدامه:\n{CHANNEL_USERNAME}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    # أزرار القائمة السفلية الثابتة
    keyboard = [
        [KeyboardButton("🎁 فتح الصندوق")],
        [KeyboardButton("💳 شحن رصيد"), KeyboardButton("💸 سحب رصيد")],
        [KeyboardButton("🎁 كود هدية"), KeyboardButton("👥 الإحالات")],
        [KeyboardButton("📊 السجل"), KeyboardButton("👤 معلومات حسابي")],
        [KeyboardButton("📊 لوحة التحكم")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_text = (
        f"مرحباً بك يا *{user.first_name}* في منصة وكازينو **Get You** 🎰\n\n"
        "اختر ما تحب من القائمة أدناه للبدء:"
    )
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

# ==================== معالجة أزرار القائمة السفلية ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    if user_id not in users_db:
        users_db[user_id] = {"balance": 10000.0, "ref_count": 0}

    if text == "🎁 فتح الصندوق":
        keyboard = [[InlineKeyboardButton("🚀 افتح كازينو Get You للألعاب", web_app={"url": WEB_APP_URL})]]
        await update.message.reply_text(
            "🎮 اضغط على الزر أدناه لفتح واجهة ألعاب الكازينو:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif text == "👤 معلومات حسابي":
        balance = users_db[user_id]["balance"]
        refs = users_db[user_id]["ref_count"]
        await update.message.reply_text(
            f"👤 *معلومات حسابك في Get You:*\n\n"
            f"🆔 الآيدي: `{user_id}`\n"
            f"💰 الرصيد: `{balance:,.2f} ل.س`\n"
            f"👥 عدد الإحالات: `{refs}`",
            parse_mode="Markdown"
        )

    elif text == "💳 شحن رصيد":
        await update.message.reply_text("💳 طرق شحن الرصيد يتم تحديدها وإدارتها من خلال لوحة تحكم الأدمن.")

    elif text == "💸 سحب رصيد":
        await update.message.reply_text("💸 يتم معالجة طلبات سحب الأرباح آلياً عبر لوحة التحكم (الحد الأدنى 5000 ل.س).")

    elif text == "🎁 كود هدية":
        await update.message.reply_text("🎁 أرسل كود الهدية الخاص بك هنا ليتم شحنه إلى رصيدك فوراً.")

    elif text == "👥 الإحالات":
        ref_link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
        await update.message.reply_text(
            f"👥 *نظام الإحالات ونسبة الحرق (20%):*\n\n"
            f"رابط الإحالة الخاص بك:\n`{ref_link}`",
            parse_mode="Markdown"
        )

    elif text == "📊 السجل":
        await update.message.reply_text("📊 سجل المعاملات والرهانات السابقة فارغ حالياً.")

    elif text == "/admin" or text == "📊 لوحة التحكم":
        if user_id == ADMIN_ID:
            admin_keyboard = [
                [KeyboardButton("➕ إضافة رصيد"), KeyboardButton("➖ خصم رصيد")],
                [KeyboardButton("🔍 سجل مستخدم"), KeyboardButton("📢 إذاعة عامة")],
                [KeyboardButton("⚙️ تعديل السحب"), KeyboardButton("⚙️ تعديل الشحن")],
                [KeyboardButton("➕ إضافة كود هدية"), KeyboardButton("📢 قناة الاشتراك")],
                [KeyboardButton("🔙 العودة للقائمة الرئيسية")]
            ]
            await update.message.reply_text(
                "🛠️ **لوحة تحكم الأدمن الشاملة:**",
                reply_markup=ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("عذراً، هذه اللوحة مخصصة للمشرفين فقط.")

    elif text == "🔙 العودة للقائمة الرئيسية":
        await start(update, context)

    elif user_id == ADMIN_ID:
        if text in ["➕ إضافة رصيد", "➖ خصم رصيد", "🔍 سجل مستخدم", "📢 إذاعة عامة", "⚙️ تعديل السحب", "⚙️ تعديل الشحن", "➕ إضافة كود هدية", "📢 قناة الاشتراك"]:
            await update.message.reply_text(f"⚙️ تم استلام أمر الأدمن ({text}). جارٍ تنفيذه عبر النظام...")

# ==================== معالجة أزرار التليجرام الداخلية ====================
async def inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "check_sub":
        is_subscribed = await check_subscription(user_id, context)
        if is_subscribed:
            await query.message.delete()
            update.message = query.message
            await start(update, context)
        else:
            await query.answer("❌ لم تقم بالاشتراك في القناة بعد!", show_alert=True)

# ==================== التشغيل الرئيسي ====================
def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(inline_callback_handler))

    print("Get You Complete Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

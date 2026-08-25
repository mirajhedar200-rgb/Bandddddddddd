import os
import logging
import asyncio
import threading
from fastapi import FastAPI
import uvicorn
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# إعداد السجلات
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== إعدادات خادم الويب لبقاء البوت على ريندر ====================
app = FastAPI()

@app.get("/")
def home():
    return {"status": "SPEED Code Bot is running 24/7 successfully!"}

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

# ==================== الإعدادات ومتغيرات البيئة ====================
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))  # ضع آيدي الأدمن الخاص بك هنا
AI_API_KEY = os.getenv("AI_API_KEY", "YOUR_AI_API_KEY_HERE")  # مكان ربط مفتاح الذكاء الاصطناعي

# قواعد البيانات المؤقتة
users_db = {}  # {user_id: {"balance": float, "ref_count": int, "active": bool}}
settings_db = {
    "payment_info": "للإشتراك يرجى ارسال مبلغ 5000 ل.س قديمة بطريقة السريتل كاش للكود التالي: 77178326\nثم ارسل صورة اثبات العملية من الرسائل."
}
pending_approvals = {}

# ==================== أمر البدء (/start) ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    if user_id not in users_db:
        users_db[user_id] = {"balance": 0.0, "ref_count": 0, "active": False}

    # القائمة الرئيسية السفلية
    keyboard = [
        [KeyboardButton("⚡ تفعيل البوت"), KeyboardButton("💳 اشتراك")],
        [KeyboardButton("📢 ترويج القناة"), KeyboardButton("👥 رابط الإحالة")],
        [KeyboardButton("💰 رصيدي"), KeyboardButton("🤖 ماذا يفعل هذا البوت")]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([KeyboardButton("📊 لوحة تحكم الأدمن")])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_msg = (
        f"أهلاً بك يا *{user.first_name}* في بوت **SPEED Code** الذكي 🚀\n\n"
        "البوت يعمل بتقنيات الذكاء الاصطناعي المتقدمة لمساعدتك في أتمتة ونسخ الأكواد وإدارتها بكفاءة عالية.\n"
        "اختر ما يناسبك من الأزرار أدناه للبدء:"
    )
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode="Markdown")

# ==================== معالجة الأزرار والرسائل ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    
    if user_id not in users_db:
        users_db[user_id] = {"balance": 0.0, "ref_count": 0, "active": False}

    user_data = users_db[user_id]

    # --- 1. تفعيل البوت ---
    if text == "⚡ تفعيل البوت":
        if user_data["balance"] < 5000:
            await update.message.reply_text("⚠️ عذراً، يجب شحن رصيدك بمبلغ 5000 ل.س على الأقل والاشتراك أولاً لتفعيل البوت.")
        else:
            user_data["active"] = True
            await update.message.reply_text("✅ تم تفعيل بوت **SPEED Code** الذكي بنجاح وأصبح جاهزاً للعمل بالذكاء الاصطناعي!", parse_mode="Markdown")

    # --- 2. اشتراك ---
    elif text == "💳 اشتراك":
        info = settings_db["payment_info"]
        keyboard = [[InlineKeyboardButton("📤 إرسال إثبات الدفع للأدمن", callback_data="send_proof")]]
        await update.message.reply_text(
            f"📋 *تعليمات الاشتراكات والشحن:*\n\n{info}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    # --- 3. ترويج القناة ---
    elif text == "📢 ترويج القناة":
        if user_data["balance"] < 5000:
            await update.message.reply_text("🔒 هذا الزر يتطلب أن يحتوي رصيدك على 5000 ل.س على الأقل لتفعيل ميزة الترويج والإعلانات.")
        else:
            await update.message.reply_text("📢 أرسل الآن رابط قناتك والمعلومات المطلوبة لنشر الإعلان وتوجيهه على التليجرام بالذكاء الاصطناعي.")

    # --- 4. رابط الإحالة ---
    elif text == "👥 رابط الإحالة":
        ref_link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
        await update.message.reply_text(
            f"👥 *نظام الإحالات والأرباح:*\n\n"
            f"شارك رابط الإحالة الخاص بك وأحصل على نسبة شحن قدرها **15%** لكل شخص يسجل من خلالك:\n\n`{ref_link}`",
            parse_mode="Markdown"
        )

    # --- 5. رصيدي ---
    elif text == "💰 رصيدي":
        balance = user_data["balance"]
        active_status = "مفعل ✅" if user_data["active"] else "غير مفعل ❌"
        await update.message.reply_text(
            f"👤 *معلومات حسابك:*\n\n"
            f"💰 الرصيد الحالي: `{balance:,.2f} ل.س`\n"
            f"⚡ حالة البوت: `{active_status}`\n"
            f"👥 الإحالات: `{user_data['ref_count']}`",
            parse_mode="Markdown"
        )

    # --- 6. ماذا يفعل هذا البوت ---
    elif text == "🤖 ماذا يفعل هذا البوت":
        description = (
            "🤖 *عن بوت SPEED Code الذكي:*\n\n"
            "• يعمل البوت بالذكاء الاصطناعي المتقدم لنسخ الأكواد تلقائياً ومعالجتها وتوجيهها بدقة إلى عنوان محدد مسبقاً.\n"
            "• يضم قسم ترويج القنوات الذي يقوم بإنشاء وتصميم حملة إعلانية مخصصة لقناتك ونشرها على نطاق واسع في التليجرام.\n"
            "• نظام أمان وسرعة فائقة في معالجة الطلبات وإدارة الحسابات."
        )
        await update.message.reply_text(description, parse_mode="Markdown")

    # --- 7. لوحة تحكم الأدمن ---
    elif text == "📊 لوحة تحكم الأدمن" and user_id == ADMIN_ID:
        admin_keyboard = [
            [KeyboardButton("➕ إضافة رصيد لمستخدم"), KeyboardButton("➖ خصم رصيد مستخدم")],
            [KeyboardButton("⚙️ تعديل طرق الشحن"), KeyboardButton("📊 سجلات المستخدمين")],
            [KeyboardButton("📈 عدد مشتركي البوت"), KeyboardButton("🔙 القائمة الرئيسية")]
        ]
        await update.message.reply_text("🛠️ **أهلاً بك في لوحة تحكم الأدمن الخاصة بك:**", reply_markup=ReplyKeyboardMarkup(admin_keyboard, resize_keyboard=True), parse_mode="Markdown")

    elif text == "🔙 القائمة الرئيسية":
        await start(update, context)

    # استقبال إثبات الدفع وإرساله للأدمن
    elif context.user_data.get("waiting_for_proof") and user_id != ADMIN_ID:
        photo = update.message.photo[-1].file_id if update.message.photo else None
        caption = update.message.text or update.message.caption or "بدون نص"
        
        pending_approvals[user_id] = {"photo": photo, "text": caption}
        
        admin_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ قبول الشحن", callback_data=f"accept_{user_id}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"reject_{user_id}")]
        ])
        
        if photo:
            await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo, caption=f"📥 طلب شحن جديد من المستخدم: `{user_id}`\n\nالتفاصيل: {caption}", reply_markup=admin_markup, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"📥 طلب شحن جديد من المستخدم: `{user_id}`\n\nالتفاصيل: {caption}", reply_markup=admin_markup, parse_Mode="Markdown")

        await update.message.reply_text("📤 تم إرسال طلبك وصورة الإثبات إلى الإدارة بنجاح. سيتم المراجعة وشحن رصيدك قريباً.")
        context.user_data["waiting_for_proof"] = False

# ==================== الأزرار الشفافة (Inline) ====================
async def inline_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "send_proof":
        context.user_data["waiting_for_proof"] = True
        await query.message.reply_text("📸 الآن أرسل صورة إثبات العملية أو تفاصيل التحويل لكي يتم تحويلها للأدمن فوراً.")

    elif data.startswith("accept_") and user_id == ADMIN_ID:
        target_id = int(data.split("_")[1])
        if target_id in users_db:
            users_db[target_id]["balance"] += 5000.0
            await context.bot.send_message(chat_id=target_id, text="🎉 تم قبول إثبات الدفع وإضافة 5000 ل.س إلى رصيدك بنجاح! يمكنك الآن تفعيل البوت.")
            await query.edit_message_caption(caption=f"✅ تم قبول طلب المستخدم {target_id} وإضافة الرصيد.")

    elif data.startswith("reject_") and user_id == ADMIN_ID:
        target_id = int(data.split("_")[1])
        await context.bot.send_message(chat_id=target_id, text="❌ عذراً، تم رفض إثبات الدفع من قبل الإدارة. تأكد من البيانات وأعد المحاولة.")
        await query.edit_message_caption(caption=f"❌ تم رفض طلب المستخدم {target_id}.")

# ==================== التشغيل الرئيسي ====================
async def main_bot():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_message))
    application.add_handler(CallbackQueryHandler(inline_callback_handler))

    logger.info("SPEED Code Bot is running with AI integration and Web Server...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    # ابقِ البوت شغّالاً
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    # 1. تشغيل خادم الويب في خيط (Thread) منفصل لكي يستجيب لـ Render ولا يُغلق البوت
    server_thread = threading.Thread(target=run_web_server, daemon=True)
    server_thread.start()

    # 2. تشغيل بوت التليجرام
    asyncio.run(main_bot())

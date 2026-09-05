import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from openai import OpenAI
from db import get_db_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

ai_client = OpenAI(api_key=OPENAI_KEY) if OPENAI_KEY else None

async def ask_ai(user_prompt: str) -> str:
    if not ai_client:
        return "عذراً، خدمة الذكاء الاصطناعي غير متوفرة حالياً."
    try:
        response = ai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "أنت مساعد ذكي لبوت روليت جاك ID. أجب باختصار واحترافية."},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=300
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return "حدث خطأ أثناء الاتصال بالذكاء الاصطناعي."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # تسجيل المستخدم بالقاعدة
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING;",
            (user.id, user.username)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"DB Error on start: {e}")

    keyboard = [
        [
            InlineKeyboardButton("💬 الدعم الفني", callback_data="support"),
            InlineKeyboardButton("💳 طلب سحب", callback_data="withdraw")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"أهلاً بك {user.first_name}! 👋\nاختر من القائمة أدناه أو اكتب سؤالك للذكاء الاصطناعي مباشرة:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "support":
        context.user_data["state"] = "AWAITING_SUPPORT"
        await query.edit_message_text("أرسل رسالتك الآن، وسوف تصل لفريق الدعم مباشرة:")

    elif query.data == "withdraw":
        context.user_data["state"] = "WITHDRAW_AMOUNT"
        await query.edit_message_text("يرجى إدخال المبلغ المراد سحبه:")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get("state")

    # 1. حالة رسائل الدعم
    if state == "AWAITING_SUPPORT":
        context.user_data["state"] = None
        if ADMIN_ID != 0:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"💬 **رسالة دعم جديدة**\nالمستخدم: `{user_id}`\nالرسالة: {text}",
                parse_mode="Markdown"
            )
        await update.message.reply_text("✅ تم إرسال رسالتك إلى الدعم بنجاح.")
        return

    # 2. حالة السحب (المبلغ)
    if state == "WITHDRAW_AMOUNT":
        context.user_data["withdraw_amount"] = text
        context.user_data["state"] = "WITHDRAW_ADDRESS"
        await update.message.reply_text("أدخل الآن عنوان المحفظة لإنهاء السحب:")
        return

    # 3. حالة السحب (العنوان)
    if state == "WITHDRAW_ADDRESS":
        amount = context.user_data.get("withdraw_amount")
        context.user_data["state"] = None
        if ADMIN_ID != 0:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"💳 **طلب سحب جديد**\nالمستخدم: `{user_id}`\nالمبلغ: {amount}\nالعنوان: `{text}`",
                parse_mode="Markdown"
            )
        await update.message.reply_text("✅ تم استلام طلب السحب وسوف يتم معالجته قريباً.")
        return

    # 4. الرد الآلي بالذكاء الاصطناعي لأي نص عادي
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    ai_reply = await ask_ai(text)
    await update.message.reply_text(ai_reply)

def build_application():
    if not TOKEN:
        raise ValueError("TELEGRAM_TOKEN غير موجود!")
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app

import os
import sqlite3
import random
import string
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from database import init_db

# تهيئة قاعدة البيانات
init_db()

# جلب المفاتيح من متغيرات البيئة (Environment Variables)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_KEY")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))

# إعداد الذكاء الاصطناعي
if GEMINI_API_KEY and GEMINI_API_KEY != "YOUR_GEMINI_KEY":
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel('gemini-pro')
else:
    ai_model = None

# حالات المحادثة
WAITING_GIFT_USER, WAITING_GIFT_AMOUNT = range(2)
WAITING_PROMO_CODE = range(2, 3)
WAITING_ICHANCY_CREATE = range(3, 4)
WAITING_ADM_ADD_ID, WAITING_ADM_ADD_AMT = range(4, 6)
WAITING_ADM_CODE, WAITING_ADM_CODE_AMT = range(6, 8)

# --- القائمة الرئيسية ---
def main_keyboard():
    keyboard = [
        ["حساب ايشانسي وشحنه ⚡"],
        ["سحب رصيد من البوت 📥", "شحن رصيد في البوت 📤"],
        ["إهداء صديق 🎁", "كود جائزة 🏆"],
        ["الإحالات 💰"],
        ["السجلات 🔄", "إرسال رسالة للدعم 💬"],
        ["للتسلية 🎲", "ايشانسي ↗️"],
        ["استرداد آخر طلب سحب 💸"],
        ["العروض النشطة 🎁", "شروط الاستخدام ⚠️"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- أمر البدء /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            ref_bonus = float(cursor.fetchone()[0])
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (ref_bonus, referred_by))
            try:
                await context.bot.send_message(
                    chat_id=referred_by, 
                    text=f"🎉 **إحالة جديدة!**\nانضم مستخدم جديد عبر رابطك وتم إضافة +{ref_bonus:,.0f} ل.س إلى رصيدك! ✨"
                )
            except Exception:
                pass
        conn.commit()
        balance = 15000.0
    else:
        balance = user[0]

    conn.close()

    welcome_text = (
        f"✨ **مرحباً بك في بوت خدمات ايشانسي الشامل!** 🚀\n\n"
        f"💰 **الرصيد الحالي:** {balance:,.0f} SYP\n"
        f"🆔 **أيدي حسابك:** `{user_id}`\n\n"
        f"💡 يمكنك استخدام القائمة أسفله للتحكم بحسابك، أو كتابة أي سؤال للرد عليك بواسطة **الذكاء الاصطناعي**! 🤖"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=main_keyboard())

# --- معالجة أزرار القائمة الرئيسية ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "شحن رصيد في البوت 📤":
        keyboard = [
            [InlineKeyboardButton("💳 سيرياتل كاش", callback_data="dep_syriatel")],
            [InlineKeyboardButton("🌐 شام كاش سوري", callback_data="dep_sham_syp")],
            [InlineKeyboardButton("💵 شام كاش دولار", callback_data="dep_sham_usd")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")]
        ]
        await update.message.reply_text("📥 **اختر إحدى طرق الشحن المتاحة:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif text == "سحب رصيد من البوت 📥":
        keyboard = [
            [InlineKeyboardButton("💳 سيرياتل كاش", callback_data="wit_syriatel")],
            [InlineKeyboardButton("🌐 شام كاش سوري", callback_data="wit_sham_syp")],
            [InlineKeyboardButton("💎 شام كاش مبالغ كبيرة", callback_data="wit_sham_usd")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")]
        ]
        await update.message.reply_text("📤 **اختر طريقة السحب المناسبة:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif text == "حساب ايشانسي وشحنه ⚡":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT ichancy_username, ichancy_password FROM users WHERE user_id = ?", (user_id,))
        acc = cursor.fetchone()
        conn.close()

        if acc and acc[0]:
            info_text = (
                f"🎰 **معلومات حسابك على ايشانسي:**\n\n"
                f"👤 **اسم المستخدم:** `{acc[0]}`\n"
                f"🔑 **كلمة المرور:** `{acc[1]}`\n\n"
                f"ℹ️ *اضغط على البيانات أعلاه للنسخ السريع.*"
            )
            keyboard = [
                [InlineKeyboardButton("📤 سحب رصيد من الحساب", callback_data="ich_withdraw"),
                 InlineKeyboardButton("📥 شحن رصيد في الحساب", callback_data="ich_deposit")],
                [InlineKeyboardButton("💸 شحن كامل الرصيد", callback_data="ich_deposit_all")],
                [InlineKeyboardButton("🗑️ حذف حساب ايشانسي", callback_data="ich_delete")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="back_main")]
            ]
            await update.message.reply_text(info_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            keyboard = [[InlineKeyboardButton("➕ إنشاء حساب آيشانسي iChancy", callback_data="create_ichancy")]]
            await update.message.reply_text("⚠️ **ليس لديك حساب ايشانسي مرتبط بعد.**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif text == "الإحالات 💰":
        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={user_id}"
        await update.message.reply_text(
            f"👥 **نظام الإحالات والربح:**\n\n"
            f"🔗 **رابطك الخاص:**\n`{ref_link}`\n\n"
            f"🎁 قم بدعوة أصدقائك واحصل على **2,000 ل.س** فور تسجيل كل شخص عبر رابطك!",
            parse_mode='Markdown'
        )

    elif text == "كود جائزة 🏆":
        await update.message.reply_text("🎫 **أدخل كود الهدية الخاص بك الآن:**")
        return WAITING_PROMO_CODE

    elif text == "إهداء صديق 🎁":
        await update.message.reply_text("👤 **أدخل أيدي (ID) الصديق الذي تريد تحويل الرصيد إليه:**")
        return WAITING_GIFT_USER

    elif text == "السجلات 🔄":
        await update.message.reply_text("📜 **لا توجد عمليات معلقة أو سجلات حالياً.**")

    elif text == "إرسال رسالة للدعم 💬":
        await update.message.reply_text("💬 للتواصل مع الدعم الفني اراسلنا على: @Support_Admin_Username")

    elif text == "للتسلية 🎲":
        await update.message.reply_text("🎲 قريباً سيتم إضافة ألعاب كازينو وتسلية داخل البوت!")

    elif text == "ايشانسي ↗️":
        await update.message.reply_text("🌐 رابط الموقع الرسمي: https://ichancy.com")

    elif text == "استرداد آخر طلب سحب 💸":
        await update.message.reply_text("⚠️ لا يوجد طلب سحب قيد الإلغاء حالياً.")

    elif text == "العروض النشطة 🎁":
        await update.message.reply_text("🔥 **العروض النشطة:**\n- بونص 100% عند الشحن عن طريق شام كاش!\n- بونص ترحيبي 15,000 ل.س لجميع الأعضاء الجدد.")

    elif text == "شروط الاستخدام ⚠️":
        await update.message.reply_text("📜 **شروط الاستخدام:**\n1. يمنع إنشائ أكثر من حساب لكل شخص.\n2. أي محاولة احتيال تؤدي لحظر الحساب نهائياً.")

    else:
        # الذكاء الاصطناعي للرد على الاستفسارات العامة
        if ai_model:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            try:
                response = ai_model.generate_content(f"أنت مساعد ذكي لبوت خدمات وسحب وشحن. أجب بشكل مختصر ولطيف باللغة العربية: {text}")
                await update.message.reply_text(f"🤖 **الذكاء الاصطناعي:**\n\n{response.text}", parse_mode='Markdown')
            except Exception:
                await update.message.reply_text("🤖 أهلاً بك! يمكنك استخدام أزرار القائمة للتحكم بحسابك.")
        else:
            await update.message.reply_text("🤖 أهلاً بك! استخدم خيارات القائمة للتحكم بالحساب.")

# --- معالجة الكولباك والأزرار التفاعلية ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "back_main":
        await query.message.delete()

    elif data in ["dep_syriatel", "dep_sham_syp", "dep_sham_usd"]:
        await query.edit_message_text("📥 **للشحن عبر هذه الطريقة:**\nقم بتحويل المبلغ للرقم/المحفظة المعتمدة ثم أرسل الإشعار لدعم البوت للتحقق والإيداع.")

    elif data in ["wit_syriatel", "wit_sham_syp", "wit_sham_usd"]:
        await query.edit_message_text("📤 **طلب سحب:**\nأرسل المبلغ المطلوب وسلسلة رقم المحفظة عبر خدمة الدعم للبدء بالمعالجة.")

    elif data == "create_ichancy":
        username = "usr_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET ichancy_username = ?, ichancy_password = ? WHERE user_id = ?", (username, password, user_id))
        conn.commit()
        conn.close()
        await query.edit_message_text(
            f"✅ **تم إنشاء حسابك على iChancy بنجاح!**\n\n"
            f"👤 **اسم المستخدم:** `{username}`\n"
            f"🔑 **كلمة المرور:** `{password}`",
            parse_mode='Markdown'
        )

    elif data == "ich_delete":
        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET ichancy_username = NULL, ichancy_password = NULL WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text("🗑️ تم حذف ربط حساب ايشانسي بنجاح.")

    elif data in ["ich_deposit", "ich_deposit_all", "ich_withdraw"]:
        await query.edit_message_text("⚡ جاري معالجة طلبك عبر الخادم الخاص بـ iChancy...")

# --- كود جائزة (Promo Code) ---
async def process_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code_text = update.message.text.strip()
    user_id = update.effective_user.id

    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT reward, is_used FROM promo_codes WHERE code = ?", (code_text,))
    promo = cursor.fetchone()

    if promo:
        if promo[1] == 1:
            await update.message.reply_text("❌ هذا الكود تم استخدامه من قبل!")
        else:
            reward = promo[0]
            cursor.execute("UPDATE promo_codes SET is_used = 1 WHERE code = ?", (code_text,))
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward, user_id))
            conn.commit()
            await update.message.reply_text(f"🎉 **مبروك!** تم شحن +{reward:,.0f} ل.س إلى حسابك بنجاح! ✨", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ الكود المدخل غير صحيح أو غير موجود.")

    conn.close()
    return ConversationHandler.END

# --- إهداء صديق ---
async def gift_user_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(update.message.text.strip())
        context.user_data['gift_target'] = target_id
        await update.message.reply_text("💵 أدخل المبلغ الذي تريد تحويله لصديقك:")
        return WAITING_GIFT_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ أيدي غير صالح. تم إلغاء العملية.")
        return ConversationHandler.END

async def gift_amount_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
        user_id = update.effective_user.id
        target_id = context.user_data.get('gift_target')

        if amount <= 0:
            await update.message.reply_text("❌ قيمة المبلغ غير صحيحة.")
            return ConversationHandler.END

        conn = sqlite3.connect('ichancy_bot.db')
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        balance = cursor.fetchone()[0]

        if balance < amount:
            await update.message.reply_text("❌ رصيدك غير كافي لإكمال التحويل!")
        else:
            cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
            conn.commit()
            await update.message.reply_text(f"✅ تم تحويل {amount:,.0f} ل.س إلى المستخدم {target_id} بنجاح!")
            try:
                await context.bot.send_message(chat_id=target_id, text=f"🎁 **وصَلك إهداء!**\nقام المستخدم `{user_id}` بتحويل {amount:,.0f} ل.س إلى حسابك!", parse_mode='Markdown')
            except Exception:
                pass

        conn.close()
    except ValueError:
        await update.message.reply_text("❌ مبلغ غير صالح.")
    return ConversationHandler.END

# --- لوحة الأدمن ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    admin_keyboard = [
        [InlineKeyboardButton("➕ منح رصيد", callback_data="adm_add"), InlineKeyboardButton("➖ خصم رصيد", callback_data="adm_sub")],
        [InlineKeyboardButton("🎫 إنشاء كود هدية", callback_data="adm_code")]
    ]
    await update.message.reply_text("⚙️ **لوحة تحكم الأدمن الشاملة:**", reply_markup=InlineKeyboardMarkup(admin_keyboard), parse_mode='Markdown')

# --- تشغيل البوت ---
def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # محادثات الإدخال المتعدد
    promo_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^كود جائزة 🏆$"), lambda u, c: WAITING_PROMO_CODE)],
        states={WAITING_PROMO_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_promo_code)]},
        fallbacks=[]
    )

    gift_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^إهداء صديق 🎁$"), lambda u, c: WAITING_GIFT_USER)],
        states={
            WAITING_GIFT_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_user_step)],
            WAITING_GIFT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_amount_step)]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(promo_handler)
    app.add_handler(gift_handler)
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("⚡ البوت يعمل بكامل الخصائص والميزات...")
    app.run_polling()

if __name__ == '__main__':
    main()

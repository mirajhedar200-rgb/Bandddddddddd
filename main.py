import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from config import TOKEN, ADMIN_IDS, REFERRAL_REWARD
from database import init_db, SessionLocal
from models import User, ForcedChannel
from utils.keep_alive import keep_alive
from utils.keyboards import get_main_menu_keyboard, get_admin_keyboard

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

async def check_forced_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    channels = db.query(ForcedChannel).all()
    db.close()
    
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        return True
        
    not_subscribed = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=ch.channel_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                not_subscribed.append(ch.channel_username)
        except Exception:
            not_subscribed.append(ch.channel_username)
            
    if not_subscribed:
        buttons = [[InlineKeyboardButton(f"اشترك في {ch}", url=f"https://t.me/{ch.replace('@', '')}")] for ch in not_subscribed]
        buttons.append([InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_sub")])
        text = "⚠️ **عذراً، يجب عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:**\n\nيرجى الاشتراك ثم اضغط على زر التحقق أدناه 👇"
        
        if update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_forced_subscription(update, context):
        return
        
    user = update.effective_user
    db = SessionLocal()
    db_user = db.query(User).filter(User.id == user.id).first()
    
    args = context.args
    inviter_id = None
    if args and args[0].isdigit():
        inviter_id = int(args[0])
        
    if not db_user:
        if inviter_id and inviter_id != user.id:
            inviter = db.query(User).filter(User.id == inviter_id).first()
            if inviter:
                inviter.referrals_count += 1
                inviter.balance += REFERRAL_REWARD
                db.commit()
                try:
                    await context.bot.send_message(
                        chat_id=inviter_id,
                        text=f"🎉 **مبروك!** انضم شخص جديد عبر رابط إحالتك.\n➕ تم إضافة المكافأة إلى رصيدك بنجاح.",
                        parse_mode="Markdown"
                    )
                except:
                    pass
                    
        db_user = User(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            invited_by=inviter_id
        )
        db.add(db_user)
        db.commit()
    
    db.close()
    
    welcome_text = (
        f"✨ **أهلاً بك عزيزي {user.first_name} في بوت الإحالات الاحترافي!** 🚀\n\n"
        f"💎 ادعُ أصدقائك عبر رابطك الخاص، اجمع الأرصدة، واحصل على مكافآت فورية.\n\n"
        f"اختر ما ترغب به من الأزرار أدناه 👇"
    )
    
    if update.callback_query:
        await update.callback_query.message.edit_text(welcome_text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text(welcome_text, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    
    db = SessionLocal()
    
    if data == "my_account":
        user = db.query(User).filter(User.id == user_id).first()
        text = (
            f"👤 **معلومات حسابك الشخصي:**\n\n"
            f"🆔 الآيدي: `{user.id}`\n"
            f"🏷️ الاسم: {user.full_name}\n"
            f"💰 الرصيد الحالي: `{user.balance}`\n"
            f"👥 عدد الإحالات: `{user.referrals_count}` شخص\n"
            f"📅 تاريخ الانضمام: {user.joined_at.strftime('%Y-%m-%d %H:%M')}"
        )
        keyboard = [[InlineKeyboardButton("🔙 عودة للقائمة", callback_data="main_menu")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif data == "my_referral":
        bot_username = context.bot.username
        ref_link = f"https://t.me/{bot_username}?start={user_id}"
        text = (
            f"🔗 **رابط الإحالة الخاص بك:**\n\n"
            f"`{ref_link}`\n\n"
            f"انسخ هذا الرابط وشاركه مع أصدقائك لتحصل على مكافآت فورية! 🚀"
        )
        keyboard = [[InlineKeyboardButton("🔙 عودة للقائمة", callback_data="main_menu")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif data == "leaderboard":
        top_users = db.query(User).order_by(User.referrals_count.desc()).limit(10).all()
        text = "🏆 **قائمة أفضل المتصدرين للإحالات:**\n\n"
        for i, u in enumerate(top_users, 1):
            name = u.full_name or "مستخدم"
            text += f"{i}. {name} ⟵ `{u.referrals_count}` إحالة\n"
        keyboard = [[InlineKeyboardButton("🔙 عودة للقائمة", callback_data="main_menu")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif data == "check_sub":
        db.close()
        await start(update, context)
        return
        
    elif data == "main_menu":
        db.close()
        await start(update, context)
        return
        
    elif data == "admin_panel":
        if user_id in ADMIN_IDS:
            keyboard = get_admin_keyboard()
            await query.message.edit_text("🎛️ **أهلاً بك في لوحة تحكم المشرف:**\n\nاختر العملية المطلوبة:", reply_markup=keyboard, parse_mode="Markdown")
        else:
            await query.answer("❌ عذراً، هذه اللوحة للمشرفين فقط!", show_alert=True)
            
    db.close()

if __name__ == '__main__':
    init_db()
    keep_alive()
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("🚀 Bot is up and running smoothly with Self-Ping enabled...")
    app.run_polling()

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 تفاصيل حسامي", callback_data="my_account"),
         InlineKeyboardButton("🔗 رابط الإحالة", callback_data="my_referral")],
        [InlineKeyboardButton("🏆 لوحة المتصدرين", callback_data="leaderboard"),
         InlineKeyboardButton("⚙️ لوحة الأدمن", callback_data="admin_panel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة رصيد", callback_data="admin_add"),
         InlineKeyboardButton("➖ خصم رصيد", callback_data="admin_sub")],
        [InlineKeyboardButton("🔍 بحث عن مستخدم", callback_data="admin_search"),
         InlineKeyboardButton("💰 سعر الإحالة", callback_data="admin_set_reward")],
        [InlineKeyboardButton("📢 إذاعة عامة", callback_data="admin_broadcast"),
         InlineKeyboardButton("📢 الاشتراكات الإجبارية", callback_data="admin_channels")],
        [InlineKeyboardButton("🔙 عودة للقائمة", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

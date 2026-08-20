import sqlite3

def init_db():
    conn = sqlite3.connect('ichancy_bot.db')
    cursor = conn.cursor()
    
    # جدول المستخدمين
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 15000.0,
            referred_by INTEGER,
            ichancy_username TEXT,
            ichancy_password TEXT
        )
    ''')
    
    # جدول الإعدادات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # جدول أكواد الهدايا
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            reward REAL,
            is_used INTEGER DEFAULT 0
        )
    ''')

    # قيم افتراضية
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('welcome_bonus', '15000')")
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('referral_bonus', '2000')")
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('min_withdraw', '5000')")
    cursor.execute("INSERT OR IGNORE INTO settings VALUES ('forced_channel', '')")
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()

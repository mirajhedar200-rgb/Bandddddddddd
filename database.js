const sqlite3 = require('sqlite3').verbose();
const path = require('path');
const dbPath = path.resolve(__dirname, 'bot_database.db');
const db = new sqlite3.Database(dbPath);

db.serialize(() => {
    db.run(`CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 0,
        referral_balance INTEGER DEFAULT 0,
        referred_by INTEGER,
        opened_count INTEGER DEFAULT 0,
        accepted_terms INTEGER DEFAULT 0,
        joined_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )`);
    db.run(`CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)`);
    db.run(`CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, amount INTEGER, status TEXT, details TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )`);
    db.run(`CREATE TABLE IF NOT EXISTS promo_codes (code TEXT PRIMARY KEY, reward INTEGER, uses_left INTEGER)`);
    db.run(`CREATE TABLE IF NOT EXISTS used_codes (user_id INTEGER, code TEXT, PRIMARY KEY (user_id, code))`);
});
module.exports = db;
const { Pool } = require('pg');

// الاتصال بقاعدة بيانات PostgreSQL عبر رابط DATABASE_URL
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: {
    rejectUnauthorized: false // مطلوب للاتصال الآمن على سيرفرات Render
  }
});

// إنشاء الجداول تلقائياً في PostgreSQL في حال عدم وجودها
const initDb = async () => {
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username VARCHAR(255),
        balance INT DEFAULT 0,
        referral_balance INT DEFAULT 0,
        opened_count INT DEFAULT 0,
        referred_by BIGINT,
        accepted_terms INT DEFAULT 0,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );

      CREATE TABLE IF NOT EXISTS settings (
        key VARCHAR(255) PRIMARY KEY,
        value TEXT
      );

      CREATE TABLE IF NOT EXISTS promo_codes (
        code VARCHAR(255) PRIMARY KEY,
        reward INT,
        uses_left INT
      );

      CREATE TABLE IF NOT EXISTS used_codes (
        user_id BIGINT,
        code VARCHAR(255),
        PRIMARY KEY (user_id, code)
      );

      CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        type VARCHAR(50),
        amount INT,
        status VARCHAR(50),
        details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );
    `);
    console.log('✅ PostgreSQL Tables initialized successfully');
  } catch (err) {
    console.error('❌ Error initializing PostgreSQL database:', err);
  }
};

initDb();

module.exports = pool;

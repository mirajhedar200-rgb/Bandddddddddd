const { Pool } = require('pg');

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: {
    rejectUnauthorized: false
  }
});

// إنشاء الجداول في PostgreSQL
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

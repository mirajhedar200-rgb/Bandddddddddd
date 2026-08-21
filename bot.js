require('dotenv').config();
const { Telegraf } = require('telegraf');
const express = require('express');
const pool = require('./database'); // استيراد قاعدة البيانات

// التحقق من وجود التوكن
if (!process.env.BOT_TOKEN) {
    console.error("❌ خطأ: لم يتم العثور على BOT_TOKEN في متغيرات البيئة!");
    process.exit(1);
}

const bot = new Telegraf(process.env.BOT_TOKEN);
const app = express();

// إعداد خادم Express ليظل البوت يعمل على Render
app.get('/', (req, res) => res.send('Bot is running!'));
const PORT = process.env.PORT || 3000;

// هنا يمكنك إضافة الأوامر الخاصة بك (bot.command, bot.on, etc.)
// مثال:
bot.start((ctx) => ctx.reply('مرحباً بك! البوت يعمل الآن.'));

// ----------------------------------------------------
// تشغيل البوت والخادم
// ----------------------------------------------------
app.listen(PORT, () => {
    console.log(`✅ Server is running on port ${PORT}`);
    
    // تشغيل البوت مع التقاط أي خطأ عند التشغيل
    bot.launch()
        .then(() => {
            console.log('✅ Bot started successfully!');
        })
        .catch((err) => {
            console.error('❌ CRITICAL ERROR during bot startup:', err);
            process.exit(1); // إغلاق البوت عند الفشل ليحاول Render إعادة تشغيله
        });
});

// إيقاف البوت عند إنهاء العملية
process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));

const { Telegraf, Markup } = require('telegraf'); 
const express = require('express'); 
const axios = require('axios'); 
const db = require('./database'); // يربط مع قاعدة البيانات الموجودة لديك

const BOT_TOKEN = process.env.BOT_TOKEN || 'YOUR_BOT_TOKEN_HERE'; 
const RENDER_URL = process.env.RENDER_URL || 'https://boooox.onrender.com'; 
const ADMIN_ID = parseInt(process.env.ADMIN_ID) || 123456789; 

const bot = new Telegraf(BOT_TOKEN); 
const app = express(); 

app.use(express.json()); 

const userState = {}; 

// حماية البوت من الانهيار عند حدوث أي أخطاء غير متوقعة
bot.catch((err, ctx) => {
    console.error(`❌ Bot Error for ${ctx.updateType}:`, err);
});

// دالة مرنة للتعامل مع الاستعلامات سواء كانت PostgreSQL أو SQLite
function queryDB(queryText, params = []) {
    return new Promise((resolve, reject) => {
        if (db.query) {
            // PostgreSQL syntax
            let pgQuery = queryText;
            let paramIndex = 1;
            while (pgQuery.includes('?')) {
                pgQuery = pgQuery.replace('?', `$${paramIndex++}`);
            }
            db.query(pgQuery, params, (err, res) => {
                if (err) reject(err);
                else resolve(res.rows);
            });
        } else if (db.all) {
            // SQLite syntax
            db.all(queryText, params, (err, rows) => {
                if (err) reject(err);
                else resolve(rows);
            });
        } else {
            resolve([]);
        }
    });
}

function runDB(queryText, params = []) {
    return new Promise((resolve, reject) => {
        if (db.query) {
            let pgQuery = queryText;
            let paramIndex = 1;
            while (pgQuery.includes('?')) {
                pgQuery = pgQuery.replace('?', `$${paramIndex++}`);
            }
            db.query(pgQuery, params, (err, res) => {
                if (err) reject(err);
                else resolve(res);
            });
        } else if (db.run) {
            db.run(queryText, params, function(err) {
                if (err) reject(err);
                else resolve(this);
            });
        } else {
            resolve(null);
        }
    });
}

// أمان إضافي للتحقق من القناة
async function checkSubscription(ctx, next) { 
    if (ctx.from && ctx.from.id === ADMIN_ID) return next(); 
    try { 
        const rows = await queryDB('SELECT value FROM settings WHERE key = "channel_username"');
        const channelUsername = (rows && rows.length > 0) ? rows[0].value.trim() : (process.env.CHANNEL_USERNAME || '');

        if (!channelUsername || channelUsername === '@YourChannelUsername') return next();

        const member = await ctx.telegram.getChatMember(channelUsername, ctx.from.id); 
        if (['creator', 'administrator', 'member'].includes(member.status)) { 
            return next(); 
        } 
        return ctx.reply(
            `📢 أهلاً بك! يرجى الاشتراك في القناة أولاً لاستخدام البوت:\n${channelUsername}`, 
            Markup.inlineKeyboard([ 
                [Markup.button.url('📢 اشترك بالقناة', `https://t.me/${channelUsername.replace('@','')}`)], 
                [Markup.button.callback('✅ تحقق من الاشتراك', 'verify_sub')] 
            ]) 
        ); 
    } catch (e) { 
        return next(); 
    } 
} 

// معالجة /start وإلغاء التعليق
bot.start(async (ctx) => { 
    const userId = ctx.from.id; 
    delete userState[userId];

    try {
        const users = await queryDB('SELECT * FROM users WHERE user_id = ?', [userId]);
        if (users.length === 0) { 
            const startParam = ctx.payload;
            const referrer = (startParam && parseInt(startParam) !== userId) ? parseInt(startParam) : null; 
            
            await runDB('INSERT INTO users (user_id, username, referred_by) VALUES (?, ?, ?)', [userId, ctx.from.username || '', referrer]);
            
            if (referrer) { 
                await runDB('UPDATE users SET referral_balance = referral_balance + 300 WHERE user_id = ?', [referrer]);
                bot.telegram.sendMessage(referrer, '🎉 قام شخص بالتسجيل عبر رابط إحالتك! تمت إضافة 300 ل.س.').catch(() => {}); 
            } 
            showWelcomeAndTerms(ctx); 
        } else if (!users[0].accepted_terms) { 
            showWelcomeAndTerms(ctx); 
        } else { 
            showMainMenu(ctx); 
        } 
    } catch (err) {
        console.error('Error in /start:', err);
        showMainMenu(ctx);
    }
}); 

function showWelcomeAndTerms(ctx) { 
    ctx.reply(
        `👋 **أهلاً بك في بوت Green Lucky Box 🌿**\n\n📜 **شروط الاستخدام:**\n1. يمنع استخدام أي أساليب غش.\n2. التقيد باللعب العادل.\n\nيرجى الضغط على القبول للمتابعة:`, 
        Markup.inlineKeyboard([ 
            [Markup.button.callback('✅ أوافق على الشروط والأحكام', 'accept_terms')] 
        ]) 
    ); 
} 

bot.action('verify_sub', checkSubscription, (ctx) => { 
    ctx.deleteMessage().catch(() => {}); 
    bot.start(ctx); 
}); 

bot.action('accept_terms', async (ctx) => { 
    await runDB('UPDATE users SET accepted_terms = 1 WHERE user_id = ?', [ctx.from.id]);
    ctx.deleteMessage().catch(() => {}); 
    showMainMenu(ctx); 
}); 

async function showMainMenu(ctx) { 
    const userId = ctx.from.id; 
    const rows = await queryDB('SELECT balance, referral_balance FROM users WHERE user_id = ?', [userId]);
    const balance = (rows && rows.length > 0) ? rows[0].balance : 0; 
    const refBalance = (rows && rows.length > 0) ? rows[0].referral_balance : 0; 
    
    ctx.replyWithHTML( 
        `🌿 <b>أهلاً بك في Green Lucky Box</b>\n\n🆔 <b>معرفك (ID):</b> <code>${userId}</code>\n💰 <b>الرصيد الرئيسي:</b> ${balance.toLocaleString()} ل.س\n👥 <b>رصيد الإحالات:</b> ${refBalance.toLocaleString()} ل.س`, 
        Markup.keyboard([ 
            ['🎁 فتح الصندوق'], 
            ['💳 شحن رصيد', '💸 سحب رصيد'], 
            ['🎁 كود هدية', '👥 الإحالات'], 
            ['📊 السجل', '👤 معلومات حسابي'] 
        ]).resize() 
    ); 
} 

// لوحة تحكم الأدمن
bot.command('admin', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    delete userState[ADMIN_ID];
    ctx.reply('🛠 **لوحة تحكم الأدمن الشاملة:**', Markup.inlineKeyboard([ 
        [Markup.button.callback('➕ إضافة رصيد', 'admin_add_bal'), Markup.button.callback('➖ خصم رصيد', 'admin_sub_bal')], 
        [Markup.button.callback('🔍 سجل مستخدم', 'admin_user_history'), Markup.button.callback('📢 إذاعة عامة', 'admin_broadcast')], 
        [Markup.button.callback('⚙️ تعديل الشحن', 'set_recharge'), Markup.button.callback('⚙️ تعديل السحب', 'set_withdraw')], 
        [Markup.button.callback('➕ إضافة كود هدية', 'add_promo_code'), Markup.button.callback('📢 قناة الاشتراك', 'set_channel')] 
    ])); 
}); 

bot.action('admin_add_bal', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'awaiting_add_bal' }; 
    ctx.reply('➕ أرسل **ID المستخدم + المبلغ** بهذا الشكل:\n`123456789 5000`', { parse_mode: 'Markdown' }); 
}); 

// معالجة استقبال الرسائل وحل مشكلة التوقف
bot.on('text', async (ctx, next) => { 
    const userId = ctx.from.id; 
    const text = ctx.message.text ? ctx.message.text.trim() : '';

    if (text.startsWith('/')) return next();

    const state = userState[userId]; 

    if (userId === ADMIN_ID && state) { 
        if (state.step === 'awaiting_add_bal') { 
            delete userState[ADMIN_ID]; 
            const parts = text.split(/\s+/); 
            const targetId = parseInt(parts[0]); 
            const amount = parseInt(parts[1]); 

            if (!targetId || isNaN(targetId) || isNaN(amount)) {
                return ctx.reply('❌ صيغة خاطئة! أرسل آيدي صحيح ومبلغ.'); 
            }

            try {
                await runDB('UPDATE users SET balance = balance + ? WHERE user_id = ?', [amount, targetId]);
                ctx.reply(`✅ تمت إضافة ${amount.toLocaleString()} ل.س للمستخدم \`${targetId}\`.`, { parse_mode: 'Markdown' }); 
                bot.telegram.sendMessage(targetId, `🎉 تم إيداع ${amount.toLocaleString()} ل.س في حسابك!`).catch(() => {}); 
            } catch (e) {
                ctx.reply('❌ تعذر العثور على المستخدم أو حدث خطأ.');
            }
            return; 
        } 
    } 

    return next();
}); 

// ضبط مسار Webhook لضمان استجابة أسرع وأقوى على منصة Render
app.use(bot.webhookCallback(`/bot${BOT_TOKEN}`));

app.get('/', (req, res) => {
    res.send('Server & Telegram Bot is running perfectly!');
});

const PORT = process.env.PORT || 10000; 

app.listen(PORT, async () => { 
    console.log(`Server listening on port ${PORT}`); 
    try {
        await bot.telegram.setWebhook(`${RENDER_URL}/bot${BOT_TOKEN}`);
        console.log('✅ Webhook attached successfully to Render!');
    } catch (e) {
        console.error('❌ Webhook error:', e.message);
    }
});

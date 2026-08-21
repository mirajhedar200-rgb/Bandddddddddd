const { Telegraf, Markup } = require('telegraf'); 
const express = require('express'); 
const axios = require('axios'); 
const db = require('./database'); 

const BOT_TOKEN = process.env.BOT_TOKEN || 'YOUR_BOT_TOKEN_HERE'; 
const RENDER_URL = process.env.RENDER_URL || 'https://boooox.onrender.com'; 
const ADMIN_ID = parseInt(process.env.ADMIN_ID) || 123456789; 

const bot = new Telegraf(BOT_TOKEN); 
const app = express(); 

app.use(express.json()); 

const userState = {}; 

bot.catch((err, ctx) => {
    console.error(`❌ Bot Error:`, err);
});

// دالة مرنة تتوافق مع PostgreSQL و SQLite
function queryDB(queryText, params = []) {
    return new Promise((resolve, reject) => {
        if (db.query) {
            let pgQuery = queryText;
            let paramIndex = 1;
            while (pgQuery.includes('?')) {
                pgQuery = pgQuery.replace('?', `$${paramIndex++}`);
            }
            db.query(pgQuery, params, (err, res) => {
                if (err) reject(err);
                else resolve(res ? res.rows : []);
            });
        } else if (db.all) {
            db.all(queryText, params, (err, rows) => {
                if (err) reject(err);
                else resolve(rows || []);
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

// الاشتراك الإجباري
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

bot.start(async (ctx) => { 
    const userId = ctx.from.id; 
    delete userState[userId];

    try {
        const users = await queryDB('SELECT * FROM users WHERE user_id = ?', [userId]);
        if (!users || users.length === 0) { 
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

// ==================== لوحة تحكم الأدمن المصححة بالكامل ====================

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

// إجراءات أزرار الأدمن
bot.action('admin_add_bal', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'awaiting_add_bal' }; 
    ctx.reply('➕ أرسل **ID المستخدم + المبلغ** بهذا الشكل:\n`123456789 5000`', { parse_mode: 'Markdown' }); 
}); 

bot.action('admin_sub_bal', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'awaiting_sub_bal' }; 
    ctx.reply('➖ أرسل **ID المستخدم + المبلغ المراد خصمه** بهذا الشكل:\n`123456789 2000`', { parse_mode: 'Markdown' }); 
}); 

bot.action('admin_user_history', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'awaiting_user_id_history' }; 
    ctx.reply('🔍 أرسل **ID المستخدم** للبحث عن سجله ورصيده:'); 
}); 

bot.action('admin_broadcast', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'awaiting_broadcast_msg' }; 
    ctx.reply('📢 أرسل الرسالة التي تريد إذاعتها لجميع المشتركين:'); 
}); 

bot.action('set_recharge', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'awaiting_set_recharge' }; 
    ctx.reply('⚙️ أرسل التعليمات أو رقم سيريتل كاش الجديد المخصص للشحن:'); 
}); 

bot.action('set_withdraw', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'awaiting_set_withdraw' }; 
    ctx.reply('⚙️ أرسل التعليمات والشروط الجديدة المخصصة لسحب الأرباح:'); 
}); 

bot.action('add_promo_code', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'awaiting_add_promo' }; 
    ctx.reply('➕ أرسل **الكود + قيمة المكافأة + عدد الاستخدامات** بهذا الشكل:\n`GIFT100 5000 10`', { parse_mode: 'Markdown' }); 
}); 

bot.action('set_channel', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'awaiting_set_channel' }; 
    ctx.reply('📢 أرسل معرف القناة الجديدة مع الـ `@`:\nمثال: `@MyNewChannel`'); 
}); 

// معالجة كافة المدخلات والرسائل النصية للأدمن وللمستخدمين
bot.on('text', async (ctx, next) => { 
    const userId = ctx.from.id; 
    const text = ctx.message.text ? ctx.message.text.trim() : '';

    if (text.startsWith('/')) return next();

    const state = userState[userId]; 

    if (userId === ADMIN_ID && state) { 
        if (state.step === 'awaiting_set_channel') {
            delete userState[ADMIN_ID]; 
            if (!text.startsWith('@')) return ctx.reply('❌ اكتب المعرف مع الـ `@`.');
            await runDB('INSERT INTO settings (key, value) VALUES ("channel_username", ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', [text]);
            return ctx.reply(`✅ تم تحديث قناة الاشتراك الإجباري إلى: ${text}`); 

        } else if (state.step === 'awaiting_set_recharge') { 
            delete userState[ADMIN_ID]; 
            await runDB('INSERT INTO settings (key, value) VALUES ("syriatel_info", ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', [text]);
            return ctx.reply('✅ تم تحديث معلومات الشحن بنجاح!'); 

        } else if (state.step === 'awaiting_set_withdraw') { 
            delete userState[ADMIN_ID]; 
            await runDB('INSERT INTO settings (key, value) VALUES ("withdraw_info", ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', [text]);
            return ctx.reply('✅ تم تحديث معلومات السحب بنجاح!'); 

        } else if (state.step === 'awaiting_add_promo') { 
            delete userState[ADMIN_ID]; 
            const parts = text.split(/\s+/); 
            const code = parts[0]; 
            const reward = parseInt(parts[1]); 
            const uses = parseInt(parts[2]); 
            if (!code || isNaN(reward) || isNaN(uses)) { 
                return ctx.reply('❌ صيغة خاطئة! أرسل: الكود المبلغ الاستخدامات\nمثال: `FREE2026 5000 10`', { parse_mode: 'Markdown' }); 
            } 
            try {
                await runDB('INSERT INTO promo_codes (code, reward, uses_left) VALUES (?, ?, ?)', [code, reward, uses]);
                return ctx.reply(`✅ تم إنشاء الكود \`${code}\` بنجاح!`, { parse_mode: 'Markdown' }); 
            } catch (err) {
                return ctx.reply('❌ الكود موجود مسبقاً أو حدث خطأ.');
            }

        } else if (state.step === 'awaiting_add_bal') { 
            delete userState[ADMIN_ID]; 
            const parts = text.split(/\s+/); 
            const targetId = parseInt(parts[0]); 
            const amount = parseInt(parts[1]); 

            if (!targetId || isNaN(targetId) || isNaN(amount)) {
                return ctx.reply('❌ صيغة خاطئة! أرسل الآيدي والمبلغ.'); 
            }

            try {
                await runDB('UPDATE users SET balance = balance + ? WHERE user_id = ?', [amount, targetId]);
                ctx.reply(`✅ تمت إضافة ${amount.toLocaleString()} ل.س للمستخدم \`${targetId}\`.`, { parse_mode: 'Markdown' }); 
                bot.telegram.sendMessage(targetId, `🎉 تم إيداع ${amount.toLocaleString()} ل.س في حسابك!`).catch(() => {}); 
            } catch (e) {
                ctx.reply('❌ تعذر تعديل الرصيد.');
            }
            return; 

        } else if (state.step === 'awaiting_sub_bal') { 
            delete userState[ADMIN_ID]; 
            const parts = text.split(/\s+/); 
            const targetId = parseInt(parts[0]); 
            const amount = parseInt(parts[1]); 

            if (!targetId || isNaN(targetId) || isNaN(amount)) {
                return ctx.reply('❌ صيغة خاطئة! أرسل الآيدي والمبلغ المراد خصمه.'); 
            }

            try {
                await runDB('UPDATE users SET balance = balance - ? WHERE user_id = ?', [amount, targetId]);
                ctx.reply(`✅ تم خصم ${amount.toLocaleString()} ل.س من المستخدم \`${targetId}\`.`, { parse_mode: 'Markdown' }); 
                bot.telegram.sendMessage(targetId, `⚠️ تم خصم ${amount.toLocaleString()} ل.س من حسابك!`).catch(() => {}); 
            } catch (e) {
                ctx.reply('❌ تعذر خصم الرصيد.');
            }
            return; 

        } else if (state.step === 'awaiting_user_id_history') { 
            delete userState[ADMIN_ID]; 
            const targetId = parseInt(text); 
            if (isNaN(targetId)) return ctx.reply('❌ أرسل آيدي صحيح.');
            
            const users = await queryDB('SELECT * FROM users WHERE user_id = ?', [targetId]);
            if (!users || users.length === 0) return ctx.reply('❌ المستخدم غير موجود.'); 
            
            const u = users[0];
            return ctx.reply(`👤 **معلومات المستخدم:**\n\n🆔 الآيدي: \`${u.user_id}\`\n💰 الرصيد الرئيسي: ${u.balance.toLocaleString()} ل.س\n👥 رصيد الإحالات: ${u.referral_balance.toLocaleString()} ل.س\n📦 الصناديق المفتوحة: ${u.opened_count}`, { parse_mode: 'Markdown' }); 

        } else if (state.step === 'awaiting_broadcast_msg') { 
            delete userState[ADMIN_ID]; 
            ctx.reply('⏳ جاري إرسال الإذاعة لجميع المشتركين...'); 
            const users = await queryDB('SELECT user_id FROM users');
            let count = 0;
            for (const u of users) {
                try {
                    await bot.telegram.sendMessage(u.user_id, text);
                    count++;
                } catch (e) {}
            }
            return ctx.reply(`✅ تمت الإذاعة بنجاح واستلمها ${count} مستخدم!`); 
        } 
    } 

    return next();
}); 

// مسار الـ Webhook الخاص بالسيرفر
app.use(bot.webhookCallback(`/bot${BOT_TOKEN}`));

app.get('/', (req, res) => {
    res.send('Bot is live and working!');
});

const PORT = process.env.PORT || 10000; 

app.listen(PORT, async () => { 
    console.log(`Server listening on port ${PORT}`); 
    try {
        await bot.telegram.setWebhook(`${RENDER_URL}/bot${BOT_TOKEN}`);
        console.log('✅ Webhook attached!');
    } catch (e) {
        console.error('❌ Webhook error:', e.message);
    }
});

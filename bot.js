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

// دوال قاعدة البيانات
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

// تهيئة جدول الإعدادات تلقائياً
async function initTables() {
    try {
        await runDB(`CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)`);
        console.log('✅ Settings table ready.');
    } catch (e) {
        console.log('Settings table error:', e.message);
    }
}
initTables();

// التحقق من الاشتراك
async function checkSubscription(ctx, next) { 
    if (ctx.from && ctx.from.id === ADMIN_ID) return next(); 
    try { 
        const rows = await queryDB('SELECT value FROM settings WHERE key = ?', ['channel_username']);
        const channelUsername = (rows && rows.length > 0) ? rows[0].value.trim() : '';

        if (!channelUsername) return next();

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
    delete userState[userId];
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

// ==================== أزرار المستخدمين ====================

// زر فتح الصندوق
bot.hears('🎁 فتح الصندوق', checkSubscription, async (ctx) => {
    const userId = ctx.from.id;
    try {
        const rows = await queryDB('SELECT balance FROM users WHERE user_id = ?', [userId]);
        const balance = (rows && rows.length > 0) ? rows[0].balance : 0;
        
        // يمكنك تعديل تكلفة فتح الصندوق أو الجائزة حسب رغبتك هنا
        const prize = Math.floor(Math.random() * 500) + 100; // جائزة عشوائية تجريبية
        await runDB('UPDATE users SET balance = balance + ?, opened_count = opened_count + 1 WHERE user_id = ?', [prize, userId]);
        
        ctx.reply(`🎁 **مبروك! لقد فتحت الصندوق بنجاح**\n🎉 ربحت جائزة قيمتها: **${prize.toLocaleString()} ل.س**`);
    } catch (e) {
        ctx.reply('❌ حدث خطأ أثناء فتح الصندوق، حاول مرة أخرى.');
    }
});

bot.hears('💳 شحن رصيد', checkSubscription, async (ctx) => { 
    userState[ctx.from.id] = { step: 'user_req_recharge' }; 
    const rows = await queryDB('SELECT value FROM settings WHERE key = ?', ['syriatel_info']);
    const info = (rows && rows.length > 0 && rows[0].value) 
        ? rows[0].value 
        : 'طريقة الشحن المتوفرة: سيريتل كاش.\nيرجى التحويل ثم كتابة التفاصيل.';

    ctx.reply(`💳 **قسم شحن الرصيد**\n\n📌 **تعليمات ومعلومات الشحن:**\n${info}\n\n👇 **يرجى إرسال (المبلغ + رقم عملية التحويل) الآن في رسالة واحدة:**`); 
}); 

bot.hears('💸 سحب رصيد', checkSubscription, async (ctx) => { 
    userState[ctx.from.id] = { step: 'user_req_withdraw' }; 
    const rows = await queryDB('SELECT value FROM settings WHERE key = ?', ['withdraw_info']);
    const info = (rows && rows.length > 0 && rows[0].value) 
        ? rows[0].value 
        : 'الحد الأدنى للسحب من البوت 40000 ل.س.';

    ctx.reply(`💸 **قسم سحب الأرباح**\n\n📌 **تعليمات ومعلومات السحب:**\n${info}\n\n👇 **أرسل المبلغ المراد سحبه مع عنوان استقبال أرباحك الآن:**`); 
}); 

bot.hears('🎁 كود هدية', checkSubscription, (ctx) => { 
    userState[ctx.from.id] = { step: 'awaiting_promo' }; 
    ctx.reply('🎁 أدخل كود الهدية الذي حصلت عليه:'); 
}); 

bot.hears('👥 الإحالات', checkSubscription, async (ctx) => { 
    const userId = ctx.from.id; 
    const link = `https://t.me/${ctx.botInfo.username}?start=${userId}`; 
    const rows = await queryDB('SELECT referral_balance FROM users WHERE user_id = ?', [userId]);
    const refBalance = (rows && rows.length > 0) ? rows[0].referral_balance : 0;

    ctx.reply(`👥 **نظام الإحالات**\n\n🔗 **رابط الإحالة الخاص بك:**\n\`${link}\` \n\n💰 **رصيد الإحالات الحالي:** ${refBalance.toLocaleString()} ل.س`, { parse_mode: 'Markdown' }); 
}); 

bot.hears('📊 السجل', checkSubscription, async (ctx) => { 
    const rows = await queryDB('SELECT type, amount, status FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 5', [ctx.from.id]);
    if (!rows || rows.length === 0) return ctx.reply('📊 لا يوجد لديك عمليات شحن أو سحب سابقة.'); 
    
    let text = '📊 **سجل عملياتك الأخيرة:**\n\n'; 
    rows.forEach((r, i) => { 
        const typeText = r.type === 'recharge' ? '💳 شحن' : '💸 سحب'; 
        text += `${i + 1}. ${typeText} - ${(r.amount || 0).toLocaleString()} ل.س (${r.status})\n`; 
    }); 
    ctx.reply(text); 
}); 

bot.hears('👤 معلومات حسابي', checkSubscription, async (ctx) => { 
    const rows = await queryDB('SELECT balance, referral_balance, opened_count FROM users WHERE user_id = ?', [ctx.from.id]);
    if (!rows || rows.length === 0) return; 
    const u = rows[0];
    ctx.replyWithHTML(`👤 <b>معلومات حسابك:</b>\n💰 الرصيد: ${(u.balance || 0).toLocaleString()} ل.س\n👥 الإحالات: ${(u.referral_balance || 0).toLocaleString()} ل.س\n🎁 الصناديق المفتوحة: ${u.opened_count || 0}`); 
}); 

// ==================== لوحة تحكم الأدمن ====================

bot.command('admin', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    delete userState[ADMIN_ID];
    ctx.reply('🛠 **لوحة تحكم الأدمن:**', Markup.inlineKeyboard([ 
        [Markup.button.callback('⚙️ تعديل الشحن', 'set_recharge'), Markup.button.callback('⚙️ تعديل السحب', 'set_withdraw')], 
        [Markup.button.callback('📢 قناة الاشتراك', 'set_channel')] 
    ])); 
}); 

bot.action('set_recharge', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'admin_set_recharge' }; 
    ctx.reply('⚙️ أرسل الآن النص أو التعليمات الجديدة الخاصة بـ **قسم الشحن** ليتم حفظها مباشرة:'); 
}); 

bot.action('set_withdraw', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'admin_set_withdraw' }; 
    ctx.reply('⚙️ أرسل الآن النص أو التعليمات الجديدة الخاصة بـ **قسم السحب** ليتم حفظها مباشرة:'); 
}); 

bot.action('set_channel', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    userState[ADMIN_ID] = { step: 'admin_set_channel' }; 
    ctx.reply('📢 أرسل معرف القناة الجديدة مع `@`:'); 
}); 

// ==================== معالجة النصوص المركزية ====================

bot.on('text', async (ctx, next) => { 
    const userId = ctx.from.id; 
    const text = ctx.message.text ? ctx.message.text.trim() : '';

    if (text.startsWith('/')) return next();

    const state = userState[userId]; 
    if (!state) return next();

    // 1. معالجة تحديث الأدمن للشحن والسحب
    if (userId === ADMIN_ID) {
        if (state.step === 'admin_set_recharge') {
            delete userState[ADMIN_ID];
            await runDB("INSERT INTO settings (key, value) VALUES ('syriatel_info', ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", [text]);
            return ctx.reply('✅ تم تحديث تعليمات الشحن وحفظها في قاعدة البيانات بنجاح!');
        }
        if (state.step === 'admin_set_withdraw') {
            delete userState[ADMIN_ID];
            await runDB("INSERT INTO settings (key, value) VALUES ('withdraw_info', ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", [text]);
            return ctx.reply('✅ تم تحديث تعليمات السحب وحفظها في قاعدة البيانات بنجاح!');
        }
        if (state.step === 'admin_set_channel') {
            delete userState[ADMIN_ID];
            await runDB("INSERT INTO settings (key, value) VALUES ('channel_username', ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", [text]);
            return ctx.reply(`✅ تم تحديث قناة الاشتراك إلى: ${text}`);
        }
    }

    // 2. معالجة طلبات المستخدمين (شحن، سحب، كود)
    if (state.step === 'user_req_recharge') { 
        delete userState[userId]; 
        await runDB("INSERT INTO transactions (user_id, type, amount, status, details) VALUES (?, 'recharge', 0, 'pending', ?)", [userId, text]); 
        ctx.reply('✅ تم إرسال طلب الشحن للإدارة بنجاح.'); 
        bot.telegram.sendMessage(ADMIN_ID, `📩 **طلب شحن جديد!**\n👤 من: \`${userId}\`\n📝 التفاصيل: ${text}`, { parse_mode: 'Markdown' }).catch(() => {}); 
        return;
    } 

    if (state.step === 'user_req_withdraw') { 
        delete userState[userId]; 
        await runDB("INSERT INTO transactions (user_id, type, amount, status, details) VALUES (?, 'withdraw', 0, 'pending', ?)", [userId, text]); 
        ctx.reply('✅ تم إرسال طلب السحب للإدارة بنجاح.'); 
        bot.telegram.sendMessage(ADMIN_ID, `💸 **طلب سحب جديد!**\n👤 من: \`${userId}\`\n📝 التفاصيل: ${text}`, { parse_mode: 'Markdown' }).catch(() => {}); 
        return;
    } 

    if (state.step === 'awaiting_promo') { 
        delete userState[userId]; 
        const codes = await queryDB('SELECT reward, uses_left FROM promo_codes WHERE code = ?', [text]); 
        if (!codes || codes.length === 0 || codes[0].uses_left <= 0) {
            return ctx.reply('❌ الكود غير صحيح أو منتهي الصلاحية.'); 
        }
        await runDB('UPDATE users SET balance = balance + ? WHERE user_id = ?', [codes[0].reward, userId]); 
        await runDB('UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?', [text]); 
        ctx.reply(`🎉 مبروك! تمت إضافة ${codes[0].reward.toLocaleString()} ل.س لرصيدك.`); 
        return;
    }

    return next();
}); 

app.use(bot.webhookCallback(`/bot${BOT_TOKEN}`));

const PORT = process.env.PORT || 10000; 
app.listen(PORT, async () => { 
    console.log(`Server listening on port ${PORT}`); 
    try {
        await bot.telegram.setWebhook(`${RENDER_URL}/bot${BOT_TOKEN}`);
        console.log('✅ Webhook attached!');
    } catch (e) {
        console.error('Webhook error:', e.message);
    }
});

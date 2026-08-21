const { Telegraf, Markup } = require('telegraf'); 
const express = require('express'); 
const axios = require('axios'); 
const db = require('./database'); 

const BOT_TOKEN = process.env.BOT_TOKEN || 'YOUR_BOT_TOKEN_HERE'; 
const RENDER_URL = process.env.RENDER_URL || 'https://your-app-name.onrender.com'; 
const ADMIN_ID = parseInt(process.env.ADMIN_ID) || 123456789; 

const bot = new Telegraf(BOT_TOKEN); 
const app = express(); 

app.use(express.json()); 

const userState = {}; 

// معالجة الأخطاء العامة للبوت حتى لا ينهار السيرفر أبداً عند حدوث خطأ
bot.catch((err, ctx) => {
    console.error(`❌ Bot Error:`, err);
});

function calculatePrize(openedCount) { 
    if (openedCount === 18) return 10000; 
    if (openedCount === 20) return 15000; 
    const cycleIndex = ((openedCount - 1) % 10) + 1; 
    switch(cycleIndex) { 
        case 1: return 5000; 
        case 2: return 4000; 
        case 5: return 3000; 
        case 8: return 5000; 
        default: return 0; 
    } 
} 

function getRequiredChannel() {
    return new Promise((resolve) => {
        db.get('SELECT value FROM settings WHERE key = "channel_username"', (err, row) => {
            if (row && row.value) {
                resolve(row.value.trim());
            } else {
                resolve(process.env.CHANNEL_USERNAME || '');
            }
        });
    });
}

async function checkSubscription(ctx, next) { 
    if (ctx.from && ctx.from.id === ADMIN_ID) return next(); 
    try { 
        const channelUsername = await getRequiredChannel();
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

// أمر Start وتصفير حالة الحساب المعلقة
bot.start(async (ctx) => { 
    const userId = ctx.from.id; 
    delete userState[userId]; // مسح أي أصل معلق لحل مشكلة التوقف

    const startParam = ctx.payload; 
    db.get('SELECT * FROM users WHERE user_id = ?', [userId], (err, user) => { 
        if (!user) { 
            const referrer = (startParam && parseInt(startParam) !== userId) ? parseInt(startParam) : null; 
            db.run('INSERT INTO users (user_id, username, referred_by) VALUES (?, ?, ?)', [userId, ctx.from.username || '', referrer], () => { 
                if (referrer) { 
                    db.run('UPDATE users SET referral_balance = referral_balance + 300 WHERE user_id = ?', [referrer]); 
                    bot.telegram.sendMessage(referrer, '🎉 قام شخص بالتسجيل عبر رابط إحالتك! تمت إضافة 300 ل.س لرصيد الإحالات الخاص بك.').catch(() => {}); 
                } 
                showWelcomeAndTerms(ctx); 
            }); 
        } else if (!user.accepted_terms) { 
            showWelcomeAndTerms(ctx); 
        } else { 
            showMainMenu(ctx); 
        } 
    }); 
}); 

function showWelcomeAndTerms(ctx) { 
    ctx.reply(
        `👋 **أهلاً بك في بوت Green Lucky Box 🌿**\n\n📜 **شروط الاستخدام:**\n1. يمنع استخدام أي أساليب غش أو ثغرات.\n2. التقيد باللعب العادل.\n\nيرجى الضغط على القبول للمتابعة:`, 
        Markup.inlineKeyboard([ 
            [Markup.button.callback('✅ أوافق على الشروط والأحكام', 'accept_terms')] 
        ]) 
    ); 
} 

bot.action('verify_sub', checkSubscription, (ctx) => { 
    ctx.deleteMessage().catch(() => {}); 
    bot.start(ctx); 
}); 

bot.action('accept_terms', (ctx) => { 
    db.run('UPDATE users SET accepted_terms = 1 WHERE user_id = ?', [ctx.from.id], () => { 
        ctx.deleteMessage().catch(() => {}); 
        showMainMenu(ctx); 
    }); 
}); 

function showMainMenu(ctx) { 
    const userId = ctx.from.id; 
    db.get('SELECT balance, referral_balance FROM users WHERE user_id = ?', [userId], (err, row) => { 
        const balance = row ? row.balance : 0; 
        const refBalance = row ? row.referral_balance : 0; 
        ctx.replyWithHTML( 
            `🌿 <b>أهلاً بك في Green Lucky Box</b>\n\n🆔 <b>معرفك (ID):</b> <code>${userId}</code>\n💰 <b>الرصيد الرئيسي:</b> ${balance.toLocaleString()} ل.س\n👥 <b>رصيد الإحالات:</b> ${refBalance.toLocaleString()} ل.س`, 
            Markup.keyboard([ 
                ['🎁 فتح الصندوق'], 
                ['💳 شحن رصيد', '💸 سحب رصيد'], 
                ['🎁 كود هدية', '👥 الإحالات'], 
                ['📊 السجل', '👤 معلومات حسابي'] 
            ]).resize() 
        ); 
    }); 
} 

bot.hears('🎁 فتح الصندوق', checkSubscription, (ctx) => { 
    const userId = ctx.from.id; 
    db.get('SELECT balance FROM users WHERE user_id = ?', [userId], (err, row) => { 
        if (!row || row.balance < 2000) { 
            return ctx.reply('⚠️ رصيدك غير كافٍ! سعر فتح الصندوق 2000 ل.س. اشحن حسابك لتستمتع باللعب.'); 
        } 
        const webAppUrl = `${RENDER_URL}?user_id=${userId}`; 
        ctx.reply('🎁 سعر الصندوق 2000 ل.س قديمة. هل تريد الشراء والفتح؟', Markup.inlineKeyboard([ 
            [Markup.button.webApp('📦 افتح الصندوق الآن', webAppUrl)], 
            [Markup.button.callback('❌ إلغاء', 'cancel_act')] 
        ]) ); 
    }); 
}); 

bot.action('cancel_act', (ctx) => ctx.deleteMessage().catch(() => {})); 

app.post('/api/open-box', (req, res) => { 
    const userId = req.body.user_id; 
    if (!userId) return res.json({ success: false, message: 'بيانات مستخدم غير صالحة' }); 
    db.get('SELECT balance, opened_count FROM users WHERE user_id = ?', [userId], (err, user) => { 
        if (!user || user.balance < 2000) { 
            return res.json({ success: false, message: 'رصيدك غير كافٍ! اشحن لتفتح' }); 
        } 
        const newCount = user.opened_count + 1; 
        const prize = calculatePrize(newCount); 
        const newBalance = user.balance - 2000 + prize; 
        db.run('UPDATE users SET balance = ?, opened_count = ? WHERE user_id = ?', [newBalance, newCount, userId], (err) => { 
            if (err) return res.json({ success: false, message: 'حدث خطأ في السيرفر' }); 
            res.json({ success: true, prize: prize, newBalance: newBalance }); 
        }); 
    }); 
}); 

bot.hears('💳 شحن رصيد', checkSubscription, (ctx) => { 
    userState[ctx.from.id] = { step: 'awaiting_recharge' }; 
    db.get('SELECT value FROM settings WHERE key = "syriatel_info"', (err, row) => { 
        const info = row ? row.value : 'يرجى التحويل لسيريتل كاش على الرقم المعين من الإدارة.'; 
        ctx.reply(`💳 **شحن الرصيد بواسطة سيريتل كاش**\n\n📌 **معلومات الشحن:**\n${info}\n\nيرجى إرسال **المبلغ + رقم العملية** في رسالة واحدة:`); 
    }); 
}); 

bot.hears('💸 سحب رصيد', checkSubscription, (ctx) => { 
    userState[ctx.from.id] = { step: 'awaiting_withdraw' }; 
    db.get('SELECT value FROM settings WHERE key = "withdraw_info"', (err, row) => { 
        const info = row ? row.value : 'ادخل عنوان استلام الأرباح والمبلغ المراد سحبه.'; 
        ctx.reply(`💸 **سحب الأرباح**\n\n📌 **معلومات السحب:**\n${info}\n\nيرجى إرسال **عنوان الاستلام + المبلغ**:`); 
    }); 
}); 

bot.hears('🎁 كود هدية', checkSubscription, (ctx) => { 
    userState[ctx.from.id] = { step: 'awaiting_promo' }; 
    ctx.reply('🎁 أدخل كود الهدية الذي حصلت عليه:'); 
}); 

bot.hears('👥 الإحالات', checkSubscription, (ctx) => { 
    const userId = ctx.from.id; 
    const link = `https://t.me/${ctx.botInfo.username}?start=${userId}`; 
    db.get('SELECT referral_balance FROM users WHERE user_id = ?', [userId], (err, row) => { 
        const refBalance = row ? row.referral_balance : 0; 
        ctx.reply(`👥 **نظام الإحالات**\n\n🔗 **رابط الإحالة الخاص بك:**\n\`${link}\` \n\n💰 **رصيد الإحالات الحالي:** ${refBalance.toLocaleString()} ل.س\n\n*(ملاحظة: تحصل على 300 ل.س لكل صديق يدخل عبر رابطك).*`, { parse_mode: 'Markdown' }); 
    }); 
}); 

bot.hears('📊 السجل', checkSubscription, (ctx) => { 
    db.all('SELECT type, amount, status, created_at FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 5', [ctx.from.id], (err, rows) => { 
        if (!rows || rows.length === 0) return ctx.reply('📊 لا يوجد لديك عمليات شحن أو سحب سابقة.'); 
        let text = '📊 **سجل عملياتك الأخيرة:**\n\n'; 
        rows.forEach((r, i) => { 
            const typeText = r.type === 'recharge' ? '💳 شحن' : '💸 سحب'; 
            text += `${i + 1}. ${typeText} - ${r.amount.toLocaleString()} ل.س (${r.status})\n📅 ${r.created_at}\n\n`; 
        }); 
        ctx.reply(text); 
    }); 
}); 

bot.hears('👤 معلومات حسابي', checkSubscription, (ctx) => { 
    db.get('SELECT balance, referral_balance, opened_count, joined_at FROM users WHERE user_id = ?', [ctx.from.id], (err, row) => { 
        if (!row) return; 
        ctx.replyWithHTML( 
            `👤 <b>معلومات حسابك الشخصي:</b>\n\n` + 
            `🆔 <b>ID:</b> <code>${ctx.from.id}</code>\n` + 
            `💰 <b>الرصيد الرئيسي:</b> ${row.balance.toLocaleString()} ل.س\n` + 
            `👥 <b>رصيد الإحالات:</b> ${row.referral_balance.toLocaleString()} ل.س\n` + 
            `📦 <b>عدد مرات فتح الصندوق:</b> ${row.opened_count} مرة\n` + 
            `📅 <b>تاريخ الانضمام:</b> ${row.joined_at}` 
        ); 
    }); 
}); 

// --- لوحة تحكم الأدمن --- 
bot.command('admin', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
    delete userState[ADMIN_ID]; // تصفير الحالة السابقة عند فتح اللوحة
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

// معالج النصوص مع حماية من الأخطاء العشوائية
bot.on('text', async (ctx, next) => { 
    const userId = ctx.from.id; 
    const text = ctx.message.text ? ctx.message.text.trim() : '';

    if (text.startsWith('/')) return next();

    const state = userState[userId]; 

    if (userId === ADMIN_ID && state) { 
        if (state.step === 'awaiting_set_channel') {
            delete userState[ADMIN_ID]; 
            if (!text.startsWith('@')) return ctx.reply('❌ اكتب المعرف مع الـ `@`.');
            db.run('INSERT OR REPLACE INTO settings (key, value) VALUES ("channel_username", ?)', [text], () => { 
                ctx.reply(`✅ تم تحديث القناة إلى: ${text}`); 
            }); 
            return;
        } else if (state.step === 'awaiting_set_recharge') { 
            delete userState[ADMIN_ID]; 
            db.run('INSERT OR REPLACE INTO settings (key, value) VALUES ("syriatel_info", ?)', [text], () => { 
                ctx.reply('✅ تم تحديث تعليمات الشحن!'); 
            }); 
            return; 
        } else if (state.step === 'awaiting_set_withdraw') { 
            delete userState[ADMIN_ID]; 
            db.run('INSERT OR REPLACE INTO settings (key, value) VALUES ("withdraw_info", ?)', [text], () => { 
                ctx.reply('✅ تم تحديث تعليمات السحب!'); 
            }); 
            return; 
        } else if (state.step === 'awaiting_add_promo') { 
            delete userState[ADMIN_ID]; 
            const parts = text.split(/\s+/); 
            const code = parts[0]; 
            const reward = parseInt(parts[1]); 
            const uses = parseInt(parts[2]); 
            if (!code || isNaN(reward) || isNaN(uses)) { 
                return ctx.reply('❌ صيغة خاطئة! أرسل: الكود المبلغ الاستخدامات'); 
            } 
            db.run('INSERT INTO promo_codes (code, reward, uses_left) VALUES (?, ?, ?)', [code, reward, uses], (err) => { 
                if (err) return ctx.reply('❌ الكود موجود مسبقاً.'); 
                ctx.reply(`✅ تم إنشاء الكود \`${code}\` بنجاح!`, { parse_mode: 'Markdown' }); 
            }); 
            return; 
        } else if (state.step === 'awaiting_add_bal') { 
            delete userState[ADMIN_ID]; 
            const parts = text.split(/\s+/); 
            const targetId = parseInt(parts[0]); 
            const amount = parseInt(parts[1]); 

            if (!targetId || isNaN(targetId) || isNaN(amount)) {
                return ctx.reply('❌ صيغة خاطئة! أرسل الآيدي والمبلغ الحقيقي المستهدف.'); 
            }

            db.run('UPDATE users SET balance = balance + ? WHERE user_id = ?', [amount, targetId], function(err) { 
                if (err || this.changes === 0) return ctx.reply('❌ هذا المستخدم غير موجود بقاعدة البيانات!'); 
                ctx.reply(`✅ تمت إضافة ${amount.toLocaleString()} ل.س للمستخدم \`${targetId}\`.`, { parse_mode: 'Markdown' }); 
                bot.telegram.sendMessage(targetId, `🎉 تم إيداع ${amount.toLocaleString()} ل.س في حسابك!`).catch(() => {}); 
            }); 
            return; 
        } else if (state.step === 'awaiting_sub_bal') { 
            delete userState[ADMIN_ID]; 
            const parts = text.split(/\s+/); 
            const targetId = parseInt(parts[0]); 
            const amount = parseInt(parts[1]); 

            if (!targetId || isNaN(targetId) || isNaN(amount)) {
                return ctx.reply('❌ صيغة خاطئة! أرسل الآيدي والمبلغ الحقيقي.'); 
            }

            db.run('UPDATE users SET balance = balance - ? WHERE user_id = ?', [amount, targetId], function(err) { 
                if (err || this.changes === 0) return ctx.reply('❌ المستخدم غير موجود بقاعدة البيانات!'); 
                ctx.reply(`✅ تم خصم ${amount.toLocaleString()} ل.س من المستخدم \`${targetId}\`.`, { parse_mode: 'Markdown' }); 
                bot.telegram.sendMessage(targetId, `⚠️ تم خصم ${amount.toLocaleString()} ل.س من حسابك!`).catch(() => {}); 
            }); 
            return; 
        } else if (state.step === 'awaiting_user_id_history') { 
            delete userState[ADMIN_ID]; 
            const targetId = parseInt(text); 
            if (isNaN(targetId)) return ctx.reply('❌ يرجى إرسال آيدي صحيح.');
            
            db.get('SELECT * FROM users WHERE user_id = ?', [targetId], (err, user) => { 
                if (!user) return ctx.reply('❌ المستخدم غير موجود.'); 
                ctx.reply(`👤 المستخدم: \`${targetId}\`\n💰 الرصيد: ${user.balance.toLocaleString()} ل.س`, { parse_mode: 'Markdown' }); 
            }); 
            return; 
        } else if (state.step === 'awaiting_broadcast_msg') { 
            delete userState[ADMIN_ID]; 
            ctx.reply('⏳ جاري إرسال الإذاعة...'); 
            db.all('SELECT user_id FROM users', [], (err, users) => { 
                if (!users) return; 
                users.forEach((u) => { 
                    bot.telegram.sendMessage(u.user_id, text).catch(() => {}); 
                }); 
                ctx.reply('✅ تم إرسال الإذاعة بنجاح!'); 
            }); 
            return; 
        } 
    } 

    if (state) {
        if (state.step === 'awaiting_recharge') { 
            delete userState[userId]; 
            db.run('INSERT INTO transactions (user_id, type, amount, status, details) VALUES (?, "recharge", 0, "pending", ?)', [userId, text]); 
            ctx.reply('✅ تم إرسال طلب الشحن بنجاح للإدارة!'); 
            bot.telegram.sendMessage(ADMIN_ID, `📩 **طلب شحن جديد!**\n👤 المستخدم: \`${userId}\`\n📝 التفاصيل: ${text}`, { parse_mode: 'Markdown' }).catch(() => {}); 
            return;
        } else if (state.step === 'awaiting_withdraw') { 
            delete userState[userId]; 
            db.run('INSERT INTO transactions (user_id, type, amount, status, details) VALUES (?, "withdraw", 0, "pending", ?)', [userId, text]); 
            ctx.reply('✅ تم إرسال طلب السحب بنجاح للإدارة!'); 
            bot.telegram.sendMessage(ADMIN_ID, `💸 **طلب سحب جديد!**\n👤 المستخدم: \`${userId}\`\n📝 التفاصيل: ${text}`, { parse_mode: 'Markdown' }).catch(() => {}); 
            return;
        } else if (state.step === 'awaiting_promo') { 
            delete userState[userId]; 
            db.get('SELECT reward, uses_left FROM promo_codes WHERE code = ?', [text], (err, code) => { 
                if (!code || code.uses_left <= 0) return ctx.reply('❌ الكود غير صحيح أو انتهى.'); 
                db.run('UPDATE users SET balance = balance + ? WHERE user_id = ?', [code.reward, userId]); 
                db.run('UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?', [text]); 
                ctx.reply(`🎉 مبروك! تمت إضافة ${code.reward.toLocaleString()} ل.س لرصيدك.`); 
            }); 
            return;
        }
    }

    return next();
}); 

setInterval(() => { 
    axios.get(RENDER_URL) 
        .then(() => console.log('⚡ Keep-Alive Active')) 
        .catch((err) => console.log('⚡ Keep-Alive Ping:', err.message)); 
}, 3 * 60 * 1000); 

app.get('*', (req, res) => {
    res.send(`
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Green Lucky Box</title>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body { font-family: system-ui, sans-serif; text-align: center; padding: 30px 15px; background: #121212; color: #fff; margin: 0; }
            .card { background: #1e1e1e; padding: 25px; border-radius: 16px; }
            h1 { color: #28a745; }
            button { width: 100%; max-width: 300px; padding: 15px; font-size: 18px; font-weight: bold; background: #28a745; color: white; border: none; border-radius: 10px; cursor: pointer; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🌿 Green Lucky Box 🎁</h1>
            <p>اضغط أسفله لتجربة حظك وفتح الصندوق!</p>
            <button onclick="openBox()">📦 افتح الصندوق (2000 ل.س)</button>
        </div>
        <script>
            const tg = window.Telegram.WebApp;
            tg.expand();
            function openBox() {
                const urlParams = new URLSearchParams(window.location.search);
                const userId = urlParams.get('user_id');
                if (!userId) return alert('❌ لا يمكن التعرف على حسابك');
                fetch('/api/open-box', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: userId })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) alert(\`🎉 مبروك! ربحت \${data.prize} ل.س!\`);
                    else alert(\`❌ \${data.message}\`);
                });
            }
        </script>
    </body>
    </html>
    `);
});

const PORT = process.env.PORT || 3000; 

app.listen(PORT, () => { 
    console.log(`Server listening on port ${PORT}`); 
});

async function startBot() {
    try {
        await bot.telegram.deleteWebhook({ drop_pending_updates: true });
        await bot.launch();
        console.log('✅ Telegram Bot Ready!');
    } catch (err) {
        console.error('❌ Failed to connect Bot:', err.message);
    }
}

startBot();

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));

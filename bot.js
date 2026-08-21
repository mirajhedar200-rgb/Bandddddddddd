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

async function getRequiredChannel() {
    try {
        const res = await db.query('SELECT value FROM settings WHERE key = $1', ['channel_username']);
        if (res.rows.length > 0 && res.rows[0].value) {
            return res.rows[0].value.trim();
        }
    } catch (e) {}
    return process.env.CHANNEL_USERNAME || '@YourChannelUsername';
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

bot.start(checkSubscription, async (ctx) => { 
    const userId = ctx.from.id; 
    const startParam = ctx.payload; 
    try {
        const userRes = await db.query('SELECT * FROM users WHERE user_id = $1', [userId]);
        if (userRes.rows.length === 0) {
            const referrer = (startParam && parseInt(startParam) !== userId) ? parseInt(startParam) : null; 
            await db.query('INSERT INTO users (user_id, username, referred_by) VALUES ($1, $2, $3)', [userId, ctx.from.username || '', referrer]);
            if (referrer) { 
                await db.query('UPDATE users SET referral_balance = referral_balance + 300 WHERE user_id = $1', [referrer]);
                bot.telegram.sendMessage(referrer, '🎉 قام شخص بالتسجيل عبر رابط إحالتك! تمت إضافة 300 ل.س لرصيد الإحالات الخاص بك.').catch(() => {}); 
            } 
            showWelcomeAndTerms(ctx); 
        } else if (!userRes.rows[0].accepted_terms) { 
            showWelcomeAndTerms(ctx); 
        } else { 
            showMainMenu(ctx); 
        }
    } catch (e) {
        console.error(e);
    }
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

bot.action('accept_terms', async (ctx) => { 
    await db.query('UPDATE users SET accepted_terms = 1 WHERE user_id = $1', [ctx.from.id]);
    ctx.deleteMessage().catch(() => {}); 
    showMainMenu(ctx); 
}); 

async function showMainMenu(ctx) { 
    const userId = ctx.from.id; 
    const res = await db.query('SELECT balance, referral_balance FROM users WHERE user_id = $1', [userId]);
    const row = res.rows[0];
    const balance = row ? parseInt(row.balance) : 0; 
    const refBalance = row ? parseInt(row.referral_balance) : 0; 
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

bot.hears('🎁 فتح الصندوق', checkSubscription, async (ctx) => { 
    const userId = ctx.from.id; 
    const res = await db.query('SELECT balance FROM users WHERE user_id = $1', [userId]);
    const row = res.rows[0];
    if (!row || parseInt(row.balance) < 2000) { 
        return ctx.reply('⚠️ رصيدك غير كافٍ! سعر فتح الصندوق 2000 ل.س. اشحن حسابك لتستمتع باللعب.'); 
    } 
    const webAppUrl = `${RENDER_URL}?user_id=${userId}`; 
    ctx.reply('🎁 سعر الصندوق 2000 ل.س قديمة. هل تريد الشراء والفتح؟', Markup.inlineKeyboard([ 
        [Markup.button.webApp('📦 افتح الصندوق الآن', webAppUrl)], 
        [Markup.button.callback('❌ إلغاء', 'cancel_act')] 
    ]) ); 
}); 

bot.action('cancel_act', (ctx) => ctx.deleteMessage().catch(() => {})); 

app.post('/api/open-box', async (req, res) => { 
    const userId = req.body.user_id; 
    if (!userId) return res.json({ success: false, message: 'بيانات مستخدم غير صالحة' }); 
    try {
        const userRes = await db.query('SELECT balance, opened_count FROM users WHERE user_id = $1', [userId]);
        const user = userRes.rows[0];
        if (!user || parseInt(user.balance) < 2000) { 
            return res.json({ success: false, message: 'رصيدك غير كافٍ! اشحن لتفتح' }); 
        } 
        const newCount = parseInt(user.opened_count) + 1; 
        const prize = calculatePrize(newCount); 
        const newBalance = parseInt(user.balance) - 2000 + prize; 
        
        await db.query('UPDATE users SET balance = $1, opened_count = $2 WHERE user_id = $3', [newBalance, newCount, userId]);
        res.json({ success: true, prize: prize, newBalance: newBalance }); 
    } catch(err) {
        res.json({ success: false, message: 'حدث خطأ في السيرفر' });
    }
}); 

bot.hears('💳 شحن رصيد', checkSubscription, async (ctx) => { 
    userState[ctx.from.id] = { step: 'awaiting_recharge' }; 
    const res = await db.query('SELECT value FROM settings WHERE key = $1', ['syriatel_info']);
    const info = res.rows[0] ? res.rows[0].value : 'يرجى التحويل لسيريتل كاش على الرقم المعين من الإدارة.'; 
    ctx.reply(`💳 **شحن الرصيد بواسطة سيريتل كاش**\n\n📌 **معلومات الشحن:**\n${info}\n\nيرجى إرسال **المبلغ + رقم العملية** في رسالة واحدة:`); 
}); 

bot.hears('💸 سحب رصيد', checkSubscription, async (ctx) => { 
    userState[ctx.from.id] = { step: 'awaiting_withdraw' }; 
    const res = await db.query('SELECT value FROM settings WHERE key = $1', ['withdraw_info']);
    const info = res.rows[0] ? res.rows[0].value : 'ادخل عنوان استلام الأرباح والمبلغ المراد سحبه.'; 
    ctx.reply(`💸 **سحب الأرباح**\n\n📌 **معلومات السحب:**\n${info}\n\nيرجى إرسال **عنوان الاستلام + المبلغ**:`); 
}); 

bot.hears('🎁 كود هدية', checkSubscription, (ctx) => { 
    userState[ctx.from.id] = { step: 'awaiting_promo' }; 
    ctx.reply('🎁 أدخل كود الهدية الذي حصلت عليه:'); 
}); 

bot.hears('👥 الإحالات', checkSubscription, async (ctx) => { 
    const userId = ctx.from.id; 
    const link = `https://t.me/${ctx.botInfo.username}?start=${userId}`; 
    const res = await db.query('SELECT referral_balance FROM users WHERE user_id = $1', [userId]);
    const refBalance = res.rows[0] ? parseInt(res.rows[0].referral_balance) : 0; 
    ctx.reply(`👥 **نظام الإحالات**\n\n🔗 **رابط الإحالة الخاص بك:**\n\`${link}\` \n\n💰 **رصيد الإحالات الحالي:** ${refBalance.toLocaleString()} ل.س\n\n*(ملاحظة: تحصل على 300 ل.س لكل صديق يدخل عبر رابطك).*`, { parse_mode: 'Markdown' }); 
}); 

bot.hears('📊 السجل', checkSubscription, async (ctx) => { 
    const res = await db.query('SELECT type, amount, status, created_at FROM transactions WHERE user_id = $1 ORDER BY id DESC LIMIT 5', [ctx.from.id]);
    const rows = res.rows;
    if (!rows || rows.length === 0) return ctx.reply('📊 لا يوجد لديك عمليات شحن أو سحب سابقة.'); 
    let text = '📊 **سجل عملياتك الأخيرة:**\n\n'; 
    rows.forEach((r, i) => { 
        const typeText = r.type === 'recharge' ? '💳 شحن' : '💸 سحب'; 
        text += `${i + 1}. ${typeText} - ${parseInt(r.amount).toLocaleString()} ل.س (${r.status})\n📅 ${r.created_at}\n\n`; 
    }); 
    ctx.reply(text); 
}); 

bot.hears('👤 معلومات حسابي', checkSubscription, async (ctx) => { 
    const res = await db.query('SELECT balance, referral_balance, opened_count, joined_at FROM users WHERE user_id = $1', [ctx.from.id]);
    const row = res.rows[0];
    if (!row) return; 
    ctx.replyWithHTML( 
        `👤 <b>معلومات حسابك الشخصي:</b>\n\n` + 
        `🆔 <b>ID:</b> <code>${ctx.from.id}</code>\n` + 
        `💰 <b>الرصيد الرئيسي:</b> ${parseInt(row.balance).toLocaleString()} ل.س\n` + 
        `👥 <b>رصيد الإحالات:</b> ${parseInt(row.referral_balance).toLocaleString()} ل.س\n` + 
        `📦 <b>عدد مرات فتح الصندوق:</b> ${row.opened_count} مرة\n` + 
        `📅 <b>تاريخ الانضمام:</b> ${row.joined_at}` 
    ); 
}); 

// --- لوحة تحكم الأدمن --- 
bot.command('admin', (ctx) => { 
    if (ctx.from.id !== ADMIN_ID) return; 
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
    ctx.reply('📢 أرسل معرف القناة الجديدة مع الـ `@` (تأكد أن البوت مشرف داخل القناة):\nمثال: `@MyNewChannel`'); 
}); 

// --- استقبال النصوص --- 
bot.on('text', checkSubscription, async (ctx) => { 
    const userId = ctx.from.id; 
    const state = userState[userId]; 

    if (userId === ADMIN_ID && state) { 
        const text = ctx.message.text; 

        if (state.step === 'awaiting_set_channel') {
            delete userState[ADMIN_ID]; 
            const newChannel = text.trim();
            if (!newChannel.startsWith('@')) {
                return ctx.reply('❌ يرجى كتابة المعرف بشكل صحيح مع الرمز `@` في البداية.');
            }
            await db.query('INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', ['channel_username', newChannel]);
            ctx.reply(`✅ تم تحديث قناة الاشتراك الإجباري إلى: ${newChannel}\n\n⚠️ **تنبيه:** تأكد أن البوت مضاف في القناة ولديه صلاحية الإشراف (Admin).`); 
            return;
        } else if (state.step === 'awaiting_set_recharge') { 
            delete userState[ADMIN_ID]; 
            await db.query('INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', ['syriatel_info', text]);
            ctx.reply('✅ تم تحديث معلومات تعليمات الشحن بنجاح!'); 
            return; 
        } else if (state.step === 'awaiting_set_withdraw') { 
            delete userState[ADMIN_ID]; 
            await db.query('INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', ['withdraw_info', text]);
            ctx.reply('✅ تم تحديث معلومات تعليمات السحب بنجاح!'); 
            return; 
        } else if (state.step === 'awaiting_add_promo') { 
            delete userState[ADMIN_ID]; 
            const parts = text.split(' '); 
            const code = parts[0]; 
            const reward = parseInt(parts[1]); 
            const uses = parseInt(parts[2]); 
            if (!code || isNaN(reward) || isNaN(uses)) { 
                return ctx.reply('❌ صيغة خاطئة! أرسل [الكود والمكافأة وعدد الاستخدامات] بمسافة بينها.\nمثال: `FREE2026 5000 10`', { parse_mode: 'Markdown' }); 
            } 
            try {
                await db.query('INSERT INTO promo_codes (code, reward, uses_left) VALUES ($1, $2, $3)', [code, reward, uses]);
                ctx.reply(`✅ تم إنشاء كود الهدية \`${code}\` بمكافأة ${reward} ل.س لـ ${uses} مستخدم بنجاح!`, { parse_mode: 'Markdown' }); 
            } catch(e) {
                ctx.reply('❌ هذا الكود موجود مسبقاً، يرجى تغيير اسم الكود.');
            }
            return; 
        } else if (state.step === 'awaiting_add_bal') { 
            delete userState[ADMIN_ID]; 
            const [targetId, amount] = text.split(' '); 
            if (!targetId || isNaN(amount)) return ctx.reply('❌ صيغة خاطئة! أرسل الآيدي والمبلغ بمسافة بينهما.'); 
            const res = await db.query('UPDATE users SET balance = balance + $1 WHERE user_id = $2', [parseInt(amount), targetId]);
            if (res.rowCount === 0) return ctx.reply('❌ هذا المستخدم غير موجود!'); 
            ctx.reply(`✅ تمت إضافة ${amount} ل.س للمستخدم \`${targetId}\` بنجاح.`, { parse_mode: 'Markdown' }); 
            bot.telegram.sendMessage(targetId, `🎉 تم إيداع ${amount} ل.س في حسابك بواسطة الإدارة!`).catch(() => {}); 
            return; 
        } else if (state.step === 'awaiting_sub_bal') { 
            delete userState[ADMIN_ID]; 
            const [targetId, amount] = text.split(' '); 
            if (!targetId || isNaN(amount)) return ctx.reply('❌ صيغة خاطئة! أرسل الآيدي والمبلغ بمسافة بينهما.'); 
            const res = await db.query('UPDATE users SET balance = balance - $1 WHERE user_id = $2', [parseInt(amount), targetId]);
            if (res.rowCount === 0) return ctx.reply('❌ هذا المستخدم غير موجود!'); 
            ctx.reply(`✅ تم خصم ${amount} ل.س من المستخدم \`${targetId}\` بنجاح.`, { parse_mode: 'Markdown' }); 
            return; 
        } else if (state.step === 'awaiting_user_id_history') { 
            delete userState[ADMIN_ID]; 
            const targetId = text.trim(); 
            const userRes = await db.query('SELECT * FROM users WHERE user_id = $1', [targetId]);
            const user = userRes.rows[0];
            if (!user) return ctx.reply('❌ المستخدم غير موجود في قاعدة البيانات.'); 
            const txsRes = await db.query('SELECT type, amount, status, details, created_at FROM transactions WHERE user_id = $1 ORDER BY id DESC LIMIT 5', [targetId]);
            const txs = txsRes.rows;
            let report = `👤 **بيانات المستخدم:** \`${targetId}\`\n\n` + 
                `💰 الرصيد الرئيسي: ${user.balance} ل.س\n` + 
                `👥 رصيد الإحالات: ${user.referral_balance} ل.س\n` + 
                `📦 فتحات الصندوق: ${user.opened_count}\n\n` + 
                `📊 **أحدث عمليات الشحن والسحب:**\n`; 
            if (!txs || txs.length === 0) { 
                report += 'لا توجد عمليات سابقة.'; 
            } else { 
                txs.forEach((t, i) => { 
                    const typeStr = t.type === 'recharge' ? '💳 شحن' : '💸 سحب'; 
                    report += `${i + 1}. ${typeStr} | الحالة: ${t.status}\nالتفاصيل: ${t.details}\n📅 ${t.created_at}\n\n`; 
                }); 
            } 
            ctx.reply(report, { parse_mode: 'Markdown' }); 
            return; 
        } else if (state.step === 'awaiting_broadcast_msg') { 
            delete userState[ADMIN_ID]; 
            ctx.reply('⏳ جاري إرسال الإذاعة لجميع المشتركين...'); 
            const usersRes = await db.query('SELECT user_id FROM users');
            let successCount = 0; 
            for (const u of usersRes.rows) {
                try {
                    await bot.telegram.sendMessage(u.user_id, text);
                    successCount++;
                } catch(e) {}
            }
            ctx.reply(`✅ تم إنهاء الإذاعة بنجاح! وصلت الرسالة إلى ${successCount} مستخدم.`); 
            return; 
        } 
    } 

    if (!state) return; 
    const text = ctx.message.text; 
    if (state.step === 'awaiting_recharge') { 
        delete userState[userId]; 
        await db.query('INSERT INTO transactions (user_id, type, amount, status, details) VALUES ($1, \'recharge\', 0, \'pending\', $2)', [userId, text]);
        ctx.reply('✅ تم إرسال طلب الشحن بنجاح للادارة! سيتم مراجعته وإضافة الرصيد لحسابك.'); 
        bot.telegram.sendMessage(ADMIN_ID, `📩 **طلب شحن جديد!**\n\n👤 المستخدم: ${userId}\n📝 التفاصيل: ${text}`).catch(() => {}); 
    } else if (state.step === 'awaiting_withdraw') { 
        delete userState[userId]; 
        await db.query('INSERT INTO transactions (user_id, type, amount, status, details) VALUES ($1, \'withdraw\', 0, \'pending\', $2)', [userId, text]);
        ctx.reply('✅ تم إرسال طلب السحب بنجاح للإدارة! سيتم المعالجة قريباً.'); 
        bot.telegram.sendMessage(ADMIN_ID, `💸 **طلب سحب جديد!**\n\n👤 المستخدم: ${userId}\n📝 التفاصيل: ${text}`).catch(() => {}); 
    } else if (state.step === 'awaiting_promo') { 
        delete userState[userId]; 
        const codeRes = await db.query('SELECT reward, uses_left FROM promo_codes WHERE code = $1', [text]);
        const code = codeRes.rows[0];
        if (!code || parseInt(code.uses_left) <= 0) return ctx.reply('❌ الكود غير صحيح أو انتهت صلاحيته.'); 
        const usedRes = await db.query('SELECT * FROM used_codes WHERE user_id = $1 AND code = $2', [userId, text]);
        if (usedRes.rows.length > 0) return ctx.reply('⚠️ لقد استخدمت هذا الكود من قبل!'); 
        
        await db.query('UPDATE users SET balance = balance + $1 WHERE user_id = $2', [code.reward, userId]); 
        await db.query('UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = $1', [text]); 
        await db.query('INSERT INTO used_codes (user_id, code) VALUES ($1, $2)', [userId, text]); 
        ctx.reply(`🎉 مبروك! تمت إضافة ${parseInt(code.reward).toLocaleString()} ل.س لرصيدك.`); 
    } 
}); 

// --- تشغيل السيرفر والـ Webhook ليعمل على Render بدون مشاكل ---
app.use(bot.webhookCallback(`/bot${BOT_TOKEN}`));

const PORT = process.env.PORT || 10000; 
app.listen(PORT, async () => { 
    console.log(`Server listening on port ${PORT}`); 
    try {
        await bot.telegram.setWebhook(`${RENDER_URL}/bot${BOT_TOKEN}`);
        console.log('✅ Webhook attached successfully!');
    } catch (e) {
        console.error('Webhook error:', e.message);
    }
});

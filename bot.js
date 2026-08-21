const { Telegraf, Markup } = require('telegraf'); 
const express = require('express'); 
const axios = require('axios'); 

const BOT_TOKEN = process.env.BOT_TOKEN || 'YOUR_BOT_TOKEN_HERE'; 
const RENDER_URL = process.env.RENDER_URL || 'https://your-app-name.onrender.com'; 
const ADMIN_ID = parseInt(process.env.ADMIN_ID) || 123456789; 

const bot = new Telegraf(BOT_TOKEN); 
const app = express(); 

app.use(express.json()); 

const userState = {}; 

// تخزين محلي بدلاً من قاعدة البيانات
const db = {
    users: {},       // تخزين المستخدمين: user_id -> { balance, referral_balance, opened_count, accepted_terms, joined_at, username }
    transactions: [], // سجل العمليات
    promo_codes: {},  // كود الهدية -> { reward, uses_left }
    used_codes: {},   // user_id_code -> true
    settings: {
        channel_username: process.env.CHANNEL_USERNAME || '@YourChannelUsername',
        syriatel_info: 'يرجى التحويل لسيريتل كاش على الرقم المعين من الإدارة.',
        withdraw_info: 'ادخل عنوان استلام الأرباح والمبلغ المراد سحبه.'
    }
};

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
    return db.settings.channel_username || '@YourChannelUsername';
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
        if (!db.users[userId]) {
            const referrer = (startParam && parseInt(startParam) !== userId) ? parseInt(startParam) : null; 
            db.users[userId] = {
                user_id: userId,
                username: ctx.from.username || '',
                referred_by: referrer,
                balance: 0,
                referral_balance: 0,
                opened_count: 0,
                accepted_terms: 0,
                joined_at: new Date().toISOString().split('T')[0]
            };

            if (referrer && db.users[referrer]) { 
                db.users[referrer].referral_balance += 300;
                bot.telegram.sendMessage(referrer, '🎉 قام شخص بالتسجيل عبر رابط إحالتك! تمت إضافة 300 ل.س لرصيد الإحالات الخاص بك.').catch(() => {}); 
            } 
            showWelcomeAndTerms(ctx); 
        } else if (!db.users[userId].accepted_terms) { 
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
    const userId = ctx.from.id;
    if (db.users[userId]) {
        db.users[userId].accepted_terms = 1;
    }
    ctx.deleteMessage().catch(() => {}); 
    showMainMenu(ctx); 
}); 

async function showMainMenu(ctx) { 
    const userId = ctx.from.id; 
    const user = db.users[userId] || { balance: 0, referral_balance: 0 };
    const balance = parseInt(user.balance) || 0; 
    const refBalance = parseInt(user.referral_balance) || 0; 
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
    const user = db.users[userId];
    if (!user || parseInt(user.balance) < 2000) { 
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
        const user = db.users[userId];
        if (!user || parseInt(user.balance) < 2000) { 
            return res.json({ success: false, message: 'رصيدك غير كافٍ! اشحن لتفتح' }); 
        } 
        const newCount = parseInt(user.opened_count || 0) + 1; 
        const prize = calculatePrize(newCount); 
        const newBalance = parseInt(user.balance) - 2000 + prize; 
        
        user.balance = newBalance;
        user.opened_count = newCount;

        res.json({ success: true, prize: prize, newBalance: newBalance }); 
    } catch(err) {
        res.json({ success: false, message: 'حدث خطأ في السيرفر' });
    }
}); 

bot.hears('💳 شحن رصيد', checkSubscription, async (ctx) => { 
    userState[ctx.from.id] = { step: 'awaiting_recharge' }; 
    const info = db.settings.syriatel_info; 
    ctx.reply(`💳 **شحن الرصيد بواسطة سيريتل كاش**\n\n📌 **معلومات الشحن:**\n${info}\n\nيرجى إرسال **المبلغ + رقم العملية** في رسالة واحدة:`); 
}); 

bot.hears('💸 سحب رصيد', checkSubscription, async (ctx) => { 
    userState[ctx.from.id] = { step: 'awaiting_withdraw' }; 
    const info = db.settings.withdraw_info; 
    ctx.reply(`💸 **سحب الأرباح**\n\n📌 **معلومات السحب:**\n${info}\n\nيرجى إرسال **عنوان الاستلام + المبلغ**:`); 
}); 

bot.hears('🎁 كود هدية', checkSubscription, (ctx) => { 
    userState[ctx.from.id] = { step: 'awaiting_promo' }; 
    ctx.reply('🎁 أدخل كود الهدية الذي حصلت عليه:'); 
}); 

bot.hears('👥 الإحالات', checkSubscription, async (ctx) => { 
    const userId = ctx.from.id; 
    const link = `https://t.me/${ctx.botInfo.username}?start=${userId}`; 
    const user = db.users[userId];
    const refBalance = user ? parseInt(user.referral_balance) : 0; 
    ctx.reply(`👥 **نظام الإحالات**\n\n🔗 **رابط الإحالة الخاص بك:**\n\`${link}\` \n\n💰 **رصيد الإحالات الحالي:** ${refBalance.toLocaleString()} ل.س\n\n*(ملاحظة: تحصل على 300 ل.س لكل صديق يدخل عبر رابطك).*`, { parse_mode: 'Markdown' }); 
}); 

bot.hears('📊 السجل', checkSubscription, async (ctx) => { 
    const userId = ctx.from.id;
    const rows = db.transactions.filter(t => t.user_id == userId).slice(-5).reverse();
    if (!rows || rows.length === 0) return ctx.reply('📊 لا يوجد لديك عمليات شحن أو سحب سابقة.'); 
    let text = '📊 **سجل عملياتك الأخيرة:**\n\n'; 
    rows.forEach((r, i) => { 
        const typeText = r.type === 'recharge' ? '💳 شحن' : '💸 سحب'; 
        text += `${i + 1}. ${typeText} - ${parseInt(r.amount).toLocaleString()} ل.س (${r.status})\n📅 ${r.created_at}\n\n`; 
    }); 
    ctx.reply(text); 
}); 

bot.hears('👤 معلومات حسابي', checkSubscription, async (ctx) => { 
    const user = db.users[ctx.from.id];
    if (!user) return; 
    ctx.replyWithHTML( 
        `👤 <b>معلومات حسابك الشخصي:</b>\n\n` + 
        `🆔 <b>ID:</b> <code>${ctx.from.id}</code>\n` + 
        `💰 <b>الرصيد الرئيسي:</b> ${parseInt(user.balance).toLocaleString()} ل.س\n` + 
        `👥 <b>رصيد الإحالات:</b> ${parseInt(user.referral_balance).toLocaleString()} ل.س\n` + 
        `📦 <b>عدد مرات فتح الصندوق:</b> ${user.opened_count} مرة\n` + 
        `📅 <b>تاريخ الانضمام:</b> ${user.joined_at}` 
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
            db.settings.channel_username = newChannel;
            ctx.reply(`✅ تم تحديث قناة الاشتراك الإجباري إلى: ${newChannel}\n\n⚠️ **تنبيه:** تأكد أن البوت مضاف في القناة ولديه صلاحية الإشراف (Admin).`); 
            return;
        } else if (state.step === 'awaiting_set_recharge') { 
            delete userState[ADMIN_ID]; 
            db.settings.syriatel_info = text;
            ctx.reply('✅ تم تحديث معلومات تعليمات الشحن بنجاح!'); 
            return; 
        } else if (state.step === 'awaiting_set_withdraw') { 
            delete userState[ADMIN_ID]; 
            db.settings.withdraw_info = text;
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
            if (db.promo_codes[code]) {
                return ctx.reply('❌ هذا الكود موجود مسبقاً، يرجى تغيير اسم الكود.');
            }
            db.promo_codes[code] = { reward, uses_left: uses };
            ctx.reply(`✅ تم إنشاء كود الهدية \`${code}\` بمكافأة ${reward} ل.س لـ ${uses} مستخدم بنجاح!`, { parse_mode: 'Markdown' }); 
            return; 
        } else if (state.step === 'awaiting_add_bal') { 
            delete userState[ADMIN_ID]; 
            const [targetIdStr, amountStr] = text.split(' '); 
            const targetId = targetIdStr ? targetIdStr.trim() : null;
            const amount = parseInt(amountStr);
            
            if (!targetId || isNaN(amount)) return ctx.reply('❌ صيغة خاطئة! أرسل الآيدي والمبلغ بمسافة بينهما.'); 
            if (!db.users[targetId]) return ctx.reply('❌ هذا المستخدم غير موجود!'); 
            
            db.users[targetId].balance = parseInt(db.users[targetId].balance || 0) + amount; 
            ctx.reply(`✅ تمت إضافة ${amount} ل.س للمستخدم \`${targetId}\` بنجاح.`, { parse_mode: 'Markdown' }); 
            bot.telegram.sendMessage(targetId, `🎉 تم إيداع ${amount} ل.س في حسابك بواسطة الإدارة!`).catch(() => {}); 
            return; 
        } else if (state.step === 'awaiting_sub_bal') { 
            delete userState[ADMIN_ID]; 
            const [targetIdStr, amountStr] = text.split(' '); 
            const targetId = targetIdStr ? targetIdStr.trim() : null;
            const amount = parseInt(amountStr);

            if (!targetId || isNaN(amount)) return ctx.reply('❌ صيغة خاطئة! أرسل الآيدي والمبلغ بمسافة بينهما.'); 
            if (!db.users[targetId]) return ctx.reply('❌ هذا المستخدم غير موجود!'); 
            
            db.users[targetId].balance = parseInt(db.users[targetId].balance || 0) - amount; 
            ctx.reply(`✅ تم خصم ${amount} ل.س من المستخدم \`${targetId}\` بنجاح.`, { parse_mode: 'Markdown' }); 
            return; 
        } else if (state.step === 'awaiting_user_id_history') { 
            delete userState[ADMIN_ID]; 
            const targetId = text.trim(); 
            const user = db.users[targetId];
            if (!user) return ctx.reply('❌ المستخدم غير موجود في قاعدة البيانات.'); 
            const txs = db.transactions.filter(t => t.user_id == targetId).slice(-5).reverse();
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
            let successCount = 0; 
            for (const uid of Object.keys(db.users)) {
                try {
                    await bot.telegram.sendMessage(uid, text);
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
        db.transactions.push({
            user_id: userId,
            type: 'recharge',
            amount: 0,
            status: 'pending',
            details: text,
            created_at: new Date().toISOString().replace('T', ' ').substring(0, 19)
        });
        ctx.reply('✅ تم إرسال طلب الشحن بنجاح للادارة! سيتم مراجعته وإضافة الرصيد لحسابك.'); 
        bot.telegram.sendMessage(ADMIN_ID, `📩 **طلب شحن جديد!**\n\n👤 المستخدم: ${userId}\n📝 التفاصيل: ${text}`).catch(() => {}); 
    } else if (state.step === 'awaiting_withdraw') { 
        delete userState[userId]; 
        db.transactions.push({
            user_id: userId,
            type: 'withdraw',
            amount: 0,
            status: 'pending',
            details: text,
            created_at: new Date().toISOString().replace('T', ' ').substring(0, 19)
        });
        ctx.reply('✅ تم إرسال طلب السحب بنجاح للإدارة! سيتم المعالجة قريباً.'); 
        bot.telegram.sendMessage(ADMIN_ID, `💸 **طلب سحب جديد!**\n\n👤 المستخدم: ${userId}\n📝 التفاصيل: ${text}`).catch(() => {}); 
    } else if (state.step === 'awaiting_promo') { 
        delete userState[userId]; 
        const promo = db.promo_codes[text];
        if (!promo || promo.uses_left <= 0) return ctx.reply('❌ الكود غير صحيح أو انتهت صلاحيته.'); 
        
        const usedKey = `${userId}_${text}`;
        if (db.used_codes[usedKey]) return ctx.reply('⚠️ لقد استخدمت هذا الكود من قبل!'); 
        
        db.users[userId].balance += promo.reward; 
        promo.uses_left -= 1; 
        db.used_codes[usedKey] = true; 
        ctx.reply(`🎉 مبروك! تمت إضافة ${parseInt(promo.reward).toLocaleString()} ل.س لرصيدك.`); 
    } 
}); 

// --- تشغيل السيرفر والـ Webhook ليعمل على Render ---
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

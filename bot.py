import os, sqlite3, asyncio, logging, html, json, urllib.request
from datetime import datetime, timedelta, timezone
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "bot.db")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@")
PAYMENT_CODE = os.getenv("PAYMENT_CODE", "77178326")
REFERRAL_REWARD_OLD = int(os.getenv("REFERRAL_REWARD_OLD", "3000"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
PORT = int(os.getenv("PORT", "10000"))

PACKAGES = {
    "p500":  (500, 100, "زيادة 500 مشترك"),
    "p1000": (1000, 200, "زيادة 1000 مشترك"),
    "p2000": (2000, 250, "زيادة 2000 مشترك"),
    "pad":   ("3000+", 400, "إعلان احترافي ممول 3000+"),
}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("promo-bot")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0,
      referred_by INTEGER, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS topups(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER,
      operation TEXT, status TEXT DEFAULT 'pending', created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS orders(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, package TEXT,
      target TEXT, price INTEGER, status TEXT DEFAULT 'pending',
      expires_at TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS referrals(
      id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER, user_id INTEGER UNIQUE,
      reward INTEGER, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS partner_channels(
      id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT UNIQUE, title TEXT,
      active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    """)
    c.commit(); c.close()

def now():
    return datetime.now(timezone.utc).isoformat()

def ensure_user(user_id, username=None, referred_by=None):
    c = db()
    row = c.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        c.execute("INSERT INTO users(id,username,referred_by,created_at) VALUES(?,?,?,?)",
                  (user_id, username, referred_by, now()))
        if referred_by and referred_by != user_id:
            # Reward is recorded when the referred user places their first paid order.
            pass
        c.commit()
    else:
        c.execute("UPDATE users SET username=? WHERE id=?", (username, user_id))
        c.commit()
    c.close()

def balance(uid):
    c=db(); r=c.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone(); c.close()
    return int(r["balance"]) if r else 0

def add_balance(uid, amount):
    c=db(); c.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount,uid)); c.commit(); c.close()

def take_balance(uid, amount):
    c=db()
    r=c.execute("UPDATE users SET balance=balance-? WHERE id=? AND balance>=?", (amount,uid,amount))
    ok = r.rowcount == 1
    c.commit(); c.close(); return ok

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text="💳 شحن رصيد", callback_data="topup"),
       InlineKeyboardButton(text="📣 زيادة المشتركين", callback_data="packages")],
      [InlineKeyboardButton(text="💰 رصيدي واشتراكاتي", callback_data="info"),
       InlineKeyboardButton(text="👥 نظام الإحالات", callback_data="ref")],
      [InlineKeyboardButton(text="🤖 المساعد الذكي", callback_data="ai"),
       InlineKeyboardButton(text="🆘 الدعم", callback_data="support")],
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ رجوع", callback_data="home")]])

class Form(StatesGroup):
    topup_amount = State()
    partner_channel = State()
    topup_operation = State()
    order_target = State()
    ai_question = State()
    support_message = State()

async def send_home(m: Message, edit=False):
    text = (
      "👋 <b>Welcome Bot — منصة ترويج Telegram</b>\n\n"
      "نساعدك في إدارة حملات ترويج حقيقية لقناتك أو بوتك عبر "
      "قنوات/شركاء يوافقون على نشر الإعلانات.\n\n"
      "⚠️ لا يمكن للبوت إضافة مستخدمين وهميين أو إجبار أشخاص على الاشتراك. "
      "النتائج تعتمد على الحملة والشبكة الإعلانية."
    )
    if edit:
        await m.edit_text(text, reply_markup=main_kb())
    else:
        await m.answer(text, reply_markup=main_kb())

@dp.message(CommandStart())
async def start(m: Message):
    payload = m.text.split(maxsplit=1)[1] if len(m.text.split()) > 1 else ""
    ref = int(payload[3:]) if payload.startswith("ref") and payload[3:].isdigit() else None
    ensure_user(m.from_user.id, m.from_user.username, ref)
    await send_home(m)

@dp.callback_query(F.data=="home")
async def home(q: CallbackQuery):
    await q.answer()
    await q.message.edit_text("👋 <b>القائمة الرئيسية</b>\nاختر الخدمة:", reply_markup=main_kb())

@dp.callback_query(F.data=="packages")
async def packages(q: CallbackQuery):
    await q.answer()
    b=balance(q.from_user.id)
    kb=InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text="🚀 500 مشترك — 100 ل.س", callback_data="pkg:p500")],
      [InlineKeyboardButton(text="🚀 1000 مشترك — 200 ل.س", callback_data="pkg:p1000")],
      [InlineKeyboardButton(text="🚀 2000 مشترك — 250 ل.س", callback_data="pkg:p2000")],
      [InlineKeyboardButton(text="📢 إعلان احترافي 3000+ — 400 ل.س", callback_data="pkg:pad")],
      [InlineKeyboardButton(text="↩️ رجوع", callback_data="home")]
    ])
    await q.message.edit_text(f"📣 <b>الباقات</b>\nرصيدك: <b>{b:,} ل.س</b>\n\nاختر الباقة ثم أرسل @username أو رابط القناة/البوت.", reply_markup=kb)

@dp.callback_query(F.data.startswith("pkg:"))
async def choose_pkg(q: CallbackQuery, state: FSMContext):
    await q.answer()
    key=q.data.split(":")[1]
    amount=PACKAGES[key][1]
    if balance(q.from_user.id) < amount:
        await q.message.edit_text(f"❌ رصيدك غير كافٍ.\nالسعر: {amount:,} ل.س\nرصيدك: {balance(q.from_user.id):,} ل.س", reply_markup=back_kb())
        return
    await state.update_data(package=key)
    await state.set_state(Form.order_target)
    await q.message.edit_text("🎯 أرسل الآن رابط القناة/البوت أو @username الذي تريد ترويجه.", reply_markup=back_kb())

@dp.message(Form.order_target)
async def create_order(m: Message, state: FSMContext):
    target=m.text.strip()
    data=await state.get_data(); key=data["package"]
    price=PACKAGES[key][1]
    if balance(m.from_user.id) < price:
        await m.answer("❌ لم يعد رصيدك كافياً.", reply_markup=main_kb()); await state.clear(); return
    if not take_balance(m.from_user.id, price):
        await m.answer("❌ تعذر خصم الرصيد.", reply_markup=main_kb()); await state.clear(); return
    c=db()
    c.execute("INSERT INTO orders(user_id,package,target,price,status,expires_at,created_at) VALUES(?,?,?,?,?,?,?)",
              (m.from_user.id,key,target,price,"pending",(datetime.now(timezone.utc)+timedelta(hours=64)).isoformat(),now()))
    oid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Referral reward: only once, after first paid order.
    u=c.execute("SELECT referred_by FROM users WHERE id=?", (m.from_user.id,)).fetchone()
    if u and u["referred_by"]:
        already=c.execute("SELECT 1 FROM referrals WHERE user_id=?", (m.from_user.id,)).fetchone()
        if not already:
            c.execute("INSERT INTO referrals(referrer_id,user_id,reward,created_at) VALUES(?,?,?,?)",
                      (u["referred_by"],m.from_user.id,REFERRAL_REWARD_OLD,now()))
            c.execute("UPDATE users SET balance=balance+? WHERE id=?", (REFERRAL_REWARD_OLD,u["referred_by"]))
    c.commit(); c.close(); await state.clear()
    await m.answer(f"✅ تم إنشاء الطلب #{oid}.\nتم خصم {price:,} ل.س.\n\n⏱ التفعيل/التنفيذ خلال مدة الحملة حتى 64 ساعة حسب توفر شبكة النشر.\n📌 لا يعني ذلك ضمان عدد محدد من الأعضاء.", reply_markup=main_kb())
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"📣 <b>طلب ترويج جديد #{oid}</b>\nالمستخدم: <code>{m.from_user.id}</code>\nالهدف: {html.escape(target)}\nالباقة: {html.escape(PACKAGES[key][2])}\nالسعر: {price} ل.س", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
          [InlineKeyboardButton(text="✅ اعتماد", callback_data=f"approve:{oid}"),
           InlineKeyboardButton(text="❌ رفض/استرداد", callback_data=f"reject:{oid}")]
        ]))

@dp.callback_query(F.data=="topup")
async def topup(q: CallbackQuery, state: FSMContext):
    await q.answer()
    await state.set_state(Form.topup_amount)
    await q.message.edit_text(f"💳 <b>شحن الرصيد</b>\n\nأرسل المبلغ الذي تريد شحنه.\nالحد الأدنى: <b>100 ل.س جديدة</b>\nطريقة الدفع: سيريتل كاش\nكود الدفع: <code>{PAYMENT_CODE}</code>", reply_markup=back_kb())

@dp.message(Form.topup_amount)
async def topup_amount(m: Message, state: FSMContext):
    try: amount=int(m.text.replace(",","").strip())
    except: amount=0
    if amount<100:
        await m.answer("❌ الحد الأدنى 100 ل.س جديدة. أرسل مبلغاً صحيحاً."); return
    await state.update_data(amount=amount)
    await state.set_state(Form.topup_operation)
    await m.answer("📨 أرسل الآن <b>رقم العملية</b> بعد إتمام التحويل.", reply_markup=back_kb())

@dp.message(Form.topup_operation)
async def topup_operation(m: Message, state: FSMContext):
    data=await state.get_data(); op=m.text.strip()
    c=db(); c.execute("INSERT INTO topups(user_id,amount,operation,status,created_at) VALUES(?,?,?,?,?)",
                      (m.from_user.id,data["amount"],op,"pending",now()))
    tid=c.execute("SELECT last_insert_rowid()").fetchone()[0]; c.commit(); c.close(); await state.clear()
    await m.answer(f"✅ تم إرسال طلب الشحن #{tid} للإدارة.\nسيضاف الرصيد بعد موافقة الأدمن.", reply_markup=main_kb())
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"💳 <b>طلب شحن #{tid}</b>\nالمستخدم: <code>{m.from_user.id}</code>\nالمبلغ: {data['amount']:,} ل.س\nرقم العملية: <code>{html.escape(op)}</code>",
          reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ موافقة",callback_data=f"topup_ok:{tid}"),InlineKeyboardButton(text="❌ رفض",callback_data=f"topup_no:{tid}")]]))

@dp.callback_query(F.data.startswith("topup_ok:"))
async def topup_ok(q: CallbackQuery):
    if q.from_user.id != ADMIN_ID: return await q.answer("غير مسموح", show_alert=True)
    tid=int(q.data.split(":")[1]); c=db()
    r=c.execute("SELECT user_id,amount,status FROM topups WHERE id=?",(tid,)).fetchone()
    if not r or r["status"]!="pending": c.close(); return await q.answer("تمت معالجة الطلب")
    c.execute("UPDATE topups SET status='approved' WHERE id=?",(tid,)); c.execute("UPDATE users SET balance=balance+? WHERE id=?",(r["amount"],r["user_id"])); c.commit(); c.close()
    await q.message.edit_text(f"✅ تمت الموافقة على شحن #{tid}.")
    await bot.send_message(r["user_id"],f"💰 تمت إضافة <b>{r['amount']:,} ل.س</b> إلى رصيدك.\nالرصيد الحالي: {balance(r['user_id']):,} ل.س")

@dp.callback_query(F.data.startswith("topup_no:"))
async def topup_no(q: CallbackQuery):
    if q.from_user.id != ADMIN_ID: return await q.answer("غير مسموح", show_alert=True)
    tid=int(q.data.split(":")[1]); c=db(); c.execute("UPDATE topups SET status='rejected' WHERE id=? AND status='pending'",(tid,)); c.commit(); c.close()
    await q.message.edit_text(f"❌ تم رفض طلب الشحن #{tid}.")

@dp.callback_query(F.data=="info")
async def info(q: CallbackQuery):
    await q.answer(); c=db()
    orders=c.execute("SELECT package,target,price,status,expires_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",(q.from_user.id,)).fetchall()
    c.close()
    lines=[f"💰 رصيدك: <b>{balance(q.from_user.id):,} ل.س</b>","", "📋 آخر الطلبات:"]
    for o in orders:
        lines.append(f"#{o['package']} — {o['price']:,} ل.س — {o['status']} — {html.escape(o['target'])}")
    await q.message.edit_text("\n".join(lines),reply_markup=back_kb())

@dp.callback_query(F.data=="ref")
async def ref(q: CallbackQuery):
    await q.answer(); me=await bot.get_me(); c=db()
    count=c.execute("SELECT COUNT(*) n FROM referrals WHERE referrer_id=?",(q.from_user.id,)).fetchone()["n"]; c.close()
    link=f"https://t.me/{me.username}?start=ref{q.from_user.id}"
    await q.message.edit_text(f"👥 <b>نظام الإحالات</b>\n\nرابطك:\n<code>{link}</code>\n\nالمنضمون عن طريقك: <b>{count}</b>\nالمكافأة: <b>{REFERRAL_REWARD_OLD:,} ل.س قديمة</b> لكل اشتراك مدفوع يتم عبر رابطك.",reply_markup=back_kb())

@dp.callback_query(F.data=="support")
async def support(q: CallbackQuery, state: FSMContext):
    await q.answer(); await state.set_state(Form.support_message)
    await q.message.edit_text("🆘 أرسل رسالتك للدعم الآن.",reply_markup=back_kb())

@dp.message(Form.support_message)
async def support_message(m: Message,state:FSMContext):
    await state.clear()
    if ADMIN_ID: await bot.send_message(ADMIN_ID,f"🆘 دعم من <code>{m.from_user.id}</code>:\n{html.escape(m.text)}")
    await m.answer("✅ تم إرسال رسالتك للدعم.",reply_markup=main_kb())

@dp.callback_query(F.data=="ai")
async def ai_start(q: CallbackQuery,state:FSMContext):
    await q.answer()
    if not OPENAI_API_KEY:
        await q.message.edit_text("🤖 المساعد الذكي غير مفعّل حالياً.\nأضف OPENAI_API_KEY في متغيرات Render لتفعيله.",reply_markup=back_kb()); return
    await state.set_state(Form.ai_question)
    await q.message.edit_text("🤖 أرسل سؤالك وسأساعدك في كتابة وصف إعلاني احترافي أو اقتراح حملة.",reply_markup=back_kb())

@dp.message(Form.ai_question)
async def ai_question(m: Message,state:FSMContext):
    await state.clear()
    prompt=("أنت مساعد تسويق لبوت Telegram. اكتب إجابة عربية مختصرة ومهنية. "
            "لا تعد بزيادة وهمية أو أعضاء مزيفين، واقترح ترويجاً حقيقياً عبر قنوات وشبكات موافقة.\nسؤال العميل:\n"+m.text)
    try:
        req=urllib.request.Request(
          "https://api.openai.com/v1/responses",
          data=json.dumps({"model":OPENAI_MODEL,"input":prompt}).encode(),
          headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=45) as r: data=json.loads(r.read().decode())
        answer=data.get("output_text") or "تعذر الحصول على إجابة."
    except Exception as e:
        log.exception("AI error"); answer="تعذر الاتصال بالمساعد الذكي حالياً."
    await m.answer(html.escape(answer),reply_markup=main_kb())

# Admin panel
def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
      [InlineKeyboardButton(text="💳 طلبات الشحن",callback_data="adm:topups")],
      [InlineKeyboardButton(text="📣 طلبات الترويج",callback_data="adm:orders")],
      [InlineKeyboardButton(text="📊 الإحصائيات",callback_data="adm:stats")],
      [InlineKeyboardButton(text="➕ إضافة رصيد",callback_data="adm:add")],
      [InlineKeyboardButton(text="➖ خصم رصيد",callback_data="adm:sub")],
      [InlineKeyboardButton(text="📢 القنوات الشريكة",callback_data="adm:partners")],
    ])

@dp.message(Command("admin"))
async def admin(m:Message):
    if m.from_user.id!=ADMIN_ID: return
    await m.answer("👑 <b>لوحة الإدارة</b>",reply_markup=admin_kb())


@dp.callback_query(F.data=="adm:partners")
async def adm_partners(q:CallbackQuery):
    if q.from_user.id != ADMIN_ID:
        return await q.answer("غير مسموح", show_alert=True)
    c=db()
    rows=c.execute("SELECT id,chat_id,title,active FROM partner_channels ORDER BY id DESC").fetchall()
    c.close()
    buttons=[]
    for r in rows:
        state="🟢" if r["active"] else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{state} {r['title'] or r['chat_id']}",
            callback_data=f"partner:toggle:{r['id']}")])
    buttons.append([InlineKeyboardButton(text="➕ إضافة قناة",callback_data="partner:add")])
    buttons.append([InlineKeyboardButton(text="🗑️ حذف قناة",callback_data="partner:delete_menu")])
    buttons.append([InlineKeyboardButton(text="↩️ رجوع",callback_data="adm:home")])
    await q.message.edit_text(
        "📢 <b>القنوات الشريكة</b>\n\n"
        "أضف فقط القنوات التي وافقت على استقبال الإعلانات، "
        "ويجب أن يكون البوت مشرفاً فيها مع صلاحية نشر الرسائل.\n\n"
        f"عدد القنوات: <b>{len(rows)}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data=="adm:home")
async def adm_home(q:CallbackQuery):
    if q.from_user.id != ADMIN_ID:
        return await q.answer("غير مسموح", show_alert=True)
    await q.answer()
    await q.message.edit_text("👑 <b>لوحة الإدارة</b>",reply_markup=admin_kb())

@dp.callback_query(F.data=="partner:add")
async def partner_add(q:CallbackQuery,state:FSMContext):
    if q.from_user.id != ADMIN_ID:
        return await q.answer("غير مسموح", show_alert=True)
    await q.answer()
    await state.set_state(Form.partner_channel)
    await q.message.edit_text(
        "➕ <b>إضافة قناة شريكة</b>\n\n"
        "أرسل @username للقناة أو Chat ID للقناة.\n"
        "مثال: <code>@mychannel</code>\n\n"
        "تأكد أن البوت مشرف في القناة ولديه صلاحية نشر الرسائل.",
        reply_markup=back_kb())

@dp.message(Form.partner_channel)
async def partner_channel_message(m:Message,state:FSMContext):
    if m.from_user.id != ADMIN_ID:
        return
    chat_id=m.text.strip()
    try:
        chat=await bot.get_chat(chat_id)
        # Verify bot has enough rights to publish in the channel.
        me=await bot.get_me()
        member=await bot.get_chat_member(chat.id, me.id)
        can_post = getattr(member, "can_post_messages", False)
        if not can_post:
            await m.answer("❌ البوت ليس لديه صلاحية نشر الرسائل في هذه القناة. أضفه مشرفاً وفعّل صلاحية نشر الرسائل ثم أعد المحاولة.")
            return
        title=chat.title or chat.username or str(chat.id)
        c=db()
        c.execute(
            "INSERT OR REPLACE INTO partner_channels(chat_id,title,active) VALUES(?,?,1)",
            (str(chat.id),title))
        c.commit(); c.close()
        await state.clear()
        await m.answer(f"✅ تمت إضافة القناة الشريكة:\n<b>{html.escape(title)}</b>\n\nيمكن الآن استخدامها ضمن شبكة النشر.",reply_markup=main_kb())
    except Exception as e:
        log.exception("partner add")
        await m.answer("❌ تعذر الوصول إلى القناة. تأكد من أن @username صحيح وأن البوت مشرف فيها.")

@dp.callback_query(F.data.startswith("partner:toggle:"))
async def partner_toggle(q:CallbackQuery):
    if q.from_user.id != ADMIN_ID:
        return await q.answer("غير مسموح", show_alert=True)
    pid=int(q.data.split(":")[2])
    c=db(); c.execute("UPDATE partner_channels SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(pid,)); c.commit(); c.close()
    await q.answer("تم تغيير الحالة")
    await adm_partners(q)

@dp.callback_query(F.data=="partner:delete_menu")
async def partner_delete_menu(q:CallbackQuery):
    if q.from_user.id != ADMIN_ID:
        return await q.answer("غير مسموح", show_alert=True)
    c=db(); rows=c.execute("SELECT id,chat_id,title FROM partner_channels ORDER BY id DESC").fetchall(); c.close()
    buttons=[[InlineKeyboardButton(text=f"🗑️ {r['title'] or r['chat_id']}",callback_data=f"partner:delete:{r['id']}")] for r in rows]
    buttons.append([InlineKeyboardButton(text="↩️ رجوع",callback_data="adm:partners")])
    await q.message.edit_text("🗑️ <b>اختر القناة المراد حذفها:</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("partner:delete:"))
async def partner_delete(q:CallbackQuery):
    if q.from_user.id != ADMIN_ID:
        return await q.answer("غير مسموح", show_alert=True)
    pid=int(q.data.split(":")[2])
    c=db(); c.execute("DELETE FROM partner_channels WHERE id=?",(pid,)); c.commit(); c.close()
    await q.answer("تم الحذف")
    await adm_partners(q)

@dp.callback_query(F.data=="adm:stats")
async def adm_stats(q:CallbackQuery):
    if q.from_user.id!=ADMIN_ID:return
    c=db()
    users=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    orders=c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
    pending=c.execute("SELECT COUNT(*) n FROM orders WHERE status='pending'").fetchone()["n"]
    topups=c.execute("SELECT COUNT(*) n FROM topups WHERE status='pending'").fetchone()["n"]
    c.close()
    await q.message.edit_text(f"📊 <b>الإحصائيات</b>\nالمستخدمون: {users}\nالطلبات: {orders}\nطلبات الترويج المعلقة: {pending}\nطلبات الشحن المعلقة: {topups}",reply_markup=admin_kb())

@dp.callback_query(F.data=="adm:topups")
async def adm_topups(q:CallbackQuery):
    if q.from_user.id!=ADMIN_ID:return
    c=db(); rows=c.execute("SELECT id,user_id,amount,operation,status FROM topups ORDER BY id DESC LIMIT 15").fetchall(); c.close()
    text="💳 <b>آخر طلبات الشحن</b>\n\n"+("\n".join([f"#{r['id']} | {r['user_id']} | {r['amount']} | {r['status']}" for r in rows]) or "لا توجد طلبات")
    await q.message.edit_text(text,reply_markup=admin_kb())

@dp.callback_query(F.data=="adm:orders")
async def adm_orders(q:CallbackQuery):
    if q.from_user.id!=ADMIN_ID:return
    c=db(); rows=c.execute("SELECT id,user_id,package,target,price,status FROM orders ORDER BY id DESC LIMIT 15").fetchall(); c.close()
    text="📣 <b>آخر طلبات الترويج</b>\n\n"+("\n".join([f"#{r['id']} | {r['user_id']} | {r['target']} | {r['status']}" for r in rows]) or "لا توجد طلبات")
    await q.message.edit_text(text,reply_markup=admin_kb())


async def broadcast_to_partners(text: str, buttons=None):
    """Publish an approved campaign to active partner channels."""
    c=db()
    rows=c.execute("SELECT id,chat_id,title FROM partner_channels WHERE active=1").fetchall()
    c.close()
    sent=0
    failed=[]
    for r in rows:
        try:
            await bot.send_message(r["chat_id"], text, reply_markup=buttons)
            sent += 1
        except Exception as e:
            failed.append((r["id"], str(e)))
            log.warning("Partner channel %s failed: %s", r["chat_id"], e)
    return sent, failed

async def admin_order_action(q:CallbackQuery, approve:bool):
    if q.from_user.id!=ADMIN_ID:return await q.answer("غير مسموح",show_alert=True)
    oid=int(q.data.split(":")[1]); c=db()
    r=c.execute("SELECT user_id,price,status FROM orders WHERE id=?",(oid,)).fetchone()
    if not r or r["status"]!="pending": c.close(); return await q.answer("تمت المعالجة")
    if approve:
        c.execute("UPDATE orders SET status='approved' WHERE id=?",(oid,))
        order=c.execute("SELECT target,package FROM orders WHERE id=?",(oid,)).fetchone()
        c.commit()
        c.close()
        ad_text=(
            "📢 <b>إعلان ممول</b>\n\n"
            "🚀 اكتشف الآن هذا البوت/القناة:\n"
            f"<code>{html.escape(order['target'])}</code>\n\n"
            "اضغط الرابط للدخول مباشرة."
        )
        sent, failed = await broadcast_to_partners(ad_text)
        msg=f"✅ تم اعتماد طلب الترويج #{oid}.\n📣 تم إرسال الإعلان إلى <b>{sent}</b> قناة شريكة."
        if failed:
            msg += f"\n⚠️ تعذر النشر في {len(failed)} قناة."
    else:
        c.execute("UPDATE orders SET status='rejected' WHERE id=?",(oid,))
        c.execute("UPDATE users SET balance=balance+? WHERE id=?",(r["price"],r["user_id"]))
        msg=f"❌ تم رفض الطلب #{oid} وإعادة {r['price']} ل.س إلى رصيدك."
        c.commit(); c.close()
    await q.message.edit_text(msg); await bot.send_message(r["user_id"],msg)

@dp.callback_query(F.data.startswith("approve:"))
async def approve(q:CallbackQuery): await admin_order_action(q,True)
@dp.callback_query(F.data.startswith("reject:"))
async def reject(q:CallbackQuery): await admin_order_action(q,False)

async def health(request):
    return web.json_response({"ok":True,"service":"telegram-promo-bot"})

async def start_web():
    app=web.Application(); app.router.add_get("/",health); app.router.add_get("/health",health)
    runner=web.AppRunner(app); await runner.setup()
    site=web.TCPSite(runner,"0.0.0.0",PORT); await site.start()
    log.info("Health server listening on %s",PORT)

async def main():
    init_db()
    await start_web()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__=="__main__":
    asyncio.run(main())

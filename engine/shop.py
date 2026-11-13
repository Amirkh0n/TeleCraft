"""Shop bots: catalog (category -> product -> variants), cart, checkout (pickup/delivery, cash or card
receipt), order tracking. Admin side lives in ``engine/shop_admin.py`` (``sa:`` callbacks, ``sa_*`` states);
the customer side uses ``sh:`` callbacks and ``sh_*`` states.

Stock is decremented atomically when the order is placed (``UPDATE ... WHERE stock >= qty``) and given
back when an active order is cancelled.
"""
from sqlalchemy import func, select, update
from telegram import (
    InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, InputMediaPhoto, KeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.error import Forbidden, TelegramError

from core.logger import get_logger
from engine import cinema, shop_admin, shop_logic as logic, subscription
from engine.audience import touch_user
from engine.booking_time import parse_phone, utcnow
from models.shop import (
    ACTIVE_STATUSES, DELIVERY, PAID_NO, PAID_PENDING, PAID_REJECTED, PAID_YES, PAY_CARD, PAY_CASH, PICKUP,
    ST_CANCELLED, ST_CONFIRMED, ST_DONE, ST_NEW, ST_PREPARING, ST_SHIPPING,
    CartItem, Order, OrderItem, ShopCategory, ShopImage, ShopProduct, ShopSettings, ShopVariant,
)
from models.user_sessions import UserSession

logger = get_logger("shop")
esc = cinema.esc
show = cinema._show
money = logic.fmt_money

WELCOME = ("🛍 <b>Do‘konimizga xush kelibsiz!</b>\n\nKatalogdan mahsulot tanlang, savatga qo‘shing va buyurtma bering — "
           "yetkazib beramiz yoki o‘zingiz olib ketasiz.")
PAGE = 6
STATUS_NAMES = {ST_NEW: "🆕 Yangi", ST_CONFIRMED: "✅ Tasdiqlandi", ST_PREPARING: "👨‍🍳 Tayyorlanmoqda",
                ST_SHIPPING: "🚚 Yo‘lda", ST_DONE: "✔️ Yetkazildi", ST_CANCELLED: "❌ Bekor qilindi"}
PAY_NAMES = {PAID_NO: "to‘lanmagan", PAID_PENDING: "chek tekshirilmoqda", PAID_YES: "to‘langan", PAID_REJECTED: "chek rad etilgan"}


def status_name(order) -> str:
    if order.status == ST_SHIPPING and order.delivery_type == PICKUP:
        return "🏪 Olib ketishga tayyor"
    if order.status == ST_DONE and order.delivery_type == PICKUP:
        return "✔️ Topshirildi"
    return STATUS_NAMES.get(order.status, order.status)


# ------------------------------------------------------------------ basics

async def get_settings(session, bot_id: int) -> ShopSettings:
    st = (await session.execute(select(ShopSettings).where(ShopSettings.bot_id == bot_id))).scalar_one_or_none()
    if st is None:
        st = ShopSettings(bot_id=bot_id)
        session.add(st)
        await session.commit()
    return st


async def ensure_setup(session, bot) -> ShopSettings:
    st = await get_settings(session, bot.id)
    await cinema.ensure_start_menu(session, bot, WELCOME)
    return st


async def session_of(session, bot, user_id: int) -> UserSession:
    from engine.actions import get_user_session
    us = await get_user_session(session, bot.id, user_id)
    if us is None:
        menu = await cinema.ensure_start_menu(session, bot, WELCOME)
        us = UserSession(bot_id=bot.id, tg_user_id=user_id, current_menu_id=menu.id)
        session.add(us)
        await session.commit()
    return us


async def set_state(session, us, state=None, data=None):
    us.state, us.state_data = state, data
    await session.commit()


def display_name(user: dict) -> str:
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
    return (name or user.get("username") or "Mijoz")[:120]


async def images_of(session, product_id: int) -> list:
    return list((await session.execute(
        select(ShopImage).where(ShopImage.product_id == product_id).order_by(ShopImage.position, ShopImage.id))).scalars().all())


async def variants_of(session, product_id: int) -> list:
    return list((await session.execute(
        select(ShopVariant).where(ShopVariant.product_id == product_id).order_by(ShopVariant.position, ShopVariant.id))).scalars().all())


async def visible_product(session, bot, product_id: int, admin: bool = False):
    p = await session.get(ShopProduct, product_id)
    if p is None or p.bot_id != bot.id:
        return None
    if admin:
        return p
    cat = await session.get(ShopCategory, p.category_id)
    return p if p.is_active and cat and cat.is_active else None


# ------------------------------------------------------------------ home, catalog

async def cart_count(session, bot, uid: int) -> int:
    return (await session.execute(select(func.coalesce(func.sum(CartItem.qty), 0)).where(
        CartItem.bot_id == bot.id, CartItem.tg_user_id == uid))).scalar() or 0


async def home_markup(session, bot, uid: int) -> Markup:
    n = await cart_count(session, bot, uid)
    rows = [[Btn("🛍 Katalog", callback_data="sh:cat"), Btn(f"🛒 Savat{f' ({n})' if n else ''}", callback_data="sh:cart")],
            [Btn("📦 Buyurtmalarim", callback_data="sh:orders:0"), Btn("🔎 Qidirish", callback_data="sh:find")],
            [Btn("☎️ Aloqa", callback_data="sh:contact")]]
    if await cinema.is_admin(session, bot, uid):
        rows.append([Btn("🛠 Admin panel", callback_data="sa:home")])
    return Markup(rows)


async def show_home(tg, callback, chat_id, session, bot):
    menu = await cinema.ensure_start_menu(session, bot, WELCOME)
    await show(tg, callback, chat_id, menu.message_text or WELCOME, await home_markup(session, bot, chat_id))


async def show_categories(tg, callback, chat_id, session, bot, admin: bool):
    conds = [ShopCategory.bot_id == bot.id] + ([] if admin else [ShopCategory.is_active.is_(True)])
    cats = (await session.execute(select(ShopCategory).where(*conds).order_by(ShopCategory.position, ShopCategory.id))).scalars().all()
    if not cats:
        return await show(tg, callback, chat_id, "Katalog hozircha bo‘sh. Tez orada mahsulotlar qo‘shiladi!",
                          Markup([[Btn("🏠 Bosh sahifa", callback_data="sh:home")]]))
    kb = [[Btn(f"{'' if c.is_active else '🙈 '}{c.title}"[:60], callback_data=f"sh:c:{c.id}:0")] for c in cats]
    kb.append([Btn("🛒 Savat", callback_data="sh:cart"), Btn("🏠 Bosh sahifa", callback_data="sh:home")])
    await show(tg, callback, chat_id, "🛍 <b>Katalog</b>\nBo‘limni tanlang:", Markup(kb))


def product_button(p) -> Btn:
    out = " ❌" if p.stock is not None and p.stock <= 0 else ""
    return Btn(f"{p.title} · {money(p.price)}{out}"[:60], callback_data=f"sh:p:{p.id}")


async def show_products(tg, callback, chat_id, session, bot, cat, page: int, admin: bool):
    conds = [ShopProduct.category_id == cat.id] + ([] if admin else [ShopProduct.is_active.is_(True)])
    total = (await session.execute(select(func.count(ShopProduct.id)).where(*conds))).scalar() or 0
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    rows = (await session.execute(select(ShopProduct).where(*conds).order_by(ShopProduct.position, ShopProduct.id)
                                  .limit(PAGE).offset(page * PAGE))).scalars().all()
    kb = [[product_button(p)] for p in rows]
    nav = ([Btn("⬅️", callback_data=f"sh:c:{cat.id}:{page - 1}")] if page else []) + ([Btn("➡️", callback_data=f"sh:c:{cat.id}:{page + 1}")] if page < pages - 1 else [])
    if nav:
        kb.append(nav)
    kb.append([Btn("⬅️ Katalog", callback_data="sh:cat"), Btn("🛒 Savat", callback_data="sh:cart")])
    await show(tg, callback, chat_id, f"📂 <b>{esc(cat.title)}</b>" if rows else f"📂 <b>{esc(cat.title)}</b>\nBu bo‘limda hozircha mahsulot yo‘q.", Markup(kb))


async def search(tg, chat_id, session, bot, query: str):
    q = f"%{query.strip()[:60]}%"
    rows = (await session.execute(
        select(ShopProduct).join(ShopCategory, ShopCategory.id == ShopProduct.category_id)
        .where(ShopProduct.bot_id == bot.id, ShopProduct.is_active.is_(True), ShopCategory.is_active.is_(True),
               ShopProduct.title.ilike(q)).order_by(ShopProduct.id).limit(10))).scalars().all()
    kb = [[product_button(p)] for p in rows] + [[Btn("🛍 Katalog", callback_data="sh:cat"), Btn("🏠 Bosh sahifa", callback_data="sh:home")]]
    await tg.send_message(chat_id=chat_id, text="🔎 Topilgan mahsulotlar:" if rows else "Hech narsa topilmadi. Boshqa so‘z yozing.",
                          reply_markup=Markup(kb))


# ------------------------------------------------------------------ product card

def product_caption(p, variants, *, admin_note: str = "") -> str:
    lines = [f"<b>{esc(p.title)}</b>"]
    price = money(p.price) if not variants or all(v.price is None for v in variants) else \
        "dan " + money(min(logic.unit_price(p, v) for v in variants))
    if p.old_price and p.old_price > p.price and not variants:
        lines.append(f"<s>{money(p.old_price)}</s> → <b>{price}</b> (−{logic.discount_percent(p)}%)")
    else:
        lines.append(f"<b>{price}</b>")
    if not variants:
        lines.append(logic.stock_label(p.stock))
    if p.description:
        lines.append("\n" + esc(p.description[:600]))
    if admin_note:
        lines.append(admin_note)
    return "\n".join(lines)[:1000]


async def show_product(tg, callback, chat_id, session, bot, p, admin: bool):
    variants = await variants_of(session, p.id)
    images = await images_of(session, p.id)
    kb = []
    if variants:
        for v in variants:
            sold_out = v.stock is not None and v.stock <= 0
            label = f"{'❌ ' if sold_out else ''}{v.name} — {money(logic.unit_price(p, v))}"
            kb.append([Btn(label[:60], callback_data=f"sh:add:{p.id}:{v.id}")])
    elif p.stock is None or p.stock > 0:
        kb.append([Btn("🛒 Savatga qo‘shish", callback_data=f"sh:add:{p.id}")])
    if len(images) > 1:
        kb.append([Btn(f"🖼 Barcha rasmlar ({len(images)})", callback_data=f"sh:pi:{p.id}")])
    kb.append([Btn("🛒 Savat", callback_data="sh:cart"), Btn("⬅️ Orqaga", callback_data=f"sh:c:{p.category_id}:0")])
    if admin:
        kb.append([Btn("🛠 Tahrirlash", callback_data=f"sa:p:{p.id}")])
    text, markup = product_caption(p, variants, admin_note="" if p.is_active else "\n🙈 <i>Yashirilgan</i>"), Markup(kb)
    if images:
        try:
            await tg.send_photo(chat_id=chat_id, photo=images[0].file_id, caption=text, parse_mode="HTML", reply_markup=markup)
            return
        except Forbidden:
            raise
        except TelegramError as exc:
            logger.info("product photo not sent: %s", exc)
    await show(tg, callback, chat_id, text, markup)


async def send_album(tg, chat_id, session, p):
    images = (await images_of(session, p.id))[:10]
    try:
        await tg.send_media_group(chat_id=chat_id, media=[InputMediaPhoto(media=i.file_id) for i in images])
    except Forbidden:
        raise
    except TelegramError as exc:
        logger.info("album not sent: %s", exc)


# ------------------------------------------------------------------ cart

async def load_cart(session, bot, uid: int):
    """-> (lines, notes). Lines are dicts; invalid rows are dropped and over-stock quantities clamped."""
    items = (await session.execute(select(CartItem).where(CartItem.bot_id == bot.id, CartItem.tg_user_id == uid)
                                   .order_by(CartItem.id))).scalars().all()
    lines, notes = [], []
    for it in items:
        p = await visible_product(session, bot, it.product_id)
        v = await session.get(ShopVariant, it.variant_id) if it.variant_id else None
        if p is None or (it.variant_id and (v is None or v.product_id != p.id)):
            await session.delete(it)
            notes.append("Ba’zi mahsulotlar sotuvdan olingani uchun savatdan chiqarildi.")
            continue
        cap = logic.available(p, v)
        if cap is not None and it.qty > cap:
            if cap <= 0:
                await session.delete(it)
                notes.append(f"«{p.title}» tugagani uchun savatdan chiqarildi.")
                continue
            it.qty = cap
            notes.append(f"«{p.title}» soni qoldiqqa moslandi ({cap} ta).")
        price = logic.unit_price(p, v)
        lines.append({"item": it, "product": p, "variant": v, "price": price, "qty": it.qty, "sum": price * it.qty,
                      "title": p.title + (f" ({v.name})" if v else "")})
    if notes:
        await session.commit()
    return lines, list(dict.fromkeys(notes))


async def show_cart(tg, callback, chat_id, session, bot):
    lines, notes = await load_cart(session, bot, chat_id)
    if not lines:
        text = "🛒 Savatingiz bo‘sh."
        if notes:
            text += "\n\n" + "\n".join(f"ℹ️ {esc(n)}" for n in notes)
        return await show(tg, callback, chat_id, text, Markup([[Btn("🛍 Katalog", callback_data="sh:cat")], [Btn("🏠 Bosh sahifa", callback_data="sh:home")]]))
    st = await get_settings(session, bot.id)
    subtotal = sum(l["sum"] for l in lines)
    out = ["🛒 <b>Savat</b>\n"]
    kb = []
    for n, l in enumerate(lines, 1):
        out.append(f"{n}. {esc(l['title'])}\n    {l['qty']} × {money(l['price'])} = <b>{money(l['sum'])}</b>")
        iid = l["item"].id
        kb.append([Btn("➖", callback_data=f"sh:ci:{iid}:d"), Btn(f"{n}. {l['qty']} ta", callback_data="sh:noop"),
                   Btn("➕", callback_data=f"sh:ci:{iid}:u"), Btn("🗑", callback_data=f"sh:ci:{iid}:x")])
    out.append(f"\nJami: <b>{money(subtotal)}</b>")
    if st.min_order and subtotal < st.min_order:
        out.append(f"⚠️ Minimal buyurtma: {money(st.min_order)}")
    if st.delivery_fee:
        free = f" ({money(st.free_delivery_from)} dan bepul)" if st.free_delivery_from else ""
        out.append(f"🚚 Yetkazish: {money(st.delivery_fee)}{free}")
    out += [f"ℹ️ {esc(n)}" for n in notes]
    kb.append([Btn("✅ Buyurtma berish", callback_data="sh:co")])
    kb.append([Btn("🧹 Tozalash", callback_data="sh:cclear"), Btn("🛍 Davom etish", callback_data="sh:cat")])
    await show(tg, callback, chat_id, "\n".join(out), Markup(kb))


async def add_to_cart(tg, chat_id, session, bot, p, variant_id):
    variants = await variants_of(session, p.id)
    v = next((x for x in variants if x.id == variant_id), None) if variant_id else None
    if variants and v is None:
        return await tg.send_message(chat_id=chat_id, text="Variantni tanlang.")
    if not variants and variant_id:
        return
    cap = logic.available(p, v)
    existing = (await session.execute(select(CartItem).where(
        CartItem.bot_id == bot.id, CartItem.tg_user_id == chat_id, CartItem.product_id == p.id,
        CartItem.variant_id.is_(None) if v is None else CartItem.variant_id == v.id))).scalars().first()
    qty = (existing.qty if existing else 0) + 1
    if cap is not None and qty > cap:
        return await tg.send_message(chat_id=chat_id, text="❌ Bu mahsulot tugagan." if cap <= 0 else f"❌ Omborda atigi {cap} ta bor.")
    if existing:
        existing.qty = qty
    else:
        session.add(CartItem(bot_id=bot.id, tg_user_id=chat_id, product_id=p.id, variant_id=v.id if v else None, qty=1))
    await session.commit()
    name = p.title + (f" ({v.name})" if v else "")
    await tg.send_message(chat_id=chat_id, parse_mode="HTML", text=f"✅ <b>{esc(name)}</b> savatga qo‘shildi ({qty} ta).",
                          reply_markup=Markup([[Btn("🛒 Savat", callback_data="sh:cart"), Btn("🛍 Davom etish", callback_data=f"sh:c:{p.category_id}:0")]]))


async def change_cart_item(tg, callback, chat_id, session, bot, item_id: int, op: str):
    it = await session.get(CartItem, item_id)
    if it is None or it.bot_id != bot.id or it.tg_user_id != chat_id:
        return await show_cart(tg, callback, chat_id, session, bot)
    if op == "x" or (op == "d" and it.qty <= 1):
        await session.delete(it)
    elif op == "d":
        it.qty -= 1
    elif op == "u":
        p = await session.get(ShopProduct, it.product_id)
        v = await session.get(ShopVariant, it.variant_id) if it.variant_id else None
        cap = logic.available(p, v) if p else 0
        if cap is not None and it.qty + 1 > cap:
            await session.commit()
            await tg.send_message(chat_id=chat_id, text=f"❌ Omborda atigi {cap} ta bor.")
            return await show_cart(tg, callback, chat_id, session, bot)
        it.qty += 1
    await session.commit()
    await show_cart(tg, callback, chat_id, session, bot)


# ------------------------------------------------------------------ checkout

async def start_checkout(tg, callback, chat_id, session, bot, us):
    lines, notes = await load_cart(session, bot, chat_id)
    st = await get_settings(session, bot.id)
    if not lines:
        return await show_cart(tg, callback, chat_id, session, bot)
    subtotal = sum(l["sum"] for l in lines)
    if st.min_order and subtotal < st.min_order:
        await tg.send_message(chat_id=chat_id, text=f"⚠️ Minimal buyurtma summasi {money(st.min_order)}.")
        return await show_cart(tg, callback, chat_id, session, bot)
    if not (st.delivery_enabled or st.pickup_enabled) or not (st.cash_enabled or (st.card_enabled and st.card_number)):
        return await show(tg, callback, chat_id, "Hozircha buyurtma qabul qilinmayapti. Keyinroq urinib ko‘ring.",
                          Markup([[Btn("⬅️ Savat", callback_data="sh:cart")]]))
    last = (await session.execute(select(Order.phone).where(Order.bot_id == bot.id, Order.tg_user_id == chat_id)
                                  .order_by(Order.id.desc()).limit(1))).scalar_one_or_none()
    await set_state(session, us, "sh_phone", {})
    keys = [[KeyboardButton("📞 Raqamni ulashish", request_contact=True)]]
    if last:
        keys.append([KeyboardButton(last)])
    await tg.send_message(chat_id=chat_id, text="📞 Telefon raqamingizni yuboring (tugma orqali yoki yozing, masalan +998901234567). Bekor qilish: /cancel",
                          reply_markup=ReplyKeyboardMarkup(keys, resize_keyboard=True, one_time_keyboard=True))


async def ask_delivery(tg, chat_id, session, bot, us, data):
    st = await get_settings(session, bot.id)
    options = ([(DELIVERY, "🚚 Yetkazib berish")] if st.delivery_enabled else []) + ([(PICKUP, "🏪 Olib ketaman")] if st.pickup_enabled else [])
    if len(options) == 1:
        return await choose_delivery(tg, chat_id, session, bot, us, data, options[0][0])
    await set_state(session, us, "sh_flow", data)
    await tg.send_message(chat_id=chat_id, text="Qanday qabul qilasiz?",
                          reply_markup=Markup([[Btn(label, callback_data=f"sh:od:{key}")] for key, label in options]))


async def choose_delivery(tg, chat_id, session, bot, us, data, dtype):
    data["dtype"] = dtype
    if dtype == DELIVERY:
        await set_state(session, us, "sh_addr", data)
        return await tg.send_message(
            chat_id=chat_id, text="📍 Yetkazish manzilini yozing yoki lokatsiya yuboring.",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📍 Lokatsiyani yuborish", request_location=True)]], resize_keyboard=True, one_time_keyboard=True))
    await ask_payment(tg, chat_id, session, bot, us, data)


async def ask_payment(tg, chat_id, session, bot, us, data):
    st = await get_settings(session, bot.id)
    options = ([(PAY_CASH, "💵 Naqd pul")] if st.cash_enabled else []) + ([(PAY_CARD, "💳 Karta (chek bilan)")] if st.card_enabled and st.card_number else [])
    if len(options) == 1:
        return await choose_payment(tg, chat_id, session, bot, us, data, options[0][0])
    await set_state(session, us, "sh_flow", data)
    await tg.send_message(chat_id=chat_id, text="To‘lov usulini tanlang:",
                          reply_markup=Markup([[Btn(label, callback_data=f"sh:op:{key}")] for key, label in options]))


async def choose_payment(tg, chat_id, session, bot, us, data, method):
    data["pay"] = method
    await set_state(session, us, "sh_flow", data)
    lines, _ = await load_cart(session, bot, chat_id)
    st = await get_settings(session, bot.id)
    subtotal = sum(l["sum"] for l in lines)
    fee = logic.delivery_cost(data["dtype"], subtotal, fee=st.delivery_fee, free_from=st.free_delivery_from)
    out = ["🧾 <b>Buyurtmani tasdiqlang</b>\n"]
    out += [f"• {esc(l['title'])} — {l['qty']} × {money(l['price'])}" for l in lines]
    out.append(f"\nMahsulotlar: {money(subtotal)}")
    if data["dtype"] == DELIVERY:
        out.append(f"Yetkazish: {money(fee) if fee else 'bepul'}")
    out.append(f"<b>Jami: {money(subtotal + fee)}</b>\n")
    out.append(f"📞 {esc(data['phone'])}")
    out.append(f"🚚 Yetkazish: {esc(data.get('addr') or 'lokatsiya')}" if data["dtype"] == DELIVERY else "🏪 Olib ketish")
    out.append("💳 Karta (chek yuborasiz)" if method == PAY_CARD else "💵 Naqd pul")
    await tg.send_message(chat_id=chat_id, text="\n".join(out), parse_mode="HTML",
                          reply_markup=Markup([[Btn("✅ Tasdiqlash", callback_data="sh:ok")], [Btn("✖️ Bekor qilish", callback_data="sh:home")]]))


async def place_order(tg, callback, chat_id, session, bot, us, user: dict):
    data = us.state_data or {}
    if us.state != "sh_flow" or not all(k in data for k in ("phone", "dtype", "pay")):
        await set_state(session, us)
        return await show_cart(tg, callback, chat_id, session, bot)
    lines, notes = await load_cart(session, bot, chat_id)
    st = await get_settings(session, bot.id)
    if not lines:
        await set_state(session, us)
        return await show_cart(tg, callback, chat_id, session, bot)
    if data["pay"] == PAY_CARD and not (st.card_enabled and st.card_number) or data["pay"] == PAY_CASH and not st.cash_enabled:
        await set_state(session, us)
        return await tg.send_message(chat_id=chat_id, text="To‘lov usuli hozir mavjud emas. Qaytadan urinib ko‘ring.")
    subtotal = sum(l["sum"] for l in lines)
    if st.min_order and subtotal < st.min_order:
        await set_state(session, us)
        return await tg.send_message(chat_id=chat_id, text=f"⚠️ Minimal buyurtma summasi {money(st.min_order)}.")
    # Reserve stock atomically; any shortage rolls the whole order back.
    for l in lines:
        target = ShopVariant if l["variant"] else ShopProduct
        tid = l["variant"].id if l["variant"] else l["product"].id
        if logic.available(l["product"], l["variant"]) is None:
            continue
        res = await session.execute(update(target).where(target.id == tid, target.stock >= l["qty"]).values(stock=target.stock - l["qty"]))
        if res.rowcount != 1:
            await session.rollback()
            await set_state(session, us)
            await tg.send_message(chat_id=chat_id, parse_mode="HTML", text=f"❌ <b>{esc(l['title'])}</b> yetarli emas. Savatni tekshiring.")
            return await show_cart(tg, None, chat_id, session, bot)
    fee = logic.delivery_cost(data["dtype"], subtotal, fee=st.delivery_fee, free_from=st.free_delivery_from)
    order = Order(bot_id=bot.id, tg_user_id=chat_id, user_name=display_name(user), username=user.get("username"),
                  phone=data["phone"], delivery_type=data["dtype"], address=data.get("addr"), lat=data.get("lat"), lon=data.get("lon"),
                  payment_method=data["pay"], subtotal=subtotal, delivery_fee=fee, total=subtotal + fee)
    session.add(order)
    await session.flush()
    for l in lines:
        session.add(OrderItem(order_id=order.id, product_id=l["product"].id, variant_id=l["variant"].id if l["variant"] else None,
                              title=l["title"], price=l["price"], qty=l["qty"]))
        await session.delete(l["item"])
    await session.commit()
    await set_state(session, us)
    if order.payment_method == PAY_CARD:
        await set_state(session, us, "sh_receipt", {"order": order.id})
        info = [f"✅ Buyurtma <b>#{order.id}</b> qabul qilindi.\n", f"💳 To‘lov: <b>{money(order.total)}</b>", f"Karta: <code>{esc(st.card_number)}</code>"]
        if st.card_holder:
            info.append(f"Egasi: {esc(st.card_holder)}")
        if st.pay_note:
            info += ["", esc(st.pay_note)]
        info += ["", "O‘tkazgach <b>chek rasmini</b> shu yerga yuboring."]
        await tg.send_message(chat_id=chat_id, parse_mode="HTML", text="\n".join(info))
    else:
        await tg.send_message(chat_id=chat_id, parse_mode="HTML", text=f"✅ Buyurtma <b>#{order.id}</b> qabul qilindi. Tez orada bog‘lanamiz!",
                              reply_markup=Markup([[Btn("📦 Buyurtmalarim", callback_data="sh:orders:0"), Btn("🏠 Bosh sahifa", callback_data="sh:home")]]))
    await shop_admin.notify_order(tg, session, bot, order)


async def on_receipt(bot, message, session, tg, us, user: dict) -> bool:
    uid = user["id"]
    order = await session.get(Order, (us.state_data or {}).get("order"))
    if order is None or order.bot_id != bot.id or order.tg_user_id != uid or order.payment_method != PAY_CARD \
            or order.status == ST_CANCELLED or order.payment_status not in (PAID_NO, PAID_REJECTED):
        await set_state(session, us)
        return False
    if message.get("photo"):
        file_id, kind = message["photo"][-1]["file_id"], "photo"
    elif (message.get("document") or {}).get("mime_type", "").startswith("image/"):
        file_id, kind = message["document"]["file_id"], "document"
    else:
        await tg.send_message(chat_id=uid, text="📸 Chekning rasmini yuboring. Bekor qilish: /cancel")
        return True
    order.receipt_file_id, order.receipt_type, order.payment_status = file_id, kind, PAID_PENDING
    order.updated_at = utcnow()
    await session.commit()
    await set_state(session, us)
    await tg.send_message(chat_id=uid, text="✅ Chek yuborildi. Admin tekshirgach xabar beramiz.",
                          reply_markup=Markup([[Btn("📦 Buyurtmalarim", callback_data="sh:orders:0")]]))
    await shop_admin.notify_receipt(tg, session, bot, order)
    return True


# ------------------------------------------------------------------ orders

async def order_items(session, order_id: int) -> list:
    return list((await session.execute(select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id))).scalars().all())


def order_text(order, items, *, admin: bool = False) -> str:
    out = [f"📦 <b>Buyurtma #{order.id}</b> — {status_name(order)}"]
    if admin:
        who = f"👤 {esc(order.user_name)}" + (f" @{esc(order.username)}" if order.username else "") + f"  <code>{order.tg_user_id}</code>"
        out += [who, f"📞 {esc(order.phone)}"]
    out.append("")
    out += [f"• {esc(i.title)} — {i.qty} × {money(i.price)}" for i in items]
    out.append(f"\nMahsulotlar: {money(order.subtotal)}")
    if order.delivery_type == DELIVERY:
        out.append(f"Yetkazish: {money(order.delivery_fee) if order.delivery_fee else 'bepul'}")
    out.append(f"<b>Jami: {money(order.total)}</b>")
    if order.delivery_type == DELIVERY:
        place = esc(order.address) if order.address else ""
        if order.lat is not None:
            place += f"\n📍 https://maps.google.com/?q={order.lat},{order.lon}"
        out.append(f"\n🚚 {place or 'Yetkazish'}")
    else:
        out.append("\n🏪 Olib ketish")
    out.append(f"{'💳 Karta' if order.payment_method == PAY_CARD else '💵 Naqd'} — {PAY_NAMES.get(order.payment_status, '')}")
    return "\n".join(out)


async def show_orders(tg, callback, chat_id, session, bot, page: int):
    total = (await session.execute(select(func.count(Order.id)).where(Order.bot_id == bot.id, Order.tg_user_id == chat_id))).scalar() or 0
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    rows = (await session.execute(select(Order).where(Order.bot_id == bot.id, Order.tg_user_id == chat_id)
                                  .order_by(Order.id.desc()).limit(PAGE).offset(page * PAGE))).scalars().all()
    if not rows:
        return await show(tg, callback, chat_id, "Sizda hali buyurtma yo‘q.", Markup([[Btn("🛍 Katalog", callback_data="sh:cat")], [Btn("🏠 Bosh sahifa", callback_data="sh:home")]]))
    kb = [[Btn(f"#{o.id} · {money(o.total)} · {status_name(o)}"[:60], callback_data=f"sh:o:{o.id}")] for o in rows]
    nav = ([Btn("⬅️", callback_data=f"sh:orders:{page - 1}")] if page else []) + ([Btn("➡️", callback_data=f"sh:orders:{page + 1}")] if page < pages - 1 else [])
    if nav:
        kb.append(nav)
    kb.append([Btn("🏠 Bosh sahifa", callback_data="sh:home")])
    await show(tg, callback, chat_id, f"📦 <b>Buyurtmalarim</b> ({total})", Markup(kb))


async def show_order(tg, callback, chat_id, session, bot, order):
    kb = []
    if order.payment_method == PAY_CARD and order.payment_status in (PAID_NO, PAID_REJECTED) and order.status != ST_CANCELLED:
        kb.append([Btn("📸 Chek yuborish", callback_data=f"sh:orcpt:{order.id}")])
    if order.status == ST_NEW and order.payment_status != PAID_YES:
        kb.append([Btn("🚫 Bekor qilish", callback_data=f"sh:oc:{order.id}")])
    kb.append([Btn("⬅️ Buyurtmalar", callback_data="sh:orders:0")])
    await show(tg, callback, chat_id, order_text(order, await order_items(session, order.id)), Markup(kb))


async def restock(session, order):
    for it in await order_items(session, order.id):
        if it.variant_id:
            await session.execute(update(ShopVariant).where(ShopVariant.id == it.variant_id, ShopVariant.stock.is_not(None))
                                  .values(stock=ShopVariant.stock + it.qty))
        elif it.product_id:
            await session.execute(update(ShopProduct).where(ShopProduct.id == it.product_id, ShopProduct.stock.is_not(None))
                                  .values(stock=ShopProduct.stock + it.qty))


async def cancel_order(session, order) -> bool:
    """Cancels an active order once and gives the stock back. False when it was already closed."""
    if order.status not in ACTIVE_STATUSES:
        return False
    order.status, order.updated_at = ST_CANCELLED, utcnow()
    await restock(session, order)
    await session.commit()
    return True


# ------------------------------------------------------------------ updates

async def handle(bot, update_, session, tg):
    if update_.get("callback_query"):
        await _on_callback(bot, update_["callback_query"], session, tg)
    elif update_.get("message"):
        await _on_message(bot, update_["message"], session, tg)


async def _on_callback(bot, callback, session, tg):
    user = callback["from"]
    uid = user["id"]
    data = callback.get("data") or ""
    await touch_user(session, bot.id, user)
    admin = await cinema.is_admin(session, bot, uid)
    if data.startswith("sa:"):
        if admin:
            await shop_admin.on_callback(bot, callback, session, tg, await session_of(session, bot, uid))
        return
    if data == subscription.CHECK_CALLBACK:
        if await subscription.gate(tg, bot, uid, session, use_cache=False):
            await show_home(tg, None, uid, session, bot)
        return
    if not data.startswith("sh:"):
        return
    if not admin and not await subscription.gate(tg, bot, uid, session):
        return
    us = await session_of(session, bot, uid)
    parts = data.split(":")
    act, arg = parts[1], parts[2:]
    num = [int(p) for p in arg if p.lstrip("-").isdigit()]
    flow_acts = ("od", "op", "ok")
    if act not in flow_acts and act != "noop" and us.state and us.state.startswith("sh_"):
        await set_state(session, us)

    if act == "noop":
        return
    if act == "home":
        return await show_home(tg, callback, uid, session, bot)
    if act == "cat":
        return await show_categories(tg, callback, uid, session, bot, admin)
    if act == "cart":
        return await show_cart(tg, callback, uid, session, bot)
    if act == "cclear":
        for it in (await session.execute(select(CartItem).where(CartItem.bot_id == bot.id, CartItem.tg_user_id == uid))).scalars().all():
            await session.delete(it)
        await session.commit()
        return await show_cart(tg, callback, uid, session, bot)
    if act == "contact":
        st = await get_settings(session, bot.id)
        return await show(tg, callback, uid, "☎️ <b>Aloqa</b>\n\n" + (esc(st.contact_text) if st.contact_text else "Aloqa ma’lumoti hali kiritilmagan."),
                          Markup([[Btn("🏠 Bosh sahifa", callback_data="sh:home")]]))
    if act == "find":
        await set_state(session, us, "sh_find")
        return await show(tg, callback, uid, "🔎 Mahsulot nomini yozing.", Markup([[Btn("✖️ Bekor qilish", callback_data="sh:home")]]))
    if act == "orders":
        return await show_orders(tg, callback, uid, session, bot, num[0] if num else 0)
    if act == "co":
        return await start_checkout(tg, callback, uid, session, bot, us)
    if act in flow_acts:
        flow = dict(us.state_data or {})
        if us.state != "sh_flow":
            return await show_cart(tg, callback, uid, session, bot)
        if act == "od" and arg and arg[0] in (DELIVERY, PICKUP):
            st = await get_settings(session, bot.id)
            if (arg[0] == DELIVERY and st.delivery_enabled) or (arg[0] == PICKUP and st.pickup_enabled):
                return await choose_delivery(tg, uid, session, bot, us, flow, arg[0])
        if act == "op" and arg and arg[0] in (PAY_CASH, PAY_CARD) and "dtype" in flow:
            return await choose_payment(tg, uid, session, bot, us, flow, arg[0])
        if act == "ok":
            return await place_order(tg, callback, uid, session, bot, us, user)
        return
    if not num:
        return
    if act == "c":
        cat = await session.get(ShopCategory, num[0])
        if cat is None or cat.bot_id != bot.id or (not cat.is_active and not admin):
            return await show_categories(tg, callback, uid, session, bot, admin)
        return await show_products(tg, callback, uid, session, bot, cat, num[1] if len(num) > 1 else 0, admin)
    if act in ("p", "pi", "add"):
        p = await visible_product(session, bot, num[0], admin)
        if p is None:
            return await show_categories(tg, callback, uid, session, bot, admin)
        if act == "p":
            return await show_product(tg, callback, uid, session, bot, p, admin)
        if act == "pi":
            return await send_album(tg, uid, session, p)
        if not p.is_active:
            return
        return await add_to_cart(tg, uid, session, bot, p, num[1] if len(num) > 1 else None)
    if act == "ci":
        return await change_cart_item(tg, callback, uid, session, bot, num[0], arg[1] if len(arg) > 1 else "")
    if act in ("o", "oc", "occ", "orcpt"):
        order = await session.get(Order, num[0])
        if order is None or order.bot_id != bot.id or order.tg_user_id != uid:
            return await show_orders(tg, callback, uid, session, bot, 0)
        if act == "o":
            return await show_order(tg, callback, uid, session, bot, order)
        if act == "oc":
            return await show(tg, callback, uid, f"🚫 Buyurtma #{order.id} bekor qilinsinmi?",
                              Markup([[Btn("✅ Ha", callback_data=f"sh:occ:{order.id}"), Btn("✖️ Yo‘q", callback_data=f"sh:o:{order.id}")]]))
        if act == "occ":
            if order.status == ST_NEW and order.payment_status != PAID_YES and await cancel_order(session, order):
                await shop_admin.notify_text(tg, session, bot, f"🚫 Mijoz buyurtma #{order.id} ni bekor qildi.")
            return await show_order(tg, callback, uid, session, bot, order)
        if order.payment_method == PAY_CARD and order.payment_status in (PAID_NO, PAID_REJECTED) and order.status != ST_CANCELLED:
            await set_state(session, us, "sh_receipt", {"order": order.id})
            return await show(tg, callback, uid, "📸 Chek rasmini yuboring.", Markup([[Btn("✖️ Bekor qilish", callback_data=f"sh:o:{order.id}")]]))
        return await show_order(tg, callback, uid, session, bot, order)


async def _on_message(bot, message, session, tg):
    if (message.get("chat") or {}).get("type") != "private":
        return
    sender = message["from"]
    uid = sender["id"]
    if sender.get("is_bot"):
        return
    text = (message.get("text") or "").strip()
    cmd = text.split()[0].split("@")[0] if text else ""
    payload = text.split(maxsplit=1)[1].strip() if cmd == "/start" and len(text.split()) > 1 else None
    await touch_user(session, bot.id, sender, source=payload)
    admin = await cinema.is_admin(session, bot, uid)
    if not admin and not await subscription.gate(tg, bot, uid, session):
        return
    us = await session_of(session, bot, uid)
    remove = ReplyKeyboardRemove()

    if cmd in ("/start", "/cancel"):
        had_flow = bool(us.state and us.state.startswith("sh_"))
        if us.state and us.state.startswith("sa_") and cmd == "/cancel" and admin:
            await shop_admin.cancel(bot, session, tg, us, uid)
        await set_state(session, us)
        if had_flow:
            await tg.send_message(chat_id=uid, text="Bekor qilindi.", reply_markup=remove)
        if cmd == "/start" and payload and payload[0] == "p" and payload[1:].isdigit():
            p = await visible_product(session, bot, int(payload[1:]), admin)
            if p:
                return await show_product(tg, None, uid, session, bot, p, admin)
        return await show_home(tg, None, uid, session, bot)
    if admin and cmd == "/admin":
        await set_state(session, us)
        return await shop_admin.show_home(tg, None, uid, session, bot)
    if us.state and us.state.startswith("sa_") and admin:
        if await shop_admin.on_message(bot, message, session, tg, us):
            return
    state = us.state
    if state == "sh_receipt":
        if await on_receipt(bot, message, session, tg, us, sender):
            return
    elif state == "sh_phone":
        raw = (message.get("contact") or {}).get("phone_number") or text
        try:
            phone = parse_phone(raw)
        except ValueError as exc:
            return await tg.send_message(chat_id=uid, text=f"❌ {exc}")
        await tg.send_message(chat_id=uid, text="✅ Raqam qabul qilindi.", reply_markup=remove)
        return await ask_delivery(tg, uid, session, bot, us, {"phone": phone})
    elif state == "sh_addr":
        data = dict(us.state_data or {})
        if message.get("location"):
            data.update(lat=message["location"]["latitude"], lon=message["location"]["longitude"], addr=None)
        elif 5 <= len(text) <= 300:
            data.update(addr=text, lat=None, lon=None)
        else:
            return await tg.send_message(chat_id=uid, text="📍 Manzilni batafsilroq yozing (5–300 belgi) yoki lokatsiya yuboring.")
        await tg.send_message(chat_id=uid, text="✅ Manzil qabul qilindi.", reply_markup=remove)
        return await ask_payment(tg, uid, session, bot, us, data)
    elif state == "sh_find" and text:
        await set_state(session, us)
        return await search(tg, uid, session, bot, text)
    elif state == "sh_flow":
        return await tg.send_message(chat_id=uid, text="Yuqoridagi tugmalardan birini tanlang yoki /cancel.")
    if text and not text.startswith("/"):
        return await search(tg, uid, session, bot, text)  # typing a name anywhere searches the catalog
    await show_home(tg, None, uid, session, bot)

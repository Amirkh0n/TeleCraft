"""Admin side of the shop bot, inside the child bot itself (``/admin``, ``sa:`` callbacks, ``sa_*`` states).

Admins manage categories, products (photos by ``file_id``, variants, stock), orders and their statuses,
payment receipts and settings. Admins are the bot owner and the people added from the constructor bot.
"""
from sqlalchemy import delete, func, select, update
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import TelegramError

from core.logger import get_logger
from engine import cinema, shop_logic as logic
from engine.booking_time import utcnow
from models.shop import (
    ACTIVE_STATUSES, DELIVERY, PAID_NO, PAID_PENDING, PAID_REJECTED, PAID_YES, PAY_CARD, PAY_CASH,
    ST_CANCELLED, ST_CONFIRMED, ST_DONE, ST_NEW, ST_PREPARING, ST_SHIPPING,
    CartItem, Order, OrderItem, ShopCategory, ShopImage, ShopProduct, ShopSettings, ShopVariant,
)

logger = get_logger("shop.admin")
esc = cinema.esc
show = cinema._show
money = logic.fmt_money
PAGE = 8
FLOW = [ST_NEW, ST_CONFIRMED, ST_PREPARING, ST_SHIPPING, ST_DONE]

# (entity, field) -> (label, kind, limit, minimum, clearable)
FIELDS = {
    ("cat", "title"): ("Bo‘lim nomi", "text", 120, 0, False),
    ("prod", "title"): ("Mahsulot nomi", "text", 120, 0, False),
    ("prod", "description"): ("Tavsif", "long", 1500, 0, True),
    ("prod", "price"): ("Narx (so‘mda)", "int", 2_000_000_000, 1, False),
    ("prod", "old"): ("Eski (chegirmadan oldingi) narx", "int", 2_000_000_000, 1, True),
    ("prod", "stock"): ("Ombordagi soni (bo‘sh = cheksiz)", "int", 1_000_000, 0, True),
    ("set", "card"): ("Karta raqami", "card", 40, 0, True),
    ("set", "holder"): ("Karta egasi", "text", 120, 0, True),
    ("set", "note"): ("To‘lov bo‘yicha izoh", "long", 500, 0, True),
    ("set", "contact"): ("Aloqa ma’lumoti (manzil, telefon, ish vaqti)", "long", 1000, 0, True),
    ("set", "fee"): ("Yetkazish narxi (0 = bepul)", "int", 100_000_000, 0, False),
    ("set", "free"): ("Shu summadan yuqori buyurtmada yetkazish bepul", "int", 2_000_000_000, 1, True),
    ("set", "min"): ("Minimal buyurtma summasi (0 = cheklov yo‘q)", "int", 2_000_000_000, 0, False),
}
TOGGLES = {"cash": ("cash_enabled", "💵 Naqd"), "card": ("card_enabled", "💳 Karta"),
           "delivery": ("delivery_enabled", "🚚 Yetkazish"), "pickup": ("pickup_enabled", "🏪 Olib ketish")}


def core():
    from engine import shop
    return shop


def kb_of(rows):
    return Markup(rows)


def back(data, text="⬅️ Orqaga"):
    return [Btn(text, callback_data=data)]


async def set_state(session, us, state=None, data=None):
    us.state, us.state_data = state, data
    await session.commit()


async def cancel(bot, session, tg, us, uid):
    await tg.send_message(chat_id=uid, text="Bekor qilindi.")


async def confirm(tg, callback, uid, text, yes, no):
    await show(tg, callback, uid, text, kb_of([[Btn("✅ Ha", callback_data=yes), Btn("✖️ Yo‘q", callback_data=no)]]))


async def move(session, items, item_id, delta):
    ids = [i.id for i in items]
    if item_id not in ids:
        return
    i = ids.index(item_id)
    j = i + delta
    if 0 <= j < len(items):
        items[i], items[j] = items[j], items[i]
    for pos, item in enumerate(items):
        item.position = pos
    await session.commit()


# ------------------------------------------------------------------ notifications

async def notify_text(tg, session, bot, text):
    for admin_id in await cinema.admin_ids(session, bot):
        try:
            await tg.send_message(chat_id=admin_id, text=text)
        except TelegramError as exc:
            logger.info("notice to %s failed: %s", admin_id, exc)


async def notify_order(tg, session, bot, order):
    c = core()
    text = "🔔 <b>Yangi buyurtma!</b>\n\n" + c.order_text(order, await c.order_items(session, order.id), admin=True)
    markup = kb_of([[Btn("📦 Buyurtmani ochish", callback_data=f"sa:o:{order.id}")]])
    for admin_id in await cinema.admin_ids(session, bot):
        try:
            await tg.send_message(chat_id=admin_id, text=text[:4096], parse_mode="HTML", reply_markup=markup)
        except TelegramError as exc:
            logger.info("order notice to %s failed: %s", admin_id, exc)


def receipt_markup(order):
    return kb_of([[Btn("✅ To‘lov to‘g‘ri", callback_data=f"sa:pok:{order.id}"), Btn("❌ Rad etish", callback_data=f"sa:prj:{order.id}")],
                  [Btn("📦 Buyurtma", callback_data=f"sa:o:{order.id}")]])


async def send_receipt(tg, admin_id, order):
    caption = f"🧾 <b>Chek — buyurtma #{order.id}</b>\n👤 {esc(order.user_name)}  <code>{order.tg_user_id}</code>\n💰 {money(order.total)}"
    if order.receipt_type == "document":
        await tg.send_document(chat_id=admin_id, document=order.receipt_file_id, caption=caption, parse_mode="HTML", reply_markup=receipt_markup(order))
    else:
        await tg.send_photo(chat_id=admin_id, photo=order.receipt_file_id, caption=caption, parse_mode="HTML", reply_markup=receipt_markup(order))


async def notify_receipt(tg, session, bot, order):
    for admin_id in await cinema.admin_ids(session, bot):
        try:
            await send_receipt(tg, admin_id, order)
        except TelegramError as exc:
            logger.info("receipt notice to %s failed: %s", admin_id, exc)


async def tell_customer(tg, order, text, markup=None):
    try:
        await tg.send_message(chat_id=order.tg_user_id, text=text, parse_mode="HTML", reply_markup=markup)
    except TelegramError as exc:
        logger.info("customer %s not notified: %s", order.tg_user_id, exc)


# ------------------------------------------------------------------ home

async def show_home(tg, callback, chat_id, session, bot):
    new = (await session.execute(select(func.count(Order.id)).where(Order.bot_id == bot.id, Order.status == ST_NEW))).scalar() or 0
    pend = (await session.execute(select(func.count(Order.id)).where(
        Order.bot_id == bot.id, Order.payment_status == PAID_PENDING, Order.status != ST_CANCELLED))).scalar() or 0
    rows = [[Btn(f"📦 Buyurtmalar ({new})", callback_data="sa:ords:n:0"), Btn(f"🧾 Cheklar ({pend})", callback_data="sa:chk")],
            [Btn("🗂 Bo‘limlar", callback_data="sa:cats"), Btn("🛍 Mahsulotlar", callback_data="sa:cats:p")],
            [Btn("📊 Statistika", callback_data="sa:stats"), Btn("⚙️ Sozlamalar", callback_data="sa:set")],
            [Btn("🏠 Xaridor ko‘rinishi", callback_data="sh:home")]]
    await show(tg, callback, chat_id, "🛠 <b>Admin panel</b>\nBuyurtmalar, mahsulotlar va sozlamalarni shu yerda boshqarasiz.", kb_of(rows))


# ------------------------------------------------------------------ orders

FILTERS = {"n": ("🆕 Yangi", (ST_NEW,)), "a": ("⏳ Jarayonda", (ST_CONFIRMED, ST_PREPARING, ST_SHIPPING)),
           "d": ("✔️ Yakunlangan", (ST_DONE, ST_CANCELLED))}


async def orders_list(tg, callback, uid, session, bot, flt, page):
    flt = flt if flt in FILTERS else "n"
    label, statuses = FILTERS[flt]
    conds = (Order.bot_id == bot.id, Order.status.in_(statuses))
    total = (await session.execute(select(func.count(Order.id)).where(*conds))).scalar() or 0
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    rows = (await session.execute(select(Order).where(*conds).order_by(Order.id.desc()).limit(PAGE).offset(page * PAGE))).scalars().all()
    kb = [[Btn(f"{'✅' if f == flt else ''}{FILTERS[f][0]}", callback_data=f"sa:ords:{f}:0") for f in FILTERS]]
    kb += [[Btn(f"#{o.id} {o.user_name} · {money(o.total)}"[:60], callback_data=f"sa:o:{o.id}")] for o in rows]
    nav = ([Btn("⬅️", callback_data=f"sa:ords:{flt}:{page - 1}")] if page else []) + ([Btn("➡️", callback_data=f"sa:ords:{flt}:{page + 1}")] if page < pages - 1 else [])
    if nav:
        kb.append(nav)
    kb.append(back("sa:home"))
    await show(tg, callback, uid, f"📦 <b>Buyurtmalar — {label}</b> ({total})" if rows else f"📦 <b>{label}</b>: buyurtma yo‘q.", kb_of(kb))


def next_status_button(order):
    nxt = {ST_NEW: ("✅ Tasdiqlash", ST_CONFIRMED), ST_CONFIRMED: ("👨‍🍳 Tayyorlanmoqda", ST_PREPARING),
           ST_PREPARING: ("🚚 Yo‘lda" if order.delivery_type == DELIVERY else "🏪 Olib ketishga tayyor", ST_SHIPPING),
           ST_SHIPPING: ("✔️ Yakunlash", ST_DONE)}.get(order.status)
    return Btn(nxt[0], callback_data=f"sa:os:{order.id}:{nxt[1]}") if nxt else None


async def order_screen(tg, callback, uid, session, order):
    c = core()
    text = c.order_text(order, await c.order_items(session, order.id), admin=True)
    kb = []
    if order.status in ACTIVE_STATUSES:
        btn = next_status_button(order)
        if btn:
            kb.append([btn])
        if order.payment_method == PAY_CARD and order.payment_status == PAID_PENDING:
            kb.append([Btn("✅ To‘lov to‘g‘ri", callback_data=f"sa:pok:{order.id}"), Btn("❌ Chekni rad etish", callback_data=f"sa:prj:{order.id}")])
        kb.append([Btn("🚫 Bekor qilish", callback_data=f"sa:ox:{order.id}")])
    if order.receipt_file_id:
        kb.append([Btn("🧾 Chekni ko‘rish", callback_data=f"sa:orc:{order.id}")])
    if order.lat is not None:
        kb.append([Btn("📍 Xaritada", url=f"https://maps.google.com/?q={order.lat},{order.lon}")])
    kb.append(back("sa:ords:n:0", "⬅️ Buyurtmalar"))
    await show(tg, callback, uid, text[:4096], kb_of(kb))


async def set_status(tg, session, order, status):
    c = core()
    if order.status not in ACTIVE_STATUSES or status not in FLOW:
        return False
    if FLOW.index(status) <= FLOW.index(order.status):
        return False
    order.status, order.updated_at = status, utcnow()
    if status == ST_DONE and order.payment_method == PAY_CASH:
        order.payment_status = PAID_YES
    await session.commit()
    await tell_customer(tg, order, f"📦 Buyurtma <b>#{order.id}</b>: {c.status_name(order)}",
                        kb_of([[Btn("📦 Buyurtma", callback_data=f"sh:o:{order.id}")]]))
    return True


async def order_action(tg, callback, uid, session, bot, us, act, order, arg):
    c = core()
    if act == "o":
        return await order_screen(tg, callback, uid, session, order)
    if act == "os":
        if not await set_status(tg, session, order, arg[1] if len(arg) > 1 else ""):
            await tg.send_message(chat_id=uid, text="ℹ️ Holat allaqachon o‘zgargan.")
        return await order_screen(tg, callback, uid, session, order)
    if act == "ox":
        return await confirm(tg, callback, uid, f"🚫 Buyurtma #{order.id} bekor qilinsinmi? (Ombor qoldig‘i qaytariladi)", f"sa:oxok:{order.id}", f"sa:o:{order.id}")
    if act == "oxok":
        if await c.cancel_order(session, order):
            await tell_customer(tg, order, f"❌ Buyurtma <b>#{order.id}</b> bekor qilindi. Savollar bo‘lsa, biz bilan bog‘laning.")
        return await order_screen(tg, callback, uid, session, order)
    if act == "orc":
        if order.receipt_file_id:
            await send_receipt(tg, uid, order)
        return
    if order.status == ST_CANCELLED or order.payment_method != PAY_CARD:
        return await tg.send_message(chat_id=uid, text="ℹ️ Bu buyurtma uchun chek kerak emas.")
    if order.payment_status != PAID_PENDING:
        return await tg.send_message(chat_id=uid, text=f"ℹ️ To‘lov #{order.id} allaqachon ko‘rib chiqilgan.")
    if act == "pok":
        order.payment_status, order.updated_at = PAID_YES, utcnow()
        await session.commit()
        await tell_customer(tg, order, f"✅ Buyurtma <b>#{order.id}</b> uchun to‘lov tasdiqlandi. Rahmat!")
        await tg.send_message(chat_id=uid, text=f"✅ To‘lov #{order.id} tasdiqlandi.", reply_markup=kb_of([[Btn("📦 Buyurtma", callback_data=f"sa:o:{order.id}")]]))
        return
    if act == "prj":
        await set_state(session, us, "sa_reject", {"order": order.id})
        await tg.send_message(chat_id=uid, text=f"❌ Chek #{order.id} rad etiladi. Sababini yozing (mijozga yuboriladi) yoki /skip.")


async def receipts_list(tg, callback, uid, session, bot):
    rows = (await session.execute(select(Order).where(Order.bot_id == bot.id, Order.payment_status == PAID_PENDING, Order.status != ST_CANCELLED)
                                  .order_by(Order.id).limit(20))).scalars().all()
    kb = [[Btn(f"#{o.id} {o.user_name} · {money(o.total)}"[:60], callback_data=f"sa:orc:{o.id}")] for o in rows]
    kb.append(back("sa:home"))
    await show(tg, callback, uid, "🧾 <b>Tekshirilmagan cheklar</b>" if rows else "Tekshirilmagan chek yo‘q. ✅", kb_of(kb))


# ------------------------------------------------------------------ categories & products

async def own_cat(session, bot, cid):
    c = await session.get(ShopCategory, cid)
    return c if c and c.bot_id == bot.id else None


async def own_product(session, bot, pid):
    p = await session.get(ShopProduct, pid)
    return p if p and p.bot_id == bot.id else None


async def cats_screen(tg, callback, uid, session, bot, mode=""):
    cats = (await session.execute(select(ShopCategory).where(ShopCategory.bot_id == bot.id).order_by(ShopCategory.position, ShopCategory.id))).scalars().all()
    target = "pl" if mode == "p" else "cat"
    kb = [[Btn(f"{'' if c.is_active else '🙈 '}{c.title}"[:60], callback_data=f"sa:{target}:{c.id}:0")] for c in cats]
    if mode != "p":
        kb.append([Btn("➕ Bo‘lim qo‘shish", callback_data="sa:cn")])
    kb.append(back("sa:home"))
    title = "🛍 <b>Mahsulotlar</b> — bo‘limni tanlang" if mode == "p" else "🗂 <b>Bo‘limlar</b>"
    await show(tg, callback, uid, title if cats else "Hali bo‘lim yo‘q. Avval bo‘lim qo‘shing (masalan «Kiyim»).", kb_of(kb if cats else [[Btn("➕ Bo‘lim qo‘shish", callback_data="sa:cn")], back("sa:home")]))


async def cat_screen(tg, callback, uid, session, cat):
    count = (await session.execute(select(func.count(ShopProduct.id)).where(ShopProduct.category_id == cat.id))).scalar() or 0
    kb = [[Btn("🛍 Mahsulotlar", callback_data=f"sa:pl:{cat.id}:0")],
          [Btn("✏️ Nomi", callback_data=f"sa:ef:cat:{cat.id}:title"), Btn("🙈 Ko‘rsatish/yashirish", callback_data=f"sa:ct:{cat.id}")],
          [Btn("⬆️", callback_data=f"sa:cup:{cat.id}"), Btn("⬇️", callback_data=f"sa:cdn:{cat.id}"), Btn("🗑 O‘chirish", callback_data=f"sa:cdel:{cat.id}")],
          back("sa:cats", "⬅️ Bo‘limlar")]
    await show(tg, callback, uid, f"🗂 <b>{esc(cat.title)}</b> {'✅ ko‘rinadi' if cat.is_active else '🙈 yashirin'}\nMahsulotlar: {count}", kb_of(kb))


async def products_screen(tg, callback, uid, session, cat, page):
    conds = (ShopProduct.category_id == cat.id,)
    total = (await session.execute(select(func.count(ShopProduct.id)).where(*conds))).scalar() or 0
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    rows = (await session.execute(select(ShopProduct).where(*conds).order_by(ShopProduct.position, ShopProduct.id).limit(PAGE).offset(page * PAGE))).scalars().all()
    kb = [[Btn(f"{'' if p.is_active else '🙈 '}{p.title} · {money(p.price)}"[:60], callback_data=f"sa:p:{p.id}")] for p in rows]
    nav = ([Btn("⬅️", callback_data=f"sa:pl:{cat.id}:{page - 1}")] if page else []) + ([Btn("➡️", callback_data=f"sa:pl:{cat.id}:{page + 1}")] if page < pages - 1 else [])
    if nav:
        kb.append(nav)
    kb.append([Btn("➕ Mahsulot qo‘shish", callback_data=f"sa:pn:{cat.id}")])
    kb.append(back(f"sa:cat:{cat.id}", "⬅️ Bo‘lim"))
    await show(tg, callback, uid, f"🛍 <b>{esc(cat.title)}</b> — mahsulotlar ({total})", kb_of(kb))


async def product_screen(tg, callback, uid, session, product):
    c = core()
    variants = await c.variants_of(session, product.id)
    images = await c.images_of(session, product.id)
    lines = [f"🛍 <b>{esc(product.title)}</b> {'✅' if product.is_active else '🙈 yashirin'}", f"💰 {money(product.price)}"
             + (f" (eski: {money(product.old_price)})" if product.old_price else "")]
    lines.append(f"📦 Ombor: {'cheksiz' if product.stock is None else product.stock}" + (" (variantlar bor — variant qoldig‘i ishlaydi)" if variants else ""))
    lines.append(f"🖼 Rasmlar: {len(images)}")
    if variants:
        lines.append("🎛 Variantlar: " + "; ".join(f"{esc(v.name)}" + (f" {money(v.price)}" if v.price else "") + (f" [{v.stock}]" if v.stock is not None else "") for v in variants))
    if product.description:
        lines.append("\n" + esc(product.description[:300]))
    f = f"sa:ef:prod:{product.id}:"
    kb = [[Btn("👁 Xaridor ko‘rinishi", callback_data=f"sh:p:{product.id}")],
          [Btn("✏️ Nomi", callback_data=f + "title"), Btn("📝 Tavsif", callback_data=f + "description")],
          [Btn("💰 Narx", callback_data=f + "price"), Btn("🏷 Eski narx", callback_data=f + "old"), Btn("📦 Ombor", callback_data=f + "stock")],
          [Btn("🖼 Rasm qo‘shish", callback_data=f"sa:img:{product.id}"), Btn("🧹 Rasmlarni tozalash", callback_data=f"sa:imgc:{product.id}")],
          [Btn("🎛 Variantlar", callback_data=f"sa:vl:{product.id}")],
          [Btn("🙈 Yashirish" if product.is_active else "✅ Ko‘rsatish", callback_data=f"sa:pt:{product.id}")],
          [Btn("⬆️", callback_data=f"sa:pup:{product.id}"), Btn("⬇️", callback_data=f"sa:pdn:{product.id}"), Btn("🗑 O‘chirish", callback_data=f"sa:pdel:{product.id}")],
          back(f"sa:pl:{product.category_id}:0", "⬅️ Mahsulotlar")]
    await show(tg, callback, uid, "\n".join(lines), kb_of(kb))


async def variants_screen(tg, callback, uid, session, product):
    variants = await core().variants_of(session, product.id)
    kb = [[Btn(f"🗑 {v.name}"[:60], callback_data=f"sa:vd:{v.id}")] for v in variants]
    kb.append([Btn("➕ Qo‘shish / yangilash", callback_data=f"sa:vn:{product.id}")])
    if variants:
        kb.append([Btn("🧹 Hammasini o‘chirish", callback_data=f"sa:vc:{product.id}")])
    kb.append(back(f"sa:p:{product.id}", "⬅️ Mahsulot"))
    text = (f"🎛 <b>{esc(product.title)}</b> — variantlar\n"
            + ("\n".join(f"• {esc(v.name)} — {money(logic.unit_price(product, v))}" + (f" · {v.stock} ta" if v.stock is not None else "") for v in variants) or "Variant yo‘q.")
            + "\n\nVariant bo‘lsa, xaridor avval variantni tanlaydi.")
    await show(tg, callback, uid, text, kb_of(kb))


async def delete_products(session, product_ids):
    if not product_ids:
        return
    await session.execute(delete(CartItem).where(CartItem.product_id.in_(product_ids)))
    await session.execute(update(OrderItem).where(OrderItem.product_id.in_(product_ids)).values(product_id=None, variant_id=None))
    await session.execute(delete(ShopImage).where(ShopImage.product_id.in_(product_ids)))
    await session.execute(delete(ShopVariant).where(ShopVariant.product_id.in_(product_ids)))
    await session.execute(delete(ShopProduct).where(ShopProduct.id.in_(product_ids)))
    await session.commit()


# ------------------------------------------------------------------ settings & stats

async def settings_screen(tg, callback, uid, session, bot):
    st = await core().get_settings(session, bot.id)
    on = lambda v: "✅" if v else "⛔️"  # noqa: E731
    text = (f"⚙️ <b>Sozlamalar</b>\n\n💳 Karta: <code>{esc(st.card_number or '—')}</code> ({esc(st.card_holder or '—')})\n"
            f"🚚 Yetkazish: {money(st.delivery_fee)}" + (f", {money(st.free_delivery_from)} dan bepul" if st.free_delivery_from else "") + "\n"
            f"🧮 Minimal buyurtma: {money(st.min_order) if st.min_order else 'yo‘q'}\n"
            f"☎️ Aloqa: {esc((st.contact_text or '—')[:100])}\n\n"
            f"{on(st.cash_enabled)} naqd · {on(st.card_enabled)} karta · {on(st.delivery_enabled)} yetkazish · {on(st.pickup_enabled)} olib ketish")
    f = "sa:ef:set:0:"
    kb = [[Btn("💳 Karta", callback_data=f + "card"), Btn("👤 Egasi", callback_data=f + "holder")],
          [Btn("📝 To‘lov izohi", callback_data=f + "note"), Btn("☎️ Aloqa", callback_data=f + "contact")],
          [Btn("🚚 Yetkazish narxi", callback_data=f + "fee"), Btn("🎁 Bepul yetkazish", callback_data=f + "free")],
          [Btn("🧮 Minimal summa", callback_data=f + "min")],
          [Btn(f"{on(getattr(st, attr))} {label}", callback_data=f"sa:tg:{key}") for key, (attr, label) in TOGGLES.items()][:2],
          [Btn(f"{on(getattr(st, attr))} {label}", callback_data=f"sa:tg:{key}") for key, (attr, label) in TOGGLES.items()][2:],
          back("sa:home")]
    await show(tg, callback, uid, text, kb_of(kb))


async def stats_screen(tg, callback, uid, session, bot):
    async def count(*conds):
        return (await session.execute(select(func.count(Order.id)).where(Order.bot_id == bot.id, *conds))).scalar() or 0
    revenue = (await session.execute(select(func.coalesce(func.sum(Order.total), 0)).where(Order.bot_id == bot.id, Order.status == ST_DONE))).scalar() or 0
    products = (await session.execute(select(func.count(ShopProduct.id)).where(ShopProduct.bot_id == bot.id))).scalar() or 0
    lines = ["📊 <b>Statistika</b>\n", f"🛍 Mahsulotlar: {products}", f"📦 Buyurtmalar: {await count()}",
             f"🆕 Yangi: {await count(Order.status == ST_NEW)} · ⏳ Jarayonda: {await count(Order.status.in_((ST_CONFIRMED, ST_PREPARING, ST_SHIPPING)))}",
             f"✔️ Yakunlangan: {await count(Order.status == ST_DONE)} · ❌ Bekor: {await count(Order.status == ST_CANCELLED)}",
             f"💰 Yakunlangan buyurtmalar summasi: {money(revenue)}"]
    top = (await session.execute(
        select(OrderItem.title, func.sum(OrderItem.qty).label("q")).join(Order, Order.id == OrderItem.order_id)
        .where(Order.bot_id == bot.id, Order.status != ST_CANCELLED).group_by(OrderItem.title).order_by(func.sum(OrderItem.qty).desc()).limit(5))).all()
    if top:
        lines.append("\n🏆 <b>Ko‘p sotilgan</b>")
        lines += [f"• {esc(t)} — {q} ta" for t, q in top]
    await show(tg, callback, uid, "\n".join(lines), kb_of([back("sa:home")]))


# ------------------------------------------------------------------ callbacks

async def on_callback(bot, callback, session, tg, us):
    uid = callback["from"]["id"]
    parts = (callback.get("data") or "").split(":")
    act, arg = parts[1], parts[2:]
    num = [int(p) for p in arg if p.lstrip("-").isdigit()]
    n0 = num[0] if num else 0
    if us.state and us.state.startswith("sa_"):
        await set_state(session, us)

    if act == "home":
        return await show_home(tg, callback, uid, session, bot)
    if act == "cats":
        return await cats_screen(tg, callback, uid, session, bot, arg[0] if arg else "")
    if act == "cn":
        await set_state(session, us, "sa_cn")
        return await show(tg, callback, uid, "🗂 Bo‘lim nomini yozing.", kb_of([back("sa:cats", "✖️ Bekor qilish")]))
    if act == "set":
        return await settings_screen(tg, callback, uid, session, bot)
    if act == "tg":
        if arg and arg[0] in TOGGLES:
            st = await core().get_settings(session, bot.id)
            attr = TOGGLES[arg[0]][0]
            setattr(st, attr, not getattr(st, attr))
            await session.commit()
        return await settings_screen(tg, callback, uid, session, bot)
    if act == "stats":
        return await stats_screen(tg, callback, uid, session, bot)
    if act == "chk":
        return await receipts_list(tg, callback, uid, session, bot)
    if act == "ords":
        return await orders_list(tg, callback, uid, session, bot, arg[0] if arg else "n", num[0] if num else 0)
    if act == "ef":
        return await edit_field(tg, callback, uid, session, bot, us, arg)
    if not num:
        return

    if act in ("o", "os", "ox", "oxok", "orc", "pok", "prj"):
        order = await session.get(Order, n0)
        if order is None or order.bot_id != bot.id:
            return await orders_list(tg, callback, uid, session, bot, "n", 0)
        return await order_action(tg, callback, uid, session, bot, us, act, order, arg)
    if act in ("cat", "ct", "cup", "cdn", "cdel", "cdelok", "pl", "pn"):
        cat = await own_cat(session, bot, n0)
        if cat is None:
            return await cats_screen(tg, callback, uid, session, bot)
        return await cat_action(tg, callback, uid, session, bot, us, act, cat, num)
    if act in ("p", "pt", "pup", "pdn", "pdel", "pdelok", "img", "imgc", "vl", "vn", "vc"):
        product = await own_product(session, bot, n0)
        if product is None:
            return await cats_screen(tg, callback, uid, session, bot, "p")
        return await product_action(tg, callback, uid, session, bot, us, act, product)
    if act == "vd":
        v = await session.get(ShopVariant, n0)
        product = await own_product(session, bot, v.product_id) if v else None
        if product is None:
            return await cats_screen(tg, callback, uid, session, bot, "p")
        await session.execute(delete(CartItem).where(CartItem.variant_id == v.id))
        await session.execute(update(OrderItem).where(OrderItem.variant_id == v.id).values(variant_id=None))
        await session.delete(v)
        await session.commit()
        return await variants_screen(tg, callback, uid, session, product)


async def cat_action(tg, callback, uid, session, bot, us, act, cat, num):
    if act == "cat":
        return await cat_screen(tg, callback, uid, session, cat)
    if act == "ct":
        cat.is_active = not cat.is_active
        await session.commit()
        return await cat_screen(tg, callback, uid, session, cat)
    if act in ("cup", "cdn"):
        items = list((await session.execute(select(ShopCategory).where(ShopCategory.bot_id == bot.id).order_by(ShopCategory.position, ShopCategory.id))).scalars().all())
        await move(session, items, cat.id, -1 if act == "cup" else 1)
        return await cats_screen(tg, callback, uid, session, bot)
    if act == "cdel":
        return await confirm(tg, callback, uid, f"🗑 «{esc(cat.title)}» bo‘limi va undagi barcha mahsulotlar o‘chiriladi. Davom etasizmi?", f"sa:cdelok:{cat.id}", f"sa:cat:{cat.id}")
    if act == "cdelok":
        ids = list((await session.execute(select(ShopProduct.id).where(ShopProduct.category_id == cat.id))).scalars().all())
        await delete_products(session, ids)
        await session.delete(cat)
        await session.commit()
        return await cats_screen(tg, callback, uid, session, bot)
    if act == "pl":
        return await products_screen(tg, callback, uid, session, cat, num[1] if len(num) > 1 else 0)
    if act == "pn":
        await set_state(session, us, "sa_pt", {"cat": cat.id})
        return await show(tg, callback, uid, "🛍 Yangi mahsulot nomini yozing.", kb_of([back(f"sa:pl:{cat.id}:0", "✖️ Bekor qilish")]))


async def product_action(tg, callback, uid, session, bot, us, act, product):
    c = core()
    if act == "p":
        return await product_screen(tg, callback, uid, session, product)
    if act == "pt":
        product.is_active = not product.is_active
        await session.commit()
        return await product_screen(tg, callback, uid, session, product)
    if act in ("pup", "pdn"):
        items = list((await session.execute(select(ShopProduct).where(ShopProduct.category_id == product.category_id).order_by(ShopProduct.position, ShopProduct.id))).scalars().all())
        await move(session, items, product.id, -1 if act == "pup" else 1)
        return await product_screen(tg, callback, uid, session, product)
    if act == "pdel":
        return await confirm(tg, callback, uid, f"🗑 «{esc(product.title)}» o‘chirilsinmi? (Eski buyurtmalar saqlanadi)", f"sa:pdelok:{product.id}", f"sa:p:{product.id}")
    if act == "pdelok":
        cid = product.category_id
        await delete_products(session, [product.id])
        cat = await session.get(ShopCategory, cid)
        return await products_screen(tg, callback, uid, session, cat, 0)
    if act == "img":
        await set_state(session, us, "sa_img", {"product": product.id, "added": 0})
        return await show(tg, callback, uid, "🖼 Rasmlarni yuboring (bir nechta bo‘lishi mumkin). Tugagach /done.", kb_of([back(f"sa:p:{product.id}", "✖️ Bekor qilish")]))
    if act == "imgc":
        await session.execute(delete(ShopImage).where(ShopImage.product_id == product.id))
        await session.commit()
        return await product_screen(tg, callback, uid, session, product)
    if act == "vl":
        return await variants_screen(tg, callback, uid, session, product)
    if act == "vn":
        await set_state(session, us, "sa_var", {"product": product.id})
        return await show(tg, callback, uid,
                          "🎛 Variantlarni yuboring, har qatorda bittadan:\n<code>nom | narx | qoldiq</code>\nNarx va qoldiq ixtiyoriy (<code>-</code> = mahsulot narxi / cheksiz).\n"
                          "Masalan:\n<code>S\nM | 120000\nL | - | 5</code>\nBir xil nomli variant yangilanadi.",
                          kb_of([back(f"sa:vl:{product.id}", "✖️ Bekor qilish")]))
    if act == "vc":
        ids = list((await session.execute(select(ShopVariant.id).where(ShopVariant.product_id == product.id))).scalars().all())
        if ids:
            await session.execute(delete(CartItem).where(CartItem.variant_id.in_(ids)))
            await session.execute(update(OrderItem).where(OrderItem.variant_id.in_(ids)).values(variant_id=None))
            await session.execute(delete(ShopVariant).where(ShopVariant.id.in_(ids)))
            await session.commit()
        return await variants_screen(tg, callback, uid, session, product)


# ------------------------------------------------------------------ editing fields

async def ask(tg, callback, uid, session, us, entity, ent_id, field):
    label, kind, limit, minimum, clearable = FIELDS[(entity, field)]
    await set_state(session, us, "sa_ef", {"entity": entity, "id": ent_id, "field": field})
    hint = "Raqam yuboring." if kind == "int" else "Karta raqamini yuboring." if kind == "card" else f"Matn yuboring (≤ {limit} belgi)."
    await show(tg, callback, uid, f"✏️ <b>{esc(label)}</b>\n{hint}" + ("\nTozalash: /clear" if clearable else "") + "\nBekor qilish: /cancel", None)


async def edit_field(tg, callback, uid, session, bot, us, arg):
    if len(arg) < 3 or (arg[0], arg[2]) not in FIELDS or not arg[1].isdigit():
        return
    entity, ent_id, field = arg[0], int(arg[1]), arg[2]
    if entity == "cat" and not await own_cat(session, bot, ent_id):
        return
    if entity == "prod" and not await own_product(session, bot, ent_id):
        return
    await ask(tg, callback, uid, session, us, entity, ent_id, field)


def parse_value(kind, limit, minimum, text):
    if not text:
        return None, "Matn yuboring."
    if kind == "int":
        try:
            return logic.parse_int(text, minimum=minimum, maximum=limit), None
        except ValueError:
            return None, f"Raqam {minimum} dan {limit} gacha bo‘lsin."
    if kind == "card":
        digits = "".join(ch for ch in text if ch.isdigit())
        if not 8 <= len(digits) <= 20:
            return None, "Karta raqamini to‘g‘ri yuboring (16 xonali)."
        return " ".join(digits[i:i + 4] for i in range(0, len(digits), 4)), None
    if len(text) > limit:
        return None, f"Juda uzun (≤ {limit} belgi)."
    return text, None


ATTRS = {("cat", "title"): "title", ("prod", "title"): "title", ("prod", "description"): "description", ("prod", "price"): "price",
         ("prod", "old"): "old_price", ("prod", "stock"): "stock", ("set", "card"): "card_number", ("set", "holder"): "card_holder",
         ("set", "note"): "pay_note", ("set", "contact"): "contact_text", ("set", "fee"): "delivery_fee",
         ("set", "free"): "free_delivery_from", ("set", "min"): "min_order"}


async def apply_field(session, bot, entity, ent_id, field, value):
    obj = {"cat": lambda: session.get(ShopCategory, ent_id), "prod": lambda: session.get(ShopProduct, ent_id),
           "set": lambda: core().get_settings(session, bot.id)}[entity]
    obj = await obj()
    setattr(obj, ATTRS[(entity, field)], value)
    await session.commit()


async def after_edit(tg, uid, session, bot, entity, ent_id):
    if entity == "cat":
        return await cat_screen(tg, None, uid, session, await session.get(ShopCategory, ent_id))
    if entity == "prod":
        return await product_screen(tg, None, uid, session, await session.get(ShopProduct, ent_id))
    return await settings_screen(tg, None, uid, session, bot)


def image_of(message):
    if message.get("photo"):
        return message["photo"][-1]["file_id"]
    doc = message.get("document") or {}
    return doc["file_id"] if doc.get("mime_type", "").startswith("image/") else None


# ------------------------------------------------------------------ messages

async def on_message(bot, message, session, tg, us) -> bool:
    uid = message["from"]["id"]
    text = (message.get("text") or "").strip()
    state, data = us.state, us.state_data or {}
    c = core()

    if state == "sa_cn":
        if not text or len(text) > 120:
            await tg.send_message(chat_id=uid, text="Nom 1–120 belgi bo‘lsin.")
            return True
        count = (await session.execute(select(func.count(ShopCategory.id)).where(ShopCategory.bot_id == bot.id))).scalar() or 0
        cat = ShopCategory(bot_id=bot.id, title=text, position=count)
        session.add(cat)
        await session.commit()
        await set_state(session, us)
        await cat_screen(tg, None, uid, session, cat)
        return True

    if state == "sa_pt":
        cat = await own_cat(session, bot, data.get("cat"))
        if cat is None or not text or len(text) > 120:
            await tg.send_message(chat_id=uid, text="Nom 1–120 belgi bo‘lsin.")
            return True
        await set_state(session, us, "sa_pp", {"cat": cat.id, "title": text})
        await tg.send_message(chat_id=uid, text="💰 Narxini yozing (so‘mda, masalan 150000).")
        return True

    if state == "sa_pp":
        try:
            price = logic.parse_int(text, minimum=1)
        except ValueError:
            await tg.send_message(chat_id=uid, text="❌ Narxni raqam bilan yozing (masalan 150000).")
            return True
        await set_state(session, us, "sa_pd", {**data, "price": price})
        await tg.send_message(chat_id=uid, text="📝 Tavsifini yozing (≤ 1500 belgi). O‘tkazib yuborish: /skip")
        return True

    if state == "sa_pd":
        if text != "/skip" and (not text or len(text) > 1500):
            await tg.send_message(chat_id=uid, text="Tavsif 1–1500 belgi bo‘lsin yoki /skip.")
            return True
        cat = await own_cat(session, bot, data.get("cat"))
        if cat is None:
            await set_state(session, us)
            return True
        count = (await session.execute(select(func.count(ShopProduct.id)).where(ShopProduct.category_id == cat.id))).scalar() or 0
        product = ShopProduct(bot_id=bot.id, category_id=cat.id, title=data["title"], price=data["price"], position=count,
                              description=None if text == "/skip" else text)
        session.add(product)
        await session.commit()
        await set_state(session, us, "sa_img", {"product": product.id, "added": 0, "new": True})
        await tg.send_message(chat_id=uid, text="🖼 Mahsulot rasmlarini yuboring (bir nechta bo‘lishi mumkin). Tugagach /done, rasmsiz davom etish: /skip")
        return True

    if state == "sa_img":
        product = await own_product(session, bot, data.get("product"))
        if product is None:
            await set_state(session, us)
            return True
        if text in ("/done", "/skip"):
            if data.get("new"):
                await set_state(session, us, "sa_stock", {"product": product.id})
                await tg.send_message(chat_id=uid, text="📦 Ombordagi sonini yozing. Cheksiz bo‘lsa: /skip")
            else:
                await set_state(session, us)
                await product_screen(tg, None, uid, session, product)
            return True
        file_id = image_of(message)
        if not file_id:
            await tg.send_message(chat_id=uid, text="🖼 Rasm yuboring. Tugatish: /done")
            return True
        count = (await session.execute(select(func.count(ShopImage.id)).where(ShopImage.product_id == product.id))).scalar() or 0
        if count >= 10:
            await tg.send_message(chat_id=uid, text="Ko‘pi bilan 10 ta rasm. Tugatish: /done")
            return True
        session.add(ShopImage(product_id=product.id, position=count, file_id=file_id))
        await session.commit()
        data["added"] = int(data.get("added", 0)) + 1
        await set_state(session, us, "sa_img", dict(data))
        await tg.send_message(chat_id=uid, text=f"✅ {data['added']}-rasm qo‘shildi. Yana yuboring yoki /done.")
        return True

    if state == "sa_stock":
        product = await own_product(session, bot, data.get("product"))
        if product is None:
            await set_state(session, us)
            return True
        if text != "/skip":
            try:
                product.stock = logic.parse_int(text, maximum=1_000_000)
            except ValueError:
                await tg.send_message(chat_id=uid, text="Raqam yozing yoki /skip.")
                return True
            await session.commit()
        await set_state(session, us)
        await tg.send_message(chat_id=uid, text="✅ Mahsulot qo‘shildi. Variantlar (o‘lcham/rang) kerak bo‘lsa «🎛 Variantlar» ni bosing.")
        await product_screen(tg, None, uid, session, product)
        return True

    if state == "sa_var":
        product = await own_product(session, bot, data.get("product"))
        if product is None:
            await set_state(session, us)
            return True
        variants, errors = logic.parse_variants(text)
        if errors and not variants:
            await tg.send_message(chat_id=uid, text="❌ " + "\n".join(errors) + "\nQayta yuboring yoki /cancel.")
            return True
        existing = {v.name.lower(): v for v in await c.variants_of(session, product.id)}
        pos = len(existing)
        for name, price, stock in variants:
            v = existing.get(name.lower())
            if v:
                v.price, v.stock = price, stock
            else:
                session.add(ShopVariant(product_id=product.id, name=name, price=price, stock=stock, position=pos))
                pos += 1
        await session.commit()
        await set_state(session, us)
        if errors:
            await tg.send_message(chat_id=uid, text="⚠️ Ba’zi qatorlar o‘tkazib yuborildi:\n" + "\n".join(errors))
        await variants_screen(tg, None, uid, session, product)
        return True

    if state == "sa_ef":
        entity, ent_id, field = data.get("entity"), data.get("id"), data.get("field")
        if (entity, field) not in FIELDS:
            await set_state(session, us)
            return True
        label, kind, limit, minimum, clearable = FIELDS[(entity, field)]
        if text == "/clear" and not clearable:
            await tg.send_message(chat_id=uid, text="❌ Bu maydonni bo‘sh qoldirib bo‘lmaydi.")
            return True
        if text == "/clear":
            value = None
        else:
            value, err = parse_value(kind, limit, minimum, text)
            if err:
                await tg.send_message(chat_id=uid, text=f"❌ {err}")
                return True
        await apply_field(session, bot, entity, ent_id, field, value)
        await set_state(session, us)
        await after_edit(tg, uid, session, bot, entity, ent_id)
        return True

    if state == "sa_reject":
        order = await session.get(Order, data.get("order"))
        await set_state(session, us)
        if order is None or order.bot_id != bot.id or order.payment_status != PAID_PENDING:
            await tg.send_message(chat_id=uid, text="Bu chek allaqachon ko‘rib chiqilgan.")
            return True
        order.payment_status, order.updated_at = PAID_REJECTED, utcnow()
        await session.commit()
        why = "" if text in ("/skip", "") else f"\nSabab: {esc(text[:500])}"
        await tell_customer(tg, order, f"❌ Buyurtma <b>#{order.id}</b> uchun chek tasdiqlanmadi.{why}\nTo‘g‘ri chekni qayta yuborishingiz mumkin.",
                            kb_of([[Btn("📸 Chek yuborish", callback_data=f"sh:orcpt:{order.id}")]]))
        await tg.send_message(chat_id=uid, text=f"❌ Chek #{order.id} rad etildi.", reply_markup=kb_of([[Btn("📦 Buyurtma", callback_data=f"sa:o:{order.id}")]]))
        return True
    return False

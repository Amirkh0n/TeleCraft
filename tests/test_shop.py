import pytest
from sqlalchemy import select

from engine import shop as core
from helpers import OWNER, USER, send
from helpers import message as _message
from models.admin_links import AdminLink
from models.shop import (
    CartItem, Order, OrderItem, ShopCategory, ShopImage, ShopProduct, ShopVariant,
)

USER2 = 888


def message(text=None, *, user=USER, **extra):
    return _message(text, user=user, **extra)


def cb(data, user=USER, mid=9):
    return {"update_id": None, "callback_query": {
        "id": "c", "from": {"id": user, "first_name": "Ali"}, "data": data,
        "message": {"message_id": mid, "chat": {"id": user, "type": "private"}},
    }}


def screen(env):
    return env.tg.calls[-1][1]


def datas(env, call=None):
    kb = (call or screen(env)).get("reply_markup")
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data] if kb and hasattr(kb, "inline_keyboard") else []


async def press(env, data, user=USER):
    await send(env, cb(data, user))


async def row(env, model, **where):
    q = select(model).execution_options(populate_existing=True)
    for k, v in where.items():
        q = q.where(getattr(model, k) == v)
    return list((await env.session.execute(q)).scalars().all())


@pytest.fixture
async def sh(env):
    env.bot.kind = "shop"
    env.bot.username = "shopbot"
    await env.session.commit()
    await core.ensure_setup(env.session, env.bot)
    return env


async def settings(env, **kw):
    st = await core.get_settings(env.session, env.bot.id)
    for k, v in kw.items():
        setattr(st, k, v)
    await env.session.commit()
    return st


async def make_product(env, *, title="Krossovka", price=100000, stock=None, variants=(), cat=None, images=1, **kw):
    if cat is None:
        cat = ShopCategory(bot_id=env.bot.id, title="Oyoq kiyim")
        env.session.add(cat)
        await env.session.commit()
    p = ShopProduct(bot_id=env.bot.id, category_id=cat.id, title=title, price=price, stock=stock, **kw)
    env.session.add(p)
    await env.session.commit()
    for i in range(images):
        env.session.add(ShopImage(product_id=p.id, position=i, file_id=f"img{p.id}_{i}"))
    vs = []
    for i, (name, vprice, vstock) in enumerate(variants):
        v = ShopVariant(product_id=p.id, name=name, price=vprice, stock=vstock, position=i)
        env.session.add(v)
        vs.append(v)
    await env.session.commit()
    return p, vs, cat


async def order_cash_pickup(env, user=USER):
    await press(env, "sh:co", user)
    await send(env, message("+998901234567", user=user))
    await press(env, "sh:od:pickup", user)
    await press(env, "sh:op:cash", user)
    await press(env, "sh:ok", user)


# ------------------------------------------------------------------ catalog

async def test_home_and_empty_catalog(sh):
    await send(sh, message("/start"))
    assert "Do‘konimizga" in screen(sh)["text"] and "sh:cat" in datas(sh) and "sa:home" not in datas(sh)
    await press(sh, "sh:cat")
    assert "bo‘sh" in screen(sh)["text"]


async def test_browse_category_product_card_with_discount(sh):
    p, _, cat = await make_product(sh, old_price=150000, stock=3, description="Qulay")
    await press(sh, "sh:cat")
    assert f"sh:c:{cat.id}:0" in datas(sh)
    await press(sh, f"sh:c:{cat.id}:0")
    assert f"sh:p:{p.id}" in datas(sh)
    await press(sh, f"sh:p:{p.id}")
    photo = sh.tg.of("send_photo")[-1]
    assert photo["photo"] == f"img{p.id}_0" and "−33%" in photo["caption"] and "Qulay" in photo["caption"]
    assert f"sh:add:{p.id}" in datas(sh, photo)


async def test_hidden_product_and_category_not_visible(sh):
    p, _, cat = await make_product(sh, is_active=False)
    await press(sh, f"sh:p:{p.id}")
    assert not sh.tg.of("send_photo")
    p.is_active = True
    cat.is_active = False
    await sh.session.commit()
    await press(sh, f"sh:p:{p.id}")
    assert not sh.tg.of("send_photo")
    await press(sh, f"sh:add:{p.id}")
    assert not await row(sh, CartItem)


async def test_album_and_search(sh):
    p, _, _ = await make_product(sh, images=3)
    await press(sh, f"sh:pi:{p.id}")
    assert len(sh.tg.of("send_media_group")[-1]["media"]) == 3
    await send(sh, message("kross"))
    assert f"sh:p:{p.id}" in datas(sh)
    await send(sh, message("yoq narsa"))
    assert "topilmadi" in screen(sh)["text"]


# ------------------------------------------------------------------ cart

async def test_add_to_cart_and_stock_limit(sh):
    p, _, _ = await make_product(sh, stock=2)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, f"sh:add:{p.id}")
    assert (await row(sh, CartItem))[0].qty == 2
    await press(sh, f"sh:add:{p.id}")
    assert "atigi 2" in screen(sh)["text"] and (await row(sh, CartItem))[0].qty == 2


async def test_variant_required_and_priced(sh):
    p, (s, m), _ = await make_product(sh, variants=[("S", None, 5), ("M", 120000, 0)])
    await press(sh, f"sh:add:{p.id}")
    assert "tanlang" in screen(sh)["text"] and not await row(sh, CartItem)
    await press(sh, f"sh:add:{p.id}:{m.id}")  # sold out
    assert not await row(sh, CartItem)
    await press(sh, f"sh:add:{p.id}:{s.id}")
    await press(sh, "sh:cart")
    assert "Krossovka (S)" in screen(sh)["text"] and "100 000" in screen(sh)["text"]


async def test_variant_of_other_product_rejected(sh):
    p1, _, _ = await make_product(sh, variants=[("S", None, None)])
    p2, (v2,), _ = await make_product(sh, title="Boshqa", variants=[("X", None, None)])
    await press(sh, f"sh:add:{p1.id}:{v2.id}")
    assert not await row(sh, CartItem)


async def test_cart_plus_minus_remove_clear(sh):
    p, _, _ = await make_product(sh, stock=2)
    await press(sh, f"sh:add:{p.id}")
    item = (await row(sh, CartItem))[0]
    await press(sh, f"sh:ci:{item.id}:u")
    assert (await row(sh, CartItem))[0].qty == 2
    await press(sh, f"sh:ci:{item.id}:u")  # over stock
    assert (await row(sh, CartItem))[0].qty == 2
    await press(sh, f"sh:ci:{item.id}:d")
    assert (await row(sh, CartItem))[0].qty == 1
    await press(sh, f"sh:ci:{item.id}:d")
    assert not await row(sh, CartItem) and "bo‘sh" in screen(sh)["text"]
    await press(sh, f"sh:add:{p.id}")
    await press(sh, "sh:cclear")
    assert not await row(sh, CartItem)


async def test_cannot_touch_other_users_cart_item(sh):
    p, _, _ = await make_product(sh)
    await press(sh, f"sh:add:{p.id}", user=USER2)
    item = (await row(sh, CartItem))[0]
    await press(sh, f"sh:ci:{item.id}:x", user=USER)
    assert len(await row(sh, CartItem)) == 1


async def test_cart_drops_removed_product_and_clamps_stock(sh):
    p, _, _ = await make_product(sh, stock=5)
    await press(sh, f"sh:add:{p.id}")
    item = (await row(sh, CartItem))[0]
    item.qty = 4
    p.stock = 2
    await sh.session.commit()
    await press(sh, "sh:cart")
    assert "2 ta" in screen(sh)["text"] and (await row(sh, CartItem))[0].qty == 2
    p.stock = 0
    await sh.session.commit()
    await press(sh, "sh:cart")
    assert "tugagani" in screen(sh)["text"] and not await row(sh, CartItem)


# ------------------------------------------------------------------ checkout

async def test_cash_pickup_order_decrements_stock_and_notifies_admin(sh):
    p, _, _ = await make_product(sh, stock=5)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, f"sh:add:{p.id}")
    await order_cash_pickup(sh)
    order = (await row(sh, Order))[0]
    assert order.total == 200000 and order.delivery_fee == 0 and order.phone == "+998901234567" and order.payment_method == "cash"
    assert (await row(sh, ShopProduct))[0].stock == 3 and not await row(sh, CartItem)
    items = await row(sh, OrderItem)
    assert items[0].title == "Krossovka" and items[0].qty == 2
    notice = [kw for kw in sh.tg.of("send_message") if kw["chat_id"] == OWNER and "Yangi buyurtma" in kw["text"]]
    assert notice and f"sa:o:{order.id}" in datas(sh, notice[0])


async def test_delivery_fee_free_threshold_and_address(sh):
    await settings(sh, delivery_fee=15000, free_delivery_from=300000)
    p, _, _ = await make_product(sh, price=100000)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, "sh:co")
    await send(sh, message("901234567"))
    await press(sh, "sh:od:delivery")
    await send(sh, message("yo"))
    assert "batafsil" in screen(sh)["text"]
    await send(sh, message("Toshkent, Chilonzor 5-uy"))
    await press(sh, "sh:op:cash")
    assert "115 000" in screen(sh)["text"]
    await press(sh, "sh:ok")
    order = (await row(sh, Order))[0]
    assert order.delivery_fee == 15000 and order.total == 115000 and order.address == "Toshkent, Chilonzor 5-uy"


async def test_delivery_by_location(sh):
    p, _, _ = await make_product(sh)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, "sh:co")
    await send(sh, message(contact={"phone_number": "998901112233"}))
    await press(sh, "sh:od:delivery")
    await send(sh, message(location={"latitude": 41.3, "longitude": 69.2}))
    await press(sh, "sh:op:cash")
    await press(sh, "sh:ok")
    order = (await row(sh, Order))[0]
    assert order.lat == 41.3 and order.phone == "+998901112233"


async def test_bad_phone_rejected(sh):
    p, _, _ = await make_product(sh)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, "sh:co")
    await send(sh, message("abc"))
    assert "noto‘g‘ri" in screen(sh)["text"] and not await row(sh, Order)


async def test_min_order(sh):
    await settings(sh, min_order=500000)
    p, _, _ = await make_product(sh, price=100000)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, "sh:co")
    assert any("Minimal" in t for t in sh.tg.texts(USER))
    assert not (await row(sh, CartItem))[0].tg_user_id == 0
    await send(sh, message("+998901234567"))
    assert not await row(sh, Order)


async def test_single_option_skips_choice(sh):
    await settings(sh, delivery_enabled=False, card_enabled=False)
    p, _, _ = await make_product(sh)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, "sh:co")
    await send(sh, message("+998901234567"))
    assert "Buyurtmani tasdiqlang" in screen(sh)["text"] and "sh:ok" in datas(sh)


async def test_confirm_without_flow_does_nothing(sh):
    p, _, _ = await make_product(sh)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, "sh:ok")
    assert not await row(sh, Order) and (await row(sh, CartItem))


async def test_oversell_protection_rolls_back(sh):
    p, _, _ = await make_product(sh, stock=2)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, f"sh:add:{p.id}", user=USER2)
    await press(sh, "sh:co")
    await send(sh, message("+998901234567"))
    await press(sh, "sh:od:pickup")
    await press(sh, "sh:op:cash")
    # stock disappears between confirmation and placing the order
    (await row(sh, ShopProduct))[0].stock = 0
    await sh.session.commit()
    await press(sh, "sh:ok")
    assert not await row(sh, Order)
    assert (await row(sh, ShopProduct))[0].stock == 0


async def test_two_users_last_item(sh):
    p, _, _ = await make_product(sh, stock=1)
    await press(sh, f"sh:add:{p.id}", user=USER)
    await press(sh, f"sh:add:{p.id}", user=USER2)
    await order_cash_pickup(sh, USER)
    await order_cash_pickup(sh, USER2)
    assert len(await row(sh, Order)) == 1 and (await row(sh, ShopProduct))[0].stock == 0


# ------------------------------------------------------------------ card payment

async def card_order(sh):
    await settings(sh, card_number="8600 1111 2222 3333", card_holder="A. B.")
    p, _, _ = await make_product(sh, stock=4)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, "sh:co")
    await send(sh, message("+998901234567"))
    await press(sh, "sh:od:pickup")
    await press(sh, "sh:op:card")
    await press(sh, "sh:ok")
    return p, (await row(sh, Order))[0]


async def test_card_order_receipt_and_approve(sh):
    p, order = await card_order(sh)
    assert "8600 1111 2222 3333" in sh.tg.texts(USER)[-1] and order.payment_status == "unpaid"
    await send(sh, message("matn"))
    assert "rasm" in screen(sh)["text"]
    await send(sh, message(photo=[{"file_id": "a"}, {"file_id": "chek"}]))
    order = (await row(sh, Order))[0]
    assert order.payment_status == "pending" and order.receipt_file_id == "chek"
    notice = sh.tg.of("send_photo")[-1]
    assert notice["chat_id"] == OWNER and f"sa:pok:{order.id}" in datas(sh, notice)
    await press(sh, f"sa:pok:{order.id}", user=OWNER)
    assert (await row(sh, Order))[0].payment_status == "paid"
    assert any("tasdiqlandi" in t for t in sh.tg.texts(USER))
    await press(sh, f"sa:pok:{order.id}", user=OWNER)
    assert "allaqachon" in screen(sh)["text"]


async def test_card_reject_then_resend_from_order_page(sh):
    p, order = await card_order(sh)
    await send(sh, message(photo=[{"file_id": "bad"}]))
    await press(sh, f"sa:prj:{order.id}", user=OWNER)
    await send(sh, message("Summa kam", user=OWNER))
    assert (await row(sh, Order))[0].payment_status == "rejected"
    assert any("Summa kam" in t for t in sh.tg.texts(USER))
    await press(sh, f"sh:o:{order.id}")
    assert f"sh:orcpt:{order.id}" in datas(sh)
    await press(sh, f"sh:orcpt:{order.id}")
    await send(sh, message(photo=[{"file_id": "good"}]))
    assert (await row(sh, Order))[0].payment_status == "pending"


async def test_card_disabled_without_number(sh):
    await settings(sh, cash_enabled=False)  # card on but no number -> nothing to pay with
    p, _, _ = await make_product(sh)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, "sh:co")
    assert "qabul qilinmayapti" in screen(sh)["text"]


# ------------------------------------------------------------------ orders lifecycle

async def test_status_flow_notifies_customer_and_cash_marked_paid(sh):
    p, _, _ = await make_product(sh, stock=5)
    await press(sh, f"sh:add:{p.id}")
    await order_cash_pickup(sh)
    order = (await row(sh, Order))[0]
    for status in ("confirmed", "preparing", "shipping", "done"):
        await press(sh, f"sa:os:{order.id}:{status}", user=OWNER)
    order = (await row(sh, Order))[0]
    assert order.status == "done" and order.payment_status == "paid"
    texts = sh.tg.texts(USER)
    assert any("Olib ketishga tayyor" in t for t in texts) and any("Topshirildi" in t for t in texts)
    await press(sh, f"sa:os:{order.id}:confirmed", user=OWNER)  # cannot go backwards
    assert (await row(sh, Order))[0].status == "done"


async def test_customer_cancel_restocks_once(sh):
    p, _, _ = await make_product(sh, stock=5)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, f"sh:add:{p.id}")
    await order_cash_pickup(sh)
    order = (await row(sh, Order))[0]
    assert (await row(sh, ShopProduct))[0].stock == 3
    await press(sh, f"sh:occ:{order.id}")
    await press(sh, f"sh:occ:{order.id}")
    assert (await row(sh, Order))[0].status == "cancelled" and (await row(sh, ShopProduct))[0].stock == 5


async def test_customer_cannot_cancel_after_confirmation(sh):
    p, _, _ = await make_product(sh, stock=5)
    await press(sh, f"sh:add:{p.id}")
    await order_cash_pickup(sh)
    order = (await row(sh, Order))[0]
    await press(sh, f"sa:os:{order.id}:confirmed", user=OWNER)
    await press(sh, f"sh:occ:{order.id}")
    assert (await row(sh, Order))[0].status == "confirmed"


async def test_admin_cancel_restocks_variant(sh):
    p, (v,), _ = await make_product(sh, variants=[("M", None, 3)])
    await press(sh, f"sh:add:{p.id}:{v.id}")
    await order_cash_pickup(sh)
    order = (await row(sh, Order))[0]
    assert (await row(sh, ShopVariant))[0].stock == 2
    await press(sh, f"sa:oxok:{order.id}", user=OWNER)
    assert (await row(sh, ShopVariant))[0].stock == 3
    assert any("bekor qilindi" in t for t in sh.tg.texts(USER))


async def test_orders_are_private(sh):
    p, _, _ = await make_product(sh)
    await press(sh, f"sh:add:{p.id}")
    await order_cash_pickup(sh)
    order = (await row(sh, Order))[0]
    await press(sh, f"sh:o:{order.id}", user=USER2)
    assert "Sizda hali buyurtma yo‘q" in screen(sh)["text"]
    await press(sh, f"sh:occ:{order.id}", user=USER2)
    assert (await row(sh, Order))[0].status == "new"


async def test_non_admin_cannot_use_admin(sh):
    p, _, _ = await make_product(sh)
    await press(sh, f"sa:pdelok:{p.id}")
    await press(sh, "sa:cn")
    assert await row(sh, ShopProduct)
    await send(sh, message("/admin"))
    assert "Admin panel" not in str(sh.tg.calls[-1][1].get("text", ""))


async def test_deleting_product_keeps_old_orders(sh):
    p, _, _ = await make_product(sh, stock=5)
    await press(sh, f"sh:add:{p.id}")
    await order_cash_pickup(sh)
    await press(sh, f"sa:pdelok:{p.id}", user=OWNER)
    items = await row(sh, OrderItem)
    assert items and items[0].product_id is None and items[0].title == "Krossovka"
    assert not await row(sh, ShopProduct) and not await row(sh, ShopImage)


# ------------------------------------------------------------------ admin catalog management

async def test_admin_creates_category_product_images_stock_variants(sh):
    await send(sh, message("/admin", user=OWNER))
    assert "Admin panel" in screen(sh)["text"]
    await press(sh, "sa:cn", user=OWNER)
    await send(sh, message("Kiyim", user=OWNER))
    cat = (await row(sh, ShopCategory))[0]
    await press(sh, f"sa:pn:{cat.id}", user=OWNER)
    await send(sh, message("Futbolka", user=OWNER))
    await send(sh, message("abc", user=OWNER))
    assert "raqam" in screen(sh)["text"].lower()
    await send(sh, message("85 000", user=OWNER))
    await send(sh, message("Paxta", user=OWNER))
    await send(sh, message(photo=[{"file_id": "p0"}, {"file_id": "p1"}], user=OWNER))
    await send(sh, message(user=OWNER, document={"file_id": "d1", "mime_type": "image/png"}))
    await send(sh, message("/done", user=OWNER))
    await send(sh, message("12", user=OWNER))
    p = (await row(sh, ShopProduct))[0]
    assert (p.title, p.price, p.description, p.stock) == ("Futbolka", 85000, "Paxta", 12)
    assert [i.file_id for i in sorted(await row(sh, ShopImage), key=lambda i: i.position)] == ["p1", "d1"]
    await press(sh, f"sa:vn:{p.id}", user=OWNER)
    await send(sh, message("S\nM | 90000 | 4\nbad | x", user=OWNER))
    vs = await row(sh, ShopVariant)
    assert {(v.name, v.price, v.stock) for v in vs} == {("S", None, None), ("M", 90000, 4)}
    await press(sh, f"sa:vn:{p.id}", user=OWNER)
    await send(sh, message("m | 95000 | 2", user=OWNER))  # same name (case-insensitive) updates
    vs = await row(sh, ShopVariant)
    assert len(vs) == 2 and {v.price for v in vs} == {None, 95000}


async def test_admin_edit_fields_and_clear(sh):
    p, _, _ = await make_product(sh, old_price=150000, stock=3)
    await press(sh, f"sa:ef:prod:{p.id}:price", user=OWNER)
    await send(sh, message("0", user=OWNER))
    assert "❌" in screen(sh)["text"]
    await send(sh, message("120 000", user=OWNER))
    await press(sh, f"sa:ef:prod:{p.id}:old", user=OWNER)
    await send(sh, message("/clear", user=OWNER))
    await press(sh, f"sa:ef:prod:{p.id}:stock", user=OWNER)
    await send(sh, message("/clear", user=OWNER))
    p = (await row(sh, ShopProduct))[0]
    assert (p.price, p.old_price, p.stock) == (120000, None, None)
    await press(sh, f"sa:ef:prod:{p.id}:title", user=OWNER)
    await send(sh, message("/clear", user=OWNER))  # title is not clearable
    assert (await row(sh, ShopProduct))[0].title == "Krossovka"


async def test_settings_and_toggles(sh):
    await press(sh, "sa:ef:set:0:card", user=OWNER)
    await send(sh, message("12", user=OWNER))
    assert "❌" in screen(sh)["text"]
    await send(sh, message("8600123456789012", user=OWNER))
    await press(sh, "sa:ef:set:0:fee", user=OWNER)
    await send(sh, message("15 000", user=OWNER))
    await press(sh, "sa:tg:pickup", user=OWNER)
    st = await core.get_settings(sh.session, sh.bot.id)
    await sh.session.refresh(st)
    assert st.card_number == "8600 1234 5678 9012" and st.delivery_fee == 15000 and st.pickup_enabled is False


async def test_reorder_and_delete_category_cascade(sh):
    p, _, cat = await make_product(sh)
    cat2 = ShopCategory(bot_id=sh.bot.id, title="Ikkinchi", position=1)
    sh.session.add(cat2)
    await sh.session.commit()
    await press(sh, f"sa:cup:{cat2.id}", user=OWNER)
    assert [c.title for c in sorted(await row(sh, ShopCategory), key=lambda c: c.position)] == ["Ikkinchi", "Oyoq kiyim"]
    await press(sh, f"sa:cdelok:{cat.id}", user=OWNER)
    assert not await row(sh, ShopProduct) and len(await row(sh, ShopCategory)) == 1


async def test_admin_cannot_touch_other_bot_data(sh):
    p, _, cat = await make_product(sh)
    p.bot_id = cat.bot_id = 999
    await sh.session.commit()
    await press(sh, f"sa:pdelok:{p.id}", user=OWNER)
    await press(sh, f"sa:cdelok:{cat.id}", user=OWNER)
    assert await row(sh, ShopProduct) and await row(sh, ShopCategory)


async def test_stats_and_extra_admin(sh):
    sh.session.add(AdminLink(bot_id=sh.bot.id, admin_tg_id=USER2))
    await sh.session.commit()
    p, _, _ = await make_product(sh)
    await press(sh, f"sh:add:{p.id}")
    await order_cash_pickup(sh)
    await press(sh, "sa:stats", user=USER2)
    assert "Statistika" in screen(sh)["text"] and "Krossovka" in screen(sh)["text"]
    await press(sh, "sa:ords:n:0", user=USER2)
    assert any(d.startswith("sa:o:") for d in datas(sh))


async def test_deep_link_product(sh):
    p, _, _ = await make_product(sh, title="Havola")
    await send(sh, message(f"/start p{p.id}"))
    assert "Havola" in str(sh.tg.calls[-1][1])


async def test_cancel_during_checkout_removes_keyboard(sh):
    p, _, _ = await make_product(sh)
    await press(sh, f"sh:add:{p.id}")
    await press(sh, "sh:co")
    await send(sh, message("/cancel"))
    assert "Bekor" in sh.tg.texts(USER)[-2]
    await send(sh, message("+998901234567"))
    assert not await row(sh, Order)


async def test_toggle_shop_mode_creates_menu_and_router(env):
    from constructor.flows.cinema import set_kind
    from models.menus import Menu
    from models.shop import KIND_SHOP
    await set_kind(env.session, env.bot, KIND_SHOP)
    menu = (await env.session.execute(select(Menu))).scalar_one()
    assert menu.is_start and "Do‘konimizga" in menu.message_text
    await send(env, message("/start"))
    assert any("sh:cat" in str(kw.get("reply_markup")) for kw in env.tg.of("send_message"))

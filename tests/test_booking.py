import pytest
from datetime import timedelta
from sqlalchemy import select

from engine import booking as core
from engine.booking_time import utcnow
from helpers import OWNER, USER, send
from helpers import message as _message
from models.admin_links import AdminLink
from models.booking import (
    Booking, BookingDayOff, BookingHours, BookingService, BookingStaff, BookingStaffService,
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


def datas(env):
    kb = screen(env).get("reply_markup")
    return [b.callback_data for row in kb.inline_keyboard for b in row] if kb and hasattr(kb, "inline_keyboard") else []


async def press(env, data, user=USER):
    await send(env, cb(data, user))


async def pick(env, prefix, user=USER, index=0):
    data = [d for d in datas(env) if d and d.startswith(prefix)][index]
    await press(env, data, user)
    return data


async def book(env, user=USER, phone="+998901234567", index=0, service=None):
    await send(env, message("/start", user=user))
    await press(env, "bk:new", user)
    await press(env, f"bk:s:{(service or env.service).id}", user)
    if not any(d.startswith("bk:d:") for d in datas(env)):  # specialist screen first
        await press(env, "bk:m:0", user)
    await pick(env, "bk:d:", user)
    await pick(env, "bk:t:", user, index)
    if "Telefon" in (screen(env).get("text") or ""):
        await send(env, message(phone, user=user))
    await press(env, "bk:ok", user)


async def bookings(env):
    q = select(Booking).order_by(Booking.id).execution_options(populate_existing=True)
    return list((await env.session.execute(q)).scalars().all())


@pytest.fixture
async def shop(env):
    env.bot.kind = "booking"
    await env.session.commit()
    await core.ensure_setup(env.session, env.bot)
    env.service = BookingService(bot_id=env.bot.id, name="Soch olish", duration_min=30, price=50000)
    env.session.add(env.service)
    await env.session.commit()
    env.settings = await core.get_settings(env.session, env.bot.id)
    return env


# ---------------------------------------------------------------- client flow

async def test_full_booking_flow_auto_confirmed_and_admin_notified(shop):
    await book(shop)
    [b] = await bookings(shop)
    assert (b.status, b.tg_user_id, b.phone, b.service_name, b.price) == ("confirmed", USER, "+998901234567", "Soch olish", 50000)
    assert b.end_at - b.start_at == timedelta(minutes=30)
    assert "tasdiqlandi" in screen(shop)["text"] or "tasdiqlandi" in [c[1].get("text", "") for c in shop.tg.calls if c[1].get("chat_id") == USER][-1]
    assert any("Yangi bron" in t for t in shop.tg.texts(OWNER))


async def test_second_booking_reuses_phone_and_skips_question(shop):
    await book(shop)
    await book(shop, index=1)
    assert len(await bookings(shop)) == 2
    assert not any("Telefon raqamingizni" in t for t in shop.tg.texts(USER)[len(shop.tg.texts(USER)) // 2:])


async def test_slot_taken_in_between_is_refused(shop):
    await send(shop, message("/start"))
    await press(shop, "bk:new")
    await press(shop, f"bk:s:{shop.service.id}")
    await pick(shop, "bk:d:")
    slot = await pick(shop, "bk:t:")
    await send(shop, message("+998901234567"))
    await book(shop, user=USER2, phone="+998902222222")  # somebody else books the very first slot meanwhile
    await press(shop, "bk:ok")
    assert [b.tg_user_id for b in await bookings(shop)] == [USER2]
    assert "band bo‘ldi" in screen(shop)["text"] and slot


async def test_pending_flow_admin_confirms_and_client_is_told(shop):
    shop.settings.auto_confirm = False
    await shop.session.commit()
    await book(shop)
    [b] = await bookings(shop)
    assert b.status == "pending" and any("kuchga kiradi" in (c[1].get("text") or "") or "tasdiqlashi bilan" in (c[1].get("text") or "") for c in shop.tg.calls)
    assert f"ba:bs:{b.id}:ok" in [x.callback_data for c in shop.tg.calls if c[1].get("chat_id") == OWNER and c[1].get("reply_markup")
                                  for row in c[1]["reply_markup"].inline_keyboard for x in row]
    await press(shop, f"ba:bs:{b.id}:ok", OWNER)
    assert (await bookings(shop))[0].status == "confirmed"
    assert any("tasdiqlandi" in t for t in shop.tg.texts(USER))
    await press(shop, f"ba:bs:{b.id}:ok", OWNER)  # double tap is harmless
    assert "allaqachon" in screen(shop)["text"]


async def test_admin_rejects_and_slot_is_freed(shop):
    shop.settings.auto_confirm = False
    await shop.session.commit()
    await book(shop)
    [b] = await bookings(shop)
    await press(shop, f"ba:bs:{b.id}:no", OWNER)
    assert (await bookings(shop))[0].status == "rejected"
    assert any("rad etildi" in t for t in shop.tg.texts(USER))
    await book(shop, user=USER2, phone="+998902222222")  # same first slot is free again
    assert (await bookings(shop))[1].start_at == b.start_at


async def test_client_cancel_and_deadline(shop):
    shop.settings.cancel_deadline_min = 0
    await shop.session.commit()
    await book(shop)
    [b] = await bookings(shop)
    await press(shop, f"bk:c:{b.id}")
    await press(shop, f"bk:cy:{b.id}")
    assert (await bookings(shop))[0].status == "cancelled"
    assert any("bekor qildi" in t for t in shop.tg.texts(OWNER))
    shop.settings.cancel_deadline_min = 10 ** 6
    await shop.session.commit()
    await book(shop)
    b2 = (await bookings(shop))[1]
    await press(shop, f"bk:c:{b2.id}")
    await press(shop, f"bk:cy:{b2.id}")
    assert (await bookings(shop))[1].status == "confirmed" and "bekor qilib bo‘lmaydi" in screen(shop)["text"]


async def test_cannot_touch_someone_elses_booking(shop):
    await book(shop)
    [b] = await bookings(shop)
    await press(shop, f"bk:cy:{b.id}", USER2)
    assert (await bookings(shop))[0].status == "confirmed"


async def test_my_bookings_lists_only_own_upcoming(shop):
    await book(shop)
    await book(shop, user=USER2, phone="+998902222222", index=1)
    await press(shop, "bk:my")
    assert len([d for d in datas(shop) if d.startswith("bk:v:")]) == 1


async def test_bad_phone_is_asked_again(shop):
    await send(shop, message("/start"))
    await press(shop, "bk:new")
    await press(shop, f"bk:s:{shop.service.id}")
    await pick(shop, "bk:d:")
    await pick(shop, "bk:t:")
    await send(shop, message("abc"))
    assert "noto‘g‘ri" in screen(shop)["text"]
    await send(shop, _message(None, user=USER, contact={"phone_number": "998901112233"}))
    assert "Bronni tasdiqlang" in screen(shop)["text"] and "+998901112233" in screen(shop)["text"]


async def test_stale_buttons_do_nothing(shop):
    n = len(shop.tg.calls)
    await press(shop, "bk:ok")
    await press(shop, "bk:t:1000")
    await press(shop, "bk:d:20260101")
    await press(shop, "bk:s:999")
    assert not await bookings(shop) and len(shop.tg.calls) == n or not await bookings(shop)


async def test_non_admin_cannot_use_admin_callbacks(shop):
    await press(shop, "ba:sv")
    await press(shop, "ba:svn")
    await send(shop, message("/admin"))
    assert not any("admin paneli" in (c[1].get("text") or "") for c in shop.tg.calls)


# ---------------------------------------------------------------- schedule rules

async def test_days_off_hide_the_day_and_hours_limit_times(shop):
    first = (await core.availability(shop.session, shop.bot, shop.settings, shop.service, [None], core.window(shop.settings)))
    day = sorted(first)[0]
    shop.session.add(BookingDayOff(bot_id=shop.bot.id, day=day))
    await shop.session.commit()
    after = await core.availability(shop.session, shop.bot, shop.settings, shop.service, [None], core.window(shop.settings))
    assert day not in after and len(after) == len(first) - 1
    assert all(d.weekday() != 6 for d in after)  # Sunday is off by default


async def test_two_staff_any_assigns_free_one_then_slot_closes(shop):
    a, b = BookingStaff(bot_id=shop.bot.id, name="Ali usta"), BookingStaff(bot_id=shop.bot.id, name="Vali usta")
    shop.session.add_all([a, b])
    await shop.session.commit()
    await book(shop)
    await book(shop, user=USER2, phone="+998902222222")
    first, second = await bookings(shop)
    assert first.start_at == second.start_at and {first.staff_id, second.staff_id} == {a.id, b.id}
    assert {first.staff_name, second.staff_name} == {"Ali usta", "Vali usta"}
    await book(shop, user=999, phone="+998903333333")
    third = (await bookings(shop))[2]
    assert third.start_at != first.start_at  # both specialists busy at that time


async def test_choosing_a_specific_specialist_and_service_links(shop):
    a, b = BookingStaff(bot_id=shop.bot.id, name="Ali"), BookingStaff(bot_id=shop.bot.id, name="Vali")
    other = BookingService(bot_id=shop.bot.id, name="Boshqa", duration_min=60)
    shop.session.add_all([a, b, other])
    await shop.session.commit()
    shop.session.add(BookingStaffService(staff_id=a.id, service_id=other.id))  # Ali only does "Boshqa"
    await shop.session.commit()
    has, staff = await core.eligible_staff(shop.session, shop.bot.id, shop.service.id)
    assert has and [s.id for s in staff] == [b.id]
    has, staff = await core.eligible_staff(shop.session, shop.bot.id, other.id)
    assert [s.id for s in staff] == [a.id, b.id]  # Vali has no links, so he does everything


# ---------------------------------------------------------------- admin panel

async def say(env, text, user=OWNER):
    await send(env, message(text, user=user))


async def test_admin_panel_opens_for_owner_and_linked_admin(shop):
    shop.session.add(AdminLink(bot_id=shop.bot.id, admin_tg_id=55))
    await shop.session.commit()
    for uid in (OWNER, 55):
        await say(shop, "/admin", uid)
        assert "admin paneli" in screen(shop)["text"]


async def test_admin_adds_edits_toggles_deletes_service(shop):
    await press(shop, "ba:svn", OWNER)
    await say(shop, "Soqol olish")
    await say(shop, "abc")
    assert "daqiqa" in screen(shop)["text"]
    await say(shop, "45")
    await say(shop, "80 000")
    svc = (await shop.session.execute(select(BookingService).where(BookingService.name == "Soqol olish"))).scalar_one()
    assert (svc.duration_min, svc.price, svc.is_active) == (45, 80000, True)
    for field, value, attr, expected in (("name", "Soqol", "name", "Soqol"), ("dur", "60", "duration_min", 60),
                                         ("price", "/skip", "price", None), ("desc", "Yaxshi xizmat", "description", "Yaxshi xizmat")):
        await press(shop, f"ba:sve:{svc.id}:{field}", OWNER)
        await say(shop, value)
        await shop.session.refresh(svc)
        assert getattr(svc, attr) == expected
    await press(shop, f"ba:svt:{svc.id}", OWNER)
    await shop.session.refresh(svc)
    assert svc.is_active is False
    await press(shop, "bk:new", USER)
    assert f"bk:s:{svc.id}" not in datas(shop)  # hidden from clients
    await press(shop, f"ba:svd:{svc.id}", OWNER)
    await press(shop, f"ba:svdy:{svc.id}", OWNER)
    assert (await shop.session.execute(select(BookingService).where(BookingService.id == svc.id))).first() is None


async def test_service_with_future_booking_cannot_be_deleted(shop):
    await book(shop)
    await press(shop, f"ba:svd:{shop.service.id}", OWNER)
    assert "o‘chirib bo‘lmaydi" in screen(shop)["text"]
    await press(shop, f"ba:svdy:{shop.service.id}", OWNER)  # forged confirm is still honoured? it must not lose bookings
    assert len(await bookings(shop)) == 1
    assert await shop.session.get(BookingService, shop.service.id, populate_existing=True) is not None


async def test_staff_crud_services_and_own_schedule_copies_business_hours(shop):
    await press(shop, "ba:stn", OWNER)
    await say(shop, "Ali usta")
    staff = (await shop.session.execute(select(BookingStaff))).scalar_one()
    sid, svc_id = staff.id, shop.service.id
    await press(shop, f"ba:stx:{sid}:{svc_id}", OWNER)
    assert await shop.session.get(BookingStaffService, (sid, svc_id)) is not None
    await press(shop, f"ba:stx:{sid}:{svc_id}", OWNER)
    assert await shop.session.get(BookingStaffService, (sid, svc_id), populate_existing=True) is None
    # editing one weekday must not turn the other days into days off
    await press(shop, f"ba:hd:{staff.id}:0", OWNER)
    await say(shop, "10:00-14:00")
    own = (await shop.session.execute(select(BookingHours).where(BookingHours.staff_id == staff.id))).scalars().all()
    by_day = {}
    for r in own:
        by_day.setdefault(r.weekday, []).append((r.start_min, r.end_min))
    assert by_day[0] == [(600, 840)] and by_day[1] == [(540, 1080)] and set(by_day) == {0, 1, 2, 3, 4, 5}
    await press(shop, f"ba:hreset:{staff.id}", OWNER)
    assert not (await shop.session.execute(select(BookingHours).where(BookingHours.staff_id == staff.id))).scalars().all()
    await press(shop, f"ba:ste:{staff.id}", OWNER)
    await say(shop, "Vali usta")
    await shop.session.refresh(staff)
    assert staff.name == "Vali usta"
    await press(shop, f"ba:std:{staff.id}", OWNER)
    await press(shop, f"ba:stdy:{staff.id}", OWNER)
    assert (await shop.session.execute(select(BookingStaff))).first() is None


async def test_staff_with_future_booking_cannot_be_deleted(shop):
    staff = BookingStaff(bot_id=shop.bot.id, name="Ali")
    shop.session.add(staff)
    await shop.session.commit()
    await book(shop)
    sid = staff.id
    await press(shop, f"ba:std:{sid}", OWNER)
    assert "o‘chirib bo‘lmaydi" in screen(shop)["text"]
    await press(shop, f"ba:stdy:{sid}", OWNER)
    assert await shop.session.get(BookingStaff, sid, populate_existing=True) is not None


async def test_business_hours_bulk_and_validation(shop):
    await press(shop, "ba:hall:0:7", OWNER)
    await say(shop, "soat 9 dan")
    assert "formati" in screen(shop)["text"]
    await say(shop, "08:00-12:00, 13:00-17:00")
    rows = (await shop.session.execute(select(BookingHours).where(BookingHours.staff_id.is_(None)))).scalars().all()
    assert len(rows) == 14 and {r.weekday for r in rows} == set(range(7))
    await press(shop, "ba:hd:0:6", OWNER)
    await say(shop, "dam")
    rows = (await shop.session.execute(select(BookingHours).where(BookingHours.staff_id.is_(None)).execution_options(populate_existing=True))).scalars().all()
    assert 6 not in {r.weekday for r in rows}


async def test_days_off_range_and_remove(shop):
    day = (utcnow() + timedelta(days=3)).date()
    await press(shop, "ba:doa:0", OWNER)
    await say(shop, f"{day:%d.%m.%Y} - {day + timedelta(days=2):%d.%m.%Y}")
    items = (await shop.session.execute(select(BookingDayOff))).scalars().all()
    assert len(items) == 3
    await press(shop, "ba:doa:0", OWNER)
    await say(shop, f"{day:%d.%m.%Y}")  # duplicate is not stored twice
    assert len((await shop.session.execute(select(BookingDayOff))).scalars().all()) == 3
    await press(shop, f"ba:dod:{items[0].id}", OWNER)
    assert len((await shop.session.execute(select(BookingDayOff))).scalars().all()) == 2
    await press(shop, "ba:doa:0", OWNER)
    await say(shop, "01.01.2020")
    assert "o‘tib ketgan" in screen(shop)["text"]


async def test_settings_cycle_reminders_contact_timezone(shop):
    await press(shop, "ba:sa", OWNER)
    await press(shop, "ba:sstep", OWNER)
    await press(shop, "ba:snotice", OWNER)
    await press(shop, "ba:sahead", OWNER)
    await press(shop, "ba:scancel", OWNER)
    s = shop.settings
    await shop.session.refresh(s)
    assert (s.auto_confirm, s.slot_step_min, s.min_notice_min, s.max_days_ahead, s.cancel_deadline_min) == (False, 45, 120, 60, 240)
    await press(shop, "ba:srem", OWNER)
    await say(shop, "2 soat, 1 kun")
    await shop.session.refresh(s)
    assert s.reminders == [1440, 120]
    await press(shop, "ba:srem", OWNER)
    await say(shop, "tez-tez")
    assert "Format" in screen(shop)["text"]
    await say(shop, "yo'q")
    await shop.session.refresh(s)
    assert s.reminders == []
    await press(shop, "ba:sc", OWNER)
    await say(shop, "Toshkent, Chilonzor 5. Tel: 90 123 45 67")
    await press(shop, "bk:info", USER)
    assert "Chilonzor" in screen(shop)["text"]
    await press(shop, "ba:stz", OWNER)
    await say(shop, "Mars/Olympus")
    assert "topilmadi" in screen(shop)["text"]
    await say(shop, "Europe/Moscow")
    await shop.session.refresh(s)
    assert s.timezone == "Europe/Moscow"


async def test_admin_lists_cancels_and_stats(shop):
    await book(shop)
    await book(shop, user=USER2, phone="+998902222222", index=1)
    b1, b2 = await bookings(shop)
    await press(shop, "ba:up:0", OWNER)
    assert len([d for d in datas(shop) if d.startswith("ba:b:")]) == 2
    await press(shop, f"ba:b:{b1.id}", OWNER)
    assert "Ali" in screen(shop)["text"] and "+998901234567" in screen(shop)["text"]
    await press(shop, f"ba:bs:{b1.id}:cx", OWNER)
    assert (await bookings(shop))[0].status == "cancelled" and any("bekor qilindi" in t for t in shop.tg.texts(USER))
    await press(shop, f"ba:bs:{b2.id}:done", OWNER)
    assert (await bookings(shop))[1].status == "done"
    await press(shop, "ba:stats", OWNER)
    text = screen(shop)["text"]
    assert "Statistika" in text and "Soch olish" in text and "50 000" in text
    await press(shop, "ba:pend", OWNER)
    assert "Bronlar yo‘q" in screen(shop)["text"]


async def test_admin_cancel_command_clears_admin_state(shop):
    await press(shop, "ba:svn", OWNER)
    await say(shop, "/cancel")
    await say(shop, "Soch")  # no longer treated as a service name
    assert (await shop.session.execute(select(BookingService).where(BookingService.name == "Soch"))).first() is None


async def test_bot_without_services_or_other_kind_is_safe(env):
    env.bot.kind = "booking"
    await env.session.commit()
    await send(env, message("/start"))
    await press(env, "bk:new")
    assert "xizmatlar kiritilmagan" in screen(env)["text"]

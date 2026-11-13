from datetime import timedelta

import pytest
from sqlalchemy import select

from engine import course as core
from engine.booking_time import utcnow
from helpers import OWNER, USER, send
from helpers import message as _message
from models.admin_links import AdminLink
from models.course import (
    Course, CourseModule, CoursePayment, CourseQuestion, Enrollment, Lesson, LessonFile, LessonProgress,
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
async def cr(env):
    env.bot.kind = "course"
    env.bot.username = "coursebot"
    await env.session.commit()
    await core.ensure_setup(env.session, env.bot)
    return env


async def make_course(env, *, n=3, access="free", unlock="all", published=True, **kw):
    c = Course(bot_id=env.bot.id, title=kw.pop("title", "Python"), access=access, unlock_mode=unlock, is_published=published, **kw)
    env.session.add(c)
    await env.session.commit()
    m = CourseModule(course_id=c.id, title="1-hafta", position=0)
    env.session.add(m)
    await env.session.commit()
    lessons = []
    for i in range(n):
        ls = Lesson(course_id=c.id, module_id=m.id, title=f"Dars {i + 1}", text=f"Matn {i + 1}", position=i)
        env.session.add(ls)
        await env.session.commit()
        env.session.add(LessonFile(lesson_id=ls.id, position=0, file_type="video", file_id=f"vid{i}"))
        lessons.append(ls)
    await env.session.commit()
    return c, lessons


# ------------------------------------------------------------------ student side

async def test_start_shows_home(cr):
    await send(cr, message("/start"))
    assert "Kurs botiga" in screen(cr)["text"]
    assert "cr:cat:0" in datas(cr)
    assert "ca:home" not in datas(cr)


async def test_admin_sees_admin_button(cr):
    await send(cr, message("/start", user=OWNER))
    assert "ca:home" in datas(cr)


async def test_catalog_hides_drafts(cr):
    await make_course(cr, title="Ochiq")
    await make_course(cr, title="Qoralama", published=False)
    await press(cr, "cr:cat:0")
    text = str(screen(cr)["reply_markup"])
    assert "Ochiq" in text and "Qoralama" not in text


async def test_free_course_enroll_and_lessons_all_open(cr):
    c, ls = await make_course(cr)
    await press(cr, f"cr:join:{c.id}")
    assert len(await row(cr, Enrollment, course_id=c.id, tg_user_id=USER)) == 1
    await press(cr, f"cr:l:{ls[2].id}")
    videos = cr.tg.of("send_video")
    assert videos and videos[-1]["protect_content"] is True and videos[-1]["video"] == "vid2"
    assert "Matn 3" in screen(cr)["text"]
    assert f"cr:done:{ls[2].id}" in datas(cr)


async def test_join_twice_is_idempotent(cr):
    c, _ = await make_course(cr)
    await press(cr, f"cr:join:{c.id}")
    await press(cr, f"cr:join:{c.id}")
    assert len(await row(cr, Enrollment, course_id=c.id)) == 1


async def test_not_enrolled_cannot_open_lesson_but_preview_ok(cr):
    c, ls = await make_course(cr)
    await press(cr, f"cr:l:{ls[0].id}")
    assert not cr.tg.of("send_video")
    assert "yoziling" in screen(cr)["text"]
    ls[0].is_preview = True
    await cr.session.commit()
    await press(cr, f"cr:l:{ls[0].id}")
    assert cr.tg.of("send_video")


async def test_draft_course_hidden_from_students(cr):
    c, _ = await make_course(cr, published=False)
    await press(cr, f"cr:c:{c.id}")
    assert "topilmadi" in screen(cr)["text"]


async def test_sequential_unlock_and_completion_certificate(cr):
    c, ls = await make_course(cr, n=2, unlock="seq")
    await press(cr, f"cr:join:{c.id}")
    await press(cr, f"cr:l:{ls[1].id}")
    assert "yopiq" in screen(cr)["text"] and not cr.tg.of("send_video")
    await press(cr, f"cr:l:{ls[0].id}")
    await press(cr, f"cr:done:{ls[0].id}")
    assert f"cr:l:{ls[1].id}" in datas(cr)
    await press(cr, f"cr:done:{ls[0].id}")  # twice does not duplicate
    assert len(await row(cr, LessonProgress, tg_user_id=USER)) == 1
    await press(cr, f"cr:l:{ls[1].id}")
    assert cr.tg.of("send_video")[-1]["video"] == "vid1"
    await press(cr, f"cr:done:{ls[1].id}")
    assert "SERTIFIKAT" in screen(cr)["text"]
    assert (await row(cr, Enrollment, tg_user_id=USER))[0].completed_at is not None


async def test_drip_locked_then_open(cr):
    c, ls = await make_course(cr, n=3, unlock="drip", drip_days=1)
    await press(cr, f"cr:join:{c.id}")
    await press(cr, f"cr:l:{ls[1].id}")
    assert "Ochilish vaqti" in screen(cr)["text"]
    en = (await row(cr, Enrollment))[0]
    en.enrolled_at = utcnow() - timedelta(days=1, hours=1)
    await cr.session.commit()
    await press(cr, f"cr:l:{ls[1].id}")
    assert cr.tg.of("send_video")[-1]["video"] == "vid1"


async def test_go_continues_from_first_unfinished(cr):
    c, ls = await make_course(cr, n=3)
    await press(cr, f"cr:join:{c.id}")
    await press(cr, f"cr:done:{ls[0].id}")
    await press(cr, f"cr:go:{c.id}")
    assert cr.tg.of("send_video")[-1]["video"] == "vid1"


async def test_code_course(cr):
    c, ls = await make_course(cr, access="code", access_code="Secret7")
    await press(cr, f"cr:code:{c.id}")
    await send(cr, message("wrong"))
    assert "noto‘g‘ri" in screen(cr)["text"] and not await row(cr, Enrollment)
    await send(cr, message("secret7"))
    assert len(await row(cr, Enrollment, via="code")) == 1


async def test_code_attempts_limited(cr):
    c, _ = await make_course(cr, access="code", access_code="x1")
    await press(cr, f"cr:code:{c.id}")
    for _ in range(5):
        await send(cr, message("nope"))
    assert "tugadi" in screen(cr)["text"]
    await send(cr, message("x1"))
    assert not await row(cr, Enrollment)


async def test_code_from_home_finds_course(cr):
    c, _ = await make_course(cr, access="code", access_code="HOME1")
    await press(cr, "cr:codeany")
    await send(cr, message("home1"))
    assert len(await row(cr, Enrollment, course_id=c.id)) == 1


async def test_join_wrong_access_type_is_ignored(cr):
    c, _ = await make_course(cr, access="paid", price=50000)
    await press(cr, f"cr:join:{c.id}")
    assert not await row(cr, Enrollment)


async def test_paid_flow_approve(cr):
    c, ls = await make_course(cr, access="paid", price=150000)
    st = await core.get_settings(cr.session, cr.bot.id)
    st.card_number = "8600 1234 5678 9012"
    await cr.session.commit()
    await press(cr, f"cr:pay:{c.id}")
    assert "8600 1234 5678 9012" in screen(cr)["text"] and "150 000" in screen(cr)["text"]
    await press(cr, f"cr:rcpt:{c.id}")
    await send(cr, message("matn"))
    assert "rasm" in screen(cr)["text"]
    await send(cr, message(photo=[{"file_id": "small"}, {"file_id": "bigphoto"}]))
    pays = await row(cr, CoursePayment)
    assert len(pays) == 1 and pays[0].receipt_file_id == "bigphoto" and pays[0].amount == 150000
    notice = cr.tg.of("send_photo")[-1]
    assert notice["chat_id"] == OWNER and f"ca:pok:{pays[0].id}" in datas(cr, notice)
    # a second receipt while pending is refused
    await press(cr, f"cr:rcpt:{c.id}")
    await send(cr, message(photo=[{"file_id": "again"}]))
    assert len(await row(cr, CoursePayment)) == 1
    await press(cr, f"ca:pok:{pays[0].id}", user=OWNER)
    assert (await row(cr, CoursePayment))[0].status == "approved"
    assert len(await row(cr, Enrollment, via="paid", tg_user_id=USER)) == 1
    assert any("tasdiqlandi" in t for t in cr.tg.texts(USER))
    await press(cr, f"ca:pok:{pays[0].id}", user=OWNER)  # double tap
    assert "allaqachon" in screen(cr)["text"]
    assert len(await row(cr, Enrollment)) == 1


async def test_paid_flow_reject_with_reason_then_retry(cr):
    c, _ = await make_course(cr, access="paid", price=1000)
    st = await core.get_settings(cr.session, cr.bot.id)
    st.card_number = "8600 1111 2222 3333"
    await cr.session.commit()
    await press(cr, f"cr:rcpt:{c.id}")
    await send(cr, message(photo=[{"file_id": "p1"}]))
    pay = (await row(cr, CoursePayment))[0]
    await press(cr, f"ca:prj:{pay.id}", user=OWNER)
    await send(cr, message("Summa noto‘g‘ri", user=OWNER))
    pay = (await row(cr, CoursePayment))[0]
    assert pay.status == "rejected" and pay.reason == "Summa noto‘g‘ri"
    assert any("Summa noto‘g‘ri" in t for t in cr.tg.texts(USER))
    assert not await row(cr, Enrollment)
    await press(cr, f"cr:rcpt:{c.id}")
    await send(cr, message(photo=[{"file_id": "p2"}]))
    assert len(await row(cr, CoursePayment)) == 2


async def test_paid_without_card_info(cr):
    c, _ = await make_course(cr, access="paid", price=1000)
    await press(cr, f"cr:pay:{c.id}")
    assert "kiritilmagan" in screen(cr)["text"]


async def test_non_admin_cannot_use_admin_callbacks(cr):
    c, _ = await make_course(cr, access="paid", price=1000)
    await press(cr, f"ca:del:{c.id}")
    await press(cr, f"ca:delok:{c.id}")
    assert await row(cr, Course)
    await send(cr, message("/admin"))
    assert "Admin panel" not in str(cr.tg.calls[-1][1].get("text", ""))


async def test_question_flow(cr):
    c, ls = await make_course(cr)
    await press(cr, f"cr:join:{c.id}")
    await press(cr, f"cr:ask:{ls[0].id}")
    await send(cr, message("Bu qanday ishlaydi?"))
    q = (await row(cr, CourseQuestion))[0]
    assert q.text == "Bu qanday ishlaydi?"
    assert any(f"ca:qo:{q.id}" in datas(cr, kw) for kw in cr.tg.of("send_message") if kw["chat_id"] == OWNER)
    await press(cr, f"ca:qo:{q.id}", user=OWNER)
    await send(cr, message("Mana bunday", user=OWNER))
    assert (await row(cr, CourseQuestion))[0].answer == "Mana bunday"
    assert any("Mana bunday" in t for t in cr.tg.texts(USER))


async def test_question_requires_enrollment(cr):
    c, ls = await make_course(cr)
    await press(cr, f"cr:ask:{ls[0].id}")
    await send(cr, message("savol"))
    assert not await row(cr, CourseQuestion)


async def test_deep_link_opens_course(cr):
    c, _ = await make_course(cr, title="Chuqur")
    await send(cr, message(f"/start c{c.id}"))
    assert "Chuqur" in str(cr.tg.calls[-1][1])


async def test_my_courses_progress(cr):
    c, ls = await make_course(cr, n=2)
    await press(cr, f"cr:join:{c.id}")
    await press(cr, f"cr:done:{ls[0].id}")
    await press(cr, "cr:my")
    assert "50%" in str(screen(cr)["reply_markup"])


async def test_other_bot_course_not_reachable(cr):
    c, _ = await make_course(cr)
    c.bot_id = 999
    await cr.session.commit()
    await press(cr, f"cr:join:{c.id}")
    assert not await row(cr, Enrollment)


async def test_failed_file_does_not_break_lesson(cr, monkeypatch):
    from telegram.error import BadRequest
    c, ls = await make_course(cr)
    await press(cr, f"cr:join:{c.id}")

    async def boom(**kw):
        raise BadRequest("wrong file identifier")
    monkeypatch.setattr(cr.tg, "send_video", boom, raising=False)
    await press(cr, f"cr:l:{ls[0].id}")
    assert any("yuborilmadi" in t for t in cr.tg.texts(USER)) and "Matn 1" in screen(cr)["text"]


# ------------------------------------------------------------------ admin side

async def test_admin_creates_course_module_lesson_with_files(cr):
    await send(cr, message("/admin", user=OWNER))
    assert "Admin panel" in screen(cr)["text"]
    await press(cr, "ca:cn", user=OWNER)
    await send(cr, message("Yangi kurs", user=OWNER))
    course = (await row(cr, Course))[0]
    assert course.title == "Yangi kurs" and not course.is_published
    await press(cr, f"ca:mn:{course.id}", user=OWNER)
    await send(cr, message("1-modul", user=OWNER))
    module = (await row(cr, CourseModule))[0]
    await press(cr, f"ca:ln:{module.id}", user=OWNER)
    await send(cr, message("Kirish", user=OWNER))
    await send(cr, message("Salom, dars matni", user=OWNER))
    await send(cr, message(user=OWNER, video={"file_id": "V1"}))
    await send(cr, message(user=OWNER, document={"file_id": "D1", "file_name": "a.pdf"}))
    await send(cr, message(user=OWNER, photo=[{"file_id": "P0"}, {"file_id": "P1"}]))
    await send(cr, message(user=OWNER, audio={"file_id": "A1"}))
    await send(cr, message("matn emas", user=OWNER))
    await send(cr, message("/done", user=OWNER))
    lesson = (await row(cr, Lesson))[0]
    files = await row(cr, LessonFile, lesson_id=lesson.id)
    assert [(f.file_type, f.file_id) for f in sorted(files, key=lambda f: f.position)] == [
        ("video", "V1"), ("document", "D1"), ("photo", "P1"), ("audio", "A1")]
    assert lesson.text == "Salom, dars matni"
    assert "Kirish" in screen(cr)["text"]


async def test_admin_preview_sends_unprotected(cr):
    c, ls = await make_course(cr, n=1)
    await press(cr, f"ca:lv:{ls[0].id}", user=OWNER)
    assert cr.tg.of("send_video")[-1]["protect_content"] is False


async def test_publish_requires_lessons_and_settings(cr):
    c = Course(bot_id=cr.bot.id, title="Bo‘sh")
    cr.session.add(c)
    await cr.session.commit()
    await press(cr, f"ca:pub:{c.id}", user=OWNER)
    assert not (await row(cr, Course))[0].is_published
    c2, _ = await make_course(cr, access="paid", price=5000, published=False)
    await press(cr, f"ca:pub:{c2.id}", user=OWNER)
    assert not (await row(cr, Course, id=c2.id))[0].is_published  # no card number yet
    st = await core.get_settings(cr.session, cr.bot.id)
    st.card_number = "8600 1111 2222 3333"
    await cr.session.commit()
    await press(cr, f"ca:pub:{c2.id}", user=OWNER)
    assert (await row(cr, Course, id=c2.id))[0].is_published


async def test_access_switch_asks_for_code_and_price(cr):
    c, _ = await make_course(cr)
    await press(cr, f"ca:acc:{c.id}:code", user=OWNER)
    await send(cr, message("KOD1", user=OWNER))
    assert (await row(cr, Course))[0].access_code == "KOD1"
    await press(cr, f"ca:acc:{c.id}:paid", user=OWNER)
    await send(cr, message("abc", user=OWNER))
    assert (await row(cr, Course))[0].price == 0
    await send(cr, message("120 000", user=OWNER))
    assert (await row(cr, Course))[0].price == 120000


async def test_duplicate_code_rejected(cr):
    await make_course(cr, access="code", access_code="DUP", title="A")
    c2, _ = await make_course(cr, access="code", title="B")
    await press(cr, f"ca:ef:course:{c2.id}:code", user=OWNER)
    await send(cr, message("dup", user=OWNER))
    assert "ishlatilgan" in screen(cr)["text"]


async def test_settings_validation(cr):
    await press(cr, "ca:ef:set:0:card", user=OWNER)
    await send(cr, message("123", user=OWNER))
    assert "❌" in screen(cr)["text"]
    await send(cr, message("8600123456789012", user=OWNER))
    st = await core.get_settings(cr.session, cr.bot.id)
    await cr.session.refresh(st)
    assert st.card_number == "8600 1234 5678 9012"
    await press(cr, "ca:ef:set:0:hour", user=OWNER)
    await send(cr, message("25", user=OWNER))
    await send(cr, message("7", user=OWNER))
    await cr.session.refresh(st)
    assert st.drip_hour == 7
    await press(cr, "ca:ef:set:0:tz", user=OWNER)
    await send(cr, message("Mars/Olympus", user=OWNER))
    assert "Noto‘g‘ri" in screen(cr)["text"]


async def test_reorder_lessons_and_modules(cr):
    c, ls = await make_course(cr, n=3)
    await press(cr, f"ca:ldn:{ls[0].id}", user=OWNER)
    order = [x.title for x in await core.lessons_of(cr.session, c.id)]
    assert order == ["Dars 2", "Dars 1", "Dars 3"]
    await press(cr, f"ca:lup:{ls[2].id}", user=OWNER)
    await cr.session.commit()
    order = [x.title for x in await core.lessons_of(cr.session, c.id)]
    assert order == ["Dars 2", "Dars 3", "Dars 1"]


async def test_delete_lesson_module_course_cascade(cr):
    c, ls = await make_course(cr, n=2)
    await press(cr, f"cr:join:{c.id}")
    await press(cr, f"cr:done:{ls[0].id}")
    await press(cr, f"ca:ldelok:{ls[0].id}", user=OWNER)
    assert len(await row(cr, Lesson)) == 1 and not await row(cr, LessonProgress)
    await press(cr, f"ca:delok:{c.id}", user=OWNER)
    for model in (Course, CourseModule, Lesson, LessonFile, Enrollment):
        assert not await row(cr, model), model


async def test_admin_cannot_touch_other_bots_course(cr):
    c, ls = await make_course(cr)
    c.bot_id = 999
    await cr.session.commit()
    await press(cr, f"ca:delok:{c.id}", user=OWNER)
    await press(cr, f"ca:ldelok:{ls[0].id}", user=OWNER)
    assert await row(cr, Course) and len(await row(cr, Lesson)) == 3


async def test_students_add_and_remove(cr):
    c, ls = await make_course(cr)
    await press(cr, f"ca:sa:{c.id}", user=OWNER)
    await send(cr, message("555", user=OWNER))
    assert len(await row(cr, Enrollment, tg_user_id=555, via="admin")) == 1
    en = (await row(cr, Enrollment))[0]
    await press(cr, f"ca:srok:{en.id}", user=OWNER)
    assert not await row(cr, Enrollment)


async def test_stats_and_added_admin(cr):
    cr.session.add(AdminLink(bot_id=cr.bot.id, admin_tg_id=USER2))
    await cr.session.commit()
    c, _ = await make_course(cr)
    await press(cr, "ca:stats", user=USER2)
    assert "Statistika" in screen(cr)["text"]

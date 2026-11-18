"""Ready-made bot templates."""
import re

from sqlalchemy import select

from constructor.flows import templates as flow
from core.templates import BACK, BY_KEY, TEMPLATES, Sub
from helpers import OWNER
from models.button_actions import ActionType, ButtonAction
from models.buttons import Button
from models.menus import Menu
from models.user_sessions import UserSession
from test_home import Query, buttons, henv, make_msg, upd  # noqa: F401


def test_template_data_is_valid():
    assert len({t.key for t in TEMPLATES}) == len(TEMPLATES) >= 8
    for t in TEMPLATES:
        assert 2 <= len(t.buttons) <= 8 and len(t.start) < 4000
        for text, answer in t.buttons:
            assert text and len(text) <= 60
            for label, reply in (answer.items if isinstance(answer, Sub) else [(text, answer)]):
                assert label and len(label) <= 60 and 0 < len(reply) < 4000
                assert not re.search(r"<(?!/?b>)", reply)  # only <b> is used: Telegram HTML stays valid
            if isinstance(answer, Sub):
                assert 2 <= len(answer.items) <= 6


async def menus_of(env):
    return (await env.session.execute(select(Menu).where(Menu.bot_id == env.bot.id).order_by(Menu.id))).scalars().all()


async def test_apply_builds_menus_buttons_and_back_links(henv):
    bot_id = henv.bot.id
    await flow.apply(henv.session, henv.bot, "edu")
    menus = await menus_of(henv)
    start = next(m for m in menus if m.is_start)
    assert start.message_text.startswith("Assalomu alaykum") and start.columns == 2 and len(menus) == 2
    sub = next(m for m in menus if not m.is_start)
    btns = (await henv.session.execute(select(Button, ButtonAction).join(ButtonAction, ButtonAction.button_id == Button.id).where(Button.menu_id == start.id).order_by(Button.position))).all()
    assert [b.text for b, _ in btns][0] == "📚 Kurslar" and btns[0][1].action_type == ActionType.menu and btns[0][1].value == str(sub.id)
    assert all(a.action_type in (ActionType.menu, ActionType.text) and a.value for _, a in btns)
    sub_btns = (await henv.session.execute(select(Button, ButtonAction).join(ButtonAction, ButtonAction.button_id == Button.id).where(Button.menu_id == sub.id).order_by(Button.position))).all()
    assert sub_btns[-1][0].text == BACK and sub_btns[-1][1].value == str(start.id)  # the way back to the start menu


async def test_replace_keeps_one_start_menu_and_moves_open_screens(henv):
    bot_id, tg_id = henv.bot.id, 777
    await flow.apply(henv.session, henv.bot, "cafe")
    sub = next(m for m in await menus_of(henv) if not m.is_start)
    sub_id = sub.id
    henv.session.add(UserSession(bot_id=bot_id, tg_user_id=tg_id, current_menu_id=sub_id))
    await henv.session.commit()
    assert await flow.has_content(henv.session, bot_id)
    await flow.apply(henv.session, henv.bot, "gym")
    menus = await menus_of(henv)
    assert sum(m.is_start for m in menus) == 1 and [m.title for m in menus if not m.is_start] == ["🎫 Abonementlar"]  # ids may be reused, titles tell
    us = (await henv.session.execute(select(UserSession).where(UserSession.tg_user_id == tg_id))).scalar_one()
    assert us.current_menu_id == next(m.id for m in menus if m.is_start)
    orphans = (await henv.session.execute(select(Button).where(~Button.menu_id.in_([m.id for m in menus])))).scalars().all()
    assert orphans == []


async def test_gallery_preview_and_apply_through_callbacks(henv):
    bot_id = henv.bot.id
    page = make_msg()
    await flow.show_list(upd(OWNER, query=Query(f"tpl:list:{bot_id}", page)), henv.ctx)
    data = [b.callback_data for b in buttons(page.edits[-1][1]["reply_markup"])]
    assert f"tpl:v:salon:{bot_id}" in data and data[-1] == f"bot_{bot_id}"
    page = make_msg()
    await flow.preview(upd(OWNER, query=Query(f"tpl:v:salon:{bot_id}", page)), henv.ctx)
    text, kw = page.edits[-1]
    assert "Go‘zallik saloni" in text and "o‘chiriladi" not in text  # fresh bot: no warning
    page = make_msg()
    await flow.go(upd(OWNER, query=Query(f"tpl:go:salon:{bot_id}", page)), henv.ctx)
    assert any(m.is_start and m.message_text for m in await menus_of(henv))
    page = make_msg()
    await flow.preview(upd(OWNER, query=Query(f"tpl:v:cafe:{bot_id}", page)), henv.ctx)
    assert "o‘chiriladi" in page.edits[-1][0]  # now it has content: warn before replacing


async def test_other_owners_and_junk_are_refused(henv):
    bot_id = henv.bot.id
    for who, data in ((OWNER + 1, f"tpl:go:cafe:{bot_id}"), (OWNER, "tpl:go:nope:%d" % bot_id), (OWNER, "tpl:go:cafe:abc")):
        page = make_msg()
        await flow.go(upd(who, query=Query(data, page)), henv.ctx)
    assert not any(m.message_text for m in await menus_of(henv) if m.message_text and m.message_text.startswith("Assalomu"))

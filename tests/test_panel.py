"""Bot control panel: grouped sections instead of one long list of buttons."""
from constructor.flows import bots, panel
from helpers import OWNER
from models.bots import Bot
from test_home import Query, buttons, henv, make_msg, upd  # noqa: F401


def data(kw):
    return [b.callback_data for b in buttons(kw["reply_markup"]) if b.callback_data]


async def open_panel(env, kind):
    env.bot.kind = kind
    await env.session.commit()
    page = make_msg()
    await bots.open_bot(upd(OWNER, query=Query(f"bot_{env.bot.id}", page)), env.ctx)
    return page.edits[-1][1]


async def test_top_screen_is_short_and_has_the_sections(henv):
    bot_id = henv.bot.id
    kw = await open_panel(henv, "standard")
    d = data(kw)
    assert len(buttons(kw["reply_markup"])) <= 9
    assert {f"grp:content:{bot_id}", f"grp:clients:{bot_id}", f"grp:settings:{bot_id}", f"grp:modes:{bot_id}", "edit_start_message", "test_bot", "bot_status", "back_to_bots"} <= set(d)
    assert not {"cin:home", "bkc:home", "frm:list", "menus", "adm:home", "bc:home"} & set(d)  # moved into sections


async def test_a_mode_bot_shows_only_its_own_panel(henv):
    kw = await open_panel(henv, "course")
    d = data(kw)
    assert "crsc:home" in d and not {"cin:home", "shpc:home"} & set(d) and not any(x.startswith("grp:modes") for x in d)


async def test_every_old_button_is_still_reachable(henv):
    bot_id = henv.bot.id
    reachable = set()
    for name in ("content", "clients", "settings", "modes"):
        page = make_msg()
        await panel.show_group(upd(OWNER, query=Query(f"grp:{name}:{bot_id}", page)), henv.ctx)
        d = data(page.edits[-1][1])
        assert d[-1] == f"bot_{bot_id}"  # every section has a way back
        reachable |= set(d)
    assert {"menus", "start_buttons", "frm:list", "aud:home", "bc:home", "sub:home", "adm:home", "plx:home",
            "cin:home", "bkc:home", "qzc:home", "crsc:home", "shpc:home", "jnpc:home", "pdc:home"} <= reachable


async def test_current_mode_is_marked_and_foreign_bots_are_refused(henv):
    henv.bot.kind = "shop"
    await henv.session.commit()
    page = make_msg()
    await panel.show_group(upd(OWNER, query=Query(f"grp:modes:{henv.bot.id}", page)), henv.ctx)
    titles = [b.text for b in buttons(page.edits[-1][1]["reply_markup"])]
    assert "✅ 🛒 Do‘kon bot" in titles
    other = make_msg()
    await panel.show_group(upd(OWNER + 1, query=Query(f"grp:content:{henv.bot.id}", other)), henv.ctx)
    assert "grp:content" not in " ".join(data(other.edits[-1][1]))  # fell back to the bot list
    junk = make_msg()
    await panel.show_group(upd(OWNER, query=Query("grp:content:abc", junk)), henv.ctx)
    assert junk.edits

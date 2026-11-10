"""Builder helpers for audience, broadcasts and required channels."""
import pytest

from constructor.bot import build_constructor_application
from constructor.flows.audience import normalize_channel_ref, owned_broadcast, parse_button, stats_text
from engine import audience as audience_engine
from engine import broadcast as broadcast_engine
from models.users import User


def test_parse_button():
    assert parse_button("Ochish | https://example.com/a?b=1") == ("Ochish", "https://example.com/a?b=1")
    for bad in ("", "Ochish", "| https://x.com", "Ochish | ftp://x.com", "Ochish | javascript:alert(1)", "x" * 65 + " | https://a.com"):
        with pytest.raises(ValueError):
            parse_button(bad)


@pytest.mark.parametrize("text, expected", [
    ("@my_channel", "@my_channel"),
    ("https://t.me/my_channel", "@my_channel"),
    ("t.me/my_channel/", "@my_channel"),
    ("-1001234567890", -1001234567890),
    ("my_channel", None),
    ("@ab", None),
    ("https://example.com/x", None),
    ("-12", None),
])
def test_normalize_channel_ref(text, expected):
    assert normalize_channel_ref(text) == expected


def test_stats_text_escapes_names_and_lists_sources():
    stats = {"total": 10, "active": 8, "blocked": 2, "new_24h": 1, "new_7d": 3, "new_30d": 9,
             "active_24h": 4, "active_7d": 6, "submissions": 5, "broadcast_messages": 40,
             "sources": [("ig<b>", 6)]}
    text = stats_text("My <Bot>", stats)
    assert "My &lt;Bot&gt;" in text and "ig&lt;b&gt;: 6" in text and "Jami: <b>10</b>" in text


async def test_broadcast_ownership(env):
    mine = await broadcast_engine.create_draft(env.session, env.bot.id, 1, text="x")
    owner_tg = (await env.session.get(User, env.bot.owner_id)).tg_id
    assert (await owned_broadcast(env.session, owner_tg, mine.id))[0].id == mine.id
    assert await owned_broadcast(env.session, owner_tg + 999, mine.id) == (None, None)


async def test_stats_include_broadcast_totals(env):
    b = await broadcast_engine.create_draft(env.session, env.bot.id, 1, text="x")
    b.sent = 12
    await env.session.commit()
    assert (await audience_engine.stats(env.session, env.bot.id))["broadcast_messages"] == 12


def test_all_new_callbacks_are_routable():
    app = build_constructor_application("123456789:ABCdefGHIjklMNOpqrsTUVwxyz0123456789")
    patterns = [h.pattern.pattern for h in app.handlers[0] if hasattr(h, "pattern") and h.pattern is not None]
    import re
    for data in ("aud:home", "sub:home", "sub:add", "sub:del:3", "bc:home", "bc:new", "bc:open:1", "bc:status:1",
                 "bc:preview:1", "bc:btn:1", "bc:ask:1", "bc:go:1", "bc:cancel:1", "frm:list", "scr:open:2"):
        first = next(p for p in patterns if re.search(p, data))
        assert re.search(first, data) and (":" in first or first == data), f"{data} is caught by legacy pattern {first}"

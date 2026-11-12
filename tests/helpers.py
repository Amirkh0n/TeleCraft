"""Shared helpers for engine tests: a recording fake Telegram client and data builders."""
from types import SimpleNamespace

from telegram.error import BadRequest, Forbidden

from engine import router
from models.button_actions import ButtonAction
from models.buttons import Button
from models.forms import Form, FormField
from models.menus import Menu

TOKEN = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz0123456789"
USER = 777
OWNER = 1


class FakeTG:
    """Records what the bot would send. Methods mirror telegram.Bot."""

    def __init__(self):
        self.calls = []
        self.fail_parse_once = False
        self.blocked_chats = set()
        self._next_id = 100

    def _record(self, name, **kw):
        if kw.get("chat_id") in self.blocked_chats:
            raise Forbidden("bot was blocked by the user")
        self.calls.append((name, kw))
        self._next_id += 1
        return SimpleNamespace(message_id=self._next_id)

    async def send_message(self, **kw):
        if self.fail_parse_once and kw.get("parse_mode"):
            self.fail_parse_once = False
            raise BadRequest("Can't parse entities: unsupported start tag")
        return self._record("send_message", **kw)

    async def answer_callback_query(self, *a, **kw):
        return self._record("answer_callback_query", id=a[0] if a else None)

    async def edit_message_text(self, **kw):
        return self._record("edit_message_text", **kw)

    async def send_poll(self, **kw):
        msg = self._record("send_poll", **kw)
        self._polls = getattr(self, "_polls", 0) + 1
        msg.poll = SimpleNamespace(id=f"poll{self._polls}")
        return msg

    async def stop_poll(self, **kw):
        return self._record("stop_poll", **kw)

    async def get_file(self, file_id):
        data = getattr(self, "files", {}).get(file_id, b"")
        return SimpleNamespace(file_id=file_id, download_as_bytearray=self._download(data))

    @staticmethod
    def _download(data):
        async def download_as_bytearray(*a, **kw):
            return bytearray(data)
        return download_as_bytearray

    async def delete_message(self, **kw):
        return self._record("delete_message", **kw)

    def __getattr__(self, name):
        if name.startswith("send_"):
            async def method(**kw):
                return self._record(name, **kw)
            return method
        raise AttributeError(name)

    # helpers for assertions
    def of(self, name):
        return [kw for n, kw in self.calls if n == name]

    def texts(self, chat_id=USER):
        return [kw["text"] for kw in self.of("send_message") if kw["chat_id"] == chat_id]

    def last(self, name="send_message"):
        return self.of(name)[-1]


# ------------------------------------------------------------------ builders

async def add_menu(env, title, text, *, start=False, mode="inline", columns=1, media=None):
    menu = Menu(
        bot_id=env.bot.id, title=title, message_text=text, is_start=start,
        keyboard_mode=mode, columns=columns,
        media_type=media[0] if media else None, media_file_id=media[1] if media else None,
    )
    env.session.add(menu)
    await env.session.commit()
    return menu


async def add_button(env, menu, text, action_type=None, value=None, kind="normal", position=0):
    button = Button(menu_id=menu.id, text=text, kind=kind, position=position)
    env.session.add(button)
    await env.session.flush()
    if action_type:
        env.session.add(ButtonAction(button_id=button.id, action_type=action_type, value=value))
    await env.session.commit()
    return button


async def add_form(env, fields, *, final="Rahmat, qabul qilindi!", intro=None):
    form = Form(bot_id=env.bot.id, title="Ariza", final_message=final, intro_text=intro)
    env.session.add(form)
    await env.session.flush()
    for position, (label, kind, extra) in enumerate(fields):
        env.session.add(FormField(
            form_id=form.id, position=position, label=label, prompt=f"{label}?", type=kind,
            required=extra.get("required", True), options=extra.get("options"),
        ))
    await env.session.commit()
    return form


def message(text=None, *, user=USER, update_id=None, **extra):
    msg = {"chat": {"id": user, "type": "private"}, "from": {"id": user, "first_name": "Ali", "username": "ali"}}
    if text is not None:
        msg["text"] = text
    msg.update(extra)
    return {"update_id": update_id, "message": msg}


def tap(button, *, user=USER, update_id=None):
    return {"update_id": update_id, "callback_query": {
        "id": "cb1", "from": {"id": user, "first_name": "Ali"}, "data": str(button.id),
    }}


async def send(env, update):
    await router.route_update(env.bot, update, env.session, client=env.tg)

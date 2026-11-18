"""A bot's own backup: its menus, buttons, actions and forms as one JSON file, and restoring from it.

Tokens, users and form answers are not included. File ids (media, files, videos) only work for the bot they were
uploaded to, so a backup restored into a different bot drops them, together with admin-message buttons.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import select

from models.button_actions import ActionType, ButtonAction
from models.buttons import Button
from models.forms import Form, FormField
from models.menus import Menu

FORMAT = "telecraft-bot"
VERSION = 1
MAX_MENUS = 100
MAX_BUTTONS = 800
MAX_FORMS = 30
MAX_BYTES = 2 * 1024 * 1024
BOT_SPECIFIC = {ActionType.file.value, ActionType.video.value, ActionType.media.value, ActionType.admin.value}


class BackupError(ValueError):
    """The file is not a usable TeleCraft backup (the message is shown to the owner)."""


async def export_bot(session, bot) -> dict:
    menus = (await session.execute(select(Menu).where(Menu.bot_id == bot.id).order_by(Menu.is_start.desc(), Menu.position, Menu.id))).scalars().all()
    out_menus = []
    for menu in menus:
        rows = (await session.execute(
            select(Button, ButtonAction).outerjoin(ButtonAction, ButtonAction.button_id == Button.id)
            .where(Button.menu_id == menu.id).order_by(Button.position, Button.id))).all()
        out_menus.append({
            "id": menu.id, "title": menu.title, "message_text": menu.message_text, "is_start": bool(menu.is_start), "position": menu.position,
            "keyboard_mode": menu.keyboard_mode, "columns": menu.columns, "media_type": menu.media_type, "media_file_id": menu.media_file_id,
            "buttons": [{"text": b.text, "position": b.position, "kind": b.kind,
                         "action": {"type": a.action_type.value, "value": a.value} if a else None} for b, a in rows]})
    forms = (await session.execute(select(Form).where(Form.bot_id == bot.id).order_by(Form.id))).scalars().all()
    out_forms = []
    for form in forms:
        fields = (await session.execute(select(FormField).where(FormField.form_id == form.id).order_by(FormField.position, FormField.id))).scalars().all()
        out_forms.append({"id": form.id, "title": form.title, "intro_text": form.intro_text, "final_message": form.final_message, "notify_admins": form.notify_admins,
                          "fields": [{"position": f.position, "label": f.label, "prompt": f.prompt, "type": f.type, "required": f.required, "options": f.options} for f in fields]})
    return {"format": FORMAT, "version": VERSION, "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bot_id": bot.id, "bot_username": bot.username, "menus": out_menus, "forms": out_forms}


def dumps(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")


def parse(raw: bytes) -> dict:
    """Validate a backup file. Raises BackupError with a message for the owner."""
    if len(raw) > MAX_BYTES:
        raise BackupError("Fayl juda katta (2 MB dan oshmasin).")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BackupError("Bu TeleCraft zaxira fayli emas (JSON o‘qilmadi).") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BackupError("Bu TeleCraft zaxira fayli emas.")
    if data.get("version") != VERSION:
        raise BackupError("Zaxira fayli versiyasi qo‘llab-quvvatlanmaydi.")
    menus, forms = data.get("menus"), data.get("forms", [])
    if not isinstance(menus, list) or not menus or not isinstance(forms, list):
        raise BackupError("Faylda menyular topilmadi.")
    if len(menus) > MAX_MENUS or len(forms) > MAX_FORMS:
        raise BackupError("Faylda juda ko‘p menyu yoki forma bor.")
    total = 0
    for menu in menus:
        if not isinstance(menu, dict) or not isinstance(menu.get("buttons", []), list) or not isinstance(menu.get("id"), int):
            raise BackupError("Fayl tuzilishi buzilgan.")
        total += len(menu.get("buttons", []))
        for button in menu.get("buttons", []):
            if not isinstance(button, dict) or not str(button.get("text") or "").strip():
                raise BackupError("Fayl tuzilishi buzilgan (tugma matni yo‘q).")
            action = button.get("action")
            if action is not None and (not isinstance(action, dict) or action.get("type") not in {a.value for a in ActionType}):
                raise BackupError("Faylda noma’lum tugma amali bor.")
    if total > MAX_BUTTONS:
        raise BackupError("Faylda juda ko‘p tugma bor.")
    for form in forms:
        if not isinstance(form, dict) or not isinstance(form.get("id"), int) or not str(form.get("title") or "").strip() or not isinstance(form.get("fields", []), list):
            raise BackupError("Faylda forma tuzilishi buzilgan.")
    return data


def summary(data: dict, bot_id: int) -> dict:
    same = data.get("bot_id") == bot_id
    buttons = sum(len(m.get("buttons", [])) for m in data["menus"])
    return {"menus": len(data["menus"]), "buttons": buttons, "forms": len(data.get("forms", [])), "same_bot": same, "exported_at": data.get("exported_at"),
            "from": data.get("bot_username")}


async def restore(session, bot, data: dict) -> dict:
    """Replace the bot's menus and buttons with the backup (forms are added, never deleted)."""
    from constructor.flows.templates import wipe
    same = data.get("bot_id") == bot.id
    start_data = next((m for m in data["menus"] if m.get("is_start")), data["menus"][0])
    start = (await session.execute(select(Menu).where(Menu.bot_id == bot.id, Menu.is_start == True))).scalars().first()  # noqa: E712
    if start is None:
        start = Menu(bot_id=bot.id, title="Bosh menyu", is_start=True, position=0)
        session.add(start)
        await session.flush()

    form_map, new_forms = {}, 0
    existing = {f.title: f.id for f in (await session.execute(select(Form).where(Form.bot_id == bot.id))).scalars().all()}
    for form in data.get("forms", []):
        title = str(form["title"])[:255]
        if title in existing:
            form_map[form["id"]] = existing[title]
            continue
        row = Form(bot_id=bot.id, title=title, intro_text=form.get("intro_text"), final_message=form.get("final_message"), notify_admins=bool(form.get("notify_admins", True)))
        session.add(row)
        await session.flush()
        for position, f in enumerate(form.get("fields", [])):
            session.add(FormField(form_id=row.id, position=f.get("position", position), label=str(f.get("label") or "Savol")[:100], prompt=str(f.get("prompt") or f.get("label") or "Savol"),
                                  type=f.get("type") or "text", required=bool(f.get("required", True)), options=f.get("options")))
        form_map[form["id"]] = row.id
        existing[title] = row.id
        new_forms += 1

    await wipe(session, bot.id, start)
    menu_map = {start_data["id"]: start.id}
    for position, m in enumerate(data["menus"]):
        if m is start_data:
            row = start
        else:
            row = Menu(bot_id=bot.id, title=str(m.get("title") or "Menyu")[:255], is_start=False, position=m.get("position", position))
            session.add(row)
            await session.flush()
            menu_map[m["id"]] = row.id
        row.title = str(m.get("title") or "Menyu")[:255] if row is not start else "Bosh menyu"
        row.message_text = (m.get("message_text") or None) and str(m["message_text"])[:4096]
        row.keyboard_mode = m.get("keyboard_mode") if m.get("keyboard_mode") in ("inline", "reply") else "inline"
        row.columns = 2 if m.get("columns") == 2 else 1
        row.media_type, row.media_file_id = (m.get("media_type"), m.get("media_file_id")) if same else (None, None)

    buttons = dropped = 0
    for m in data["menus"]:
        menu_id = menu_map[m["id"]]
        for position, b in enumerate(m.get("buttons", [])):
            action = b.get("action")
            value = None if action is None else action.get("value")
            if action is not None:
                kind = action["type"]
                if kind in BOT_SPECIFIC and not same:
                    dropped += 1
                    continue
                if kind == ActionType.menu.value:
                    value = str(menu_map.get(int(value))) if str(value).lstrip("-").isdigit() and int(value) in menu_map else None
                elif kind == ActionType.form.value:
                    value = str(form_map.get(int(value))) if str(value).lstrip("-").isdigit() and int(value) in form_map else None
                if value is None and kind in (ActionType.menu.value, ActionType.form.value):
                    dropped += 1
                    continue
            row = Button(menu_id=menu_id, text=str(b["text"])[:255], position=b.get("position", position), kind=b.get("kind") if b.get("kind") in ("normal", "contact", "location") else "normal")
            session.add(row)
            await session.flush()
            if action is not None:
                session.add(ButtonAction(button_id=row.id, action_type=ActionType(action["type"]), value=value))
            buttons += 1
    await session.commit()
    return {"menus": len(data["menus"]), "buttons": buttons, "forms_new": new_forms, "dropped": dropped}

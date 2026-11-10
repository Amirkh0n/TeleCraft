"""REST API behind the Mini App visual editor. Every route is scoped to the signed-in user's
own bots: ids from the URL are never trusted on their own."""
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, File, Form as FormParam, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.error import Forbidden, TelegramError

from constructor.flows.forms import build_csv
from constructor.flows.screens import reupload
from core.logger import get_logger
from engine import audience as audience_engine
from engine.render import MEDIA_TYPES, parse_media_value
from engine.telegram_client import get_client
from models.admin_links import AdminLink
from models.bots import Bot
from models.button_actions import ActionType, ButtonAction
from models.buttons import Button
from models.forms import FIELD_CHOICE, FIELD_TYPES, Form, FormField, FormSubmission
from models.menus import Menu
from models.user_sessions import UserSession
from models.users import User
from webapp.auth import current_user, get_session
from webapp.telegram_html import check_html

logger = get_logger("webapp")
router = APIRouter(prefix="/api/v1", tags=["miniapp"])

MAX_MENUS = 50
MAX_BUTTONS = 30
MAX_FORMS = 20
MAX_FIELDS = 20
MAX_TEXT = 4000
PHOTO_LIMIT = 10 * 1024 * 1024
FILE_LIMIT = 20 * 1024 * 1024

ACTION_TYPES = ("text", "link", "menu", "media", "form", "admin")


# ---------------------------------------------------------------- schemas

class ActionIn(BaseModel):
    type: Literal["text", "link", "menu", "form", "admin"]
    value: str = Field(min_length=1, max_length=MAX_TEXT)


class MenuCreate(BaseModel):
    title: str = Field(min_length=1, max_length=60)


class MenuPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=60)
    message_text: str | None = Field(default=None, max_length=MAX_TEXT)
    keyboard_mode: Literal["inline", "reply"] | None = None
    columns: int | None = Field(default=None, ge=1, le=2)
    remove_media: bool = False


class ButtonCreate(BaseModel):
    text: str = Field(min_length=1, max_length=64)
    kind: Literal["normal", "contact", "location"] = "normal"


class ButtonPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=64)
    action: ActionIn | None = None  # use "clear_action" to remove
    clear_action: bool = False


class OrderIn(BaseModel):
    ids: list[int]


class FieldIn(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=500)
    type: str
    required: bool = True
    options: list[str] | None = None


class FormIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    intro_text: str | None = Field(default=None, max_length=1000)
    final_message: str | None = Field(default=None, max_length=1000)
    notify_admins: bool = True
    fields: list[FieldIn] = Field(default_factory=list, max_length=MAX_FIELDS)


class FormCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)


# ---------------------------------------------------------------- access helpers

def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} topilmadi.")


async def owned_bot(session: AsyncSession, user: User, bot_id: int) -> Bot:
    bot = (await session.execute(select(Bot).where(Bot.id == bot_id, Bot.owner_id == user.id))).scalar_one_or_none()
    if bot is None:
        raise not_found("Bot")
    return bot


async def owned_menu(session: AsyncSession, user: User, menu_id: int):
    row = (await session.execute(
        select(Menu, Bot).join(Bot, Bot.id == Menu.bot_id).where(Menu.id == menu_id, Bot.owner_id == user.id)
    )).first()
    if row is None:
        raise not_found("Ekran")
    return row[0], row[1]


async def owned_button(session: AsyncSession, user: User, button_id: int):
    row = (await session.execute(
        select(Button, Menu, Bot).join(Menu, Menu.id == Button.menu_id).join(Bot, Bot.id == Menu.bot_id)
        .where(Button.id == button_id, Bot.owner_id == user.id)
    )).first()
    if row is None:
        raise not_found("Tugma")
    return row[0], row[1], row[2]


async def owned_form(session: AsyncSession, user: User, form_id: int):
    row = (await session.execute(
        select(Form, Bot).join(Bot, Bot.id == Form.bot_id).where(Form.id == form_id, Bot.owner_id == user.id)
    )).first()
    if row is None:
        raise not_found("Forma")
    return row[0], row[1]


# ---------------------------------------------------------------- serializers

def bot_out(bot: Bot) -> dict:
    return {
        "id": bot.id, "name": bot.name, "username": bot.username,
        "link": f"https://t.me/{bot.username}" if bot.username else None,
        "connected": bool(bot.webhook_set), "active": bool(bot.is_active),
    }


def _action_out(action: ButtonAction | None) -> dict | None:
    if action is None:
        return None
    value = action.value
    out = {"type": action.action_type.value, "value": value}
    if action.action_type == ActionType.media:
        media = parse_media_value(value) or {}
        out = {"type": "media", "value": None, "media": {"type": media.get("type"), "caption": media.get("caption", "")}}
    return out


async def load_menus(session: AsyncSession, bot_id: int) -> list[dict]:
    menus = (await session.execute(
        select(Menu).where(Menu.bot_id == bot_id).order_by(Menu.is_start.desc(), Menu.position, Menu.id)
    )).scalars().all()
    buttons = (await session.execute(
        select(Button).where(Button.menu_id.in_([m.id for m in menus])).order_by(Button.position, Button.id)
    )).scalars().all() if menus else []
    actions = {a.button_id: a for a in (await session.execute(
        select(ButtonAction).where(ButtonAction.button_id.in_([b.id for b in buttons]))
    )).scalars().all()} if buttons else {}
    by_menu: dict[int, list] = {}
    for button in buttons:
        by_menu.setdefault(button.menu_id, []).append({
            "id": button.id, "text": button.text, "kind": button.kind, "position": button.position,
            "action": _action_out(actions.get(button.id)),
        })
    return [{
        "id": m.id, "title": m.title, "message_text": m.message_text, "is_start": bool(m.is_start),
        "keyboard_mode": m.keyboard_mode, "columns": m.columns,
        "media_type": m.media_type if m.media_file_id else None,
        "buttons": by_menu.get(m.id, []),
    } for m in menus]


def _form_out(form: Form, fields: list[FormField], submissions: int = 0) -> dict:
    return {
        "id": form.id, "title": form.title, "intro_text": form.intro_text, "final_message": form.final_message,
        "notify_admins": bool(form.notify_admins), "submissions": submissions,
        "fields": [{"label": f.label, "prompt": f.prompt, "type": f.type, "required": bool(f.required),
                    "options": f.options} for f in fields],
    }


async def load_forms(session: AsyncSession, bot_id: int) -> list[dict]:
    forms = (await session.execute(select(Form).where(Form.bot_id == bot_id).order_by(Form.id))).scalars().all()
    out = []
    for form in forms:
        fields = (await session.execute(
            select(FormField).where(FormField.form_id == form.id).order_by(FormField.position, FormField.id)
        )).scalars().all()
        count = (await session.execute(
            select(func.count(FormSubmission.id)).where(FormSubmission.form_id == form.id)
        )).scalar_one()
        out.append(_form_out(form, list(fields), count))
    return out


def _check_text(text: str | None, what: str = "Matn") -> str | None:
    if text is None or not text.strip():
        return None
    problem = check_html(text)
    if problem:
        raise HTTPException(status_code=422, detail=f"{what}da xato: {problem}.")
    return text


# ---------------------------------------------------------------- bots

@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {"id": user.tg_id, "name": user.full_name}


@router.get("/bots")
async def list_bots(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    bots = (await session.execute(select(Bot).where(Bot.owner_id == user.id).order_by(Bot.id.desc()))).scalars().all()
    return [bot_out(b) for b in bots]


@router.get("/bots/{bot_id}")
async def get_bot(bot_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    return {"bot": bot_out(bot), "menus": await load_menus(session, bot.id), "forms": await load_forms(session, bot.id)}


@router.get("/bots/{bot_id}/stats")
async def bot_stats(bot_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    return await audience_engine.stats(session, bot.id)


# ---------------------------------------------------------------- menus (screens)

@router.post("/bots/{bot_id}/menus", status_code=201)
async def create_menu(bot_id: int, body: MenuCreate, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    existing = (await session.execute(select(func.count(Menu.id)).where(Menu.bot_id == bot.id))).scalar_one()
    if existing >= MAX_MENUS:
        raise HTTPException(status_code=409, detail=f"Botda {MAX_MENUS} tadan ko‘p ekran bo‘lmasin.")
    position = (await session.execute(
        select(func.coalesce(func.max(Menu.position), -1)).where(Menu.bot_id == bot.id)
    )).scalar_one() + 1
    menu = Menu(bot_id=bot.id, title=body.title.strip(), message_text=None, is_start=existing == 0, position=position)
    session.add(menu)
    await session.commit()
    return next(m for m in await load_menus(session, bot.id) if m["id"] == menu.id)


@router.patch("/menus/{menu_id}")
async def patch_menu(menu_id: int, body: MenuPatch, user: User = Depends(current_user),
                     session: AsyncSession = Depends(get_session)):
    menu, bot = await owned_menu(session, user, menu_id)
    fields = body.model_fields_set
    if "title" in fields and body.title is not None:
        menu.title = body.title.strip()
    if "message_text" in fields:
        menu.message_text = _check_text(body.message_text, "Xabar matni")
    if body.keyboard_mode is not None:
        menu.keyboard_mode = body.keyboard_mode
        if body.keyboard_mode == "inline":  # share-contact/location buttons exist on reply keyboards only
            for button in (await session.execute(
                select(Button).where(Button.menu_id == menu.id, Button.kind != "normal")
            )).scalars().all():
                await session.delete(button)
    if body.columns is not None:
        menu.columns = body.columns
    if body.remove_media:
        menu.media_type = None
        menu.media_file_id = None
    await session.commit()
    return next(m for m in await load_menus(session, bot.id) if m["id"] == menu.id)


@router.delete("/menus/{menu_id}", status_code=204)
async def delete_menu(menu_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    menu, bot = await owned_menu(session, user, menu_id)
    if menu.is_start:
        raise HTTPException(status_code=409, detail="Bosh ekranni o‘chirib bo‘lmaydi.")
    start = (await session.execute(select(Menu).where(Menu.bot_id == bot.id, Menu.is_start.is_(True)))).scalar_one()
    # Users currently on this screen move to the start screen (user_sessions.current_menu_id is required).
    for state in (await session.execute(select(UserSession).where(UserSession.current_menu_id == menu.id))).scalars().all():
        state.current_menu_id = start.id
    # Buttons elsewhere that opened this screen keep existing, without an action.
    for action in (await session.execute(
        select(ButtonAction).where(ButtonAction.action_type == ActionType.menu, ButtonAction.value == str(menu.id))
    )).scalars().all():
        await session.delete(action)
    for button in (await session.execute(select(Button).where(Button.menu_id == menu.id))).scalars().all():
        for action in (await session.execute(select(ButtonAction).where(ButtonAction.button_id == button.id))).scalars().all():
            await session.delete(action)
        await session.delete(button)
    await session.delete(menu)
    await session.commit()
    return Response(status_code=204)


def _media_kind(content_type: str | None, filename: str | None) -> str:
    content_type = (content_type or "").lower()
    if content_type == "image/gif" or (filename or "").lower().endswith(".gif"):
        return "animation"
    if content_type.startswith("image/") and content_type in ("image/jpeg", "image/png", "image/webp"):
        return "photo"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    return "document"


async def _upload_to_child(bot: Bot, user: User, file: UploadFile) -> tuple[str, str]:
    data = await file.read(FILE_LIMIT + 1)
    if not data:
        raise HTTPException(status_code=422, detail="Fayl bo‘sh.")
    kind = _media_kind(file.content_type, file.filename)
    limit = PHOTO_LIMIT if kind == "photo" else FILE_LIMIT
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"Fayl {limit // (1024 * 1024)} MB dan katta.")
    try:
        file_id = await reupload(await get_client(bot.plain_token), user.tg_id, kind, data, file.filename)
    except Forbidden:
        raise HTTPException(status_code=409, detail="Avval child botni oching va /start yuboring, keyin qayta urining.") from None
    except TelegramError as exc:
        text = str(exc).lower()
        if "chat not found" in text or "blocked" in text:
            raise HTTPException(status_code=409, detail="Avval child botni oching va /start yuboring, keyin qayta urining.") from None
        logger.warning("miniapp media upload failed: %s", exc)
        raise HTTPException(status_code=502, detail="Telegram faylni qabul qilmadi. Boshqa fayl bilan urinib ko‘ring.") from None
    return kind, file_id


@router.post("/menus/{menu_id}/media")
async def upload_menu_media(menu_id: int, file: UploadFile = File(...), user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    menu, bot = await owned_menu(session, user, menu_id)
    kind, file_id = await _upload_to_child(bot, user, file)
    menu.media_type, menu.media_file_id = kind, file_id
    await session.commit()
    return next(m for m in await load_menus(session, bot.id) if m["id"] == menu.id)


# ---------------------------------------------------------------- buttons

async def _button_out(session: AsyncSession, bot_id: int, menu_id: int, button_id: int) -> dict:
    menu = next(m for m in await load_menus(session, bot_id) if m["id"] == menu_id)
    return next(b for b in menu["buttons"] if b["id"] == button_id)


@router.post("/menus/{menu_id}/buttons", status_code=201)
async def create_button(menu_id: int, body: ButtonCreate, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    menu, bot = await owned_menu(session, user, menu_id)
    if body.kind != "normal" and menu.keyboard_mode != "reply":
        raise HTTPException(status_code=422, detail="Kontakt va lokatsiya tugmalari faqat pastki klaviaturada ishlaydi.")
    if body.kind != "normal" and (await session.execute(
        select(Button.id).where(Button.menu_id == menu.id, Button.kind == body.kind)
    )).first():
        raise HTTPException(status_code=409, detail="Bu tugma allaqachon bor.")
    count = (await session.execute(select(func.count(Button.id)).where(Button.menu_id == menu.id))).scalar_one()
    if count >= MAX_BUTTONS:
        raise HTTPException(status_code=409, detail=f"Bitta ekranda {MAX_BUTTONS} tadan ko‘p tugma bo‘lmasin.")
    position = (await session.execute(
        select(func.coalesce(func.max(Button.position), -1)).where(Button.menu_id == menu.id)
    )).scalar_one() + 1
    button = Button(menu_id=menu.id, text=body.text.strip(), kind=body.kind, position=position)
    session.add(button)
    await session.commit()
    return await _button_out(session, bot.id, menu.id, button.id)


async def _apply_action(session: AsyncSession, bot: Bot, button: Button, action: ActionIn) -> None:
    value = action.value.strip()
    if action.type == "text":
        value = _check_text(value, "Javob matni") or ""
        if not value:
            raise HTTPException(status_code=422, detail="Javob matni bo‘sh bo‘lmasin.")
    elif action.type == "link":
        if not re.fullmatch(r"https?://[^\s/$.?#][^\s]{0,500}", value):
            raise HTTPException(status_code=422, detail="Havola https:// bilan boshlanishi kerak.")
    elif action.type == "menu":
        owner_ok = value.isdigit() and (await session.execute(
            select(Menu.id).where(Menu.id == int(value), Menu.bot_id == bot.id)
        )).first()
        if not owner_ok:
            raise HTTPException(status_code=422, detail="Ekran topilmadi.")
    elif action.type == "form":
        owner_ok = value.isdigit() and (await session.execute(
            select(Form.id).where(Form.id == int(value), Form.bot_id == bot.id)
        )).first()
        if not owner_ok:
            raise HTTPException(status_code=422, detail="Forma topilmadi.")
    elif action.type == "admin":
        if not re.fullmatch(r"\d{3,15}", value):
            raise HTTPException(status_code=422, detail="Telegram ID raqam bo‘lishi kerak.")
        if (await session.execute(
            select(AdminLink.id).where(AdminLink.bot_id == bot.id, AdminLink.admin_tg_id == int(value))
        )).first() is None:
            session.add(AdminLink(bot_id=bot.id, admin_tg_id=int(value)))
    await _save_action(session, button.id, ActionType(action.type), value)


async def _save_action(session: AsyncSession, button_id: int, action_type: ActionType, value: str) -> None:
    existing = (await session.execute(select(ButtonAction).where(ButtonAction.button_id == button_id))).scalar_one_or_none()
    if existing:
        existing.action_type, existing.value = action_type, value
    else:
        session.add(ButtonAction(button_id=button_id, action_type=action_type, value=value))


@router.patch("/buttons/{button_id}")
async def patch_button(button_id: int, body: ButtonPatch, user: User = Depends(current_user),
                       session: AsyncSession = Depends(get_session)):
    button, menu, bot = await owned_button(session, user, button_id)
    if body.text is not None:
        button.text = body.text.strip()
    if body.clear_action:
        for action in (await session.execute(select(ButtonAction).where(ButtonAction.button_id == button.id))).scalars().all():
            await session.delete(action)
    elif body.action is not None:
        await _apply_action(session, bot, button, body.action)
    await session.commit()
    return await _button_out(session, bot.id, menu.id, button.id)


@router.delete("/buttons/{button_id}", status_code=204)
async def delete_button(button_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    button, _menu, _bot = await owned_button(session, user, button_id)
    for action in (await session.execute(select(ButtonAction).where(ButtonAction.button_id == button.id))).scalars().all():
        await session.delete(action)
    await session.delete(button)
    await session.commit()
    return Response(status_code=204)


@router.put("/menus/{menu_id}/buttons/order")
async def order_buttons(menu_id: int, body: OrderIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    menu, bot = await owned_menu(session, user, menu_id)
    buttons = {b.id: b for b in (await session.execute(select(Button).where(Button.menu_id == menu.id))).scalars().all()}
    if sorted(body.ids) != sorted(buttons):
        raise HTTPException(status_code=422, detail="Tugmalar ro‘yxati mos kelmadi. Sahifani yangilang.")
    for position, button_id in enumerate(body.ids):
        buttons[button_id].position = position
    await session.commit()
    return next(m for m in await load_menus(session, bot.id) if m["id"] == menu.id)


@router.post("/buttons/{button_id}/media")
async def upload_button_media(button_id: int, file: UploadFile = File(...), caption: str = FormParam(default=""),
                              user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    button, menu, bot = await owned_button(session, user, button_id)
    caption = _check_text(caption[:1024], "Izoh") or ""
    kind, file_id = await _upload_to_child(bot, user, file)
    if kind not in MEDIA_TYPES:
        raise HTTPException(status_code=422, detail="Bu fayl turi qo‘llab-quvvatlanmaydi.")
    await _save_action(session, button.id, ActionType.media, json.dumps({"type": kind, "file_id": file_id, "caption": caption}))
    await session.commit()
    return await _button_out(session, bot.id, menu.id, button.id)


# ---------------------------------------------------------------- forms

def _clean_fields(fields: list[FieldIn]) -> list[FieldIn]:
    for field in fields:
        if field.type not in FIELD_TYPES:
            raise HTTPException(status_code=422, detail="Savol turi noto‘g‘ri.")
        _check_text(field.prompt, "Savol")
        if field.type == FIELD_CHOICE:
            options = list(dict.fromkeys(o.strip() for o in (field.options or []) if o.strip()))
            if not 2 <= len(options) <= 12 or any(len(o) > 60 for o in options):
                raise HTTPException(status_code=422, detail="Tanlov savoliga 2–12 ta variant kerak (har biri 60 belgigacha).")
            field.options = options
        else:
            field.options = None
    return fields


@router.post("/bots/{bot_id}/forms", status_code=201)
async def create_form(bot_id: int, body: FormCreate, user: User = Depends(current_user),
                      session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    count = (await session.execute(select(func.count(Form.id)).where(Form.bot_id == bot.id))).scalar_one()
    if count >= MAX_FORMS:
        raise HTTPException(status_code=409, detail=f"Botda {MAX_FORMS} tadan ko‘p forma bo‘lmasin.")
    form = Form(bot_id=bot.id, title=body.title.strip())
    session.add(form)
    await session.commit()
    return next(f for f in await load_forms(session, bot.id) if f["id"] == form.id)


@router.put("/forms/{form_id}")
async def save_form(form_id: int, body: FormIn, user: User = Depends(current_user),
                    session: AsyncSession = Depends(get_session)):
    form, bot = await owned_form(session, user, form_id)
    fields = _clean_fields(list(body.fields))
    form.title = body.title.strip()
    form.intro_text = _check_text(body.intro_text, "Kirish matni")
    form.final_message = _check_text(body.final_message, "Yakuniy xabar")
    form.notify_admins = body.notify_admins
    for old in (await session.execute(select(FormField).where(FormField.form_id == form.id))).scalars().all():
        await session.delete(old)  # answers keep their own snapshot of labels, so replacing is safe
    await session.flush()
    for position, field in enumerate(fields):
        session.add(FormField(form_id=form.id, position=position, label=field.label.strip(), prompt=field.prompt,
                              type=field.type, required=field.required, options=field.options))
    await session.commit()
    return next(f for f in await load_forms(session, bot.id) if f["id"] == form.id)


@router.delete("/forms/{form_id}", status_code=204)
async def delete_form(form_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    form, _bot = await owned_form(session, user, form_id)
    for action in (await session.execute(
        select(ButtonAction).where(ButtonAction.action_type == ActionType.form, ButtonAction.value == str(form.id))
    )).scalars().all():
        await session.delete(action)
    for state in (await session.execute(select(UserSession).where(UserSession.form_id == form.id))).scalars().all():
        state.form_id = state.form_step = state.form_data = None
    for model in (FormSubmission, FormField):
        for row in (await session.execute(select(model).where(model.form_id == form.id))).scalars().all():
            await session.delete(row)
    await session.delete(form)
    await session.commit()
    return Response(status_code=204)


@router.get("/forms/{form_id}/submissions")
async def form_submissions(form_id: int, limit: int = 20, user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)):
    form, _bot = await owned_form(session, user, form_id)
    rows = (await session.execute(
        select(FormSubmission).where(FormSubmission.form_id == form.id)
        .order_by(FormSubmission.id.desc()).limit(max(1, min(limit, 100)))
    )).scalars().all()
    return [{
        "id": r.id, "tg_user_id": r.tg_user_id, "username": r.username, "full_name": r.full_name,
        "created_at": r.created_at.isoformat() if r.created_at else None, "answers": r.answers,
    } for r in rows]


@router.get("/forms/{form_id}/export.csv")
async def export_form(form_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    form, _bot = await owned_form(session, user, form_id)
    fields = (await session.execute(
        select(FormField).where(FormField.form_id == form.id).order_by(FormField.position, FormField.id)
    )).scalars().all()
    rows = (await session.execute(
        select(FormSubmission).where(FormSubmission.form_id == form.id).order_by(FormSubmission.id).limit(5000)
    )).scalars().all()
    return Response(content=build_csv(list(fields), list(rows)), media_type="text/csv; charset=utf-8")

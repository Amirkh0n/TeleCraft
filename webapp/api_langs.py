"""Mini App API: languages of a child bot and the owner's translations of its texts."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine import i18n
from models.button_actions import ActionType, ButtonAction
from models.buttons import Button
from models.menus import Menu
from models.translations import ContentTranslation
from models.users import User
from webapp.api import MAX_TEXT, _check_text, owned_bot
from webapp.auth import current_user, get_session

router = APIRouter(prefix="/api/v1", tags=["bot-languages"])


class LanguagesIn(BaseModel):
    languages: list[Literal["ru", "en"]] = Field(default_factory=list, max_length=2)


class TranslationIn(BaseModel):
    entity: Literal["menu_text", "button_text", "action_text"]
    entity_id: int
    lang: Literal["ru", "en"]
    text: str = Field(default="", max_length=MAX_TEXT)


class TranslationsIn(BaseModel):
    items: list[TranslationIn] = Field(max_length=200)


async def _overview(session: AsyncSession, bot) -> dict:
    menus = list((await session.execute(select(Menu).where(Menu.bot_id == bot.id).order_by(Menu.id))).scalars())
    rows = (await session.execute(
        select(Button, ButtonAction).outerjoin(ButtonAction, ButtonAction.button_id == Button.id)
        .join(Menu, Menu.id == Button.menu_id).where(Menu.bot_id == bot.id).order_by(Button.position, Button.id)
    )).all()
    tr: dict[tuple, str] = {}
    for row in (await session.execute(select(ContentTranslation).where(ContentTranslation.bot_id == bot.id))).scalars():
        tr[(row.entity, row.entity_id, row.lang)] = row.text
    langs = i18n.parse_langs(bot.languages)

    def mapped(entity, entity_id):
        return {lang: tr[(entity, entity_id, lang)] for lang in langs if (entity, entity_id, lang) in tr}

    by_menu: dict[int, list] = {}
    for button, action in rows:
        if button.kind != "normal":
            continue
        by_menu.setdefault(button.menu_id, []).append({
            "id": button.id, "text": button.text, "tr": mapped("button_text", button.id),
            "action_text": action.value if action and action.action_type == ActionType.text else None,
            "action_tr": mapped("action_text", button.id),
        })
    return {
        "languages": langs, "available": list(i18n.EXTRA), "labels": i18n.LANGS,
        "menus": [
            {"id": m.id, "title": m.title, "message_text": m.message_text, "tr": mapped("menu_text", m.id),
             "buttons": by_menu.get(m.id, [])}
            for m in menus
        ],
    }


@router.get("/bots/{bot_id}/translations")
async def get_translations(bot_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    return await _overview(session, bot)


@router.put("/bots/{bot_id}/languages")
async def set_languages(bot_id: int, body: LanguagesIn, user: User = Depends(current_user),
                        session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    bot.languages = i18n.join_langs(body.languages)
    await session.commit()
    return await _overview(session, bot)


@router.put("/bots/{bot_id}/translations")
async def save_translations(bot_id: int, body: TranslationsIn, user: User = Depends(current_user),
                            session: AsyncSession = Depends(get_session)):
    bot = await owned_bot(session, user, bot_id)
    bot_id = bot.id
    langs = i18n.parse_langs(bot.languages)
    menu_ids = set((await session.execute(select(Menu.id).where(Menu.bot_id == bot_id))).scalars())
    button_ids = set((await session.execute(
        select(Button.id).join(Menu, Menu.id == Button.menu_id).where(Menu.bot_id == bot_id))).scalars())
    for item in body.items:
        if item.lang not in langs:
            raise HTTPException(status_code=422, detail="Bu til botda yoqilmagan.")
        valid = menu_ids if item.entity == "menu_text" else button_ids
        if item.entity_id not in valid:
            raise HTTPException(status_code=404, detail="Matn topilmadi.")
        text = item.text.strip()
        if item.entity != "button_text":
            text = _check_text(text, "Tarjima") or ""
        key = and_(ContentTranslation.entity == item.entity, ContentTranslation.entity_id == item.entity_id,
                   ContentTranslation.lang == item.lang)
        existing = (await session.execute(select(ContentTranslation).where(key))).scalar_one_or_none()
        if not text:
            if existing:
                await session.execute(delete(ContentTranslation).where(key).execution_options(synchronize_session=False))
        elif existing:
            existing.text = text[:64] if item.entity == "button_text" else text
        else:
            session.add(ContentTranslation(bot_id=bot_id, entity=item.entity, entity_id=item.entity_id, lang=item.lang,
                                           text=text[:64] if item.entity == "button_text" else text))
    await session.commit()
    return await _overview(session, bot)

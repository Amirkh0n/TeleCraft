"""Languages of a child bot: the owner writes extra texts, the customer picks a language."""
from sqlalchemy import select, update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from models.audience import BotUser
from models.translations import ContentTranslation

BASE = "uz"
LANGS = {"uz": "🇺🇿 O‘zbekcha", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}
EXTRA = ("ru", "en")
LANG_CALLBACK = "lang:"
PICK = LANG_CALLBACK + "pick"

STRINGS = {
    "ru": {
        "choose": "🌐 Выберите язык",
        "open_hint": "Нажмите кнопку, чтобы открыть ссылку.",
        "open_link": "🔗 Открыть ссылку",
        "no_menu": "Этот раздел сейчас недоступен.",
        "no_file": "Этот файл сейчас недоступен.",
        "file_fail": "Не удалось отправить файл. Попробуйте позже.",
        "hint": "Выберите нужный раздел кнопками меню.",
    },
    "en": {
        "choose": "🌐 Choose a language",
        "open_hint": "Tap the button to open the link.",
        "open_link": "🔗 Open link",
        "no_menu": "This section is not available right now.",
        "no_file": "This file is not available right now.",
        "file_fail": "Could not send the file. Please try later.",
        "hint": "Choose a section using the menu buttons.",
    },
    "uz": {
        "choose": "🌐 Tilni tanlang",
        "open_hint": "Havolani ochish uchun tugmani bosing.",
        "open_link": "🔗 Havolani ochish",
        "no_menu": "Bu bo‘lim hozir mavjud emas.",
        "no_file": "Bu fayl hozir mavjud emas.",
        "file_fail": "Faylni yuborib bo‘lmadi. Keyinroq urinib ko‘ring.",
        "hint": "Kerakli bo‘limni menyudagi tugmalardan tanlang.",
    },
}


def parse_langs(value: str | None) -> list[str]:
    return [code for code in (value or "").split(",") if code in EXTRA]


def join_langs(codes) -> str:
    return ",".join(code for code in EXTRA if code in set(codes))


def available(bot) -> list[str]:
    """All languages of the bot, base first (just ``["uz"]`` when it is single-language)."""
    return [BASE, *parse_langs(getattr(bot, "languages", ""))]


def multilingual(bot) -> bool:
    return bool(parse_langs(getattr(bot, "languages", "")))


def s(lang: str | None, key: str) -> str:
    return STRINGS.get(lang or BASE, STRINGS[BASE]).get(key) or STRINGS[BASE][key]


async def user_lang(session, bot, user_id) -> str | None:
    """The user's chosen language, or None (not chosen / base language / bot not multilingual)."""
    if not multilingual(bot) or user_id is None:
        return None
    lang = (await session.execute(
        select(BotUser.lang).where(BotUser.bot_id == bot.id, BotUser.tg_user_id == user_id)
    )).scalar_one_or_none()
    return lang if lang in parse_langs(bot.languages) else None


async def has_chosen(session, bot, user_id) -> bool:
    raw = (await session.execute(
        select(BotUser.lang).where(BotUser.bot_id == bot.id, BotUser.tg_user_id == user_id)
    )).scalar_one_or_none()
    return raw in available(bot)


async def set_lang(session, bot, user_id, lang) -> bool:
    if lang not in available(bot):
        return False
    await session.execute(
        update(BotUser).where(BotUser.bot_id == bot.id, BotUser.tg_user_id == user_id)
        .values(lang=lang).execution_options(synchronize_session=False)
    )
    await session.commit()
    return True


def picker_markup(bot) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(LANGS[c], callback_data=LANG_CALLBACK + c)] for c in available(bot)])


async def send_picker(tg, bot, chat_id, lang=None):
    await tg.send_message(chat_id=chat_id, text="🌐 Tilni tanlang / Выберите язык / Choose a language",
                          reply_markup=picker_markup(bot))


async def load(session, bot_id, lang, entity, ids) -> dict[int, str]:
    if not lang or not ids:
        return {}
    rows = await session.execute(
        select(ContentTranslation.entity_id, ContentTranslation.text).where(
            ContentTranslation.bot_id == bot_id, ContentTranslation.lang == lang,
            ContentTranslation.entity == entity, ContentTranslation.entity_id.in_(list(ids)),
        )
    )
    return {entity_id: text for entity_id, text in rows.all()}


async def screen_texts(session, bot_id, lang, menu_id, button_ids) -> dict:
    """Translations for one screen: ``{"menu": text|None, "buttons": {id: text}}``."""
    menu = await load(session, bot_id, lang, "menu_text", [menu_id])
    return {"menu": menu.get(menu_id), "buttons": await load(session, bot_id, lang, "button_text", button_ids)}


async def translated_button_id(session, bot_id, lang, menu_id, text, button_ids_query):
    """Id of the button of ``menu`` whose translated label is ``text`` (reply keyboards)."""
    if not lang:
        return None
    return (await session.execute(
        select(ContentTranslation.entity_id).where(
            ContentTranslation.bot_id == bot_id, ContentTranslation.lang == lang,
            ContentTranslation.entity == "button_text", ContentTranslation.text == text,
            ContentTranslation.entity_id.in_(button_ids_query),
        ).limit(1)
    )).scalar_one_or_none()

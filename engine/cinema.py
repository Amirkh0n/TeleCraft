"""Cinema bots: viewers find a movie by its code or title; admins manage the catalogue from
inside the child bot itself (``/admin``).

A movie is stored as the Telegram ``file_id`` of a video the admin sent to the child bot, and
is delivered by that same ``file_id`` (file ids are bot-specific, hence the admin must upload
through the child bot, not the constructor). Never raises for normal user input.
"""
import html
import re

from sqlalchemy import delete, func, select
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from telegram.error import BadRequest, TelegramError

from core.logger import get_logger
from engine import subscription
from engine.actions import get_user_session
from engine.audience import touch_user
from models.admin_links import AdminLink
from models.audience import BotUser
from models.menus import Menu
from models.movies import Movie
from models.user_sessions import UserSession
from models.users import User

logger = get_logger("cinema")

PAGE_SIZE = 8
SEARCH_LIMIT = 10
CODE_RE = re.compile(r"^[\w-]{1,32}$", re.UNICODE)
WELCOME = "🎬 Kino botga xush kelibsiz!\n\nKino <b>kodini</b> yuboring yoki <b>nomini</b> yozib qidiring."

# admin states
ADD_VIDEO, ADD_POSTER, ADD_CODE, ADD_TITLE, ADD_DESC = "add_video", "add_poster", "add_code", "add_title", "add_desc"
EDIT_PREFIX = "edit_"  # edit_title / edit_code / edit_desc / edit_file


def esc(value) -> str:
    return html.escape(str(value or ""))


def norm_code(raw: str) -> str:
    return raw.strip().lower()


# ------------------------------------------------------------------ admins & sessions

async def admin_ids(session, bot) -> set[int]:
    ids = set((await session.execute(
        select(AdminLink.admin_tg_id).where(AdminLink.bot_id == bot.id)
    )).scalars().all())
    owner = (await session.execute(select(User.tg_id).where(User.id == bot.owner_id))).scalar_one_or_none()
    if owner is not None:
        ids.add(owner)
    return ids


async def is_admin(session, bot, user_id: int) -> bool:
    return user_id in await admin_ids(session, bot)


async def ensure_start_menu(session, bot) -> Menu:
    """Sessions need a menu (NOT NULL FK), so a cinema bot always owns a start menu."""
    menu = (await session.execute(
        select(Menu).where(Menu.bot_id == bot.id).order_by(Menu.is_start.desc(), Menu.id)
    )).scalars().first()
    if menu is None:
        menu = Menu(bot_id=bot.id, title="Bosh menyu", message_text=WELCOME, is_start=True)
        session.add(menu)
        await session.commit()
    return menu


async def _session_of(session, bot, user_id: int) -> UserSession:
    us = await get_user_session(session, bot.id, user_id)
    if us is None:
        menu = await ensure_start_menu(session, bot)
        us = UserSession(bot_id=bot.id, tg_user_id=user_id, current_menu_id=menu.id)
        session.add(us)
        await session.commit()
    return us


async def _set_state(session, us, state=None, data=None):
    us.state = state
    us.state_data = data
    await session.commit()


# ------------------------------------------------------------------ viewer side

def caption_of(movie) -> str:
    parts = [f"🎬 <b>{esc(movie.title)}</b>"]
    if movie.description:
        parts.append(esc(movie.description))
    parts.append(f"🔑 Kod: <code>{esc(movie.code)}</code>")
    text = "\n\n".join(parts)
    if len(text) > 1000:  # Telegram caps captions at 1024 characters
        text = f"🎬 <b>{esc(movie.title)}</b>\n\n🔑 Kod: <code>{esc(movie.code)}</code>"
    return text[:1000]


async def send_movie(tg, session, movie, chat_id: int, *, protect: bool = False):
    caption = caption_of(movie)
    try:
        if movie.file_type == "document":
            await tg.send_document(chat_id=chat_id, document=movie.file_id, caption=caption, parse_mode="HTML",
                                   protect_content=True)
        else:
            await tg.send_video(chat_id=chat_id, video=movie.file_id, caption=caption, parse_mode="HTML",
                                protect_content=True)
    except BadRequest as exc:
        logger.warning("movie %s: file_id rejected (%s)", movie.id, exc)
        await tg.send_message(chat_id=chat_id, text="⚠️ Bu kinoni yuborib bo‘lmadi. Keyinroq urinib ko‘ring.")
        return False
    await session.execute(Movie.__table__.update().where(Movie.id == movie.id).values(views=Movie.views + 1))
    await session.commit()
    return True


async def post_to_channel(tg, bot, movie) -> str | None:
    """Announce a movie in the bot's channel (poster + text + a «watch» deep-link button; never the
    video itself). Returns a user-facing problem, or ``None`` on success."""
    if not bot.movie_channel_id:
        return "Kino kanal ulanmagan."
    try:
        username = bot.username or (await tg.get_me()).username
        markup = Markup([[Btn("🎬 Tomosha qilish", url=f"https://t.me/{username}?start={movie.code}")]])
        if movie.poster_file_id:
            await tg.send_photo(chat_id=bot.movie_channel_id, photo=movie.poster_file_id,
                                caption=caption_of(movie), parse_mode="HTML", reply_markup=markup)
        else:
            await tg.send_message(chat_id=bot.movie_channel_id, text=caption_of(movie),
                                  parse_mode="HTML", reply_markup=markup)
    except TelegramError as exc:
        logger.warning("bot_id=%s: cannot post to channel (%s)", bot.id, exc)
        return "Kanalga yuborib bo‘lmadi. Bot kanalda administrator va xabar yuborish huquqiga ega ekanini tekshiring."
    return None


async def find_by_code(session, bot_id, code):
    return (await session.execute(
        select(Movie).where(Movie.bot_id == bot_id, func.lower(Movie.code) == norm_code(code))
    )).scalar_one_or_none()


async def search(session, bot_id, query):
    like = f"%{query.strip().lower()}%"
    return list((await session.execute(
        select(Movie).where(Movie.bot_id == bot_id, func.lower(Movie.title).like(like))
        .order_by(Movie.views.desc(), Movie.id).limit(SEARCH_LIMIT)
    )).scalars().all())


async def _viewer_text(tg, bot, text, chat_id, session):
    movie = await find_by_code(session, bot.id, text)
    if movie:
        await send_movie(tg, session, movie, chat_id)
        return
    found = await search(session, bot.id, text) if len(text.strip()) >= 2 else []
    if not found:
        await tg.send_message(chat_id=chat_id, text="😕 Hech narsa topilmadi. Kodni yoki nomning bir qismini yozing.")
        return
    rows = [[Btn(f"🎬 {m.title}"[:60], callback_data=f"mv:{m.id}")] for m in found]
    await tg.send_message(chat_id=chat_id, text="🔎 Topilgan kinolar:", reply_markup=Markup(rows))


# ------------------------------------------------------------------ admin panel

def panel_markup() -> Markup:
    return Markup([
        [Btn("➕ Kino qo‘shish", callback_data="cm:add")],
        [Btn("📋 Kinolar ro‘yxati", callback_data="cm:list:0")],
        [Btn("📊 Statistika", callback_data="cm:stats")],
    ])


async def _show(tg, callback, chat_id, text, markup=None):
    """Edit the panel message in place when the admin tapped a button, otherwise send a new one."""
    message = (callback or {}).get("message")
    if message:
        try:
            await tg.edit_message_text(
                chat_id=chat_id, message_id=message["message_id"], text=text,
                parse_mode="HTML", reply_markup=markup,
            )
            return
        except BadRequest as exc:
            if "not modified" in str(exc).lower():
                return
    await tg.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup)


async def _panel(tg, callback, chat_id):
    await _show(tg, callback, chat_id, "🛠 <b>Admin panel</b>\nKinolarni shu yerda boshqarasiz.", panel_markup())


def _movie_card(movie) -> str:
    desc = f"\n📝 {esc(movie.description)}" if movie.description else ""
    return (
        f"🎬 <b>{esc(movie.title)}</b>\n🔑 Kod: <code>{esc(movie.code)}</code>\n"
        f"👁 Ko‘rishlar: {movie.views}\n📁 Turi: {esc(movie.file_type)}{desc}"
    )


def _movie_markup(movie, has_channel=False) -> Markup:
    i = movie.id
    channel = [[Btn("📢 Kanalga yuborish", callback_data=f"cm:post:{i}")]] if has_channel else []
    return Markup([
        [Btn("▶️ Ko‘rish", callback_data=f"mv:{i}")],
        [Btn("✏️ Nomi", callback_data=f"cm:edit:{i}:title"), Btn("🔑 Kodi", callback_data=f"cm:edit:{i}:code")],
        [Btn("📝 Tavsifi", callback_data=f"cm:edit:{i}:desc"), Btn("🎞 Faylni almashtirish", callback_data=f"cm:edit:{i}:file")],
        [Btn("🖼 Poster", callback_data=f"cm:edit:{i}:poster")],
        *channel,
        [Btn("🗑 O‘chirish", callback_data=f"cm:del:{i}")],
        [Btn("⬅️ Ro‘yxat", callback_data="cm:list:0")],
    ])


async def _list(tg, callback, chat_id, session, bot, page):
    total = (await session.execute(select(func.count(Movie.id)).where(Movie.bot_id == bot.id))).scalar() or 0
    if not total:
        await _show(tg, callback, chat_id, "📭 Hali kino yo‘q.", Markup([
            [Btn("➕ Kino qo‘shish", callback_data="cm:add")], [Btn("⬅️ Orqaga", callback_data="cm:home")]]))
        return
    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, pages - 1))
    movies = (await session.execute(
        select(Movie).where(Movie.bot_id == bot.id).order_by(Movie.id.desc()).limit(PAGE_SIZE).offset(page * PAGE_SIZE)
    )).scalars().all()
    rows = [[Btn(f"{m.code} · {m.title}"[:60], callback_data=f"cm:open:{m.id}")] for m in movies]
    nav = []
    if page > 0:
        nav.append(Btn("◀️", callback_data=f"cm:list:{page - 1}"))
    if page < pages - 1:
        nav.append(Btn("▶️", callback_data=f"cm:list:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([Btn("⬅️ Orqaga", callback_data="cm:home")])
    await _show(tg, callback, chat_id, f"📋 <b>Kinolar</b> ({total}) — {page + 1}/{pages}", Markup(rows))


async def _stats(tg, callback, chat_id, session, bot):
    count, views = (await session.execute(
        select(func.count(Movie.id), func.coalesce(func.sum(Movie.views), 0)).where(Movie.bot_id == bot.id)
    )).one()
    users = (await session.execute(select(func.count(BotUser.id)).where(BotUser.bot_id == bot.id))).scalar() or 0
    top = (await session.execute(
        select(Movie).where(Movie.bot_id == bot.id, Movie.views > 0).order_by(Movie.views.desc()).limit(5)
    )).scalars().all()
    lines = [f"📊 <b>Statistika</b>\n\n🎬 Kinolar: {count}\n👁 Jami ko‘rishlar: {views}\n👥 Foydalanuvchilar: {users}"]
    if top:
        lines.append("\n🔥 <b>Eng ko‘p ko‘rilgan:</b>")
        lines += [f"{n}. {esc(m.title)} — {m.views}" for n, m in enumerate(top, 1)]
    await _show(tg, callback, chat_id, "\n".join(lines), Markup([[Btn("⬅️ Orqaga", callback_data="cm:home")]]))


async def _next_code(session, bot_id) -> str:
    codes = (await session.execute(select(Movie.code).where(Movie.bot_id == bot_id))).scalars().all()
    nums = [int(c) for c in codes if c.isdigit()]
    return str((max(nums) if nums else 100) + 1)


def _file_of(message):
    """(file_id, file_type) of a video-like message, or None."""
    if message.get("video"):
        return message["video"]["file_id"], "video"
    if message.get("animation"):
        return message["animation"]["file_id"], "video"
    doc = message.get("document")
    if doc:
        return doc["file_id"], "document"
    return None


async def _validate_code(session, bot_id, raw, *, ignore_id=None):
    code = norm_code(raw)
    if not CODE_RE.match(code):
        return None, "❌ Kod faqat harf, raqam, «-» yoki «_» dan iborat bo‘lsin (32 tagacha). Qayta yuboring."
    other = await find_by_code(session, bot_id, code)
    if other and other.id != ignore_id:
        return None, f"❌ <code>{esc(code)}</code> kodi band (<b>{esc(other.title)}</b>). Boshqa kod yuboring."
    return code, None


async def admin_callback(bot, callback, session, tg, us):
    chat_id = callback["from"]["id"]
    parts = callback["data"].split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "home":
        await _set_state(session, us)
        await _panel(tg, callback, chat_id)
    elif action == "cancel":
        await _set_state(session, us)
        await _panel(tg, callback, chat_id)
    elif action == "add":
        await _set_state(session, us, ADD_VIDEO, {})
        await _show(tg, callback, chat_id,
                    "🎞 Kinoning <b>videosini</b> shu yerga yuboring (yoki forward qiling).\nBekor qilish: /cancel",
                    Markup([[Btn("✖️ Bekor qilish", callback_data="cm:cancel")]]))
    elif action == "list":
        await _list(tg, callback, chat_id, session, bot, int(parts[2]))
    elif action == "stats":
        await _stats(tg, callback, chat_id, session, bot)
    elif action in ("open", "del", "delok", "edit", "post"):
        movie = await session.get(Movie, int(parts[2]))
        if movie is None or movie.bot_id != bot.id:
            await _show(tg, callback, chat_id, "Kino topilmadi.", Markup([[Btn("⬅️ Ro‘yxat", callback_data="cm:list:0")]]))
            return
        if action == "open":
            await _set_state(session, us)
            await _show(tg, callback, chat_id, _movie_card(movie), _movie_markup(movie, bool(bot.movie_channel_id)))
        elif action == "post":
            problem = await post_to_channel(tg, bot, movie)
            await tg.send_message(chat_id=chat_id, text="✅ Kanalga yuborildi." if not problem else f"❌ {problem}")
        elif action == "del":
            await _show(tg, callback, chat_id, f"🗑 <b>{esc(movie.title)}</b> o‘chirilsinmi?", Markup([[
                Btn("✅ Ha", callback_data=f"cm:delok:{movie.id}"), Btn("❌ Yo‘q", callback_data=f"cm:open:{movie.id}")]]))
        elif action == "delok":
            await session.execute(delete(Movie).where(Movie.id == movie.id))
            await session.commit()
            await _list(tg, callback, chat_id, session, bot, 0)
        else:
            field = parts[3]
            prompts = {
                "title": "✏️ Yangi <b>nomni</b> yuboring.",
                "code": "🔑 Yangi <b>kodni</b> yuboring.",
                "desc": "📝 Yangi <b>tavsifni</b> yuboring (o‘chirish uchun /skip).",
                "file": "🎞 Yangi <b>videoni</b> yuboring.",
                "poster": "🖼 Yangi <b>poster rasmini</b> yuboring.",
            }
            if field not in prompts:
                return
            await _set_state(session, us, EDIT_PREFIX + field, {"id": movie.id})
            await _show(tg, callback, chat_id, prompts[field] + "\nBekor qilish: /cancel",
                        Markup([[Btn("✖️ Bekor qilish", callback_data=f"cm:open:{movie.id}")]]))


async def admin_message(bot, message, session, tg, us) -> bool:
    """Feed one admin message to the state machine. Returns False if the admin is idle."""
    state, data = us.state, dict(us.state_data or {})
    if not state:
        return False
    chat_id = message["from"]["id"]
    text = (message.get("text") or "").strip()

    if state in (ADD_VIDEO, EDIT_PREFIX + "file"):
        found = _file_of(message)
        if not found:
            await tg.send_message(chat_id=chat_id, text="🎞 Video fayl yuboring (matn emas). Bekor qilish: /cancel")
            return True
        file_id, file_type = found
        if state == ADD_VIDEO:
            data.update(file_id=file_id, file_type=file_type)
            await _set_state(session, us, ADD_POSTER, data)
            await tg.send_message(
                chat_id=chat_id, parse_mode="HTML",
                text="✅ Video qabul qilindi.\n\n🖼 Endi kanal e’loni uchun <b>poster rasmini</b> yuboring. O‘tkazib yuborish: /skip",
            )
        else:
            movie = await session.get(Movie, data["id"])
            if movie and movie.bot_id == bot.id:
                movie.file_id, movie.file_type = file_id, file_type
                await session.commit()
            await _set_state(session, us)
            await tg.send_message(chat_id=chat_id, text="✅ Fayl almashtirildi.",
                                  reply_markup=Markup([[Btn("🎬 Kinoga qaytish", callback_data=f"cm:open:{data['id']}")]]))
        return True

    if state in (ADD_POSTER, EDIT_PREFIX + "poster"):
        photo = message.get("photo")
        if not photo and not (state == ADD_POSTER and text == "/skip"):
            await tg.send_message(chat_id=chat_id, text="🖼 Rasm yuboring (siqilgan foto). Bekor qilish: /cancel")
            return True
        poster = photo[-1]["file_id"] if photo else None
        if state == ADD_POSTER:
            data["poster"] = poster
            await _set_state(session, us, ADD_CODE, data)
            suggestion = await _next_code(session, bot.id)
            await tg.send_message(
                chat_id=chat_id, parse_mode="HTML",
                text=f"🔑 Endi kino <b>kodini</b> yuboring.\nAvtomatik kod: /auto (<code>{suggestion}</code>)",
            )
        else:
            movie = await session.get(Movie, data["id"])
            if movie and movie.bot_id == bot.id:
                movie.poster_file_id = poster
                await session.commit()
            await _finish_edit(tg, session, us, chat_id, data["id"], "Poster yangilandi.")
        return True

    if not text:
        await tg.send_message(chat_id=chat_id, text="Matn yuboring. Bekor qilish: /cancel")
        return True

    if state in (ADD_CODE, EDIT_PREFIX + "code"):
        raw = await _next_code(session, bot.id) if (state == ADD_CODE and text == "/auto") else text
        code, problem = await _validate_code(session, bot.id, raw, ignore_id=data.get("id"))
        if problem:
            await tg.send_message(chat_id=chat_id, text=problem, parse_mode="HTML")
            return True
        if state == ADD_CODE:
            data["code"] = code
            await _set_state(session, us, ADD_TITLE, data)
            await tg.send_message(chat_id=chat_id, text="✏️ Kino <b>nomini</b> yuboring.", parse_mode="HTML")
        else:
            movie = await session.get(Movie, data["id"])
            movie.code = code
            await session.commit()
            await _finish_edit(tg, session, us, chat_id, data["id"], "Kod yangilandi.")
        return True

    if state in (ADD_TITLE, EDIT_PREFIX + "title"):
        title = text[:255]
        if state == ADD_TITLE:
            data["title"] = title
            await _set_state(session, us, ADD_DESC, data)
            await tg.send_message(chat_id=chat_id, parse_mode="HTML",
                                  text="📝 Qisqa <b>tavsif</b> yuboring (janr, yil...). O‘tkazib yuborish: /skip")
        else:
            movie = await session.get(Movie, data["id"])
            movie.title = title
            await session.commit()
            await _finish_edit(tg, session, us, chat_id, data["id"], "Nom yangilandi.")
        return True

    if state in (ADD_DESC, EDIT_PREFIX + "desc"):
        desc = None if text == "/skip" else text[:700]
        if state == ADD_DESC:
            movie = Movie(
                bot_id=bot.id, code=data["code"], title=data["title"], description=desc,
                file_id=data["file_id"], file_type=data.get("file_type", "video"), added_by=chat_id,
                poster_file_id=data.get("poster"),
            )
            session.add(movie)
            await _set_state(session, us)
            await session.refresh(movie)
            note = ""
            if bot.movie_channel_id:
                problem = await post_to_channel(tg, bot, movie)
                note = "\n\n📢 Kanalga yuborildi." if not problem else f"\n\n⚠️ {problem}"
            await tg.send_message(
                chat_id=chat_id, parse_mode="HTML",
                text=f"✅ Saqlandi!\n\n{_movie_card(movie)}{note}",
                reply_markup=Markup([[Btn("➕ Yana qo‘shish", callback_data="cm:add")],
                                     [Btn("🛠 Admin panel", callback_data="cm:home")]]),
            )
        else:
            movie = await session.get(Movie, data["id"])
            movie.description = desc
            await session.commit()
            await _finish_edit(tg, session, us, chat_id, data["id"], "Tavsif yangilandi.")
        return True
    return False


async def _finish_edit(tg, session, us, chat_id, movie_id, note):
    await _set_state(session, us)
    await tg.send_message(chat_id=chat_id, text=f"✅ {note}",
                          reply_markup=Markup([[Btn("🎬 Kinoga qaytish", callback_data=f"cm:open:{movie_id}")]]))


# ------------------------------------------------------------------ entry point

async def handle(bot, update, session, tg):
    """Route one message/callback of a cinema bot (membership events are handled by the router)."""
    callback = update.get("callback_query")
    message = update.get("message")
    if callback:
        await _on_callback(bot, callback, session, tg)
    elif message:
        await _on_message(bot, message, session, tg)


async def _on_callback(bot, callback, session, tg):
    user = callback["from"]
    user_id = user["id"]
    data = callback.get("data") or ""
    await touch_user(session, bot.id, user)
    admin = await is_admin(session, bot, user_id)

    if data.startswith("cm:"):
        if not admin:
            return
        us = await _session_of(session, bot, user_id)
        await admin_callback(bot, callback, session, tg, us)
        return
    if data == subscription.CHECK_CALLBACK:
        if await subscription.gate(tg, bot, user_id, session, use_cache=False):
            await tg.send_message(chat_id=user_id, text=WELCOME, parse_mode="HTML")
        return
    if not admin and not await subscription.gate(tg, bot, user_id, session):
        return
    if data.startswith("mv:") and data[3:].isdigit():
        movie = await session.get(Movie, int(data[3:]))
        if movie and movie.bot_id == bot.id:
            await send_movie(tg, session, movie, user_id)


async def _on_message(bot, message, session, tg):
    sender = message["from"]
    user_id = sender["id"]
    text = (message.get("text") or "").strip()
    cmd = text.split()[0].split("@")[0] if text else ""
    payload = text.split(maxsplit=1)[1].strip() if cmd == "/start" and len(text.split()) > 1 else None
    await touch_user(session, bot.id, sender, source=payload)
    admin = await is_admin(session, bot, user_id)

    if not admin and not await subscription.gate(tg, bot, user_id, session):
        return

    if admin:
        us = await _session_of(session, bot, user_id)
        if cmd == "/cancel":
            await _set_state(session, us)
            await tg.send_message(chat_id=user_id, text="Bekor qilindi.")
            await _panel(tg, None, user_id)
            return
        if cmd == "/admin":
            await _set_state(session, us)
            await _panel(tg, None, user_id)
            return
        if us.state and cmd != "/start" and await admin_message(bot, message, session, tg, us):
            return
        if us.state and cmd == "/start":
            await _set_state(session, us)

    if cmd == "/start" and payload:  # t.me/bot?start=<movie code>
        movie = await find_by_code(session, bot.id, payload)
        if movie:
            await send_movie(tg, session, movie, user_id)
            return
        await tg.send_message(chat_id=user_id, text="😕 Bu kodli kino topilmadi.")
    if cmd == "/start":
        menu = await ensure_start_menu(session, bot)
        hint = "\n\n🛠 Admin panel: /admin" if admin else ""
        await tg.send_message(chat_id=user_id, text=(menu.message_text or WELCOME) + hint, parse_mode="HTML")
        return
    if text and not text.startswith("/"):
        await _viewer_text(tg, bot, text, user_id, session)
    elif text:
        await tg.send_message(chat_id=user_id, text="Kino kodini yoki nomini yuboring.")

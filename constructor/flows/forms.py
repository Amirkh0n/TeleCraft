"""Form builder: create forms, add questions, read and export submissions."""
import csv
import html
import io
import re

from sqlalchemy import func, select
from telegram import InlineKeyboardButton, Update
from telegram.ext import ContextTypes

from core.database import AsyncSessionLocal
from constructor import states
from constructor.session import ensure_constructor_user, save_builder_session
from constructor.ui import show_screen
from models.bots import Bot
from models.button_actions import ActionType
from models.forms import (
    FIELD_CHOICE, FIELD_EMAIL, FIELD_LOCATION, FIELD_NUMBER, FIELD_PHONE, FIELD_PHOTO, FIELD_TEXT,
    Form, FormField, FormSubmission,
)
from models.users import User

FIELD_LABELS = {
    FIELD_TEXT: "✍️ Matn", FIELD_NUMBER: "🔢 Raqam", FIELD_PHONE: "📞 Telefon",
    FIELD_EMAIL: "📧 Email", FIELD_CHOICE: "👇 Tanlov", FIELD_PHOTO: "📷 Rasm", FIELD_LOCATION: "📍 Lokatsiya",
}
MAX_FIELDS = 20
MAX_OPTIONS = 12
MAX_OPTION_LENGTH = 60
EXPORT_LIMIT = 5000
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


# ---------------------------------------------------------------- pure helpers

def parse_options(text: str) -> list[str]:
    """Options typed one per line (or separated by commas), de-duplicated and validated."""
    parts = [p.strip() for p in re.split(r"[\n,]", text or "")]
    options = list(dict.fromkeys(p for p in parts if p))
    if len(options) < 2:
        raise ValueError("Kamida 2 ta variant kerak.")
    if len(options) > MAX_OPTIONS:
        raise ValueError(f"Variantlar {MAX_OPTIONS} tadan oshmasin.")
    if any(len(o) > MAX_OPTION_LENGTH for o in options):
        raise ValueError(f"Har bir variant {MAX_OPTION_LENGTH} belgidan oshmasin.")
    return options


def _safe_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text  # spreadsheet formula injection


def build_csv(fields, submissions) -> bytes:
    """UTF-8 (with BOM, so Excel reads it right) CSV: one column per question."""
    out = io.StringIO()
    writer = csv.writer(out)
    labels = [f.label for f in fields]
    writer.writerow(["Sana", "Telegram ID", "Username", "Ism"] + [_safe_cell(label) for label in labels])
    for sub in submissions:
        by_label = {a["label"]: a["value"] for a in (sub.answers or [])}
        writer.writerow([
            sub.created_at.strftime("%Y-%m-%d %H:%M") if sub.created_at else "",
            sub.tg_user_id, _safe_cell(sub.username), _safe_cell(sub.full_name),
        ] + [_safe_cell(by_label.get(label)) for label in labels])
    return out.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------- data access

async def owned_form(session, tg_id: int, form_id: int):
    row = (await session.execute(
        select(Form, Bot).join(Bot, Bot.id == Form.bot_id).join(User, User.id == Bot.owner_id)
        .where(Form.id == form_id, User.tg_id == tg_id)
    )).first()
    return (row[0], row[1]) if row else (None, None)


def _arg(update: Update, index: int = -1) -> str:
    return update.callback_query.data.split(":")[index]


# ---------------------------------------------------------------- list / open

async def show_forms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get("current_bot_id")
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Form).join(Bot, Bot.id == Form.bot_id).join(User, User.id == Bot.owner_id)
            .where(Form.bot_id == bot_id, User.tg_id == update.effective_user.id).order_by(Form.id)
        )).scalars().all()
    keyboard = [[InlineKeyboardButton(f"📋 {f.title}", callback_data=f"frm:open:{f.id}")] for f in rows]
    keyboard.append([InlineKeyboardButton("➕ Yangi forma", callback_data="frm:new")])
    keyboard.append([InlineKeyboardButton("⬅️ Bot boshqaruvi", callback_data=f"bot_{bot_id}")])
    await show_screen(
        update,
        "📋 <b>Formalar</b>\n\nForma — bot foydalanuvchidan savollar so‘rab javoblarni yig‘adi "
        "(ariza, buyurtma, so‘rovnoma). Formani tugmaga ulaysiz.",
        keyboard,
    )


async def open_form(update: Update, context: ContextTypes.DEFAULT_TYPE, form_id: int | None = None, *, edit=True):
    form_id = form_id or int(_arg(update))
    async with AsyncSessionLocal() as session:
        form, _bot = await owned_form(session, update.effective_user.id, form_id)
        if form is None:
            await update.callback_query.answer("Forma topilmadi.", show_alert=True)
            return
        fields = (await session.execute(
            select(FormField).where(FormField.form_id == form.id).order_by(FormField.position, FormField.id)
        )).scalars().all()
        count = (await session.execute(
            select(func.count(FormSubmission.id)).where(FormSubmission.form_id == form.id)
        )).scalar_one()
    lines = [f"📋 <b>{html.escape(form.title)}</b>", ""]
    for i, f in enumerate(fields, 1):
        lines.append(f"{i}. {FIELD_LABELS.get(f.type, f.type)} — {html.escape(f.label)}{'' if f.required else ' (ixtiyoriy)'}")
    if not fields:
        lines.append("Hali savol yo‘q.")
    lines += ["", f"📥 Javoblar: {count}", f"🔔 Adminlarga xabar: {'yoqilgan' if form.notify_admins else 'o‘chirilgan'}"]
    keyboard = [
        [InlineKeyboardButton("➕ Savol qo‘shish", callback_data=f"frm:addq:{form.id}")],
        [InlineKeyboardButton("📥 Javoblar / CSV", callback_data=f"frm:subs:{form.id}")],
        [InlineKeyboardButton("👋 Kirish matni", callback_data=f"frm:intro:{form.id}"),
         InlineKeyboardButton("✅ Yakuniy xabar", callback_data=f"frm:final:{form.id}")],
        [InlineKeyboardButton("🔔 Xabarni yoqish/o‘chirish", callback_data=f"frm:notify:{form.id}")],
    ]
    if fields:
        keyboard.append([InlineKeyboardButton("↩️ Oxirgi savolni o‘chirish", callback_data=f"frm:delq:{form.id}")])
    keyboard.append([InlineKeyboardButton("🗑 Formani o‘chirish", callback_data=f"frm:del:{form.id}")])
    keyboard.append([InlineKeyboardButton("⬅️ Formalar", callback_data="frm:list")])
    await show_screen(update, "\n".join(lines), keyboard, edit=edit)


# ---------------------------------------------------------------- create form

async def new_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(user.id, context, pending_state=states.WAITING_FOR_FORM_TITLE, draft={"flow": "form_title"})
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("📋 Forma nomini yuboring. Masalan: Ariza yoki Buyurtma.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry for every text message while one of the form states is active."""
    state = context.user_data.get("state")
    text = (update.message.text or "").strip()
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    draft = dict(context.user_data.get("draft") or {})

    if state == states.WAITING_FOR_FORM_TITLE:
        if not text or len(text) > 100:
            await update.message.reply_text("❌ Nom 1–100 belgi bo‘lsin. Qayta yuboring.")
            return
        bot_id = context.user_data.get("current_bot_id")
        async with AsyncSessionLocal() as session:
            bot = (await session.execute(
                select(Bot).join(User, User.id == Bot.owner_id).where(Bot.id == bot_id, User.tg_id == update.effective_user.id)
            )).scalar_one_or_none()
            if bot is None:
                await update.message.reply_text("❌ Avval botni tanlang.")
                return
            form = Form(bot_id=bot.id, title=text)
            session.add(form)
            await session.commit()
            await session.refresh(form)
        await save_builder_session(user.id, context, pending_state="", draft={})
        await update.message.reply_text("✅ Forma yaratildi. Endi savollarni qo‘shing.")
        await open_form(update, context, form.id, edit=False)

    elif state == states.WAITING_FOR_FIELD_PROMPT:
        if not text or len(update.message.text_html) > 500:
            await update.message.reply_text("❌ Savol 1–500 belgi bo‘lsin. Qayta yuboring.")
            return
        draft.update(prompt=update.message.text_html, label=text[:60])
        await save_builder_session(user.id, context, pending_state="", draft=draft)
        keyboard = [[InlineKeyboardButton(label, callback_data=f"frm:ft:{kind}")] for kind, label in FIELD_LABELS.items()]
        await show_screen(update, "Javob turi qanday bo‘lsin?", keyboard, edit=False)

    elif state == states.WAITING_FOR_FIELD_OPTIONS:
        try:
            draft["options"] = parse_options(update.message.text)
        except ValueError as exc:
            await update.message.reply_text(f"❌ {exc} Qayta yuboring (har bir variant yangi qatorda).")
            return
        await save_builder_session(user.id, context, pending_state="", draft=draft)
        await _ask_required(update)

    elif state == states.WAITING_FOR_FORM_TEXT:
        if not text or len(update.message.text_html) > 1000:
            await update.message.reply_text("❌ Matn 1–1000 belgi bo‘lsin. Qayta yuboring.")
            return
        async with AsyncSessionLocal() as session:
            form, _bot = await owned_form(session, update.effective_user.id, int(draft.get("form_id", 0)))
            if form is None:
                await update.message.reply_text("❌ Forma topilmadi.")
                return
            setattr(form, "intro_text" if draft.get("which") == "intro" else "final_message", update.message.text_html)
            await session.commit()
        await save_builder_session(user.id, context, pending_state="", draft={})
        await update.message.reply_text("✅ Saqlandi.")
        await open_form(update, context, form.id, edit=False)


# ---------------------------------------------------------------- add question

async def add_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    form_id = int(_arg(update))
    async with AsyncSessionLocal() as session:
        form, _bot = await owned_form(session, update.effective_user.id, form_id)
        count = 0
        if form:
            count = (await session.execute(
                select(func.count(FormField.id)).where(FormField.form_id == form.id)
            )).scalar_one()
    if form is None:
        await update.callback_query.answer("Forma topilmadi.", show_alert=True)
        return
    if count >= MAX_FIELDS:
        await update.callback_query.answer(f"Bitta formada {MAX_FIELDS} tadan ko‘p savol bo‘lmasin.", show_alert=True)
        return
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(
        user.id, context, pending_state=states.WAITING_FOR_FIELD_PROMPT, draft={"flow": "field", "form_id": form.id},
    )
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("❓ Savol matnini yuboring. Masalan: Ismingiz nima?")


async def _ask_required(update: Update):
    keyboard = [[InlineKeyboardButton("✅ Majburiy", callback_data="frm:req:1"),
                 InlineKeyboardButton("⏭ Ixtiyoriy", callback_data="frm:req:0")]]
    await show_screen(update, "Bu savolga javob majburiymi?", keyboard, edit=bool(update.callback_query))


async def pick_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind = _arg(update)
    draft = dict(context.user_data.get("draft") or {})
    if kind not in FIELD_LABELS or draft.get("flow") != "field":
        await update.callback_query.answer("Qaytadan boshlang.", show_alert=True)
        return
    draft["type"] = kind
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    if kind == FIELD_CHOICE:
        await save_builder_session(user.id, context, pending_state=states.WAITING_FOR_FIELD_OPTIONS, draft=draft)
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "👇 Variantlarni yuboring — har biri yangi qatorda (2–12 ta).\nMasalan:\nToshkent\nSamarqand\nBuxoro"
        )
        return
    await save_builder_session(user.id, context, draft=draft)
    await _ask_required(update)


async def set_required(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = dict(context.user_data.get("draft") or {})
    if draft.get("flow") != "field" or "type" not in draft:
        await update.callback_query.answer("Qaytadan boshlang.", show_alert=True)
        return
    required = _arg(update) == "1"
    async with AsyncSessionLocal() as session:
        form, _bot = await owned_form(session, update.effective_user.id, int(draft["form_id"]))
        if form is None:
            await update.callback_query.answer("Forma topilmadi.", show_alert=True)
            return
        position = (await session.execute(
            select(func.coalesce(func.max(FormField.position), -1)).where(FormField.form_id == form.id)
        )).scalar_one() + 1
        session.add(FormField(
            form_id=form.id, position=position, label=draft["label"], prompt=draft["prompt"],
            type=draft["type"], required=required, options=draft.get("options"),
        ))
        await session.commit()
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(user.id, context, pending_state="", draft={})
    await open_form(update, context, form.id)


# ---------------------------------------------------------------- small actions

async def delete_last_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    form_id = int(_arg(update))
    async with AsyncSessionLocal() as session:
        form, _bot = await owned_form(session, update.effective_user.id, form_id)
        if form is None:
            await update.callback_query.answer("Forma topilmadi.", show_alert=True)
            return
        last = (await session.execute(
            select(FormField).where(FormField.form_id == form.id).order_by(FormField.position.desc(), FormField.id.desc())
        )).scalars().first()
        if last:
            await session.delete(last)
            await session.commit()
    await open_form(update, context, form_id)


async def toggle_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    form_id = int(_arg(update))
    async with AsyncSessionLocal() as session:
        form, _bot = await owned_form(session, update.effective_user.id, form_id)
        if form is None:
            await update.callback_query.answer("Forma topilmadi.", show_alert=True)
            return
        form.notify_admins = not form.notify_admins
        await session.commit()
    await open_form(update, context, form_id)


async def edit_text_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, which, form_id = update.callback_query.data.split(":")
    async with AsyncSessionLocal() as session:
        form, _bot = await owned_form(session, update.effective_user.id, int(form_id))
    if form is None:
        await update.callback_query.answer("Forma topilmadi.", show_alert=True)
        return
    user = await ensure_constructor_user(update.effective_user.id, update.effective_user.full_name)
    await save_builder_session(
        user.id, context, pending_state=states.WAITING_FOR_FORM_TEXT,
        draft={"flow": "form_text", "form_id": form.id, "which": which},
    )
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "👋 Forma boshlanishidan oldin ko‘rsatiladigan matnni yuboring."
        if which == "intro" else "✅ Forma tugagach foydalanuvchiga ko‘rsatiladigan xabarni yuboring."
    )


async def delete_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.callback_query.data.split(":")
    form_id = int(parts[-1])
    if parts[1] == "del":
        keyboard = [[InlineKeyboardButton("🗑 Ha, o‘chirish", callback_data=f"frm:delok:{form_id}")],
                    [InlineKeyboardButton("⬅️ Bekor qilish", callback_data=f"frm:open:{form_id}")]]
        await show_screen(update, "⚠️ Forma va uning barcha javoblari o‘chadi. Davom etasizmi?", keyboard)
        return
    async with AsyncSessionLocal() as session:
        form, _bot = await owned_form(session, update.effective_user.id, form_id)
        if form is not None:
            from models.button_actions import ButtonAction
            for action in (await session.execute(
                select(ButtonAction).where(ButtonAction.action_type == ActionType.form, ButtonAction.value == str(form.id))
            )).scalars().all():
                await session.delete(action)  # the buttons that opened this form stay, without an action
            for model in (FormSubmission, FormField):
                for row in (await session.execute(select(model).where(model.form_id == form.id))).scalars().all():
                    await session.delete(row)
            await session.delete(form)
            await session.commit()
    await show_forms(update, context)


# ---------------------------------------------------------------- submissions

async def show_submissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.callback_query.data.split(":")
    form_id = int(parts[-1])
    async with AsyncSessionLocal() as session:
        form, _bot = await owned_form(session, update.effective_user.id, form_id)
        if form is None:
            await update.callback_query.answer("Forma topilmadi.", show_alert=True)
            return
        fields = (await session.execute(
            select(FormField).where(FormField.form_id == form.id).order_by(FormField.position, FormField.id)
        )).scalars().all()
        subs = (await session.execute(
            select(FormSubmission).where(FormSubmission.form_id == form.id)
            .order_by(FormSubmission.id.desc()).limit(EXPORT_LIMIT)
        )).scalars().all()

    if parts[1] == "csv":
        if not subs:
            await update.callback_query.answer("Hali javob yo‘q.", show_alert=True)
            return
        await update.callback_query.answer()
        await update.callback_query.message.reply_document(
            document=io.BytesIO(build_csv(fields, list(reversed(subs)))),
            filename=f"{re.sub(r'[^A-Za-z0-9_-]+', '_', form.title)[:40] or 'forma'}.csv",
            caption=f"📥 {len(subs)} ta javob",
        )
        return

    from engine.forms import format_submission
    lines = [f"📥 <b>{html.escape(form.title)}</b> — oxirgi javoblar", ""]
    if not subs:
        lines.append("Hali javob yo‘q.")
    for sub in subs[:5]:
        sender = {"id": sub.tg_user_id, "username": sub.username}
        lines.append(format_submission(form.title, sender, sub.full_name, sub.answers or []).split("\n", 1)[1])
        lines.append("———")
    keyboard = [[InlineKeyboardButton("📄 CSV yuklab olish", callback_data=f"frm:csv:{form.id}")],
                [InlineKeyboardButton("⬅️ Forma", callback_data=f"frm:open:{form.id}")]]
    await show_screen(update, "\n".join(lines)[:3900], keyboard)


# ---------------------------------------------------------------- connect a form to a button

async def pick_form_for_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.user_data.get("current_bot_id")
    button_id = context.user_data.get("current_button_id")
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Form).join(Bot, Bot.id == Form.bot_id).join(User, User.id == Bot.owner_id)
            .where(Form.bot_id == bot_id, User.tg_id == update.effective_user.id).order_by(Form.id)
        )).scalars().all()
    keyboard = [[InlineKeyboardButton(f"📋 {f.title}", callback_data=f"frm:use:{f.id}")] for f in rows]
    keyboard.append([InlineKeyboardButton("➕ Yangi forma", callback_data="frm:new")])
    keyboard.append([InlineKeyboardButton("⬅️ Actionlar", callback_data=f"button_{button_id}")])
    await show_screen(update, "Tugma bosilganda qaysi forma ochilsin?", keyboard)


async def use_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from constructor.flows.actions import save_button_action, show_action_choices
    form_id = int(_arg(update))
    button_id = context.user_data.get("current_button_id")
    async with AsyncSessionLocal() as session:
        form, _bot = await owned_form(session, update.effective_user.id, form_id)
        if form is None or not button_id:
            await update.callback_query.answer("Forma yoki tugma topilmadi.", show_alert=True)
            return
        await save_button_action(session, button_id, ActionType.form, str(form.id))
    await show_action_choices(update, context, button_id)

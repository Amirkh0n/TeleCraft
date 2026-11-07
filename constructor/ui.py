from telegram import InlineKeyboardMarkup, Update


async def show_screen(update: Update, text: str, keyboard: list[list], *, edit: bool = True) -> None:
    """Render one builder screen without duplicating navigation messages."""
    markup = InlineKeyboardMarkup(keyboard)
    if edit and update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

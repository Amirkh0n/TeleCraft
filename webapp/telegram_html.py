"""Validation of the HTML subset Telegram accepts, so a broken message is caught while editing
instead of failing when a user opens the bot."""
from html.parser import HTMLParser

ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre", "a", "tg-spoiler", "blockquote"}


class _Checker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.error: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            self.error = f"<{tag}> ishlatib bo‘lmaydi"
            return
        if tag == "a" and not any(k == "href" and v for k, v in attrs):
            self.error = "Havolada href bo‘lishi kerak"
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag not in ALLOWED_TAGS:
            self.error = f"</{tag}> ishlatib bo‘lmaydi"
        elif not self.stack or self.stack[-1] != tag:
            self.error = f"</{tag}> teg noto‘g‘ri yopilgan"
        else:
            self.stack.pop()


def check_html(text: str) -> str | None:
    """``None`` if ``text`` is valid Telegram HTML, otherwise a short Uzbek problem description."""
    checker = _Checker()
    checker.feed(text)
    checker.close()
    if checker.error:
        return checker.error
    if checker.stack:
        return f"<{checker.stack[-1]}> yopilmagan"
    return None

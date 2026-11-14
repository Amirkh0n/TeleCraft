import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_botfather_mention_in_builder_texts_is_a_link():
    """User-facing builder texts must use constructor.ui.BOTFATHER (a link to @BotFather), never a bare word."""
    from constructor.ui import BOTFATHER
    assert BOTFATHER == '<a href="https://t.me/BotFather">BotFather</a>'  # only the word is linked
    for path in (ROOT / "constructor").rglob("*.py"):
        if path.name == "ui.py":
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"BotFather", line) and "BOTFATHER" not in line:
                raise AssertionError(f"{path.name}:{number} mentions BotFather without a link: {line.strip()}")

"""Pure helpers of the join-request bot (no database, no Telegram)."""
from models.join import MODE_AUTO, MODE_CAPTCHA, MODE_MANUAL

MODE_NAMES = {MODE_AUTO: "⚡️ Avto-qabul", MODE_MANUAL: "🖐 Qo‘lda qabul", MODE_CAPTCHA: "🤖 Captcha + avto-qabul"}
MAX_QUESTIONS = 3
MAX_QUESTION_LEN = 200
DELAYS = (0, 30, 300, 3600)  # seconds offered to the admin


def delay_label(seconds: int) -> str:
    if seconds <= 0:
        return "darhol"
    if seconds < 60:
        return f"{seconds} soniya"
    if seconds < 3600:
        return f"{seconds // 60} daqiqa"
    return f"{seconds // 3600} soat"


def parse_questions(text: str) -> list[str]:
    """One question per line, 1 to 3 of them."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        raise ValueError("Kamida bitta savol yozing (har qator — bitta savol).")
    if len(lines) > MAX_QUESTIONS:
        raise ValueError(f"Ko‘pi bilan {MAX_QUESTIONS} ta savol bo‘ladi, siz {len(lines)} ta yozdingiz.")
    if any(len(line) > MAX_QUESTION_LEN for line in lines):
        raise ValueError(f"Har bir savol {MAX_QUESTION_LEN} belgidan oshmasin.")
    return lines


def render(template: str, name: str, chat: str) -> str:
    """Fills {name} and {chat}; plain replace so stray braces in admin texts never break anything."""
    return (template or "").replace("{name}", name or "").replace("{chat}", chat or "")


def format_answers(questions: list[str], answers: list[str]) -> str:
    return "\n".join(f"❓ {q}\n💬 {a}" for q, a in zip(questions, answers))

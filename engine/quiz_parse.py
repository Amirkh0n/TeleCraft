"""The TXT test format and Telegram-poll shaping. Pure functions, no database.

Format (one question per block, blank lines are optional)::

    #Question text
    +correct option        (several + = multiple-answer question)
    -wrong option
    !optional explanation  (shown after answering; ">" works too)

Unlike a naive parser it is forgiving (BOM, CRLF, cp1251 files, wrapped lines, missing blank
lines) and strict where it matters: every problem is reported with the line it is on and the
valid questions are still kept.
"""
from dataclasses import dataclass, field

MAX_QUESTIONS = 500
MAX_OPTIONS = 10  # Telegram poll limit
POLL_QUESTION_LIMIT = 300
POLL_OPTION_LIMIT = 100
POLL_EXPLANATION_LIMIT = 200
LETTERS = "ABCDEFGHIJ"


@dataclass
class Question:
    text: str
    options: list[str]
    correct: list[int]
    explanation: str | None = None
    line: int = 0

    @property
    def multiple(self) -> bool:
        return len(self.correct) > 1


@dataclass
class ParseResult:
    questions: list[Question] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _short(text: str, n: int = 30) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def validate(q: Question) -> str | None:
    if not q.text.strip():
        return "savol matni bo‘sh"
    if len(q.options) < 2:
        return "kamida 2 ta variant kerak"
    if len(q.options) > MAX_OPTIONS:
        return f"variantlar {MAX_OPTIONS} tadan oshmasin (Telegram cheklovi)"
    if any(not o.strip() for o in q.options):
        return "bo‘sh variant bor"
    if not q.correct:
        return "to‘g‘ri javob (+) belgilanmagan"
    if len(q.correct) == len(q.options):
        return "hamma variant to‘g‘ri bo‘lishi mumkin emas"
    if len(q.text) > 3000:
        return "savol juda uzun (3000 belgigacha)"
    return None


def parse(text: str) -> ParseResult:
    result = ParseResult()
    current: Question | None = None
    stray_reported = False

    def flush():
        nonlocal current
        if current is None:
            return
        problem = validate(current)
        if problem:
            result.errors.append(f"{current.line}-qator, «{_short(current.text)}»: {problem}")
        elif len(result.questions) >= MAX_QUESTIONS:
            if not any("juda ko‘p" in e for e in result.errors):
                result.errors.append(f"Bir testda {MAX_QUESTIONS} tadan ko‘p savol bo‘lmasin: qolganlari qo‘shilmadi")
        else:
            result.questions.append(current)
        current = None

    for number, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿").split("\n"), 1):
        line = raw.strip()
        if not line:
            continue
        mark, rest = line[0], line[1:].strip()
        if mark == "#":
            flush()
            current = Question(text=rest, options=[], correct=[], line=number)
        elif current is None:
            if not stray_reported:
                result.errors.append(f"{number}-qator: savol (#) dan oldin matn bor, e’tiborga olinmadi")
                stray_reported = True
        elif mark in "+-":
            current.options.append(rest)
            if mark == "+":
                current.correct.append(len(current.options) - 1)
        elif mark in "!>":
            current.explanation = (current.explanation + " " if current.explanation else "") + rest
        elif current.explanation is not None:
            current.explanation += " " + line
        elif current.options:
            current.options[-1] += " " + line  # wrapped option
        else:
            current.text += " " + line  # wrapped question
    flush()
    return result


def format_txt(questions) -> str:
    """Inverse of :func:`parse` (accepts Question objects or QuizQuestion rows)."""
    blocks = []
    for q in questions:
        lines = [f"#{q.text}"]
        lines += [f"{'+' if i in q.correct else '-'}{opt}" for i, opt in enumerate(q.options)]
        if q.explanation:
            lines.append(f"!{q.explanation}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def poll_view(text: str, options: list[str]):
    """(text sent before the poll or None, poll question, poll options).

    Telegram limits poll questions to 300 and options to 100 characters. Longer content is sent as
    a normal message and the poll then only carries the letters A, B, C...
    """
    if len(text) <= POLL_QUESTION_LIMIT and all(len(o) <= POLL_OPTION_LIMIT for o in options):
        return None, text, list(options)
    body = "\n".join(f"<b>{LETTERS[i]})</b> {_html(o)}" for i, o in enumerate(options))
    return f"❓ {_html(text[:3000])}\n\n{body}", "Javobni tanlang", list(LETTERS[:len(options)])


def _html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def poll_explanation(value: str | None) -> str | None:
    if not value:
        return None
    return value if len(value) <= POLL_EXPLANATION_LIMIT else value[:POLL_EXPLANATION_LIMIT - 1] + "…"


EXAMPLE = """#Poytaxt qaysi shahar? (bitta to'g'ri javob)
+Toshkent
-Samarqand
-Buxoro
-Andijon
!Toshkent 1930-yildan beri poytaxt.

#Qaysilari tub sonlar? (bir nechta to'g'ri javob)
+2
+3
-4
-9

#Savol bir necha qatorga
sig'masa shunday davom ettiriladi
+To'g'ri javob
-Noto'g'ri javob
"""

AI_PROMPT = """Menga "{mavzu}" mavzusida {soni} ta test savoli tuz. Faqat quyidagi TXT formatda yoz, boshqa hech narsa qo'shma:

#Savol matni
+To'g'ri javob
-Noto'g'ri javob
-Noto'g'ri javob
-Noto'g'ri javob
!Qisqa izoh (ixtiyoriy)

Qoidalar: har bir savol # bilan boshlanadi; to'g'ri javob + bilan, noto'g'ri javoblar - bilan; har savolda 2 dan 10 gacha variant va kamida bitta to'g'ri javob; savollar orasida bo'sh qator. Savol 300, variant 100 belgidan oshmasin."""

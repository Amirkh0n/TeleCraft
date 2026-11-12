import pytest

from engine.quiz_parse import AI_PROMPT, EXAMPLE, decode, format_txt, parse, poll_explanation, poll_view

SAMPLE = """﻿#Quyidagilarning qaysi birida yozgi va qishki turi farqlanadi?
+tangachali temiratki
+psoriaz
-trixofitiya
-pufakli pemfihus

#Pustulyoz psoriazga tegishli?
+Zumbusch
-intertriginoz
-artropatik psoriaz
"""


def test_reference_style_file_with_bom_and_multiple_answers():
    r = parse(SAMPLE)
    assert not r.errors and len(r.questions) == 2
    q1, q2 = r.questions
    assert q1.correct == [0, 1] and q1.multiple and len(q1.options) == 4
    assert q2.correct == [0] and not q2.multiple and q2.text.startswith("Pustulyoz")


def test_crlf_missing_blank_lines_and_explanations():
    r = parse("#A?\r\n+yes\r\n-no\r\n!Because\r\n#B?\r\n-x\r\n+y\r\n>Izoh bor\r\nikkinchi qator")
    assert not r.errors
    assert r.questions[0].explanation == "Because"
    assert r.questions[1].correct == [1] and r.questions[1].explanation == "Izoh bor ikkinchi qator"


def test_wrapped_question_and_option_lines():
    r = parse("#Uzun savol\ndavomi\n+bir\nqator\n-ikki")
    q = r.questions[0]
    assert q.text == "Uzun savol davomi" and q.options == ["bir qator", "ikki"]


@pytest.mark.parametrize("block, fragment", [
    ("#S?\n+a", "kamida 2"),
    ("#S?\n-a\n-b", "to‘g‘ri javob"),
    ("#S?\n+a\n+b", "hamma variant"),
    ("#\n+a\n-b", "savol matni bo‘sh"),
    ("#S?\n" + "\n".join(f"{'+' if i == 0 else '-'}o{i}" for i in range(11)), "10 tadan"),
    ("#S?\n+\n-b", "bo‘sh variant"),
])
def test_invalid_questions_reported_with_line_and_valid_ones_kept(block, fragment):
    r = parse("#Yaxshi\n+a\n-b\n\n" + block + "\n\n#Yana yaxshi\n-a\n+b")
    assert [q.text for q in r.questions] == ["Yaxshi", "Yana yaxshi"]
    assert len(r.errors) == 1 and fragment in r.errors[0] and r.errors[0].startswith("5-qator")


def test_text_before_first_question_is_reported_once():
    r = parse("Salom\nBu test\n#Q\n+a\n-b")
    assert len(r.questions) == 1 and len(r.errors) == 1 and "1-qator" in r.errors[0]


def test_empty_and_garbage_input():
    assert parse("").questions == [] and parse("   \n\n").errors == []
    r = parse("hech narsa\nyo'q")
    assert not r.questions and r.errors


def test_question_limit():
    text = "\n".join(f"#Q{i}\n+a\n-b" for i in range(510))
    r = parse(text)
    assert len(r.questions) == 500 and any("500" in e for e in r.errors)


def test_roundtrip_and_example_is_valid():
    r = parse(EXAMPLE)
    assert not r.errors and len(r.questions) == 3
    again = parse(format_txt(r.questions))
    assert [(q.text, q.options, q.correct, q.explanation) for q in again.questions] == \
           [(q.text, q.options, q.correct, q.explanation) for q in r.questions]
    assert "{mavzu}" in AI_PROMPT


def test_decode_handles_bom_utf8_and_cp1251():
    assert decode("﻿#Привет".encode("utf-8")) == "#Привет" or decode("﻿#Привет".encode("utf-8")).endswith("Привет")
    assert decode("#Привет".encode("cp1251")) == "#Привет"
    assert decode("#O‘zbek".encode("utf-8")) == "#O‘zbek"


def test_poll_view_short_and_long():
    assert poll_view("Savol?", ["a", "b"]) == (None, "Savol?", ["a", "b"])
    pre, question, options = poll_view("x" * 301, ["a", "b"])
    assert pre.startswith("❓ ") and question == "Javobni tanlang" and options == ["A", "B"]
    pre, question, options = poll_view("Q", ["a" * 101, "<b>"])
    assert "&lt;b&gt;" in pre and "<b>A)</b>" in pre and options == ["A", "B"]


def test_poll_explanation_is_trimmed():
    assert poll_explanation(None) is None and poll_explanation("kalta") == "kalta"
    assert len(poll_explanation("x" * 500)) == 200

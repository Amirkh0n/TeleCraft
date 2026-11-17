"""Form responses: the table API, search, photos, delete and the Excel export."""
import io

import httpx
import pytest
from fastapi import FastAPI
from openpyxl import load_workbook

from engine.forms_export import build_xlsx
from helpers import FakeTG
from models.forms import Form, FormField, FormSubmission
from test_webapp_api import sign
from webapp import api_forms
from webapp.auth import get_session


async def make_form(env):
    form = Form(bot_id=env.bot.id, title="Ariza: yozgi/kurs?")
    env.session.add(form)
    await env.session.flush()
    for pos, (label, kind, options) in enumerate([("Ism", "text", None), ("Yosh", "number", None), ("Kurs", "choice", ["Ingliz", "IT"]),
                                                   ("Joy", "location", None), ("Rasm", "photo", None)]):
        env.session.add(FormField(form_id=form.id, position=pos, label=label, prompt=label, type=kind, options=options))
    await env.session.commit()
    return form


def answers(name, age, course, place="41.3,69.2", photo="PH"):
    return [{"label": "Ism", "type": "text", "value": name}, {"label": "Yosh", "type": "number", "value": age},
            {"label": "Kurs", "type": "choice", "value": course}, {"label": "Joy", "type": "location", "value": place},
            {"label": "Rasm", "type": "photo", "value": photo}]


@pytest.fixture
async def fc(env, monkeypatch):
    app = FastAPI()
    app.include_router(api_forms.router)

    async def override():
        yield env.session

    app.dependency_overrides[get_session] = override
    tg = FakeTG()

    async def get_client(token):
        return tg

    monkeypatch.setattr(api_forms, "get_client", get_client)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.env, c.tg = env, tg
        c.hdr = {"Authorization": f"tma {sign()}"}
        c.form = await make_form(env)
        yield c


async def add_subs(fc, n=3):
    for i in range(n):
        fc.env.session.add(FormSubmission(form_id=fc.form.id, bot_id=fc.env.bot.id, tg_user_id=100 + i, username=f"u{i}",
                                          full_name=f"Ali {i}", answers=answers(f"Ali {i}", str(20 + i), "IT" if i % 2 else "Ingliz")))
    await fc.env.session.commit()


async def test_responses_table_search_and_paging(fc, monkeypatch):
    await add_subs(fc, 3)
    data = (await fc.get(f"/api/v1/forms/{fc.form.id}/responses", headers=fc.hdr)).json()
    assert data["total"] == 3 and [c["label"] for c in data["columns"]] == ["Ism", "Yosh", "Kurs", "Joy", "Rasm"]
    assert data["rows"][0]["full_name"] == "Ali 2" and data["rows"][0]["cells"]["Kurs"] == "Ingliz" and not data["more"]
    found = (await fc.get(f"/api/v1/forms/{fc.form.id}/responses?q=u1", headers=fc.hdr)).json()
    assert found["total"] == 1 and found["rows"][0]["username"] == "u1"
    by_answer = (await fc.get(f"/api/v1/forms/{fc.form.id}/responses?q=Ingliz", headers=fc.hdr)).json()
    assert by_answer["total"] == 2
    by_tg = (await fc.get(f"/api/v1/forms/{fc.form.id}/responses?q=101", headers=fc.hdr)).json()
    assert by_tg["total"] == 1
    monkeypatch.setattr(api_forms, "PAGE", 2)
    page1 = (await fc.get(f"/api/v1/forms/{fc.form.id}/responses", headers=fc.hdr)).json()
    page2 = (await fc.get(f"/api/v1/forms/{fc.form.id}/responses?offset=2", headers=fc.hdr)).json()
    assert page1["more"] and len(page1["rows"]) == 2 and not page2["more"] and len(page2["rows"]) == 1


async def test_removed_questions_keep_their_column(fc):
    fc.env.session.add(FormSubmission(form_id=fc.form.id, bot_id=fc.env.bot.id, tg_user_id=1, full_name="Old",
                                      answers=answers("Old", "30", "IT") + [{"label": "Eski savol", "type": "text", "value": "bor edi"}]))
    await fc.env.session.commit()
    data = (await fc.get(f"/api/v1/forms/{fc.form.id}/responses", headers=fc.hdr)).json()
    assert data["columns"][-1]["label"] == "Eski savol" and data["rows"][0]["cells"]["Eski savol"] == "bor edi"


async def test_other_owners_cannot_read(fc):
    other = {"Authorization": f"tma {sign(4242)}"}
    assert (await fc.get(f"/api/v1/forms/{fc.form.id}/responses", headers=other)).status_code == 404
    assert (await fc.get(f"/api/v1/forms/{fc.form.id}/export.xlsx", headers=other)).status_code == 404
    assert (await fc.get(f"/api/v1/forms/{fc.form.id}/responses")).status_code == 401


async def test_excel_export_is_a_real_workbook(fc):
    assert (await fc.get(f"/api/v1/forms/{fc.form.id}/export.xlsx", headers=fc.hdr)).status_code == 409  # nothing yet
    await add_subs(fc, 3)
    fc.env.session.add(FormSubmission(form_id=fc.form.id, bot_id=fc.env.bot.id, tg_user_id=9, username=None, full_name="=cmd|' /C calc'!A0",
                                      answers=answers("=1+1", "x", "IT")))
    await fc.env.session.commit()
    res = await fc.get(f"/api/v1/forms/{fc.form.id}/export.xlsx", headers=fc.hdr)
    assert res.status_code == 200 and res.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert 'filename="Ariza_yozgi_kurs_.xlsx"' in res.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(res.content))
    ws = wb.worksheets[0]
    assert ws.title == "Ariza yozgikurs" and ws.freeze_panes == "A2"
    assert [c.value for c in ws[1]] == ["№", "Sana", "Telegram ID", "Username", "Ism", "Ism", "Yosh", "Kurs", "Joy", "Rasm"]
    first = [c.value for c in ws[2]]
    assert first[0] == 1 and first[2] == 100 and first[3] == "@u0" and first[6] == 20 and first[7] == "Ingliz" and first[9] == "📷 rasm"
    assert ws.cell(row=2, column=9).hyperlink.target == "https://maps.google.com/?q=41.3,69.2"
    assert ws.cell(row=2, column=2).number_format == "dd.mm.yyyy hh:mm"
    evil = ws[5]
    assert evil[4].data_type == "s" and evil[5].data_type == "s" and evil[5].value == "=1+1"  # stored as text, never a formula
    assert evil[6].value == "x"  # a bad number stays text
    summary = wb["Xulosa"]
    assert summary["B2"].value == 4
    assert {(r[0].value, r[1].value) for r in summary.iter_rows(min_row=5) if r[0].value} >= {("Kurs", None), ("Ingliz", 2), ("IT", 2)}


def test_workbook_builds_without_answers_and_with_odd_titles():
    wb = load_workbook(io.BytesIO(build_xlsx("[:*?/\\]", [], [])))
    assert wb.worksheets[0].title == "Javoblar"


async def test_photo_is_streamed_from_the_child_bot(fc):
    await add_subs(fc, 1)
    sub = (await fc.get(f"/api/v1/forms/{fc.form.id}/responses", headers=fc.hdr)).json()["rows"][0]["id"]

    class File:
        async def download_as_bytearray(self):
            return bytearray(b"\xff\xd8img")

    seen = []

    async def get_file(file_id):
        seen.append(file_id)
        return File()

    fc.tg.get_file = get_file
    res = await fc.get(f"/api/v1/forms/{fc.form.id}/submissions/{sub}/photo?label=Rasm", headers=fc.hdr)
    assert res.status_code == 200 and res.content == b"\xff\xd8img" and seen == ["PH"]
    assert (await fc.get(f"/api/v1/forms/{fc.form.id}/submissions/{sub}/photo?label=Ism", headers=fc.hdr)).status_code == 404
    assert (await fc.get(f"/api/v1/forms/{fc.form.id}/submissions/999/photo?label=Rasm", headers=fc.hdr)).status_code == 404


async def test_delete_one_response(fc):
    await add_subs(fc, 2)
    rows = (await fc.get(f"/api/v1/forms/{fc.form.id}/responses", headers=fc.hdr)).json()["rows"]
    assert (await fc.delete(f"/api/v1/forms/{fc.form.id}/submissions/{rows[0]['id']}", headers=fc.hdr)).status_code == 204
    assert (await fc.get(f"/api/v1/forms/{fc.form.id}/responses", headers=fc.hdr)).json()["total"] == 1
    other = {"Authorization": f"tma {sign(4242)}"}
    assert (await fc.delete(f"/api/v1/forms/{fc.form.id}/submissions/{rows[1]['id']}", headers=other)).status_code == 404

"""Mini App API: form responses as a searchable table, one response, its photos, Excel export."""
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import String, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.error import TelegramError

from engine.forms_export import EXPORT_LIMIT, build_xlsx, columns_for, row_for
from engine.telegram_client import get_client
from models.forms import FormField, FormSubmission
from models.users import User
from webapp.api import owned_form
from webapp.auth import current_user, get_session

router = APIRouter(prefix="/api/v1", tags=["form-responses"])
PAGE = 30


async def _fields(session, form_id: int) -> list[FormField]:
    return list((await session.execute(
        select(FormField).where(FormField.form_id == form_id).order_by(FormField.position, FormField.id))).scalars())


def _filtered(form_id: int, q: str):
    stmt = select(FormSubmission).where(FormSubmission.form_id == form_id)
    q = q.strip().lstrip("@")
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(FormSubmission.full_name.ilike(like), FormSubmission.username.ilike(like),
                              cast(FormSubmission.tg_user_id, String).like(like), cast(FormSubmission.answers, String).ilike(like)))
    return stmt


@router.get("/forms/{form_id}/responses")
async def responses(form_id: int, q: str = Query("", max_length=60), offset: int = Query(0, ge=0),
                    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    form, _bot = await owned_form(session, user, form_id)
    fields = await _fields(session, form.id)
    total = (await session.execute(select(func.count()).select_from(_filtered(form.id, q).subquery()))).scalar() or 0
    rows = (await session.execute(_filtered(form.id, q).order_by(FormSubmission.id.desc()).offset(offset).limit(PAGE))).scalars().all()
    # columns also cover questions removed from the form later, so old answers stay visible
    columns = columns_for(fields, (await session.execute(
        select(FormSubmission).where(FormSubmission.form_id == form.id).order_by(FormSubmission.id.desc()).limit(200))).scalars().all())
    return {"title": form.title, "total": total, "columns": columns, "rows": [row_for(r, columns) for r in rows],
            "more": offset + PAGE < total}


@router.get("/forms/{form_id}/export.xlsx")
async def export_xlsx(form_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    form, _bot = await owned_form(session, user, form_id)
    fields = await _fields(session, form.id)
    rows = (await session.execute(select(FormSubmission).where(FormSubmission.form_id == form.id)
                                  .order_by(FormSubmission.id).limit(EXPORT_LIMIT))).scalars().all()
    if not rows:
        raise HTTPException(status_code=409, detail="Hali javob yo‘q.")
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", form.title)[:40] or "forma"
    return Response(content=build_xlsx(form.title, fields, list(rows)),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


async def _submission(session, user, form_id: int, sub_id: int):
    form, bot = await owned_form(session, user, form_id)
    sub = (await session.execute(select(FormSubmission).where(FormSubmission.id == sub_id, FormSubmission.form_id == form.id))).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Javob topilmadi.")
    return sub, bot


@router.get("/forms/{form_id}/submissions/{sub_id}/photo")
async def submission_photo(form_id: int, sub_id: int, label: str = Query(max_length=100), user: User = Depends(current_user),
                           session: AsyncSession = Depends(get_session)):
    sub, bot = await _submission(session, user, form_id, sub_id)
    answer = next((a for a in (sub.answers or []) if a["label"] == label and a.get("type") == "photo" and a.get("value")), None)
    if answer is None:
        raise HTTPException(status_code=404, detail="Rasm topilmadi.")
    try:
        file = await (await get_client(bot.plain_token)).get_file(answer["value"])
        data = bytes(await file.download_as_bytearray())
    except TelegramError:
        raise HTTPException(status_code=502, detail="Rasmni Telegramdan olib bo‘lmadi.") from None
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.delete("/forms/{form_id}/submissions/{sub_id}", status_code=204)
async def delete_submission(form_id: int, sub_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    sub, _bot = await _submission(session, user, form_id, sub_id)
    await session.execute(delete(FormSubmission).where(FormSubmission.id == sub.id))
    await session.commit()
    return Response(status_code=204)

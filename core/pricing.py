"""Prices and limits the admins can change without a deploy.

The defaults live in ``core.plans``; an override (stored in ``app_settings``) replaces some of them in place, so
every module that reads ``plans.PLANS`` / ``KIND_PRICES`` / ``DISCOUNT`` sees the change at once.
"""
import copy
from dataclasses import replace

from sqlalchemy import select

from core import plans
from core.logger import get_logger
from models.plans import AppSetting

logger = get_logger("pricing")
KEY = "pricing"
_DEFAULT_PLANS = dict(plans.PLANS)
_DEFAULT_KIND = dict(plans.KIND_PRICES)
_DEFAULT_DISCOUNT = dict(plans.DISCOUNT)

MAX_PRICE = 10_000_000
LIMIT_FIELDS = ("max_bots", "user_cap", "broadcasts")  # None = unlimited


class PricingError(ValueError):
    """An override the admin sent is not acceptable (the message is shown to them)."""


def _int(value, name, low, high, *, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not (low <= value <= high):
        raise PricingError(f"{name}: {low} dan {high} gacha butun son kerak" + (" yoki bo‘sh (cheksiz)." if nullable else "."))
    return value


def validate(data: dict) -> dict:
    """Return a clean override dict or raise PricingError."""
    if not isinstance(data, dict):
        raise PricingError("Noto‘g‘ri so‘rov.")
    out = {"plans": {}, "kind_prices": {}, "discount": {}}
    for code, row in (data.get("plans") or {}).items():
        if code not in plans.PLANS or not isinstance(row, dict):
            raise PricingError(f"Noma’lum tarif: {code}")
        clean = {}
        if "price" in row:
            if code == plans.FREE:
                raise PricingError("Free tarif narxi o‘zgarmaydi.")
            clean["price"] = _int(row["price"], f"{plans.PLANS[code].title} narxi", 1000, MAX_PRICE)
        for f, high in (("max_bots", 1000), ("user_cap", 10_000_000), ("broadcasts", 1000)):
            if f in row:
                clean[f] = _int(row[f], f"{plans.PLANS[code].title}: {f}", 0 if f == "broadcasts" else 1, high, nullable=True)
        out["plans"][code] = clean
    for kind, price in (data.get("kind_prices") or {}).items():
        if kind not in plans.KIND_PRICES:
            raise PricingError(f"Noma’lum rejim: {kind}")
        out["kind_prices"][kind] = _int(price, f"{plans.KIND_TITLES.get(kind, kind)} narxi", 1000, MAX_PRICE)
    for months, off in (data.get("discount") or {}).items():
        if str(months) not in {str(m) for m in plans.MONTH_CHOICES} or int(months) == 1:
            raise PricingError("Chegirma faqat 3 va 12 oy uchun.")
        out["discount"][str(months)] = _int(off, f"{months} oy chegirmasi", 0, 90)
    return out


def apply(override: dict | None) -> None:
    """Reset to the defaults, then lay the override over them. Mutates the dicts in ``core.plans`` in place."""
    override = override or {}
    plans.PLANS.clear()
    plans.PLANS.update(_DEFAULT_PLANS)
    plans.KIND_PRICES.clear()
    plans.KIND_PRICES.update(_DEFAULT_KIND)
    plans.DISCOUNT.clear()
    plans.DISCOUNT.update(_DEFAULT_DISCOUNT)
    for code, row in (override.get("plans") or {}).items():
        if code in plans.PLANS and row:
            plans.PLANS[code] = replace(plans.PLANS[code], **{k: v for k, v in row.items() if k == "price" or k in LIMIT_FIELDS})
    for kind, price in (override.get("kind_prices") or {}).items():
        if kind in plans.KIND_PRICES:
            plans.KIND_PRICES[kind] = price
    for months, off in (override.get("discount") or {}).items():
        plans.DISCOUNT[int(months)] = off
    plans.invalidate()


async def load(session) -> None:
    """Read the stored override and apply it (startup). A broken value is ignored, never fatal."""
    row = await session.get(AppSetting, KEY)
    try:
        apply(validate(row.value) if row else None)
    except PricingError:
        logger.exception("Stored pricing override is invalid; using the defaults")
        apply(None)


async def current_override(session) -> dict:
    row = await session.get(AppSetting, KEY)
    return copy.deepcopy(row.value) if row else {"plans": {}, "kind_prices": {}, "discount": {}}


async def save(session, patch: dict) -> dict:
    """Merge an admin's change into the stored override and apply it. Returns the stored override."""
    clean = validate(patch)
    stored = await current_override(session)
    for part in ("plans", "kind_prices", "discount"):
        stored.setdefault(part, {})
    for code, row in clean["plans"].items():
        stored["plans"].setdefault(code, {}).update(row)
    stored["kind_prices"].update(clean["kind_prices"])
    stored["discount"].update(clean["discount"])
    row = await session.get(AppSetting, KEY)
    if row is None:
        session.add(AppSetting(key=KEY, value=stored))
    else:
        row.value = stored
    await session.commit()
    apply(stored)
    return stored


async def reset(session) -> None:
    row = await session.get(AppSetting, KEY)
    if row is not None:
        await session.delete(row)
        await session.commit()
    apply(None)


def table() -> dict:
    """Current and default values for the admin screen."""
    def plan_row(code):
        cur, base = plans.PLANS[code], _DEFAULT_PLANS[code]
        return {"code": code, "title": cur.title, "editable_price": code != plans.FREE,
                **{f: getattr(cur, f) for f in ("price", *LIMIT_FIELDS)}, "default": {f: getattr(base, f) for f in ("price", *LIMIT_FIELDS)}}
    return {"plans": [plan_row(c) for c in (plans.FREE, *plans.PAID_PLANS)],
            "kind_prices": [{"kind": k, "title": plans.KIND_TITLES.get(k, k), "price": plans.KIND_PRICES[k], "default": _DEFAULT_KIND[k]} for k in _DEFAULT_KIND],
            "discount": {str(m): plans.DISCOUNT[m] for m in plans.MONTH_CHOICES if m != 1}, "discount_default": {str(m): _DEFAULT_DISCOUNT[m] for m in plans.MONTH_CHOICES if m != 1}}

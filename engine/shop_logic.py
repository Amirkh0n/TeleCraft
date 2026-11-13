"""Pure rules of the shop bot: money formatting, variant parsing, prices, delivery fee."""
import re

MAX_VARIANTS = 30


def fmt_money(n: int) -> str:
    return f"{int(n):,}".replace(",", " ") + " so‘m"


def parse_int(text: str, *, minimum: int = 0, maximum: int = 2_000_000_000) -> int:
    """'1 500 000' / '1,500,000' -> 1500000. Raises ValueError with a user-facing message."""
    digits = re.sub(r"[\s,._]", "", (text or "").strip())
    if not digits.isdigit() or not minimum <= int(digits) <= maximum:
        raise ValueError(f"Raqam yuboring ({minimum} dan {maximum} gacha).")
    return int(digits)


def parse_variants(text: str):
    """Lines like ``XL | 120000 | 5`` (price and stock optional; ``-`` = default / unlimited).

    Returns (variants, errors): variants = [(name, price|None, stock|None)], errors = ["2-qator: ..."].
    """
    variants, errors = [], []
    for number, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        name = parts[0]
        if not name or len(name) > 80:
            errors.append(f"{number}-qator: nom 1–80 belgi bo‘lsin")
            continue
        try:
            price = None if len(parts) < 2 or parts[1] in ("", "-") else parse_int(parts[1], minimum=1)
            stock = None if len(parts) < 3 or parts[2] in ("", "-") else parse_int(parts[2], maximum=1_000_000)
        except ValueError:
            errors.append(f"{number}-qator: narx/qoldiq noto‘g‘ri")
            continue
        if len(parts) > 3:
            errors.append(f"{number}-qator: ortiqcha qism")
            continue
        variants.append((name, price, stock))
    if len(variants) > MAX_VARIANTS:
        errors.append(f"Variantlar {MAX_VARIANTS} tadan oshmasin")
        variants = variants[:MAX_VARIANTS]
    return variants, errors


def unit_price(product, variant=None) -> int:
    return variant.price if variant is not None and variant.price else product.price


def discount_percent(product) -> int:
    old = product.old_price or 0
    if old <= product.price or old <= 0:
        return 0
    return round((old - product.price) * 100 / old)


def available(product, variant=None):
    """Units that can still be bought; ``None`` means unlimited."""
    return variant.stock if variant is not None else product.stock


def delivery_cost(delivery_type: str, subtotal: int, *, fee: int, free_from) -> int:
    if delivery_type != "delivery" or fee <= 0:
        return 0
    if free_from and subtotal >= free_from:
        return 0
    return fee


def stock_label(stock) -> str:
    if stock is None:
        return "✅ Mavjud"
    if stock <= 0:
        return "❌ Tugagan"
    return f"✅ Mavjud ({stock} ta)" if stock <= 5 else "✅ Mavjud"

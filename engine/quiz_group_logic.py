"""Pure scoring and ranking rules of group quiz games."""

BASE_POINTS = 1000
SPEED_BONUS = 500
MEDALS = ["🥇", "🥈", "🥉"]


def points(ok: bool, elapsed_ms: int, limit_ms: int) -> int:
    """A correct answer is worth 1000 plus up to 500 for speed (linear over the question's time)."""
    if not ok:
        return 0
    limit_ms = max(1, limit_ms)
    elapsed = min(max(0, elapsed_ms), limit_ms)
    return BASE_POINTS + round(SPEED_BONUS * (1 - elapsed / limit_ms))


def rank(rows):
    """rows: iterable of (user_id, name, points, correct, answered, correct_ms).

    Highest points first; a tie goes to the one who answered correctly in less total time, then to
    more correct answers, then by name for a stable order.
    """
    return sorted(rows, key=lambda r: (-r[2], r[5], -r[3], r[1].lower(), r[0]))


def medal(position: int) -> str:
    return MEDALS[position] if position < len(MEDALS) else f"{position + 1}."


def fmt_points(n: int) -> str:
    return f"{n:,}".replace(",", " ")

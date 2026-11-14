from engine import quiz_group_logic as gl


def test_points():
    assert gl.points(False, 100, 30000) == 0
    assert gl.points(True, 0, 30000) == 1500
    assert gl.points(True, 15000, 30000) == 1250
    assert gl.points(True, 30000, 30000) == 1000
    assert gl.points(True, 99999, 30000) == 1000  # late/clamped
    assert gl.points(True, -5, 30000) == 1500
    assert gl.points(True, 10, 0) >= 1000


def test_rank_by_points_then_time_then_correct_then_name():
    rows = [(1, "Bob", 2000, 2, 2, 9000), (2, "Ann", 2000, 2, 2, 5000), (3, "Cy", 3000, 3, 3, 20000),
            (4, "Dan", 2000, 2, 2, 5000), (5, "Eve", 0, 0, 1, 0)]
    assert [r[1] for r in gl.rank(rows)] == ["Cy", "Ann", "Dan", "Bob", "Eve"]


def test_medals_and_format():
    assert [gl.medal(i) for i in range(4)] == ["🥇", "🥈", "🥉", "4."]
    assert gl.fmt_points(12500) == "12 500"

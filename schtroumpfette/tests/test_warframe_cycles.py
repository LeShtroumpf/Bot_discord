import datetime as dt

from warframe import cycles

END = dt.datetime(2026, 11, 1, 16, 10, 40, tzinfo=dt.UTC)  # fin d'un cycle de primes d'Ostron


def test_cetus_day_then_night():
    day = cycles.cetus(END, END - dt.timedelta(minutes=60))
    assert (day.state, day.ends_at, day.next_state) == ("jour", END - dt.timedelta(minutes=50), "nuit")
    night = cycles.cetus(END, END - dt.timedelta(minutes=10))
    assert (night.state, night.ends_at) == ("nuit", END)


def test_cetus_extrapolates_past_bounty_end():
    """Worldstate périmé : le cycle étant fixe, on continue à le calculer."""
    later = cycles.cetus(END, END + dt.timedelta(minutes=5))
    assert later.state == "jour"
    assert later.ends_at == END + dt.timedelta(minutes=100)
    much_later = cycles.cetus(END, END + dt.timedelta(minutes=150 * 3 + 120))
    assert much_later.state == "nuit"


def test_cambion_follows_cetus():
    assert cycles.cambion(END, END - dt.timedelta(minutes=60)).state == "Fass"
    assert cycles.cambion(END, END - dt.timedelta(minutes=10)).state == "Vome"


def test_circuit_rotation_ends_next_monday():
    monday = dt.datetime(2026, 11, 9, tzinfo=dt.UTC)
    assert cycles.circuit_rotation_end(dt.datetime(2026, 11, 5, 8, 0, tzinfo=dt.UTC)) == monday
    assert cycles.circuit_rotation_end(monday - dt.timedelta(seconds=1)) == monday
    assert cycles.circuit_rotation_end(monday) == monday + dt.timedelta(days=7)  # juste après le changement


def test_vallis():
    ref = cycles.VALLIS_REFERENCE
    warm = cycles.vallis(ref + dt.timedelta(seconds=10))
    assert (warm.state, warm.ends_at) == ("chaud", ref + dt.timedelta(seconds=400))
    cold = cycles.vallis(ref + dt.timedelta(seconds=500))
    assert (cold.state, cold.ends_at) == ("froid", ref + dt.timedelta(seconds=1600))


def test_vallis_matches_warframestat():
    """warframestat donnait chaud jusqu'à 15:26:48 UTC le 01/11/2026 : on tolère 30 s d'écart."""
    expected = dt.datetime(2026, 11, 1, 15, 26, 48, tzinfo=dt.UTC)
    cycle = cycles.vallis(dt.datetime(2026, 11, 1, 15, 24, tzinfo=dt.UTC))
    assert cycle.state == "chaud"
    assert abs((cycle.ends_at - expected).total_seconds()) <= 30


def test_bounty_end_from_worldstate(worldstate):
    assert cycles.cetus_bounty_end(worldstate) is not None
    assert cycles.cetus_bounty_end(None) is None
    assert cycles.cetus_bounty_end({"syndicateMissions": []}) is None

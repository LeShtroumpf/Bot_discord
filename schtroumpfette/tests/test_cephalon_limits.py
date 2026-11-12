import datetime as dt
import json

import pytest

from cephalon.config import Config
from cephalon.limits import BUDGET, BUILD, COOLDOWN, PRICES, QUOTA, Limits, StateError, cost
from cephalon.llm import Usage

CONFIG = Config()
NOON = dt.datetime(2026, 11, 11, 11, 0, tzinfo=dt.UTC)  # midi à Paris
QUESTION = Usage(input=1000, output=1000)               # 0,0006 $ sur Haiku


def answered(limits, user=1, usage=QUESTION, config=CONFIG, now=NOON, model="claude-haiku-5-5"):
    return limits.record(user, model, usage, True, config, now)


# --- Coût ---------------------------------------------------------------------------------------------------

def test_cost_prices_each_kind_of_token():
    usage = Usage(input=1_000_000, output=2_000_000, cache_write=4_000_000, cache_read=8_000_000)
    assert cost("claude-haiku-5-5", usage) == (pytest.approx(0.10 + 1.0 + 0.5 + 0.08), True)
    assert cost("claude-sonnet-5-5", usage) == (pytest.approx(2 + 20 + 10 + 0.8), True)


def test_unknown_model_costs_the_highest_price():
    dollars, known = cost("claude-futur-9", Usage(input=1_000_000, output=1_000_000, cache_write=1_000_000, cache_read=1_000_000))
    assert known is False
    assert dollars == pytest.approx(sum(max(price[index] for price in PRICES.values()) for index in range(4)))


# --- Cooldown -----------------------------------------------------------------------------------------------

def test_cooldown(limits, clock):
    assert limits.check(1, CONFIG, NOON) is None
    clock.advance(17.2)
    refusal = limits.check(1, CONFIG, NOON)
    assert (refusal.kind, refusal.seconds) == (COOLDOWN, 13)  # arrondi au-dessus
    assert limits.check(2, CONFIG, NOON) is None              # un autre joueur n'est pas concerné
    clock.advance(12.8)
    assert limits.check(1, CONFIG, NOON) is None
    assert limits.check(1, CONFIG, NOON).seconds == 30        # la question acceptée a repris le cooldown


def test_two_checks_in_a_row_accept_only_one(limits):
    assert [limits.check(1, CONFIG, NOON) is None for _ in range(2)] == [True, False]


def test_expired_cooldowns_are_dropped_when_too_many(limits, clock, monkeypatch):
    monkeypatch.setattr("cephalon.limits.MAX_COOLDOWNS", 3)
    for user in (1, 2, 3):
        limits.check(user, CONFIG, NOON)
    clock.advance(31)
    limits.check(4, CONFIG, NOON)
    assert list(limits.cooldowns) == [4]


# --- Quota --------------------------------------------------------------------------------------------------

def test_quota(limits, clock):
    config = Config(daily_questions=2)
    assert answered(limits, config=config).remaining == 1
    assert limits.record(1, "claude-haiku-5-5", QUESTION, False, config, NOON).remaining == 1  # sans réponse : pas comptée
    assert answered(limits, config=config).remaining == 0
    assert limits.check(1, config, NOON).kind == QUOTA
    assert limits.check(2, config, NOON) is None
    assert limits.check(1, Config(daily_questions=3), NOON) is None  # quota relevé dans settings.json


def test_quota_restarts_at_midnight_in_paris(limits):
    config = Config(daily_questions=1)
    answered(limits, config=config)
    late = dt.datetime(2026, 11, 11, 22, 59, tzinfo=dt.UTC)  # 23 h 59 à Paris
    assert limits.check(1, config, late).kind == QUOTA
    midnight = dt.datetime(2026, 11, 11, 23, 0, tzinfo=dt.UTC)  # minuit à Paris : déjà le lendemain
    assert limits.check(1, config, midnight) is None
    assert limits.state["day"] == "2026-11-12" and limits.state["questions"] == {}
    assert limits.state["cost_usd"] > 0  # le coût du mois, lui, continue


def test_lowered_quota_refuses_a_player_already_above_it(limits):
    for _ in range(3):
        answered(limits)
    assert limits.check(1, Config(daily_questions=2), NOON).kind == QUOTA


# --- Plafond mensuel ----------------------------------------------------------------------------------------

def test_budget(limits, clock):
    config = Config(monthly_budget=0.001, usd_to_eur=0.9)  # 0,00054 € par question
    assert answered(limits, config=config).spent == pytest.approx(0.00054)
    assert limits.check(2, config, NOON) is None
    answered(limits, config=config)  # 0,00108 € : plafond franchi
    assert limits.check(3, config, NOON).kind == BUDGET
    limits.check(1, Config(), NOON)
    assert limits.check(1, config, NOON).kind == BUDGET  # passe avant le quota et le cooldown
    assert limits.check(3, Config(monthly_budget=0.001, usd_to_eur=0.5), NOON) is None  # 0,0006 € au nouveau taux


def test_budget_restarts_on_the_first_of_the_month_in_paris(limits):
    config = Config(monthly_budget=0.0005)
    assert answered(limits, config=config).alerts == [80, 100]
    last_evening = dt.datetime(2026, 11, 30, 22, 30, tzinfo=dt.UTC)
    assert limits.check(1, config, last_evening).kind == BUDGET
    first = dt.datetime(2026, 11, 30, 23, 0, tzinfo=dt.UTC)  # 1er décembre, minuit à Paris
    assert limits.check(1, config, first) is None
    assert (limits.state["month"], limits.state["cost_usd"], limits.state["alerts"]) == ("2026-12", 0.0, [])
    assert answered(limits, config=config, now=first).alerts == [80, 100]  # de nouveau signalés le mois suivant


def test_alerts_fire_once_each(limits):
    config = Config(monthly_budget=0.0012)  # 45 % par question
    assert [answered(limits, config=config).alerts for _ in range(4)] == [[], [80], [100], []]


# --- Persistance --------------------------------------------------------------------------------------------

def test_state_is_saved_and_read_back(limits, tmp_path, clock):
    answered(limits, user=100000000000000001)
    limits.save()
    assert json.loads(limits.path.read_text(encoding="utf-8")) == {
        "month": "2026-11", "cost_usd": pytest.approx(0.0006), "alerts": [], "day": "2026-11-11",
        "questions": {"100000000000000001": 1}, "builds": {}}
    assert [path.name for path in limits.path.parent.iterdir()] == ["usage.json"]  # pas de fichier temporaire restant
    restarted = Limits(limits.path.parent, clock=clock)
    restarted.load()
    assert restarted.state == limits.state and restarted.cooldowns == {}
    assert answered(restarted, user=100000000000000001).remaining == 18


def test_missing_state_is_a_first_launch(limits):
    limits.load()
    assert limits.state["questions"] == {} and limits.state["cost_usd"] == 0


@pytest.mark.parametrize("content", [
    "{ pas du json", "[]", "{}", '{"month": "2026-11", "cost_usd": "beaucoup", "alerts": [], "day": "2026-11-11", "questions": {}}',
    '{"month": "2026-11", "cost_usd": 1, "alerts": [], "day": "2026-11-11", "questions": {"1": "deux"}}',
    '{"month": "2026-11", "cost_usd": true, "alerts": [], "day": "2026-11-11", "questions": {}}',
])
def test_unreadable_state_raises_and_starts_from_zero(limits, content):
    answered(limits)
    limits.path.parent.mkdir(parents=True)
    limits.path.write_text(content, encoding="utf-8")
    with pytest.raises(StateError):
        limits.load()
    assert limits.state["questions"] == {} and limits.state["cost_usd"] == 0
    assert limits.check(1, CONFIG, NOON) is None  # le bot répond quand même


def test_state_that_is_a_directory_is_unreadable(limits):
    limits.path.mkdir(parents=True)
    with pytest.raises(StateError):
        limits.load()


def test_unknown_alert_thresholds_are_ignored(limits):
    limits.path.parent.mkdir(parents=True)
    limits.path.write_text(json.dumps({"month": "2026-11", "cost_usd": 1, "alerts": [50, 80], "day": "2026-11-11",
                                       "questions": {"7": 4}}), encoding="utf-8")
    limits.load()
    assert limits.state["alerts"] == [80] and limits.state["cost_usd"] == 1.0


# --- Builds (/cephalon_build) -------------------------------------------------------------------------------

def test_builds_have_their_own_quota_and_cooldown(limits, clock):
    config = Config(build_daily=1, build_cooldown=120, daily_questions=2)
    assert limits.check(1, config, NOON, kind=BUILD) is None
    assert limits.check(1, config, NOON) is None                        # le cooldown des builds ne bloque pas les questions
    refusal = limits.check(1, config, NOON, kind=BUILD)
    assert refusal.kind == COOLDOWN and refusal.seconds == 120
    outcome = limits.record(1, "claude-sonnet-5-5", QUESTION, True, config, NOON, kind=BUILD)
    assert outcome.remaining == 0 and limits.state["builds"] == {"1": 1} and limits.state["questions"] == {}
    clock.advance(121)
    assert limits.check(1, config, NOON, kind=BUILD).kind == QUOTA
    assert answered(limits, config=config).remaining == 1                # le quota des questions est intact
    assert limits.check(1, Config(build_daily=2), NOON, kind=BUILD) is None  # quota relevé dans settings.json


def test_unanswered_build_is_not_counted(limits):
    assert limits.record(1, "claude-sonnet-5-5", QUESTION, False, CONFIG, NOON, kind=BUILD).remaining == 1


def test_build_costs_both_calls_in_the_common_budget(limits):
    assert limits.add_cost("claude-sonnet-5-5", Usage(input=1_000_000), NOON) is True  # lecture : 2 $
    assert limits.add_cost("modele-inconnu", Usage(), NOON) is False
    outcome = limits.record(1, "claude-sonnet-5-5", Usage(output=100_000), True, Config(), NOON, kind=BUILD)  # 1 $
    assert limits.state["cost_usd"] == pytest.approx(3.0) and outcome.spent == pytest.approx(2.7)
    assert outcome.alerts == []
    assert limits.check(2, Config(monthly_budget=2.7), NOON, kind=BUILD).kind == BUDGET


def test_builds_reset_at_midnight(limits):
    limits.record(1, "claude-sonnet-5-5", QUESTION, True, CONFIG, NOON, kind=BUILD)
    assert limits.check(1, CONFIG, NOON + dt.timedelta(hours=13), kind=BUILD) is None


def test_old_state_without_builds_is_read(limits):
    limits.path.parent.mkdir(parents=True, exist_ok=True)
    limits.path.write_text(json.dumps({"month": "2026-11", "cost_usd": 1.0, "alerts": [], "day": "2026-11-11",
                                       "questions": {"1": 3}}), encoding="utf-8")
    limits.load()
    assert limits.state["builds"] == {} and limits.state["questions"] == {"1": 3}
    limits.path.write_text(json.dumps({"month": "2026-11", "cost_usd": 1.0, "alerts": [], "day": "2026-11-11",
                                       "questions": {}, "builds": {"1": "x"}}), encoding="utf-8")
    with pytest.raises(StateError):
        limits.load()

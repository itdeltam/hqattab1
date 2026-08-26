"""Stage 9 closed a gap flagged since Stage 1: LIVE mode's confirmation
banner used to always show account_snapshot=None (-> "UNKNOWN" placeholders)
because no broker adapter existed yet to ask. Now that one exists, LIVE
startup must fetch real numbers before ever showing the banner, and must
abort -- before the operator is even asked to confirm -- if it can't.

Stage 11 added the full scheduling loop behind `run()`. Every test here
patches `main_module.run` to a stub: `run()` builds a real scheduler and
blocks forever, so it must never actually execute inside a test.
"""
import app.main as main_module
from app.broker.models import AccountSnapshot
from app.config import TradingMode


class FakeBroker:
    def __init__(self, account=None, raise_exc=None):
        self._account = account
        self._raise_exc = raise_exc

    def get_account(self):
        if self._raise_exc:
            raise self._raise_exc
        return self._account


def test_live_mode_aborts_before_confirmation_if_broker_unreachable(make_settings, monkeypatch):
    settings = make_settings(trading_mode=TradingMode.LIVE)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "build_alpaca_broker", lambda s: FakeBroker(raise_exc=ConnectionError("down")))
    calls = []
    monkeypatch.setattr(main_module, "enforce_mode_safety", lambda *a, **k: calls.append((a, k)))

    def boom_run(_settings):
        raise AssertionError("must not reach the trading loop if the broker is unreachable")

    monkeypatch.setattr(main_module, "run", boom_run)

    result = main_module.main()

    assert result == 1
    assert calls == []  # never reached the confirmation gate at all


def test_live_mode_passes_real_account_snapshot_to_confirmation_gate(make_settings, monkeypatch):
    settings = make_settings(trading_mode=TradingMode.LIVE)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    account = AccountSnapshot(cash=50_000.0, equity=52_000.0, buying_power=50_000.0, account_id="ACC-9")
    monkeypatch.setattr(main_module, "build_alpaca_broker", lambda s: FakeBroker(account=account))

    captured = {}

    def fake_enforce(settings_arg, account_snapshot=None, **kwargs):
        captured["snapshot"] = account_snapshot

    monkeypatch.setattr(main_module, "enforce_mode_safety", fake_enforce)

    run_calls = []
    monkeypatch.setattr(main_module, "run", lambda s: run_calls.append(s) or 0)

    result = main_module.main()

    assert result == 0
    assert captured["snapshot"] == {"account_id": "ACC-9", "equity": 52_000.0, "buying_power": 50_000.0}
    assert run_calls == [settings]  # confirmed LIVE startup proceeds to the trading loop


def test_live_mode_never_reaches_run_when_confirmation_is_refused(make_settings, monkeypatch):
    settings = make_settings(trading_mode=TradingMode.LIVE)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    account = AccountSnapshot(cash=50_000.0, equity=52_000.0, buying_power=50_000.0, account_id="ACC-9")
    monkeypatch.setattr(main_module, "build_alpaca_broker", lambda s: FakeBroker(account=account))

    from app.startup import LiveTradingNotConfirmed

    def fake_refuse(*_args, **_kwargs):
        raise LiveTradingNotConfirmed("not confirmed")

    monkeypatch.setattr(main_module, "enforce_mode_safety", fake_refuse)

    def boom_run(_settings):
        raise AssertionError("must not reach the trading loop without a confirmed LIVE startup")

    monkeypatch.setattr(main_module, "run", boom_run)

    result = main_module.main()

    assert result == 1


def test_paper_mode_proceeds_directly_to_the_trading_loop(make_settings, monkeypatch):
    """PAPER/APPROVAL never show a confirmation banner, so they never need
    to fetch an account snapshot in main() itself -- but Stage 11 means
    they must still reach run() to actually start trading."""
    settings = make_settings(trading_mode=TradingMode.PAPER)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    def boom_broker(_settings):
        raise AssertionError("must not build a broker for the LIVE-only confirmation banner outside LIVE mode")

    monkeypatch.setattr(main_module, "build_alpaca_broker", boom_broker)

    run_calls = []
    monkeypatch.setattr(main_module, "run", lambda s: run_calls.append(s) or 0)

    result = main_module.main()

    assert result == 0
    assert run_calls == [settings]

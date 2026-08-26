from app.market_data.live_price_cache import LivePriceCache


def test_get_returns_none_before_any_update():
    cache = LivePriceCache()
    assert cache.get("AAA") is None


def test_update_then_get_returns_the_latest_price():
    cache = LivePriceCache()
    cache.update({"AAA": 100.0, "BBB": 50.0})
    assert cache.get("AAA") == 100.0
    assert cache.get("BBB") == 50.0


def test_a_later_update_fully_replaces_the_previous_snapshot():
    """Not a merge -- a symbol missing from a later update must go back to
    unknown (None), not silently keep serving a stale price from before."""
    cache = LivePriceCache()
    cache.update({"AAA": 100.0, "BBB": 50.0})
    cache.update({"AAA": 105.0})

    assert cache.get("AAA") == 105.0
    assert cache.get("BBB") is None

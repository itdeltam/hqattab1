"""Route-level tests for the Stage 7 dashboard. The flagship test here is
test_every_route_is_read_only: it inspects the actual FastAPI route table
and asserts nothing but GET (and the framework-added HEAD/OPTIONS) is
ever allowed, anywhere in the app -- mechanical proof of "read-only,"
matching the pattern of every other stage's non-negotiable-rule test.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from app.database.models import OrderRecord, PositionRecord
from app.database.repository import record_equity_snapshot
from app.database.session import create_db_engine, make_session_factory
from app.web.dependencies import get_session
from app.web.main import app

NOW = datetime(2024, 1, 2, 9, 30)


@pytest.fixture
def session_factory():
    # StaticPool: TestClient dispatches sync routes to a worker thread, and
    # a plain sqlite:///:memory: engine gives each new connection/thread its
    # own empty database -- see app/database/session.py's docstring.
    engine = create_db_engine("sqlite:///:memory:", poolclass=StaticPool)
    return make_session_factory(engine)


@pytest.fixture
def client(session_factory):
    def override_get_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def seed(session_factory, with_data: bool):
    with session_factory() as session:
        if with_data:
            record_equity_snapshot(session, NOW, equity=100_000, cash=90_000)
            session.add(PositionRecord(symbol="AAA", qty=10, avg_entry_price=100.0, updated_at=NOW))
            session.add(OrderRecord(
                id="o1", symbol="AAA", side="buy", qty=10, status="filled",
                submitted_at=NOW, filled_qty=10, avg_fill_price=100.0, updated_at=NOW,
            ))
            session.commit()


def test_every_route_is_read_only(client):
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if methods is None:
            continue
        disallowed = methods - {"GET", "HEAD", "OPTIONS"}
        assert not disallowed, (
            f"Route {getattr(route, 'path', route)} allows {disallowed} -- "
            "the dashboard must be read-only, no exceptions."
        )


def test_dashboard_renders_on_empty_database(session_factory, client):
    seed(session_factory, with_data=False)

    response = client.get("/")

    assert response.status_code == 200
    assert "No open positions" in response.text
    assert "No orders submitted yet" in response.text
    assert "No equity snapshot recorded yet" in response.text
    assert "No activity recorded yet" in response.text


def test_dashboard_renders_with_data(session_factory, client):
    seed(session_factory, with_data=True)

    response = client.get("/")

    assert response.status_code == 200
    assert "AAA" in response.text
    assert "100000.00" in response.text or "100,000.00" in response.text or "$100000.00" in response.text


def test_dashboard_shows_current_trading_mode(client):
    response = client.get("/")
    assert "PAPER" in response.text  # default mode with no env override


def test_partial_positions_endpoint(session_factory, client):
    seed(session_factory, with_data=True)
    response = client.get("/partials/positions")
    assert response.status_code == 200
    assert "AAA" in response.text


def test_partial_orders_endpoint(session_factory, client):
    seed(session_factory, with_data=True)
    response = client.get("/partials/orders")
    assert response.status_code == 200
    assert "filled" in response.text


def test_partial_account_endpoint(session_factory, client):
    seed(session_factory, with_data=True)
    response = client.get("/partials/account")
    assert response.status_code == 200


def test_partial_system_endpoint(session_factory, client):
    seed(session_factory, with_data=True)
    response = client.get("/partials/system")
    assert response.status_code == 200
    assert "ACTIVE" in response.text or "STALE" in response.text


def test_dashboard_shows_risk_limits_and_strategy_params(client):
    response = client.get("/")
    assert "Risk Limits" in response.text
    assert "Strategy Parameters" in response.text


def test_post_to_root_is_not_allowed(client):
    response = client.post("/")
    assert response.status_code == 405

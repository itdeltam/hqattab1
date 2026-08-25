"""Read-only dashboard. Every route in this file is a GET -- there is no
POST/PUT/PATCH/DELETE anywhere, deliberately: nothing here can place,
cancel, or modify a trade, change a risk limit, or touch the trading
mode. tests/test_web_routes.py enforces this mechanically by inspecting
the actual route table, not just by convention.

Runs as its own process, separate from the Trading Engine, reading only
the shared SQLite database (see app/web/dependencies.py).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.risk.config import load_risk_limits
from app.strategy.params import StrategyParams
from app.web.data import get_account_summary, get_positions_view, get_recent_orders, get_system_status
from app.web.dependencies import get_session

app = FastAPI(title="Trading Bot Dashboard")

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


@app.get("/")
def dashboard(request: Request, session: Session = Depends(get_session)):
    settings = get_settings()
    now = datetime.now()
    return templates.TemplateResponse(request, "dashboard.html", {
        "status": get_system_status(session, settings.trading_mode.value, now),
        "account": get_account_summary(session),
        "positions": get_positions_view(session),
        "orders": get_recent_orders(session),
        "limits": load_risk_limits(settings),
        "params": StrategyParams(),
    })


@app.get("/partials/system")
def partial_system(request: Request, session: Session = Depends(get_session)):
    settings = get_settings()
    status = get_system_status(session, settings.trading_mode.value, datetime.now())
    return templates.TemplateResponse(request, "partials/system.html", {"status": status})


@app.get("/partials/account")
def partial_account(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/account.html", {"account": get_account_summary(session)})


@app.get("/partials/positions")
def partial_positions(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/positions.html", {"positions": get_positions_view(session)})


@app.get("/partials/orders")
def partial_orders(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/orders.html", {"orders": get_recent_orders(session)})

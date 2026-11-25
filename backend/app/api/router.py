"""Versioned API router. Routes are added as their shapes are agreed in
contracts/openapi.yaml."""

from fastapi import APIRouter

from app.api.routes import (
    agents,
    alerts,
    auth,
    backtests,
    brokers,
    market,
    paper,
    reports,
    settings,
    strategies,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(settings.router)
api_router.include_router(market.router)
api_router.include_router(brokers.router)
api_router.include_router(strategies.router)
api_router.include_router(backtests.router)
api_router.include_router(paper.router)
api_router.include_router(reports.router)
api_router.include_router(agents.router)
api_router.include_router(alerts.router)

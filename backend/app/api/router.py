"""Versioned API router. Routes are added as their shapes are agreed in
contracts/openapi.yaml."""

from fastapi import APIRouter

from app.api.routes import auth, brokers, market, strategies

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(market.router)
api_router.include_router(brokers.router)
api_router.include_router(strategies.router)

"""Versioned API router. Routes are added as their shapes are agreed in
contracts/openapi.yaml."""

from fastapi import APIRouter

from app.api.routes import auth

api_router = APIRouter()
api_router.include_router(auth.router)

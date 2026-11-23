"""Versioned API router. Business endpoints will be added here once their
shapes are agreed in contracts/openapi.yaml."""

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")

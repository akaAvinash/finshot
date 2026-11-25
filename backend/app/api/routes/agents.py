"""/api/v1/agents endpoints, as specified in contracts/openapi.yaml.

Read-only: every endpoint is GET, needs a valid session and no CSRF token.
Agent output is advisory; nothing here can reach the paper engine."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.agents.schemas import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    AgentEventPageOut,
    AgentHealthReportOut,
    AgentId,
    AgentRosterOut,
)
from app.agents.service import AgentService
from app.api.routes.auth import RequiredSession

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def get_agents(request: Request) -> AgentService:
    service: AgentService = request.app.state.agents
    return service


Agents = Annotated[AgentService, Depends(get_agents)]

_ERRORS: dict[int | str, dict[str, str]] = {
    401: {"description": "No valid session."},
    503: {"description": "Unavailable."},
}


@router.get("", response_model=AgentRosterOut, operation_id="listAgents", responses=_ERRORS)
async def list_agents(session: RequiredSession, agents: Agents) -> AgentRosterOut:
    return agents.roster()


@router.get(
    "/health",
    response_model=AgentHealthReportOut,
    operation_id="getAgentHealth",
    responses=_ERRORS,
)
async def get_agent_health(session: RequiredSession, agents: Agents) -> AgentHealthReportOut:
    return await agents.health(session.user_id)


@router.get(
    "/events",
    response_model=AgentEventPageOut,
    operation_id="listAgentEvents",
    responses={400: {"description": "Invalid query parameters."}, **_ERRORS},
)
async def list_agent_events(
    session: RequiredSession,
    agents: Agents,
    agent_id: Annotated[AgentId | None, Query(alias="agentId")] = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> AgentEventPageOut:
    return await agents.events(session.user_id, agent_id, cursor, limit)

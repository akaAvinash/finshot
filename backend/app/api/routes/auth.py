"""/api/v1/auth/* endpoints, as specified in contracts/openapi.yaml."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.auth.cookies import CSRF_COOKIE, SESSION_COOKIE, clear_cookie, set_cookie
from app.auth.otp import mask_phone
from app.auth.schemas import (
    AuthSessionOut,
    AuthUserOut,
    CsrfTokenOut,
    OtpChallengeOut,
    OtpRequest,
    OtpVerify,
    OtpVerifyResponse,
    SessionExpiryOut,
    SessionListOut,
    SessionSummaryOut,
)
from app.auth.service import AuthService, SessionInfo
from app.core.errors import ApiError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def get_auth(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


Auth = Annotated[AuthService, Depends(get_auth)]


async def optional_session(request: Request, auth: Auth) -> SessionInfo | None:
    return await auth.resolve_session(request.cookies.get(SESSION_COOKIE))


async def required_session(
    session: Annotated[SessionInfo | None, Depends(optional_session)],
) -> SessionInfo:
    if session is None:
        raise ApiError(401, "UNAUTHENTICATED", "Sign in to continue.")
    return session


OptionalSession = Annotated[SessionInfo | None, Depends(optional_session)]
RequiredSession = Annotated[SessionInfo, Depends(required_session)]


def _user_out(info: SessionInfo) -> AuthUserOut:
    return AuthUserOut(
        id=info.user_id,
        phone_masked=mask_phone(info.phone_e164),
        display_name=info.display_name,
        created_at=info.user_created_at,
    )


def _session_out(auth: AuthService, info: SessionInfo) -> SessionExpiryOut:
    return SessionExpiryOut(idle_expires_at=auth.idle_expires_at(info), expires_at=info.expires_at)


@router.get("/csrf", response_model=CsrfTokenOut)
async def get_csrf(request: Request, response: Response, auth: Auth) -> CsrfTokenOut:
    claims, token, issued, clear_stale_session = await auth.csrf_for_request(request)
    # Separate Set-Cookie fields, in this order: clear stale session, set CSRF.
    if clear_stale_session:
        clear_cookie(response, SESSION_COOKIE)
    if issued:
        set_cookie(response, CSRF_COOKIE, token)
    return CsrfTokenOut(csrf_token=token, context=claims.context, expires_at=claims.expires_at)


@router.post("/otp/request", response_model=OtpChallengeOut, status_code=status.HTTP_202_ACCEPTED)
async def request_otp(
    body: OtpRequest, request: Request, auth: Auth, session: OptionalSession
) -> OtpChallengeOut:
    claims = auth.enforce_csrf(request, session)
    challenge_id, expires_at, resend_at = await auth.request_otp(
        request=request, phone=body.phone, context_id=claims.context_id
    )
    return OtpChallengeOut(
        challenge_id=challenge_id, expires_at=expires_at, resend_available_at=resend_at
    )


@router.post("/otp/verify", response_model=OtpVerifyResponse)
async def verify_otp(
    body: OtpVerify, request: Request, response: Response, auth: Auth, session: OptionalSession
) -> OtpVerifyResponse:
    claims = auth.enforce_csrf(request, session)
    info, token, csrf = await auth.verify_otp(
        request=request,
        challenge_id=body.challenge_id,
        code=body.code,
        context_id=claims.context_id,
        current_session=session,
    )
    set_cookie(response, SESSION_COOKIE, token)
    set_cookie(response, CSRF_COOKIE, csrf)
    return OtpVerifyResponse(
        user=_user_out(info), session=_session_out(auth, info), csrf_token=csrf
    )


@router.get("/me", response_model=AuthSessionOut)
async def me(auth: Auth, session: RequiredSession) -> AuthSessionOut:
    return AuthSessionOut(user=_user_out(session), session=_session_out(auth, session))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, auth: Auth, session: OptionalSession) -> Response:
    auth.enforce_csrf(request, session)
    if session is not None:
        await auth.revoke_session(session, request=request)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_cookie(response, SESSION_COOKIE)
    clear_cookie(response, CSRF_COOKIE)
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(request: Request, auth: Auth, session: RequiredSession) -> Response:
    # RequiredSession runs first, so a missing or stale session is 401, not 403.
    auth.enforce_csrf(request, session)
    await auth.revoke_all_sessions(session, request=request)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_cookie(response, SESSION_COOKIE)
    clear_cookie(response, CSRF_COOKIE)
    return response


@router.get("/sessions", response_model=SessionListOut)
async def list_sessions(auth: Auth, session: RequiredSession) -> SessionListOut:
    rows = await auth.list_sessions(session)
    return SessionListOut(
        sessions=[
            SessionSummaryOut(
                id=row.id,
                device_label=row.device_label,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                expires_at=row.expires_at,
                current=current,
            )
            for row, current in rows
        ]
    )

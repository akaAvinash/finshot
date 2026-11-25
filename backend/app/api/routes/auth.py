"""/api/v1/auth/* endpoints, as specified in contracts/openapi.yaml."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response, status

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
    RecoveryCodesOut,
    RecoveryLogin,
    SessionExpiryOut,
    SessionListOut,
    SessionSummaryOut,
    StepUpResultOut,
    TotpCodeIn,
    TotpEnrollmentOut,
    TotpLogin,
)
from app.auth.service import AuthService, SessionInfo, totp_setup_required
from app.auth.stepup import StepUpService, step_up_required
from app.core.errors import ApiError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def get_auth(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


Auth = Annotated[AuthService, Depends(get_auth)]


def get_stepup(request: Request) -> StepUpService:
    service: StepUpService = request.app.state.stepup
    return service


StepUp = Annotated[StepUpService, Depends(get_stepup)]


async def optional_session(request: Request, auth: Auth) -> SessionInfo | None:
    return await auth.resolve_session(request.cookies.get(SESSION_COOKIE))


async def setup_session(
    session: Annotated[SessionInfo | None, Depends(optional_session)],
) -> SessionInfo:
    """Any valid session, including one whose account has no active
    authenticator yet. Only the operations the contract lists as available
    before setup use this."""
    if session is None:
        raise ApiError(401, "UNAUTHENTICATED", "Sign in to continue.")
    return session


async def required_session(
    session: Annotated[SessionInfo, Depends(setup_session)],
) -> SessionInfo:
    """A valid session whose account has an active authenticator. Checked
    after 401 and before any CSRF check, and changes nothing."""
    if not session.totp_enabled:
        raise totp_setup_required()
    return session


OptionalSession = Annotated[SessionInfo | None, Depends(optional_session)]
SetupSession = Annotated[SessionInfo, Depends(setup_session)]
RequiredSession = Annotated[SessionInfo, Depends(required_session)]


def ensure_stepped_up(auth: AuthService, session: SessionInfo) -> None:
    """Raise 403 STEP_UP_REQUIRED unless the session's step-up window is open.

    Call it after the CSRF check and before changing anything, so the order is
    401, CSRF, step-up."""
    if session.step_up_until is None or session.step_up_until <= auth.clock():
        raise step_up_required()


async def stepped_up_session(session: RequiredSession, auth: Auth) -> SessionInfo:
    """Dependency form of `ensure_stepped_up`, for operations that check CSRF
    in a dependency of their own."""
    ensure_stepped_up(auth, session)
    return session


SteppedUpSession = Annotated[SessionInfo, Depends(stepped_up_session)]


def _user_out(info: SessionInfo) -> AuthUserOut:
    return AuthUserOut(
        id=info.user_id,
        phone_masked=mask_phone(info.phone_e164),
        display_name=info.display_name,
        created_at=info.user_created_at,
        totp_enabled=info.totp_enabled,
    )


def _session_out(auth: AuthService, info: SessionInfo) -> SessionExpiryOut:
    open_until = info.step_up_until
    return SessionExpiryOut(
        idle_expires_at=auth.idle_expires_at(info),
        expires_at=info.expires_at,
        step_up_until=open_until if open_until is not None and open_until > auth.clock() else None,
    )


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
        request=request, phone=body.phone, context_id=claims.context_id, channel=body.channel
    )
    return OtpChallengeOut(
        challenge_id=challenge_id,
        channel=body.channel,
        expires_at=expires_at,
        resend_available_at=resend_at,
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


@router.post("/login/totp", response_model=OtpVerifyResponse)
async def login_with_totp(
    body: TotpLogin, request: Request, response: Response, auth: Auth, session: OptionalSession
) -> OtpVerifyResponse:
    auth.enforce_csrf(request, session)
    info, token, csrf = await auth.login_with_totp(
        request=request, phone=body.phone, code=body.code, current_session=session
    )
    set_cookie(response, SESSION_COOKIE, token)
    set_cookie(response, CSRF_COOKIE, csrf)
    return OtpVerifyResponse(
        user=_user_out(info), session=_session_out(auth, info), csrf_token=csrf
    )


@router.post("/login/recovery", response_model=OtpVerifyResponse)
async def login_with_recovery_code(
    body: RecoveryLogin, request: Request, response: Response, auth: Auth, session: OptionalSession
) -> OtpVerifyResponse:
    auth.enforce_csrf(request, session)
    info, token, csrf = await auth.login_with_recovery_code(
        request=request, phone=body.phone, code=body.recovery_code, current_session=session
    )
    set_cookie(response, SESSION_COOKIE, token)
    set_cookie(response, CSRF_COOKIE, csrf)
    return OtpVerifyResponse(
        user=_user_out(info), session=_session_out(auth, info), csrf_token=csrf
    )


@router.get("/me", response_model=AuthSessionOut)
async def me(auth: Auth, session: SetupSession) -> AuthSessionOut:
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
async def logout_all(request: Request, auth: Auth, session: SetupSession) -> Response:
    # SetupSession runs first, so a missing or stale session is 401, not 403.
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


@router.delete("/sessions/{sessionId}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: Annotated[str, Path(alias="sessionId")],
    request: Request,
    auth: Auth,
    session: RequiredSession,
) -> Response:
    auth.enforce_csrf(request, session)
    ensure_stepped_up(auth, session)
    try:
        target = uuid.UUID(session_id)
    except ValueError:
        raise ApiError(404, "SESSION_NOT_FOUND", "This session was not found.") from None
    await auth.revoke_other_session(session, target)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/totp/enroll", response_model=TotpEnrollmentOut)
async def enroll_totp(
    request: Request, auth: Auth, stepup: StepUp, session: SetupSession
) -> TotpEnrollmentOut:
    auth.enforce_csrf(request, session)
    secret, uri, expires_at = await stepup.enroll(
        user_id=session.user_id,
        session_created_at=session.created_at,
        account=mask_phone(session.phone_e164),
        ip=auth.client_ip(request),
    )
    return TotpEnrollmentOut(secret=secret, otpauth_uri=uri, expires_at=expires_at)


@router.post("/totp/confirm", response_model=StepUpResultOut)
async def confirm_totp(
    body: TotpCodeIn, request: Request, auth: Auth, stepup: StepUp, session: SetupSession
) -> StepUpResultOut:
    auth.enforce_csrf(request, session)
    until = await stepup.confirm(
        user_id=session.user_id,
        session_id=session.session_id,
        code=body.code,
        ip=auth.client_ip(request),
    )
    return StepUpResultOut(step_up_until=until)


@router.post("/step-up", response_model=StepUpResultOut)
async def step_up(
    body: TotpCodeIn, request: Request, auth: Auth, stepup: StepUp, session: RequiredSession
) -> StepUpResultOut:
    auth.enforce_csrf(request, session)
    until = await stepup.step_up(
        user_id=session.user_id,
        session_id=session.session_id,
        code=body.code,
        ip=auth.client_ip(request),
    )
    return StepUpResultOut(step_up_until=until)


@router.post("/totp/recovery-codes", response_model=RecoveryCodesOut)
async def regenerate_recovery_codes(
    request: Request, auth: Auth, stepup: StepUp, session: RequiredSession
) -> RecoveryCodesOut:
    auth.enforce_csrf(request, session)
    ensure_stepped_up(auth, session)
    codes, created_at = await stepup.regenerate_recovery_codes(
        user_id=session.user_id, ip=auth.client_ip(request)
    )
    return RecoveryCodesOut(codes=codes, created_at=created_at)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_totp(
    body: TotpCodeIn, request: Request, auth: Auth, stepup: StepUp, session: RequiredSession
) -> Response:
    auth.enforce_csrf(request, session)
    await stepup.disable(user_id=session.user_id, code=body.code, ip=auth.client_ip(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)

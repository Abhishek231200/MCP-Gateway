"""Auth router — email OTP login, JWT sessions."""

import hashlib
import hmac
import random
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_gateway.config import settings
from mcp_gateway.database import get_db
from mcp_gateway.models.user import User

logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])

_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_HOURS = 24
_OTP_TTL_SECONDS = 300


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=_JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[_JWT_ALGORITHM])


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(auth[7:])
        user_id = payload.get("sub")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ── OTP helpers ───────────────────────────────────────────────────────────────

def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _otp_key(email: str) -> str:
    return f"otp:{email.lower()}"


def _hash_otp(code: str) -> str:
    return hmac.new(settings.secret_key.encode(), code.encode(), hashlib.sha256).hexdigest()


async def _send_otp_email(to_email: str, name: str, code: str) -> bool:
    if not settings.resend_api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": "MCP Gateway <onboarding@resend.dev>",
                    "to": [to_email],
                    "subject": "Your MCP Gateway login code",
                    "html": f"""
                        <div style="font-family:sans-serif;max-width:420px;margin:40px auto">
                          <h2 style="color:#2563eb">MCP Gateway</h2>
                          <p>Hi {name}, here is your one-time login code:</p>
                          <div style="font-size:40px;font-weight:700;letter-spacing:10px;
                                      padding:24px;background:#f1f5f9;border-radius:10px;
                                      text-align:center;margin:24px 0;color:#111">{code}</div>
                          <p style="color:#64748b;font-size:13px">
                            Expires in 5 minutes. Do not share this code.
                          </p>
                        </div>
                    """,
                },
            )
        if resp.status_code >= 400:
            logger.warning("auth.resend_failed", status=resp.status_code)
            return False
        return True
    except Exception as exc:
        logger.warning("auth.resend_error", error=str(exc))
        return False


# ── Schemas ───────────────────────────────────────────────────────────────────

class OTPRequest(BaseModel):
    email: str


class OTPVerify(BaseModel):
    email: str
    code: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/request-otp")
async def request_otp(
    payload: OTPRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = payload.email.lower().strip()
    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Email not registered. Contact your administrator.")

    code = f"{random.randint(0, 999999):06d}"
    r = _redis()
    await r.setex(_otp_key(email), _OTP_TTL_SECONDS, _hash_otp(code))
    await r.aclose()

    sent = await _send_otp_email(user.email, user.name, code)
    logger.info("auth.otp_requested", email=email, sent=sent)

    response: dict = {"message": f"Code sent to {email}"}
    if not sent and settings.environment == "development":
        # Fallback for demo when email delivery is unavailable
        response["dev_code"] = code
        response["note"] = "Email not delivered — use this code for demo"
    return response


@router.post("/verify-otp")
async def verify_otp(
    payload: OTPVerify,
    db: AsyncSession = Depends(get_db),
) -> dict:
    email = payload.email.lower().strip()
    r = _redis()
    stored_hash = await r.get(_otp_key(email))

    if not stored_hash:
        raise HTTPException(status_code=400, detail="Code expired or not requested")

    expected = _hash_otp(payload.code.strip())
    if not hmac.compare_digest(stored_hash, expected):
        raise HTTPException(status_code=400, detail="Incorrect code")

    await r.delete(_otp_key(email))
    await r.aclose()

    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info("auth.login", email=email, role=user.role)
    return {"token": create_token(user), "user": user.to_dict()}


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)) -> dict:
    return user.to_dict()

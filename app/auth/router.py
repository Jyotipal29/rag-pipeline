"""Authentication routes (register, login, OAuth, refresh, password reset)."""

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncDatabase
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import service, email_service
from app.auth.schemas import (
    ErrorResponse,
    ForgotPasswordRequest,
    GoogleAuthResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    TokenRefreshResponse,
    UserSchema,
    VerifyEmailRequest,
)
from app.auth.utils import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    verify_refresh_token,
    verify_refresh_token_hash,
)
from app.config.settings import get_settings
from app.db.mongo import get_db
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


def _user_to_schema(user: dict) -> UserSchema:
    """Convert MongoDB user document to UserSchema."""
    return UserSchema(
        id=str(user["_id"]),
        email=user["email"],
        name=user["name"],
        auth_provider=user.get("auth_provider", "email"),
        is_verified=user.get("is_verified", False),
        created_at=user["created_at"],
        updated_at=user["updated_at"],
    )


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: RegisterRequest,
    db: AsyncDatabase = Depends(get_db),
):
    """Register a new user with email and password."""
    try:
        user = await service.register_user(
            db=db,
            email=request.email,
            password=request.password,
            name=request.name,
            auth_provider="email",
        )

        # Send verification email
        token = user.get("verification_token")
        if token:
            await email_service.send_verification_email(request.email, token)

        return RegisterResponse(
            user=_user_to_schema(user),
            message="Registration successful. Check your email to verify your account.",
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration failed")


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(
    request: LoginRequest,
    db: AsyncDatabase = Depends(get_db),
):
    """Login with email and password."""
    try:
        user = await service.verify_user_password(db, request.email, request.password)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        user_id = str(user["_id"])
        access_token = create_access_token(user_id, request.email)
        refresh_token = create_refresh_token(user_id)

        # Store hashed refresh token in database
        refresh_token_hash = hash_refresh_token(refresh_token)
        await service.update_refresh_token_hash(db, user_id, refresh_token_hash)

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=_user_to_schema(user),
        )

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Login failed")


@router.post("/logout")
async def logout(
    authorization: str | None = None,
    db: AsyncDatabase = Depends(get_db),
):
    """Logout and invalidate refresh token."""
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")

    parts = authorization.split()
    if len(parts) != 2:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")

    from app.auth.utils import verify_access_token

    token = parts[1]
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    await service.invalidate_refresh_token(db, user_id)

    return {"message": "Logged out successfully"}


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh(
    request: dict,
    db: AsyncDatabase = Depends(get_db),
):
    """Refresh access token using refresh token (refresh token rotation)."""
    refresh_token = request.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing refresh_token")

    payload = verify_refresh_token(refresh_token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user_id = payload.get("sub")
    user = await service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    # Verify refresh token hash matches stored hash
    stored_hash = user.get("refresh_token_hash")
    if not stored_hash or not verify_refresh_token_hash(refresh_token, stored_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not valid")

    # Issue new tokens (rotation)
    new_access_token = create_access_token(user_id, user["email"])
    new_refresh_token = create_refresh_token(user_id)

    # Update stored refresh token hash
    new_refresh_token_hash = hash_refresh_token(new_refresh_token)
    await service.update_refresh_token_hash(db, user_id, new_refresh_token_hash)

    return TokenRefreshResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
    )


@router.get("/google", response_model=GoogleAuthResponse)
async def google_auth():
    """Get Google OAuth authorization URL."""
    settings = get_settings()

    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Google OAuth not configured")

    scopes = "openid email profile"
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={settings.google_client_id}&"
        f"redirect_uri={settings.google_redirect_uri}&"
        f"response_type=code&"
        f"scope={scopes}&"
        f"access_type=offline"
    )

    return GoogleAuthResponse(auth_url=auth_url)


@router.get("/google/callback")
async def google_callback(
    code: str,
    db: AsyncDatabase = Depends(get_db),
):
    """Handle Google OAuth callback and issue JWT tokens."""
    settings = get_settings()

    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Google OAuth not configured")

    try:
        import httpx

        # Exchange code for tokens
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=token_data)
            response.raise_for_status()
            tokens = response.json()

        # Fetch user info
        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(userinfo_url, headers=headers)
            response.raise_for_status()
            userinfo = response.json()

        # Create or update user
        user = await service.create_or_update_google_user(
            db=db,
            google_id=userinfo["id"],
            email=userinfo["email"],
            name=userinfo.get("name", userinfo["email"]),
        )

        # Issue JWT tokens
        user_id = str(user["_id"])
        access_token = create_access_token(user_id, user["email"])
        refresh_token = create_refresh_token(user_id)

        # Store hashed refresh token
        refresh_token_hash = hash_refresh_token(refresh_token)
        await service.update_refresh_token_hash(db, user_id, refresh_token_hash)

        # Redirect to frontend with access token
        redirect_url = f"{settings.frontend_url}/auth/callback?token={access_token}&refresh_token={refresh_token}"
        return {"redirect": redirect_url, "access_token": access_token}

    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Google authentication failed")


@router.post("/verify-email")
async def verify_email(
    request: VerifyEmailRequest,
    db: AsyncDatabase = Depends(get_db),
):
    """Verify email with token."""
    success = await service.verify_email(db, request.token)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")

    return {"message": "Email verified successfully"}


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(
    request: ForgotPasswordRequest,
    db: AsyncDatabase = Depends(get_db),
):
    """Request password reset (sends email)."""
    token = await service.set_password_reset_token(db, request.email)

    if token:
        await email_service.send_password_reset_email(request.email, token)

    # Always return success for security (don't reveal if email exists)
    return {"message": "If email exists, password reset link has been sent"}


@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncDatabase = Depends(get_db),
):
    """Reset password with token."""
    success = await service.reset_password(db, request.token, request.new_password)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    return {"message": "Password reset successfully"}

"""Tests for authentication module."""

import pytest
from fastapi import status
from httpx import AsyncClient
from motor.motor_asyncio import AsyncDatabase

from app.auth.service import get_user_by_email, verify_email, set_password_reset_token, reset_password
from app.auth.utils import create_access_token, verify_access_token
from app.db.collections import USERS_COLLECTION
from app.main import app


@pytest.mark.asyncio
class TestAuthSchemas:
    """Test authentication schemas and utilities."""

    def test_create_access_token(self):
        """Test creating an access token."""
        token = create_access_token("user-123", "test@example.com")
        assert token is not None
        assert isinstance(token, str)

    def test_verify_valid_access_token(self):
        """Test verifying a valid access token."""
        token = create_access_token("user-123", "test@example.com")
        payload = verify_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@example.com"
        assert payload["type"] == "access"

    def test_verify_invalid_access_token(self):
        """Test verifying an invalid token."""
        payload = verify_access_token("invalid-token")
        assert payload is None


@pytest.mark.asyncio
class TestAuthRegistration:
    """Test user registration endpoints."""

    async def test_register_success(self, async_client: AsyncClient, test_db: AsyncDatabase):
        """Test successful user registration."""
        response = await async_client.post(
            "/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "password123",
                "name": "New User",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["user"]["email"] == "newuser@example.com"
        assert data["user"]["name"] == "New User"
        assert data["user"]["is_verified"] is False

        # Verify user in database
        user = await get_user_by_email(test_db, "newuser@example.com")
        assert user is not None

    async def test_register_duplicate_email(self, async_client: AsyncClient, test_user_email: str):
        """Test registration with duplicate email."""
        response = await async_client.post(
            "/auth/register",
            json={
                "email": test_user_email,
                "password": "password123",
                "name": "Another User",
            },
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_register_invalid_email(self, async_client: AsyncClient):
        """Test registration with invalid email."""
        response = await async_client.post(
            "/auth/register",
            json={
                "email": "invalid-email",
                "password": "password123",
                "name": "User",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_register_short_password(self, async_client: AsyncClient):
        """Test registration with password too short."""
        response = await async_client.post(
            "/auth/register",
            json={
                "email": "user@example.com",
                "password": "short",
                "name": "User",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
class TestAuthLogin:
    """Test user login endpoints."""

    async def test_login_success(self, async_client: AsyncClient, test_user_verified_creds: dict):
        """Test successful login."""
        response = await async_client.post(
            "/auth/login",
            json={
                "email": test_user_verified_creds["email"],
                "password": test_user_verified_creds["password"],
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == test_user_verified_creds["email"]

    async def test_login_unverified_email(self, async_client: AsyncClient, test_user_email: str):
        """Test login with unverified email."""
        response = await async_client.post(
            "/auth/login",
            json={
                "email": test_user_email,
                "password": "password123",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_login_invalid_password(self, async_client: AsyncClient, test_user_verified_creds: dict):
        """Test login with invalid password."""
        response = await async_client.post(
            "/auth/login",
            json={
                "email": test_user_verified_creds["email"],
                "password": "wrongpassword",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_login_nonexistent_user(self, async_client: AsyncClient):
        """Test login with nonexistent user."""
        response = await async_client.post(
            "/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestAuthRefresh:
    """Test token refresh endpoints."""

    async def test_refresh_success(self, async_client: AsyncClient, test_auth_tokens: dict):
        """Test successful token refresh."""
        response = await async_client.post(
            "/auth/refresh",
            json={"refresh_token": test_auth_tokens["refresh_token"]},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["access_token"] != test_auth_tokens["access_token"]

    async def test_refresh_invalid_token(self, async_client: AsyncClient):
        """Test refresh with invalid token."""
        response = await async_client.post(
            "/auth/refresh",
            json={"refresh_token": "invalid-token"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_refresh_missing_token(self, async_client: AsyncClient):
        """Test refresh without token."""
        response = await async_client.post(
            "/auth/refresh",
            json={},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
class TestAuthLogout:
    """Test logout endpoint."""

    async def test_logout_success(self, async_client: AsyncClient, test_auth_header: dict):
        """Test successful logout."""
        response = await async_client.post("/auth/logout", headers=test_auth_header)

        assert response.status_code == status.HTTP_200_OK

    async def test_logout_invalid_token(self, async_client: AsyncClient):
        """Test logout with invalid token."""
        response = await async_client.post(
            "/auth/logout",
            headers={"Authorization": "Bearer invalid"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestAuthVerifyEmail:
    """Test email verification."""

    async def test_verify_email_success(self, async_client: AsyncClient, test_db: AsyncDatabase):
        """Test successful email verification."""
        # Create unverified user
        response = await async_client.post(
            "/auth/register",
            json={
                "email": "verify@example.com",
                "password": "password123",
                "name": "Verify User",
            },
        )

        # Get verification token
        user = await get_user_by_email(test_db, "verify@example.com")
        token = user.get("verification_token")

        # Verify email
        response = await async_client.post("/auth/verify-email", json={"token": token})

        assert response.status_code == status.HTTP_200_OK

        # Check user is now verified
        user = await get_user_by_email(test_db, "verify@example.com")
        assert user["is_verified"] is True

    async def test_verify_email_invalid_token(self, async_client: AsyncClient):
        """Test email verification with invalid token."""
        response = await async_client.post("/auth/verify-email", json={"token": "invalid"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
class TestAuthPasswordReset:
    """Test password reset flow."""

    async def test_forgot_password_success(self, async_client: AsyncClient):
        """Test forgot password request."""
        response = await async_client.post(
            "/auth/forgot-password",
            json={"email": "test@example.com"},
        )

        # Always returns 200 for security
        assert response.status_code == status.HTTP_200_OK

    async def test_forgot_password_nonexistent(self, async_client: AsyncClient):
        """Test forgot password with nonexistent email."""
        response = await async_client.post(
            "/auth/forgot-password",
            json={"email": "nonexistent@example.com"},
        )

        # Always returns 200 for security
        assert response.status_code == status.HTTP_200_OK

    async def test_reset_password_success(self, async_client: AsyncClient, test_db: AsyncDatabase):
        """Test password reset with valid token."""
        # First, request password reset
        test_email = "reset@example.com"
        await async_client.post(
            "/auth/register",
            json={
                "email": test_email,
                "password": "oldpassword123",
                "name": "Reset User",
            },
        )

        # Verify email first
        user = await get_user_by_email(test_db, test_email)
        await verify_email(test_db, user["verification_token"])

        # Request reset
        await async_client.post(
            "/auth/forgot-password",
            json={"email": test_email},
        )

        # Get reset token
        user = await get_user_by_email(test_db, test_email)
        reset_token = user.get("reset_token")

        # Reset password
        response = await async_client.post(
            "/auth/reset-password",
            json={"token": reset_token, "new_password": "newpassword123"},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify login works with new password
        login_response = await async_client.post(
            "/auth/login",
            json={"email": test_email, "password": "newpassword123"},
        )

        assert login_response.status_code == status.HTTP_200_OK

    async def test_reset_password_invalid_token(self, async_client: AsyncClient):
        """Test password reset with invalid token."""
        response = await async_client.post(
            "/auth/reset-password",
            json={"token": "invalid", "new_password": "newpass123"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
class TestAuthGoogle:
    """Test Google OAuth flow."""

    async def test_google_auth_url(self, async_client: AsyncClient):
        """Test getting Google auth URL."""
        response = await async_client.get("/auth/google")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "auth_url" in data
        assert "accounts.google.com" in data["auth_url"]

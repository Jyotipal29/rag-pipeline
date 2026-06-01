"""Email service using Resend SDK."""

from app.config.settings import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def send_verification_email(email: str, token: str) -> bool:
    """Send email verification link."""
    settings = get_settings()

    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not configured; verification email not sent")
        return False

    try:
        from resend import Resend

        client = Resend(api_key=settings.resend_api_key)

        verification_url = f"{settings.frontend_url}/auth/verify?token={token}"

        html_body = f"""
        <h2>Verify Your Email</h2>
        <p>Click the link below to verify your email address:</p>
        <a href="{verification_url}" style="padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">
            Verify Email
        </a>
        <p>This link expires in 24 hours.</p>
        """

        response = client.emails.send(
            {
                "from": settings.email_from,
                "to": email,
                "subject": "Verify your DocMind account",
                "html": html_body,
            }
        )

        logger.info(f"Verification email sent to {email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send verification email to {email}: {e}")
        return False


async def send_password_reset_email(email: str, token: str) -> bool:
    """Send password reset link."""
    settings = get_settings()

    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not configured; reset email not sent")
        return False

    try:
        from resend import Resend

        client = Resend(api_key=settings.resend_api_key)

        reset_url = f"{settings.frontend_url}/auth/reset?token={token}"

        html_body = f"""
        <h2>Reset Your Password</h2>
        <p>Click the link below to reset your password:</p>
        <a href="{reset_url}" style="padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">
            Reset Password
        </a>
        <p>This link expires in 1 hour.</p>
        """

        response = client.emails.send(
            {
                "from": settings.email_from,
                "to": email,
                "subject": "Reset your DocMind password",
                "html": html_body,
            }
        )

        logger.info(f"Password reset email sent to {email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send password reset email to {email}: {e}")
        return False


async def send_notification(email: str, subject: str, html_body: str) -> bool:
    """Send a generic notification email."""
    settings = get_settings()

    if not settings.resend_api_key:
        logger.warning("RESEND_API_KEY not configured; notification email not sent")
        return False

    try:
        from resend import Resend

        client = Resend(api_key=settings.resend_api_key)

        response = client.emails.send(
            {
                "from": settings.email_from,
                "to": email,
                "subject": subject,
                "html": html_body,
            }
        )

        logger.info(f"Notification email sent to {email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send notification email to {email}: {e}")
        return False

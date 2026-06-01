"""Custom application exceptions."""


class AppException(Exception):
    """Base application exception."""

    def __init__(self, message: str, code: str = "app_error", status_code: int = 500):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(self.message)


class ValidationError(AppException):
    """Validation error."""

    def __init__(self, message: str):
        super().__init__(message, code="validation_error", status_code=400)


class NotFoundError(AppException):
    """Resource not found."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, code="not_found", status_code=404)


class ForbiddenError(AppException):
    """Access forbidden."""

    def __init__(self, message: str = "Access denied"):
        super().__init__(message, code="forbidden", status_code=403)


class UnauthorizedError(AppException):
    """Unauthorized access."""

    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, code="unauthorized", status_code=401)


class ConflictError(AppException):
    """Resource conflict."""

    def __init__(self, message: str = "Conflict"):
        super().__init__(message, code="conflict", status_code=409)


class InternalServerError(AppException):
    """Internal server error."""

    def __init__(self, message: str = "Internal server error"):
        super().__init__(message, code="internal_error", status_code=500)

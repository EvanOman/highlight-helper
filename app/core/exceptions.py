"""Domain exceptions for the application."""


class NotFoundError(Exception):
    """Raised when a requested entity is not found."""

    def __init__(self, detail: str = "Not found") -> None:
        self.detail = detail
        super().__init__(detail)

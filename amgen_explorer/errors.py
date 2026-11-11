"""Safe, application-authored validation messages; never wrap provider payloads."""

class UserFacingError(ValueError):
    """A local validation error safe to show verbatim in the application."""

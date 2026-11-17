"""Errors whose messages are safe for the command-line boundary."""


class StridelogError(Exception):
    """Report a fixed diagnostic without credentials or personal data."""

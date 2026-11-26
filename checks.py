"""Data checks shared by all pipeline steps."""


class DataCheckError(Exception):
    """A data check failed; the build stops with this message."""


def check(condition: bool, message: str) -> None:
    # Explicit check instead of assert: asserts are skipped when Python runs with -O
    if not condition:
        raise DataCheckError(message)

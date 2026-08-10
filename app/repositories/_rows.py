from sqlalchemy import CursorResult


def rowcount(result: object) -> int:
    return result.rowcount if isinstance(result, CursorResult) else 0

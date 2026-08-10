import re

_WHITESPACE = re.compile(r"\s+")


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = _WHITESPACE.sub(" ", value).strip()
    return collapsed or None


def normalize_company_name(value: str | None) -> str | None:
    return clean_text(value)


def normalize_person_name(value: str | None) -> str | None:
    return clean_text(value)

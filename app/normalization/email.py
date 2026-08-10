from app.normalization.text import clean_text


def normalize_email(value: str | None) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    text = text.removeprefix("mailto:").strip().strip("<>").strip()
    # local parts are case-sensitive in theory, never in practice
    return text.lower() or None

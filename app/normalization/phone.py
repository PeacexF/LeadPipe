import phonenumbers

from app.normalization.text import clean_text


def normalize_phone(value: str | None, region: str | None = None) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    try:
        parsed = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException:
        return text
    if not phonenumbers.is_valid_number(parsed):
        return text
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

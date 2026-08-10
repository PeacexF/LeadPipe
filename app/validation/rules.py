from urllib.parse import urlsplit

import phonenumbers
from email_validator import EmailNotValidError, validate_email

from app.normalization.url import HOSTNAME
from app.validation.models import VALID, FieldValidation, invalid, unknown


def validate_company_name(value: str | None) -> FieldValidation:
    if value is None:
        return invalid("missing")
    return VALID


def validate_email_field(value: str | None) -> FieldValidation:
    if value is None:
        return unknown()
    try:
        validate_email(value, check_deliverability=False)
    except EmailNotValidError:
        return invalid("syntax")
    return VALID


def validate_url_field(value: str | None) -> FieldValidation:
    if value is None:
        return unknown()
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https"):
        return invalid("scheme")
    host = parsed.hostname
    if not host or not HOSTNAME.match(host):
        return invalid("syntax")
    return VALID


def validate_phone_field(value: str | None) -> FieldValidation:
    if value is None:
        return unknown()
    try:
        parsed = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException:
        return invalid("syntax")
    if not phonenumbers.is_valid_number(parsed):
        return invalid("syntax")
    return VALID

from app.domain.models import NormalizedLead
from app.validation.models import FieldValidation, LeadValidation, ValidationStatus
from app.validation.rules import (
    validate_company_name,
    validate_email_field,
    validate_phone_field,
    validate_url_field,
)

OPTIONAL_FIELDS = ("email", "website", "phone", "source_url")


def validate_lead(lead: NormalizedLead) -> LeadValidation:
    fields: dict[str, FieldValidation] = {
        "company_name": validate_company_name(lead.company_name),
        "email": validate_email_field(lead.email),
        "website": validate_url_field(lead.website),
        "phone": validate_phone_field(lead.phone),
        "source_url": validate_url_field(lead.source.url),
    }
    return LeadValidation(status=_rollup(fields), fields=fields)


def _rollup(fields: dict[str, FieldValidation]) -> ValidationStatus:
    if any(result.is_invalid for result in fields.values()):
        return ValidationStatus.INVALID
    # nothing to contact them by, so nothing was actually verified
    if all(fields[name].status is ValidationStatus.UNKNOWN for name in OPTIONAL_FIELDS):
        return ValidationStatus.UNKNOWN
    return ValidationStatus.VALID

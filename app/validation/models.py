from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class ValidationStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FieldValidation:
    status: ValidationStatus
    reason: str | None = None

    @property
    def is_invalid(self) -> bool:
        return self.status is ValidationStatus.INVALID


@dataclass(frozen=True, slots=True)
class LeadValidation:
    status: ValidationStatus
    fields: Mapping[str, FieldValidation]

    @property
    def invalid_fields(self) -> tuple[str, ...]:
        return tuple(name for name, result in self.fields.items() if result.is_invalid)


VALID = FieldValidation(ValidationStatus.VALID)


def unknown(reason: str = "missing") -> FieldValidation:
    return FieldValidation(ValidationStatus.UNKNOWN, reason)


def invalid(reason: str) -> FieldValidation:
    return FieldValidation(ValidationStatus.INVALID, reason)

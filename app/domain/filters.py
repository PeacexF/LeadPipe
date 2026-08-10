from dataclasses import dataclass
from datetime import datetime

from app.validation.models import ValidationStatus


@dataclass(frozen=True, slots=True)
class LeadFilter:
    source: str | None = None
    country: str | None = None
    city: str | None = None
    validation_status: ValidationStatus | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None

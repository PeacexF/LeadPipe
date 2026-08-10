from app.domain.models import LEAD_FIELDS, NormalizedLead, RawRecord
from app.normalization.email import normalize_email
from app.normalization.location import normalize_city, normalize_country
from app.normalization.phone import normalize_phone
from app.normalization.text import clean_text, normalize_company_name, normalize_person_name
from app.normalization.url import extract_domain, normalize_url


def normalize_record(record: RawRecord, default_region: str | None = None) -> NormalizedLead:
    get = record.fields.get
    website = normalize_url(get("website"))
    country = normalize_country(get("country"))

    region = default_region
    if region is None and country is not None and len(country) == 2:
        region = country

    return NormalizedLead(
        source=record.source,
        collected_at=record.collected_at,
        company_name=normalize_company_name(get("company_name")),
        contact_name=normalize_person_name(get("contact_name")),
        website=website,
        website_domain=extract_domain(website),
        email=normalize_email(get("email")),
        phone=normalize_phone(get("phone"), region),
        address=clean_text(get("address")),
        city=normalize_city(get("city")),
        country=country,
        extra={k: v for k, v in record.fields.items() if k not in LEAD_FIELDS},
    )

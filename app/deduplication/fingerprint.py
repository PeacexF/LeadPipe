import re
from dataclasses import dataclass

from app.domain.models import NormalizedLead

LEGAL_SUFFIXES = frozenset(
    {
        "oy",
        "oyj",
        "ab",
        "ky",
        "tmi",
        "as",
        "asa",
        "aps",
        "ou",
        "sia",
        "uab",
        "ltd",
        "limited",
        "plc",
        "llp",
        "inc",
        "llc",
        "corp",
        "corporation",
        "company",
        "co",
        "gmbh",
        "ag",
        "kg",
        "bv",
        "nv",
        "sa",
        "sas",
        "sarl",
        "srl",
        "spa",
        "sl",
    }
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def company_slug(value: str | None) -> str | None:
    if value is None:
        return None
    tokens = [token for token in _NON_ALNUM.split(value.casefold()) if token]
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens) or None


def trigrams(value: str) -> frozenset[str]:
    # Word-padded trigrams, matching postgres pg_trgm so SQL and Python agree
    grams: set[str] = set()
    for word in _NON_ALNUM.split(value.casefold()):
        if not word:
            continue
        padded = f"  {word} "
        grams.update(padded[i : i + 3] for i in range(len(padded) - 2))
    return frozenset(grams)


def similarity(left: str, right: str) -> float:
    a, b = trigrams(left), trigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True, slots=True)
class Fingerprints:
    email: str | None = None
    domain: str | None = None
    phone: str | None = None
    name_slug: str | None = None
    location: str | None = None
    external_id: str | None = None


def fingerprints(lead: NormalizedLead) -> Fingerprints:
    email = lead.email if lead.email and "@" in lead.email else None
    phone = lead.phone if lead.phone and lead.phone.startswith("+") else None
    external_id = lead.extra.get("external_id")

    parts = [part for part in (lead.city, lead.country) if part]
    location = "|".join(part.casefold() for part in parts) if parts else None

    return Fingerprints(
        email=email,
        domain=lead.website_domain,
        phone=phone,
        name_slug=company_slug(lead.company_name),
        location=location,
        external_id=str(external_id) if external_id is not None else None,
    )

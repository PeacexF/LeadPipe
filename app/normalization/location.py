from app.normalization.text import clean_text

COUNTRY_ALIASES = {
    "finland": "FI",
    "suomi": "FI",
    "sweden": "SE",
    "sverige": "SE",
    "norway": "NO",
    "denmark": "DK",
    "estonia": "EE",
    "germany": "DE",
    "deutschland": "DE",
    "netherlands": "NL",
    "the netherlands": "NL",
    "france": "FR",
    "spain": "ES",
    "italy": "IT",
    "poland": "PL",
    "ireland": "IE",
    "united kingdom": "GB",
    "great britain": "GB",
    "uk": "GB",
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
}


def normalize_country(value: str | None) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    key = text.casefold().rstrip(".")
    if key in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[key]
    if len(text) == 2 and text.isalpha():
        return text.upper()
    return text


def normalize_city(value: str | None) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    # only recase when the source shouted or whispered; leave deliberate casing alone
    if text.isupper() or text.islower():
        return text.title()
    return text

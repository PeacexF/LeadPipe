import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.normalization.text import clean_text

HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "igshid",
    }
)

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_url(value: str | None) -> str | None:
    text = clean_text(value)
    if text is None:
        return None

    lowered = text.lower()
    if "://" in text:
        if not lowered.startswith(("http://", "https://")):
            return text
        candidate = text
    elif ":" in text and lowered.startswith(("mailto:", "tel:")):
        return text
    else:
        candidate = f"https://{text}"

    try:
        parsed = urlsplit(candidate)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return text

    if not host or not HOSTNAME.match(host):
        return text

    host = host.removeprefix("www.")
    netloc = host
    if port is not None and port != _DEFAULT_PORTS[parsed.scheme]:
        netloc = f"{host}:{port}"

    params = parse_qsl(parsed.query, keep_blank_values=True)
    kept = sorted(p for p in params if p[0].lower() not in TRACKING_PARAMS)
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), urlencode(kept), ""))


def extract_domain(url: str | None) -> str | None:
    if url is None:
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host.removeprefix("www.") if host else None

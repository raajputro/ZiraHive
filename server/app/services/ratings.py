"""Age ratings for kids' profiles.

A title's age comes from, in order: the admin's choice for the title, its certificate from
TMDB (when a TMDB key is set), the same for its series, and finally the category's default
(e.g. "Animation: 7+"). Profiles with an age limit only see titles that have an age at or
below the limit; titles with no age at all are hidden from them, to be safe.
"""
from __future__ import annotations

import re

AGES = [0, 7, 13, 16, 18]

_CERTS: dict[str, int] = {
    # US
    "G": 0, "TV-Y": 0, "TV-G": 0, "PG": 7, "TV-Y7": 7, "TV-Y7-FV": 7, "TV-PG": 7, "PG-13": 13,
    "TV-14": 13, "R": 16, "NC-17": 18, "TV-MA": 18, "NR": -1, "UNRATED": -1,
    # India (CBFC)
    "U": 0, "UA": 13, "U/A": 13, "UA 7+": 7, "UA 13+": 13, "UA 16+": 16, "A": 18, "S": 18,
    # UK
    "12": 13, "12A": 13, "15": 16, "18": 18, "R18": 18,
}


def cert_age(cert: str | None) -> int | None:
    if not cert:
        return None
    c = cert.strip().upper()
    if c in _CERTS:
        return None if _CERTS[c] < 0 else _CERTS[c]
    m = re.fullmatch(r"(\d{1,2})\+?", c)  # "13+", "16"
    return int(m.group(1)) if m else None


def effective_age(item_age: int | None = None, item_cert: str | None = None,
                  series_age: int | None = None, series_cert: str | None = None,
                  library_age: int | None = None) -> int | None:
    for value in (item_age, cert_age(item_cert), series_age, cert_age(series_cert), library_age):
        if value is not None:
            return value
    return None


def allowed(max_age: int | None, age: int | None) -> bool:
    return max_age is None or (age is not None and age <= max_age)


def pick_certification(results: list[dict], kind: str) -> str | None:
    """From TMDB release_dates (movies) or content_ratings (tv), prefer India, then US, then UK."""
    by_country: dict[str, str] = {}
    for r in results:
        country = r.get("iso_3166_1")
        if kind == "movie":
            certs = [d.get("certification") for d in r.get("release_dates", []) if d.get("certification")]
            cert = certs[0] if certs else None
        else:
            cert = r.get("rating")
        if country and cert:
            by_country[country] = cert
    for country in ("IN", "US", "GB"):
        if country in by_country:
            return by_country[country]
    return next(iter(by_country.values()), None)

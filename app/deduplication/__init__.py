from app.deduplication.fingerprint import Fingerprints, company_slug, fingerprints, similarity
from app.deduplication.matcher import (
    DEFAULT_POLICY,
    MatchPolicy,
    MatchResult,
    MatchRule,
    match,
)
from app.deduplication.merge import Candidate, MergedLead, merge

__all__ = [
    "DEFAULT_POLICY",
    "Candidate",
    "Fingerprints",
    "MatchPolicy",
    "MatchResult",
    "MatchRule",
    "MergedLead",
    "company_slug",
    "fingerprints",
    "match",
    "merge",
    "similarity",
]

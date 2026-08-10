from dataclasses import dataclass
from enum import StrEnum

from app.deduplication.fingerprint import Fingerprints, fingerprints, similarity
from app.domain.models import NormalizedLead


class MatchRule(StrEnum):
    EMAIL = "email"
    WEBSITE = "website"
    PHONE = "phone"
    NAME_LOCATION = "name_location"
    EXTERNAL_ID = "external_id"


@dataclass(frozen=True, slots=True)
class MatchPolicy:
    name_similarity_threshold: float = 0.7
    name_confidence_cap: float = 0.8
    auto_merge_threshold: float = 0.85


DEFAULT_POLICY = MatchPolicy()

EXACT_CONFIDENCE = {
    MatchRule.EMAIL: 1.0,
    MatchRule.WEBSITE: 0.95,
    MatchRule.PHONE: 0.9,
    MatchRule.EXTERNAL_ID: 1.0,
}


@dataclass(frozen=True, slots=True)
class MatchResult:
    rule: MatchRule
    confidence: float
    auto_merge: bool

    @property
    def needs_review(self) -> bool:
        return not self.auto_merge


def match(
    left: NormalizedLead,
    right: NormalizedLead,
    policy: MatchPolicy = DEFAULT_POLICY,
) -> MatchResult | None:
    a, b = fingerprints(left), fingerprints(right)

    for rule, key in (
        (MatchRule.EMAIL, "email"),
        (MatchRule.WEBSITE, "domain"),
        (MatchRule.PHONE, "phone"),
    ):
        if _equal(a, b, key):
            return _result(rule, EXACT_CONFIDENCE[rule], policy)

    name_match = _match_name_location(a, b, policy)
    if name_match is not None:
        return name_match

    if left.source.name == right.source.name and _equal(a, b, "external_id"):
        return _result(MatchRule.EXTERNAL_ID, EXACT_CONFIDENCE[MatchRule.EXTERNAL_ID], policy)

    return None


def _equal(a: Fingerprints, b: Fingerprints, key: str) -> bool:
    left = getattr(a, key)
    return left is not None and left == getattr(b, key)


def _match_name_location(
    a: Fingerprints, b: Fingerprints, policy: MatchPolicy
) -> MatchResult | None:
    if a.name_slug is None or b.name_slug is None:
        return None
    if a.location is None or a.location != b.location:
        return None
    score = similarity(a.name_slug, b.name_slug)
    if score < policy.name_similarity_threshold:
        return None
    return _result(MatchRule.NAME_LOCATION, min(score, policy.name_confidence_cap), policy)


def _result(rule: MatchRule, confidence: float, policy: MatchPolicy) -> MatchResult:
    return MatchResult(
        rule=rule,
        confidence=confidence,
        auto_merge=confidence >= policy.auto_merge_threshold,
    )

"""Pure prototype scoring; no IO, model calls, SDG scoring or real-data claims.

User skill/knowledge inputs are raw integer 0–4; requirements are already
normalized 0–1. RIASEC vectors are ordered R,I,A,S,E,C. Unavailable components
have value=None and explicit issues; no missing-value imputation is performed.
Numeric policy v1: Python float, sorted IDs, math.fsum, no display rounding.
"""
from dataclasses import dataclass
from math import fsum, hypot, isfinite, log2
from typing import Any, Mapping, Sequence

MODERATE_LAMBDA = 0.15
FAST_LAMBDA = 0.35
SCORING_VERSION = 'prototype-v1'


@dataclass(frozen=True)
class Score:
    """A computed value or explicit reasons it is unavailable."""
    value: float | None
    issues: tuple[str, ...] = ()


def _number(value: object, low: float, high: float = float('inf')) -> bool:
    """Check finite real numeric input, excluding booleans."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and isfinite(value) and low <= value <= high)


def normalize_0_4(value: object) -> Score:
    """Normalize an integer questionnaire response; reject missing/invalid values."""
    if not _number(value, 0, 4) or int(value) != value:
        return Score(None, ('Expected integer response 0–4',))
    return Score(float(value) / 4)


def capability_breakdown(users: Mapping[str, object],
                         requirements: Mapping[str, Mapping[str, object]]) -> dict[str, Any]:
    """Return coverage, importance and sorted gaps without imputing missing data."""
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    for key in sorted(requirements):
        item = requirements[key]
        required, importance = item.get('required'), item.get('importance')
        if not _number(required, 0, 1) or not _number(importance, 0, 1):
            issues.append(f'{key}: missing/invalid normalized requirement or importance')
            continue
        user = normalize_0_4(users.get(key))
        # A known zero requirement cannot create a gap, even if user is missing.
        if required == 0:
            rows.append(dict(id=key, user=user.value, required=required,
                             importance=importance, coverage=None, gap=0.0, included=False))
            continue
        if user.value is None:
            issues.append(f'{key}: {user.issues[0]}')
            continue
        rows.append(dict(id=key, user=user.value, required=required,
                         importance=importance, coverage=min(user.value / required, 1.0),
                         gap=importance * max(required - user.value, 0.0), included=True))
    included = [row for row in rows if row['included']]
    weight = fsum(row['importance'] for row in included)
    if weight == 0:
        issues.append('No positive-weight nonzero requirements')
    value = None if issues else min(100.0, 100 * fsum(
        row['importance'] * row['coverage'] for row in included) / weight)
    return dict(score=Score(value, tuple(issues)), items=rows,
                gaps=sorted(rows, key=lambda row: (-row['gap'], row['id'])))


def skill_coverage(users: Mapping[str, object],
                   requirements: Mapping[str, Mapping[str, object]]) -> Score:
    """Compute S_skills on normalized requirements and raw user responses."""
    return capability_breakdown(users, requirements)['score']


def knowledge_coverage(users: Mapping[str, object],
                       requirements: Mapping[str, Mapping[str, object]]) -> Score:
    """Compute K_knowledge using the same weighted coverage rule."""
    return capability_breakdown(users, requirements)['score']


def calculate_gaps(users: Mapping[str, object],
                   requirements: Mapping[str, Mapping[str, object]]) -> dict[str, Any]:
    """Return severity-sorted skill or knowledge gaps plus any missing-data issues."""
    result = capability_breakdown(users, requirements)
    return dict(gaps=result['gaps'], issues=result['score'].issues)


def riasec_similarity(user: Sequence[object], role: Sequence[object]) -> Score:
    """Compute six-dimensional nonnegative cosine similarity on a 0–100 scale."""
    if len(user) != 6 or len(role) != 6:
        return Score(None, ('RIASEC requires six dimensions',))
    if not all(_number(x, 0) for x in (*user, *role)):
        return Score(None, ('RIASEC contains missing/invalid values',))
    un, rn = hypot(*user), hypot(*role)
    if un == 0 or rn == 0:
        return Score(None, ('RIASEC zero vector',))
    return Score(min(100.0, 100 * fsum((u / un) * (r / rn) for u, r in zip(user, role))))


def _combine(a: Score, b: Score, a_weight: float) -> Score:
    """Combine available 0–100 components without redistributing weights."""
    if a.value is None or b.value is None:
        return Score(None, a.issues + b.issues or ('Missing component',))
    if not _number(a.value, 0, 100) or not _number(b.value, 0, 100):
        return Score(None, ('Component outside 0–100',))
    return Score(a_weight * a.value + (1 - a_weight) * b.value)


def capability_score(skills: Score, knowledge: Score) -> Score:
    """Compute S_capability = 0.75 S_skills + 0.25 K_knowledge."""
    return _combine(skills, knowledge, 0.75)


def personal_fit(capability: Score, interest: Score) -> Score:
    """Compute P = 0.70 S_capability + 0.30 I."""
    # Literal 0.30 avoids deriving a subtly different float from 1 - 0.70.
    if capability.value is None or interest.value is None:
        return Score(None, capability.issues + interest.issues or ('Missing component',))
    checked = _combine(capability, interest, 0.70)
    return checked if checked.value is None else Score(0.70 * capability.value + 0.30 * interest.value)


def github_trend(recent: object, previous: object) -> Score:
    """Compute smoothed clipped log-ratio activity momentum, not job demand."""
    if not all(_number(n, 0) and int(n) == n for n in (recent, previous)):
        return Score(None, ('Counts must be nonnegative integers',))
    return Score(50 + 50 * max(-1.0, min(1.0, log2((recent + 20) / (previous + 20)))))


def role_trend(weights: Mapping[str, object],
               snapshots: Mapping[str, Mapping[str, object]]) -> dict[str, Any]:
    """Aggregate mapped topics; any missing topic blocks the complete trend score."""
    items: list[dict[str, Any]] = []
    issues: list[str] = []
    for key in sorted(weights):
        weight = weights[key]
        snapshot = snapshots.get(key, {})
        score = github_trend(snapshot.get('recent'), snapshot.get('previous'))
        if not _number(weight, 0):
            issues.append(f'{key}: invalid topic weight')
        if score.value is None:
            issues.extend(f'{key}: {issue}' for issue in score.issues)
        items.append(dict(id=key, weight=weight, score=score, snapshot=dict(snapshot)))
    if not issues and fsum(item['weight'] for item in items) == 0:
        issues.append('No positive topic weights')
    value = None if issues else fsum(item['weight'] * item['score'].value for item in items) / fsum(item['weight'] for item in items)
    return dict(score=Score(value, tuple(issues)), topics=items)


def match_score(personal: Score, trend: Score, trend_weight: float) -> Score:
    """Compute Match(lambda), preserving unavailable component status."""
    if not _number(trend_weight, 0, 1):
        return Score(None, ('Invalid lambda',))
    if personal.value is None or trend.value is None:
        return Score(None, personal.issues + trend.issues or ('Missing component',))
    checked = _combine(personal, trend, 1 - trend_weight)
    return checked if checked.value is None else Score((1 - trend_weight) * personal.value + trend_weight * trend.value)


def rank_roles(profile: Mapping[str, Any], roles: Sequence[Mapping[str, Any]],
               trends: Mapping[str, Mapping[str, object]]) -> list[dict[str, Any]]:
    """Score both scenarios with traces; leave incomplete roles explicitly unranked.

    Role code/title must be unique/nonempty. Inputs are never mutated. Complete
    roles precede excluded roles, ordered by moderate rank then stable code.
    This engine returns the whole pool; a presentation layer selects each top five.
    """
    codes = [role.get('code') for role in roles]
    if any(not isinstance(code, str) or not code for code in codes) or len(set(codes)) != len(codes):
        raise ValueError('Roles require unique nonempty codes')
    if any(not isinstance(role.get('title'), str) or not role['title'] for role in roles):
        raise ValueError('Roles require nonempty titles')
    output: list[dict[str, Any]] = []
    for role in sorted(roles, key=lambda r: r['code']):
        skills = capability_breakdown(profile.get('skills', {}), role.get('skills', {}))
        knowledge = capability_breakdown(profile.get('knowledge', {}), role.get('knowledge', {}))
        interest = riasec_similarity(profile.get('riasec', []), role.get('riasec', []))
        capability = capability_score(skills['score'], knowledge['score'])
        personal = personal_fit(capability, interest)
        trend = role_trend(role.get('topics', {}), trends)
        moderate = match_score(personal, trend['score'], MODERATE_LAMBDA)
        fast = match_score(personal, trend['score'], FAST_LAMBDA)
        output.append(dict(code=role['code'], title=role['title'], version=SCORING_VERSION,
                           data_status=role.get('data_status', 'unspecified'),
                           skills=skills, knowledge=knowledge, I=interest,
                           S_capability=capability, P=personal, trend=trend,
                           moderate=moderate, fast=fast, moderate_rank=None, fast_rank=None,
                           score_delta=None, rank_delta=None,
                           major_skills_gaps=[g for g in skills['gaps'] if g['gap'] > 0][:3],
                           major_knowledge_gaps=[g for g in knowledge['gaps'] if g['gap'] > 0][:3]))
    eligible = [row for row in output if row['moderate'].value is not None and row['fast'].value is not None]
    for scenario in ('moderate', 'fast'):
        for rank, row in enumerate(sorted(eligible, key=lambda r: (-r[scenario].value, r['code'])), 1):
            row[scenario + '_rank'] = rank
    for row in eligible:
        row['score_delta'] = row['fast'].value - row['moderate'].value
        row['rank_delta'] = row['moderate_rank'] - row['fast_rank']
    return sorted(output, key=lambda r: (r['moderate_rank'] is None, r['moderate_rank'] or 0, r['code']))

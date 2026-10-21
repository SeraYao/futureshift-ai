"""Explicit-refresh GitHub repository activity evidence, using only the stdlib.

No network calls occur on import or cache reads. Counts are search-reported
activity proxies, never employment demand. Refreshes are atomic per occupation:
all mapped topics/windows must succeed before replacing its last good snapshot.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
from functools import lru_cache
import json
from pathlib import Path
import re
import threading
from typing import Any, Callable, Mapping
from urllib import error, parse, request

from src.scoring import Score, role_trend

API_URL = 'https://api.github.com/search/repositories'
# User-confirmed scope; relevance is an unvalidated prototype hypothesis.
MAPPING_STATUS = '原型假设，尚待验证'
MAPPING_RECORDED_ON = '2026-10-21'
ROLE_TOPICS: dict[str, dict[str, float]] = {
    '15-2051.00': {'machine-learning': 0.5, 'data-science': 0.5},
    '15-2031.00': {'operations-research': 0.5, 'optimization': 0.5},
    '15-1252.00': {'code-generation': 0.5, 'software-testing': 0.5},
}
SUPPORTED_ROLES = frozenset(('15-2051.00', '15-2031.00', '15-1252.00'))
CACHE_SECONDS = 900


class TrendError(Exception):
    """An unavailable search result, never a replacement zero count."""


def utc_now() -> datetime:
    """Return timezone-aware UTC time for fetch and cache provenance."""
    return datetime.now(timezone.utc)


def windows(as_of: date) -> dict[str, dict[str, str]]:
    """Return adjacent complete UTC 90-day windows ending before the as-of day."""
    split = as_of - timedelta(days=90)
    return {'recent': {'start': split.isoformat(), 'end_exclusive': as_of.isoformat()},
            'previous': {'start': (split - timedelta(days=90)).isoformat(),
                         'end_exclusive': split.isoformat()}}


def repository_query(topic: str, window: Mapping[str, str]) -> str:
    """Build an exact public topic query, translating exclusive ends to inclusive dates."""
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', topic):
        raise ValueError('Expected an explicit GitHub topic slug')
    last = date.fromisoformat(window['end_exclusive']) - timedelta(days=1)
    return f"topic:{topic} visibility:public fork:false created:{window['start']}..{last.isoformat()}"


def query_url(query: str) -> str:
    """Encode the full query; request only one result because only total_count is used."""
    return API_URL + '?' + parse.urlencode({'q': query, 'per_page': 1})


def evidence_score(snapshot: dict | None, expected_role: str) -> Score:
    """Score only a complete, matching official-API snapshot using the unchanged formula."""
    if not snapshot or snapshot.get('role_code') != expected_role:
        return Score(None, ('No successful query snapshot for this occupation',))
    if snapshot.get('data_status') != 'github_api' or expected_role not in ROLE_TOPICS:
        return Score(None, ('Not an approved GitHub API snapshot',))
    weights = ROLE_TOPICS[expected_role]
    if snapshot.get('topic_weights') != weights or set(snapshot.get('topics', {})) != set(weights):
        return Score(None, ('Snapshot mapping differs from the approved occupation mapping',))
    try:
        ranges = windows(date.fromisoformat(snapshot['as_of']))
        for topic in weights:
            record = snapshot['topics'][topic]
            for name in ('recent', 'previous'):
                result = record['results'][name]
                expected_query = repository_query(topic, ranges[name])
                if (record[name + '_window'] != ranges[name]
                        or result['query'] != expected_query
                        or result['source_url'] != query_url(expected_query)
                        or result['incomplete_results'] is not False
                        or result['count'] != record[name]):
                    raise ValueError('Query provenance mismatch')
    except (ValueError, KeyError, TypeError):
        return Score(None, ('Missing or mismatched original query evidence',))
    return role_trend(weights, snapshot['topics'])['score']


class GitHubTrends:
    """Process-shared throttling and disk-backed last-success caches; no automatic refresh."""

    def __init__(self, cache_path: Path | None = None, *,
                 opener: Callable[..., Any] | None = None,
                 now: Callable[[], datetime] = utc_now, timeout: float = 10.0) -> None:
        """Create an offline client; urllib is invoked only inside refresh()."""
        self.cache_path = cache_path
        self.opener = opener
        self.now = now
        self.timeout = timeout
        self.lock = threading.RLock()
        self.attempts: list[datetime] = []
        self.blocked_until: datetime | None = None
        self.snapshots: dict[str, dict] = {}
        self.cache_error: str | None = None
        self.last_errors: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        """Read only our distinct real-evidence cache, never any demo data."""
        if self.cache_path is None or not self.cache_path.exists():
            return
        try:
            contents = json.loads(self.cache_path.read_text())
            if contents.get('cache_schema') != 1 or not isinstance(contents.get('snapshots'), dict):
                raise ValueError('Invalid cache schema')
            self.snapshots = contents['snapshots']
        except (OSError, ValueError) as exc:
            self.cache_error = f'Cache unavailable: {exc}'

    def _save(self) -> None:
        """Atomically persist successes; failed attempts never overwrite a successful record."""
        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'cache_schema': 1, 'snapshots': self.snapshots},
                                       indent=2, allow_nan=False) + '\n')
        temporary.replace(self.cache_path)

    def _key(self, code: str) -> str:
        """Keep cache identity tied to the exact approved role mapping."""
        return hashlib.sha256(json.dumps([code, ROLE_TOPICS[code]], sort_keys=True).encode()).hexdigest()

    def cached(self, code: str) -> dict:
        """Return last success plus age/expiry metadata without making an HTTP request."""
        with self.lock:
            if code not in ROLE_TOPICS or code not in SUPPORTED_ROLES:
                return {'snapshot': None, 'cached': False, 'expired': None,
                        'error': 'No approved query mapping for this occupation'}
            snapshot = deepcopy(self.snapshots.get(self._key(code)))
            expired = None
            if snapshot and evidence_score(snapshot, code).value is None:
                snapshot = None
                self.cache_error = 'Invalid cached query evidence'
            if snapshot:
                try:
                    age = (self.now() - datetime.fromisoformat(snapshot['fetched_at'])).total_seconds()
                    expired = (age < 0 or age >= CACHE_SECONDS or
                               snapshot['as_of'] != self.now().date().isoformat())
                except (ValueError, KeyError, TypeError):
                    snapshot = None
                    self.cache_error = 'Invalid cached snapshot timestamps'
            return {'snapshot': snapshot, 'cached': snapshot is not None,
                    'expired': expired, 'error': self.last_errors.get(code) or self.cache_error}

    def _cooldown(self, headers: Mapping[str, str], current: datetime) -> None:
        """Respect Retry-After or reset headers without sleeping or automatic retries."""
        candidates = [current + timedelta(seconds=60)]
        retry = headers.get('Retry-After')
        if retry:
            try:
                candidates.append(current + timedelta(seconds=max(0, float(retry))))
            except ValueError:
                try:
                    candidates.append(parsedate_to_datetime(retry).astimezone(timezone.utc))
                except (ValueError, TypeError):
                    pass
        reset = headers.get('X-RateLimit-Reset')
        if reset:
            try:
                candidates.append(datetime.fromtimestamp(float(reset), timezone.utc))
            except (ValueError, OverflowError, OSError):
                pass
        self.blocked_until = max(candidates)

    def _search(self, query: str) -> dict:
        """Fetch one complete count, enforcing at most ten attempts per rolling minute."""
        current = self.now()
        self.attempts = [stamp for stamp in self.attempts if (current - stamp).total_seconds() < 60]
        if self.blocked_until and current < self.blocked_until:
            raise TrendError(f'Rate limited until {self.blocked_until.isoformat()}; refresh later')
        if len(self.attempts) >= 10:
            raise TrendError('Local limit: at most 10 anonymous search requests per minute; refresh later')
        self.attempts.append(current)
        url = query_url(query)
        req = request.Request(url, headers={'Accept': 'application/vnd.github+json',
                                           'User-Agent': 'FutureShift-AI-prototype'})
        try:
            with (self.opener or request.urlopen)(req, timeout=self.timeout) as response:
                headers = response.headers
                if getattr(response, 'status', 200) != 200:
                    raise TrendError(f'Unexpected HTTP status {response.status}')
                payload = json.loads(response.read().decode('utf-8'))
                if headers.get('X-RateLimit-Remaining') == '0':
                    self._cooldown(headers, self.now())
        except error.HTTPError as exc:
            if exc.code in (403, 429):
                self._cooldown(exc.headers or {}, self.now())
            message = f'GitHub HTTP {exc.code}: {exc.reason}'
            exc.close()
            raise TrendError(message) from exc
        except (error.URLError, TimeoutError, OSError, ValueError, UnicodeError) as exc:
            raise TrendError(f'GitHub request failed: {exc}') from exc
        if (not isinstance(payload, dict) or type(payload.get('total_count')) is not int
                or payload['total_count'] < 0 or payload.get('incomplete_results') is not False):
            raise TrendError('Missing/invalid count or incomplete search results; no score computed')
        return {'query': query, 'source_url': url, 'count': payload['total_count'],
                'incomplete_results': False, 'http_status': 200, 'fetched_at': self.now().isoformat()}

    def refresh(self, code: str) -> dict:
        """Explicitly refresh one approved role, or return a clearly marked last-good cache."""
        with self.lock:
            previous = self.cached(code)
            if code not in ROLE_TOPICS or code not in SUPPORTED_ROLES:
                return previous
            if previous['snapshot'] and not previous['expired']:
                return dict(previous, message='Using a successful cache younger than 15 minutes')
            as_of = self.now().date()
            ranges = windows(as_of)
            topics = {}
            try:
                for topic in ROLE_TOPICS[code]:
                    recent = self._search(repository_query(topic, ranges['recent']))
                    older = self._search(repository_query(topic, ranges['previous']))
                    topics[topic] = {'recent': recent['count'], 'previous': older['count'],
                                     'recent_window': ranges['recent'], 'previous_window': ranges['previous'],
                                     'results': {'recent': recent, 'previous': older},
                                     'data_status': 'github_api'}
            except TrendError as exc:
                self.last_errors[code] = str(exc)
                result = self.cached(code)
                return dict(result, attempted_at=self.now().isoformat())
            fetched = self.now().isoformat()
            snapshot = {'role_code': code, 'data_status': 'github_api', 'as_of': as_of.isoformat(),
                        'mapping_status': MAPPING_STATUS, 'mapping_recorded_on': MAPPING_RECORDED_ON,
                        'topic_weights': deepcopy(ROLE_TOPICS[code]), 'topics': topics,
                        'fetched_at': fetched, 'cached_at': fetched}
            self.snapshots[self._key(code)] = snapshot
            self.last_errors.pop(code, None)
            try:
                self._save()
                self.cache_error = None
            except OSError as exc:
                self.cache_error = f'Disk cache write failed; success retained in memory: {exc}'
            return {'snapshot': deepcopy(snapshot), 'cached': False, 'expired': False,
                    'error': self.cache_error}


@lru_cache(maxsize=1)
def shared_client(cache_path: Path) -> GitHubTrends:
    """Keep one limiter/client across Streamlit script reruns and browser sessions."""
    return GitHubTrends(cache_path)

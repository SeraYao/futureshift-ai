"""Presentation-only translations. Internal answers, evidence and serialized plans stay unchanged.

English source messages are stable catalog keys. Missing keys are errors, not English
fallbacks. Raw CV text, quotes, JSON, queries, URLs and provider responses bypass this API.
"""
from contextvars import ContextVar
import json
import re
from pathlib import Path
from string import Formatter
from typing import Any

LANGUAGES = {'en': 'English', 'zh': '中文', 'ms': 'Bahasa Melayu'}
LANGUAGE_OPTIONS = tuple(LANGUAGES)
LOCALES_DIRECTORY = Path(__file__).resolve().parent / 'locales'
_language = ContextVar('futureshift_ui_language', default='en')
CATALOGS = {code: json.loads((LOCALES_DIRECTORY / f'{code}.json').read_text(encoding='utf-8'))
            for code in LANGUAGE_OPTIONS}


def validate_catalogs(catalogs: dict | None = None) -> None:
    """Fail on missing/extra keys, empty translations or incompatible placeholders."""
    catalogs = CATALOGS if catalogs is None else catalogs
    if set(catalogs) != set(LANGUAGES):
        raise ValueError('Incomplete language catalogs')
    def fields(text):
        return sorted((field, spec, conversion) for _, field, spec, conversion in Formatter().parse(text)
                      if field is not None)
    keys = set(catalogs['en'])
    for code, catalog in catalogs.items():
        if set(catalog) != keys:
            raise ValueError(f'Incomplete translation keys: {code}')
        for key, value in catalog.items():
            if not isinstance(value, str) or not value.strip() or fields(value) != fields(catalogs['en'][key]):
                raise ValueError(f'Invalid translation: {code}: {key}')


def initialize_language(state: Any) -> str:
    """Use canonical codes, migrating old display names without touching other state."""
    reload_catalogs()
    saved = state.get('ui_language')
    if not isinstance(saved, str) or saved not in LANGUAGE_OPTIONS:
        aliases = {label: code for code, label in LANGUAGES.items()}
        aliases['简体中文'] = 'zh'
        # An absent/obsolete preference starts in English; catalog errors never fall back.
        state['ui_language'] = aliases.get(saved, 'en') if isinstance(saved, str) else 'en'
    code = state['ui_language']
    set_language(code)
    return code


def reload_catalogs() -> None:
    """Reload edited locale files on each page run, even if this module stays cached.

    Validate a complete replacement before publishing it so concurrent sessions never
    observe partially loaded catalogs. Missing keys remain errors, with no fallback.
    """
    global CATALOGS
    catalogs = {code: json.loads((LOCALES_DIRECTORY / f'{code}.json').read_text(encoding='utf-8'))
                for code in LANGUAGE_OPTIONS}
    validate_catalogs(catalogs)
    CATALOGS = catalogs


def language_name(code: str) -> str:
    """Format a canonical widget value without translating or changing that value."""
    return LANGUAGES[code]


def set_language(code: str) -> None:
    """Set the language for this render only; sessions never share mutable locale state."""
    if code not in LANGUAGES:
        raise ValueError('Unknown interface language')
    _language.set(code)


def tr(key: str, **values: Any) -> str:
    """Translate an authored message; format values without modifying original data."""
    template = CATALOGS[_language.get()][key]
    return template.format(**values) if values else template


def display_value(value: Any) -> Any:
    """Localize known interface enums in template slots; preserve numbers and opaque values."""
    if isinstance(value, str) and value in CATALOGS['en']:
        return CATALOGS[_language.get()][value]
    return value


def display_text(value: str) -> str:
    """Render an authored label, preserving machine identifiers for unconfirmed fields."""
    if re.fullmatch(r'(?:[RIASEC][12]|skill_\d+|knowledge_\d+|RIASEC)', value):
        return value
    return tr(value)


def translated_options(formatter=None):
    """Translate option labels only. Widgets still return their original typed values."""
    catalog = CATALOGS[_language.get()]
    def format_option(value):
        rendered = formatter(value) if formatter else str(value)
        if rendered in catalog:
            return catalog[rendered]
        # Rating and SDG labels consist of a stable numeric prefix and an authored name.
        match = re.fullmatch(r'(\d+(?:\.\s*|[ ·—]+))(.+)', rendered)
        if match and match[2] in catalog:
            return match[1] + catalog[match[2]]
        match = re.fullmatch(r'(\d+) hours', rendered)
        if match:
            return catalog['{v0} hours'].format(v0=match[1])
        return rendered
    return format_option


def table_text(rows: list[dict]) -> list[dict]:
    """Translate headings and authored labels on copies, keeping source values untouched."""
    label_columns = {'Item', 'Area', 'Dimension', 'Field', 'Question', 'Measure', 'Status',
                     'Window', 'Snapshot', 'Blockers'}
    result = []
    for row in rows:
        translated = {}
        for key, value in row.items():
            output_key = display_value(key)
            if key in label_columns:
                value = translate_error(value) if key == 'Blockers' else display_value(value)
            elif key == 'Answer' and row.get('Field') != 'Optional career goal':
                value = (', '.join(translated_options()(part) for part in value)
                         if isinstance(value, list) else translated_options()(value))
            elif value in ('Unavailable', 'Not supplied', 'None recorded', 'Missing'):
                value = display_value(value)
            translated[output_key] = value
        result.append(translated)
    return result


def translate_error(message: str) -> str:
    """Translate only registered application diagnostics, never arbitrary provider text.

    Domain functions keep their original errors and data. This display helper replaces
    authored diagnostic fragments; unknown technical responses remain original evidence.
    """
    if message in CATALOGS['en']:
        return tr(message)
    # Translate our wrapper only; an external exception/HTTP reason stays verbatim.
    for prefix in ('GitHub request failed: ', 'GitHub HTTP ', 'Cache unavailable: ',
                   'Disk cache write failed; success retained in memory: '):
        if message.startswith(prefix):
            return tr(prefix) + message[len(prefix):]
    # Fragments are allowlisted separately from UI labels; never run this on CV evidence.
    from src.locales.diagnostics import DIAGNOSTICS
    pattern = '|'.join(re.escape(key) for key in sorted(DIAGNOSTICS, key=len, reverse=True))
    return re.sub(pattern, lambda match: tr(match[0]), message) if pattern else message


validate_catalogs()

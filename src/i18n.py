"""Presentation-only translations. Internal answers, evidence and serialized plans stay unchanged.

English source messages are stable catalog keys. Catalog validation is strict;
unexpected runtime keys show a localized placeholder and log the missing key.
Raw CV text, quotes, JSON, queries, URLs and provider responses bypass this API.
"""
from contextvars import ContextVar
import json
import logging
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
logger = logging.getLogger(__name__)
FALLBACK_TEXT = {'en': 'Text temporarily unavailable', 'zh': '文本暂不可用',
                 'ms': 'Teks tidak tersedia buat sementara waktu'}
# Display translations are keyed by immutable occupation codes, never scoring keys.
CAREER_LABELS = {
    '15-2051.00': ('Data Scientists', 'Uses data analysis and models to investigate questions and support decisions.'),
    '15-2031.00': ('Operations Research Analysts', 'Uses quantitative analysis and optimisation to support operational decisions.'),
    '15-1252.00': ('Software Developers', 'Designs, builds, tests and maintains software applications and systems.'),
    '13-1199.05': ('Sustainability Specialists', 'Coordinates sustainability initiatives and communicates organisational progress.'),
    '17-2081.00': ('Environmental Engineers', 'Develops engineering solutions for environmental protection and pollution control.'),
    '17-2199.03': ('Energy Engineers, Except Wind and Solar', 'Evaluates energy use and designs improvements in energy efficiency.'),
    '17-2199.08': ('Robotics Engineers', 'Designs and evaluates robotic systems and their applications.'),
    '15-1211.00': ('Computer Systems Analysts', 'Analyses computer systems and organisational information needs.'),
    '15-1212.00': ('Information Security Analysts', 'Analyses information security risks and plans protective measures.'),
    '19-1029.01': ('Bioinformatics Scientists', 'Uses computational methods to investigate biological data.'),
}


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


def localized_selectbox(st: Any, label: str, options: Any, *, key: str, **kwargs: Any) -> Any:
    """Keep canonical values separate from locale-specific browser option strings."""
    widget_key = key if _language.get() == 'en' else f'{key}__{_language.get()}'
    state = st.session_state
    if key in state:
        state[key] = state[key]  # retain canonical state when the old widget disappears
        if widget_key != key:
            state[widget_key] = state[key]
    def save_selection() -> None:
        state[key] = state[widget_key]
    value = st.selectbox(label, options, key=widget_key,
                         on_change=save_selection, **kwargs)
    if widget_key != key:
        state[key] = value
    return value

def set_language(code: str) -> None:
    """Set the language for this render only; sessions never share mutable locale state."""
    if code not in LANGUAGES:
        raise ValueError('Unknown interface language')
    _language.set(code)


def tr(key: str, **values: Any) -> str:
    """Translate an authored message; format values without modifying original data."""
    language = _language.get()
    template = CATALOGS.get(language, {}).get(key)
    if not template or key not in CATALOGS['en']:
        logger.warning('Missing UI translation language=%s key=%r', language, key)
        return FALLBACK_TEXT[language]
    return template.format(**values) if values else template


def career_name(code: str, original_title: str | None = None) -> str:
    """Localize known careers by ID; unknown external titles stay verbatim."""
    if code in CAREER_LABELS:
        return tr(CAREER_LABELS[code][0])
    return original_title or tr('Career {code}', code=code)


def career_description(code: str) -> str | None:
    """Authored summaries, not purported official source translations."""
    return tr(CAREER_LABELS[code][1]) if code in CAREER_LABELS else None


def display_value(value: Any) -> Any:
    """Localize known interface enums in template slots; preserve numbers and opaque values."""
    if isinstance(value, str) and value in CATALOGS['en']:
        return tr(value)
    return value


def display_text(value: str) -> str:
    """Render an authored label, preserving machine identifiers for unconfirmed fields."""
    if re.fullmatch(r'(?:[RIASEC][12]|skill_\d+|knowledge_\d+|RIASEC)', value):
        return value
    return tr(value)


def translated_options(formatter=None):
    """Translate option labels only. Widgets still return their original typed values."""
    language = _language.get()
    catalog = CATALOGS[language]
    def localized(key):
        text = catalog.get(key)
        if not text:
            logger.warning('Missing option translation language=%s key=%r', language, key)
        return text or FALLBACK_TEXT[language]
    def format_option(value):
        rendered = formatter(value) if formatter else str(value)
        if rendered in CATALOGS['en']:
            return localized(rendered)
        # Rating and SDG labels consist of a stable numeric prefix and an authored name.
        match = re.fullmatch(r'(\d+(?:\.\s*|[ ·—]+))(.+)', rendered)
        if match and match[2] in CATALOGS['en']:
            return match[1] + localized(match[2])
        match = re.fullmatch(r'(\d+) hours', rendered)
        if match:
            return localized('{v0} hours').format(v0=match[1])
        return rendered
    return format_option


def table_text(rows: list[dict]) -> list[dict]:
    """Translate headings and authored labels on copies, keeping source values untouched."""
    label_columns = {'Item', 'Area', 'Dimension', 'Field', 'Question', 'Measure', 'Status',
                     'Window', 'Snapshot', 'Blockers', 'Career'}
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

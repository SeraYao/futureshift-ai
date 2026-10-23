# Interface languages

The header places a compact globe selector to the right of the FutureShift title.
Streamlit stacks these columns on narrow screens. `ui_language` stores only `en`,
`zh` or `ms` in session state; a new session starts with `en`. Display names are
English / 中文 / Bahasa Melayu. Learning-language preference is a separate answer. Old display-name preferences are
migrated to canonical codes; an absent or obsolete preference starts in English.
This recovery never bypasses translation-catalog validation.

## Text inventory and ownership

| Surface | Presentation source | Translated content |
| --- | --- | --- |
| Header and mode navigation | app.py | Tagline, introduction, mode names, selector |
| Student intake and confirmation | src/pathway.py | All eight steps, questions, options, rating scales, validation, sample notices, results |
| Career results and simulation | app.py | Scenario explanations, coverage and gap tables, synthetic limitations, evidence labels |
| Four-week plan | src/learning_plan.py | Phases, authored exercises, evidence suggestions, schedule, progress, download notices |
| Profile reassessment | src/reassessment.py | Before/after explanations, change labels and measures |
| Evidence reassessment | src/evidence_reassessment.py | Refresh, cache labels, experimental rankings, career-switch confirmation |
| Plan transfer | src/plan_transfer.py | Upload, preview, validation errors, restore confirmation |
| CV intake | src/cv_intake.py | Upload limits, privacy, explicit consent, review, exclusions, manual fallback, safe error details |
| O*NET audit and GitHub activity | app.py | Audit headings, table columns, quality explanations, source/modification notices, activity windows |
| Domain errors | src/locales/diagnostics.py | Allowlisted application diagnostics, rendered through translate_error |

`src/locales/en.json`, `zh.json`, and `ms.json` use the original interface message
as a stable key. `src/i18n.py` validates equal key sets, nonempty values and matching
format placeholders at import and reloads/validates all three files before each page
render, because Streamlit may keep imported modules cached after locale files change.
The complete validated catalog replaces the old one atomically; invalid catalogs
still fail without an English fallback. `tr` logs missing runtime keys and returns a nonempty localized unavailable-text message; it never displays the raw key. Add each new authored
message to all three catalogs; do not introduce a locale conditional in a page.
Indirect labels (questionnaire enums, exercise templates and scales) are also
checked by tests. All modules calling translation helpers must explicitly import them.
The SDG detail heading uses the plain key `How this pathway can contribute to the SDGs`;
the renderer adds `#### ` after translation so Markdown formatting is not part of the key.

`tr` preserves interpolation values. `display_text` translates authored labels;
`translated_options` translates their presentation while preserving typed option
values and captures the render's locale so later widget serialization is stable.
`table_text` translates copied headings and selected authored label columns, never
scoring inputs or saved data. Unknown source values remain original, not assumed
to be interface messages. Application diagnostics are allowlisted separately.
External exception reasons remain verbatim after the translated wrapper.

## Original text and data

The three demonstration careers use manually reviewed project translations, keyed by immutable occupation codes: 数据科学家 / Saintis Data, 运筹分析师 / Penganalisis Penyelidikan Operasi, and 软件开发人员 / Pembangun Perisian. These are project display names, not claimed official translations. Original official titles remain available with source information.

O*NET identifiers and flags, occupation/element codes,
source attribution, source quotations, raw technical responses, formulas, queries,
URLs, timestamps, numeric scores and raw JSON stay original. Localized explanatory
captions identify official English titles and explain quality flags. CV evidence,
redacted input previews and user free text are never automatically translated.
The CV model prompt and payload, GitHub query construction, scoring functions,
career datasets and machine-readable JSON plan format/content are unchanged. A separate localized Markdown export includes readable names and instructions while retaining stable IDs and source URLs.

The authored virtual-example goal is translated for display only; user-entered goals remain verbatim.

Language changes perform no profile/workspace reset and no consent action. Existing
canonical career IDs and internal answer values remain stable. Main-flow selectboxes keep canonical session values separate from locale-specific browser widget keys, because Streamlit serializes formatted option strings. Option formatters also capture the render language. Tests exercise all
modes and intake steps, checked tasks, sample/manual profiles, reassessment snapshots,
restore previews and restored progress, with network calls blocked or mocked.

## Verification scope (2026-10-23)

160 regression tests pass. A real isolated Chrome session used the synthetic sample,
selected Data Scientists, completed one of eight tasks, and switched en → zh → ms.
The selected code, five-hour budget, ranking values, plan and 1/8 progress persisted.
Desktop results/rankings/plans and Chinese/Malay 390px plan screenshots were visually
reviewed; no garbled text or page overflow was observed. Main dropdown options and
readable/machine export behavior also have programmatic coverage. Other intake,
CV upload and restore screens have programmatic coverage only in this pass;
framework-owned upload text and broader visual review remain follow-up work.
No live AI request or trend refresh was needed or triggered by this localization check.

# Cross-domain careers and dynamic SDG evidence (2026-10-23)

## O*NET quality audit and current career coverage

The prior whole-career gate propagated every field-level issue to the occupation. This wrongly excluded Operations Research Analysts for Biology alone (LV `Not Relevant=Y`) and Information Security Analysts for Chemistry and Biology marked not relevant. O*NET 31.0 defines `Recommend Suppress` as an optional low-precision indicator and `Not Relevant` as an optional indicator that an element is not relevant to the occupation; neither indicator encodes a zero requirement. See the [official Knowledge dictionary](https://www.onetcenter.org/dictionary/31.0/csv/knowledge.html).

The importer accepts a blank optional `Recommend Suppress` only for Knowledge / Occupational Expert rows with N≥10, preserving the blank as unavailable precision. It does not accept explicit Y, unknown/missing rows, or LV relevance other than N/Y. In the matcher, a unique official LV row marked `Not Relevant=Y` is excluded from only that occupation's scoring denominator, and the page reports per-career coverage and warns that scores with different omitted dimensions are exploratory and not fully comparable. The LV data value (including a coincident low-precision flag) is never used. Other applicable suppressed elements, missing/duplicate rows, and unknown quality remain blocking. No missing/suppressed value is zero-filled.

| O*NET-SOC | Career | Current outcome / coverage | Remaining exclusion reason |
| --- | --- | --- | --- |
| 13-1199.05 | Sustainability Specialists | Eligible · 11/11 skills, 7/7 knowledge, 6/6 interests | — |
| 15-1211.00 | Computer Systems Analysts | Excluded | Physics LV suppressed; applicable dimension |
| 15-1212.00 | Information Security Analysts | Eligible, partial · 11/11, 5/7, 6/6 | Chemistry and Biology are Not Relevant; partial score |
| 15-1252.00 | Software Developers | Excluded | Programming, Science, Operations Analysis skill LV values suppressed |
| 15-2031.00 | Operations Research Analysts | Eligible, partial · 11/11, 6/7, 6/6 | Biology is Not Relevant; partial score |
| 15-2051.00 | Data Scientists | Excluded | Science, Programming and Systems Analysis skill LV values suppressed |
| 17-2081.00 | Environmental Engineers | Eligible · 11/11, 7/7, 6/6 | — |
| 17-2199.03 | Energy Engineers, Except Wind and Solar | Eligible · 11/11, 7/7, 6/6 | — |
| 17-2199.08 | Robotics Engineers | Eligible · 11/11, 7/7, 6/6 | — |
| 19-1029.01 | Bioinformatics Scientists | Excluded | Programming skill LV suppressed |

Six occupations are currently rankable: sustainability, information security (partial), operations research (partial), environmental engineering, energy engineering, and robotics. They span organisational, computing, analytical, environmental, energy, and robotics work. The remaining four are excluded for unresolved applicable suppressed ratings. Missing occupation evidence is not interpreted as no skill/knowledge need. The questionnaire only measures eleven skills, seven knowledge areas, and RIASEC; experience, credentials, and unasked dimensions remain unassessed.

Personal-fit formula remains the existing `rank_roles` formula (70% capability + 30% interest; capability 75% skills + 25% knowledge). Knowledge weights are normalized over the applicable, quality-usable items for each occupation. Partial-coverage scores can be less comparable; this is disclosed beside the results with exact coverage and omitted Not Relevant labels. No trend adjustment enters these official rankings. The existing synthetic three-career mode remains separate, with explicitly synthetic requirements/trends. New sessions default to official cross-domain careers; returning assessments keep their prior selected mode.

## SDG context and boundary

`sdg_context.json` contains source-preserved tasks for the ten original careers,
the eighteen official element definitions and seven checked UN targets (6.3, 7.3,
9.4, 9.5, 12.2, 12.5, 12.6). It is a bounded target catalog, not all 169 targets.
Official task download: first response was truncated; one cache-bypassing request
returned the complete CSV (18,838 records, retained SHA-256), then extraction passed
shape/completeness checks. No unverified partial download was used.

`src/sdg_ai.py` supplies only public task/definition records and career/area IDs,
never profile answers, CVs or contact information. Analyses are explicitly requested
for each recommended career and its actual budget-selected practice areas. The
same skill in another career has its own tasks, context and cache key. A scenario
is grounded in a supplied task ID; text is conditional AI inference, not a verified
causal contribution. The model must give a status for every requested item,
including `insufficient_evidence` where no defensible link exists.

Validation requires exact item coverage, legal targets, task ownership, source IDs,
matching skill evidence and all three language texts. Unknown/duplicate items,
missing sources, URLs, undeclared statistics and inconsistent unsupported claims
are rejected. Official source text is displayed verbatim with local explanations;
source validity does not establish semantic/causal validity of model explanations.
There is no SDG preference weight, contribution score or change to matching math.

Persistent cache keys include career, actual practice areas, task/scenario context,
all supplied source content, model, endpoint hash, prompt and validator versions.
Cache reads never request inference. Failed requests are not cached as success;
UI remembers the failure and offers manual retry without changing profile/plan.
Successful results contain en/zh/ms together, so language changes do not regenerate
or reinterpret the analysis. Qwen3's documented `/no_think` soft switch is used
only for that configured model family; no provider/model or timeout was changed.

Qwen model reference: https://github.com/QwenLM/Qwen3/blob/main/README.md

## Verification (updated at delivery)

Phase one: 165 regression tests pass. With SDG validation/cache/manual retry tests:
178 regression tests pass (includes mocked transport negative cases, not proof of
live AI success). Isolated real Chrome checked en → zh → ms official ranking,
selected energy career, five-hour plan and 1/8 progress; numeric ranks/scores were
unchanged. Desktop Chinese ranking and Malay narrow-screen plan were visually
reviewed, without page overflow or garbled text. Broader pages are program-tested.

### Real AI evidence (separate from mocked tests)

The existing Qwen/Qwen3-8B configuration was retained, with 300-second client
timeout and 4,200 maximum output tokens. No timeout increase, TLS relaxation,
model/provider switch, automatic retry or personal-data transmission was used.
The corrected generation contract received HTTP 200 in 19.53 seconds, completed
normally (`finish_reason=stop`, 923 completion tokens), and returned three entries:

| Item | Status | Task / target / supporting source IDs |
| --- | --- | --- |
| 17-2199.03 (energy career) | linked AI inference | onet-task:17-2199.03:20854; un-target:7.3; onet-rating:17-2199.03:knowledge_02 |
| knowledge_02 (mathematics knowledge) | linked AI inference | onet-task:17-2199.03:20854; un-target:7.3; onet-rating:17-2199.03:knowledge_02 |
| skill_03 (mathematics skill) | linked AI inference | onet-task:17-2199.03:20854; un-target:7.3; onet-rating:17-2199.03:skill_03 |

These are the actual supplied official task (recommending energy-saving strategies),
UN energy-efficiency target and role-specific element sources. A validator initially
rejected the career's citation of its own mathematics knowledge as if it belonged
to a different skill. That false positive was corrected and regression-tested;
individual skill entries still cannot cite another skill's rating. Exact declared
item/target/task IDs and the official target deadline are distinguished from invented
statistics. Earlier generation attempts missing mandatory citations were rejected;
source requirements were strengthened rather than bypassed.

The retained **real HTTP response**, without editing its contents or substituting a
mock, was revalidated through the corrected production validator and written to the
production cache. No additional inference was sent for that revalidation. A second
cache operation forbidding any generator invocation returned the same record.
This proves real transport/JSON + corrected validation + persistent cache, rather
than claiming an untested uninterrupted first-attempt success.

Real Chrome subsequently displayed that cached result and source links in en, zh
and ms; career, five-hour budget, numerical rankings and 1/8 task progress remained
unchanged. Chinese SDG detail and Malay source detail were visually reviewed.
The other three official careers remain explicitly not analysed until their own
manual request. Their AI output quality has not been proven by this single-career
live check. Failure/retry and unsupported-result branches were tested with injected
errors/responses; no remote outage was deliberately induced.

Remaining boundaries: seven selected targets rather than all 169; four eligible
careers rather than a general labour-market catalog; unknown unasked qualifications;
no comparable hiring trend evidence; original authored practice templates cover only
part of the new cross-domain gaps (unsupported exercises are explicitly excluded).
AI semantic/causal truth and translations are not certified by source-ID checks.
Framework upload text and non-main-flow visual review remain outside this pass.


### Unasked knowledge limits by eligible career

Official high-importance knowledge outside the questionnaire (examples; source labels retained):

| Career | Unasked knowledge examples |
| --- | --- |
| Sustainability Specialists | Law and Government, Education and Training, English Language, Building and Construction |
| Environmental Engineers | Design, Building and Construction, English Language, Customer and Personal Service |
| Energy Engineers, Except Wind and Solar | Mechanical, Building and Construction, Design, English Language |
| Robotics Engineers | Design, Mechanical, English Language, Production and Processing |


## Changed files

- Import/provenance: `scripts/prepare_onet.py`, `data/onet_roles.json`,
  `scripts/prepare_sdg_context.py`, `data/sdg_context.json`.
- Main flow and compatibility: `src/career_pool.py`, `src/pathway.py`, `app.py`,
  `src/learning_plan.py`, `src/plan_transfer.py`.
- AI/provenance/cache presentation: `src/sdg_ai.py`, `src/sdg.py`,
  `src/cv_client.py` (shared transport and safe response metadata), `.gitignore`.
- Localisation: `src/i18n.py`, `src/locales/en.json`, `zh.json`, `ms.json`.
- Validation: `scripts/check_sdg_service.py`, `tests/test_career_pool.py`,
  `tests/test_sdg_ai.py`, `tests/test_i18n.py`, `tests/test_modes.py`,
  `tests/ui_helpers.py` (legacy workflows explicitly choose the synthetic demo).
- This report: `docs/CROSS_DOMAIN_SDG.md`.

Final local service: `http://127.0.0.1:8514/`; HTTP 200 and health `ok` verified.
No commit or push was performed. The service remains running.

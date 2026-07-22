# Evidence Extraction and Research Writing MVP Acceptance

## 1. Acceptance Result

The two agents have completed a real OpenCode run against review project `#5` and stopped at the intended external human-review gates.

| Agent | Workflow run | Persisted result | Status |
|---|---|---|---|
| `evidence-extraction-agent` | `afd37ee79a57465aa2d27f028efee796` | Full text documents, detailed outcome data, RoB 2 assessments, binary meta-analysis `#5` | `approval_pending` |
| `research-writing-agent` | `88d7458f16ad46b597b5bbc1db02cab3` | Discussion draft `#9`, version `3` | `approval_pending` |

The agents did not approve or export their own work.

## 2. Evidence Extraction Run

Review project `#5` concerns the research question:

> In hospitalized adults with COVID-19, what is the effect of hydroxychloroquine versus usual care or open control on 28-day all-cause mortality?

Included citations were local citation IDs `8` and `9`:

- PMID `33031652`, RECOVERY trial, controlled full text `PMC7556338`, local full-text document `#3`.
- PMID `33264556`, WHO Solidarity trial, controlled full text `PMC7727327`, local full-text document `#4`.

The controlled full-text tool verified the PMID and DOI against the local citation before persistence. The workflow then saved structured binary outcome counts and RoB 2 assessments tied to each full-text document.

The final saved random-effects synthesis in Meta run `#5` is:

- pooled RR `1.09`
- 95% CI `0.99-1.20`
- `I2 = 0.0%`
- `Q = 0.41`, heterogeneity `p = 0.52`
- pooled `p = 0.077`
- two studies

This result is preliminary and remains marked `needs_human_review=true`. It is not a clinical recommendation.

The evidence workflow recorded and re-verified these Skill receipts:

`clinical-study-info-extractor`, `methodology-extractor`, `retraction-watcher`, `meta-screening-fulltext`, `fulltext-fetcher`, `baseline-extraction-for-clinical-trials`, `outcome-extraction-for-clinical-trials`, `rct-bias-assessment-rob`, `meta-analysis`, and `meta-forest-binary-plot`.

## 3. Research Writing Run

The writing Agent read the persisted review source, including the saved full-text detail rows, RoB 2 assessments, and newest Meta result. It invoked:

- `biomed-outline-generator`
- `method-writing`
- `discussion-section-architect`

It saved discussion draft `#9` with a source manifest bound to `review#5`. The draft explicitly states that the pooled result requires statistical and clinical review and does not provide clinical advice. The three Skill receipts were verified in the database for workflow run `88d7458f16ad46b597b5bbc1db02cab3`; both workflow receipt sets were re-validated with the configured HMAC key.

## 4. Human Approval Gate

Both approval records are intentionally `pending`:

1. An authorized researcher must review the extracted fields, full-text locations, RoB 2 judgments, and event counts.
2. The researcher must review the pooled estimate and forest plot.
3. The writing draft can then be approved through the protected REST endpoint.
4. Only after approval should the corresponding export tool be called.

The Agent cannot approve its own evidence or writing output.

## 5. Verification

- Backend test suite: `34 passed`.
- Medical research Agent Skill contract checks: passed.
- Receipt plugin JavaScript syntax check: passed.
- Skill synchronization shell syntax check: passed.
- `git diff --check`: passed.

The system is now runnable as an MVP. The remaining work is researcher review and approval, not an unimplemented Agent step.

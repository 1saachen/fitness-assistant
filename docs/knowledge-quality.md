# Knowledge quality and governance

Run the audit and report together:

```text
python -m fitness.evaluation_cli --output-dir data/evaluation/reports
```

`fitness.governance.audit_knowledge` reloads the approved manifest and the production strategy artifact. It verifies source referential integrity, strategy membership coverage, persisted counts, duplicate IDs, and the membership snapshot in `data/evaluation/membership.json`. A missing or invalid manifest is reported as `unavailable` with `coverage: null`; it is never reported as full coverage. A changed card, collection, source, or content fingerprint produces `review_required`, even when the total card count is unchanged.

The snapshot also stores each strategy's source-card IDs. Moving or removing a source from one strategy requires review even when another strategy still covers that card and total coverage remains 74. The report command exits 0 for unchanged valid governance, 1 when membership requires review, and 2 for unavailable governance. An unavailable run removes stale retrieval report files from its output directory so an old successful result cannot appear current.

Full strategy content fingerprints also detect changes to summary, action rules, applicability, limitations or safety boundaries when card membership stays unchanged. A narrow automated heuristic flags explicit Chinese permission to automatically generate or recommend individual doses as `review_required`, even after a fingerprint refresh. Such a finding requires human review and is not medical proof; absence of a finding does not establish safe dosing or validate all possible wording.

The report keeps three provenance layers separate:

1. **Creator statement** is the claim or summary attributed to the source video. `creator_opinion` and the existing evidence label describe provenance; approval does not turn a creator statement into medical consensus.
2. **Editorial strategy** is a reviewed synthesis that chooses conservative action rules and applicability from cards. It records source membership and a safety boundary. It does not upgrade evidence or independently validate efficacy.
3. **System judgement** is deterministic issue extraction, ranking, deduplication, and bounded context assembly from user facts. It is a software decision layer, not a diagnosis or clinical validation.

Every supplement card receives an automated checklist for source presence, editorial note, explanation, and safety metadata, plus a required human checklist: verify transcript/ASR ambiguity; verify independent evidence and applicability; assess conditions, medications, and special populations; check dose, interaction, and product quality statements; preserve uncertainty and never generate an individual dose or purchase recommendation. The checklist is evidence that review work is required, not evidence that it has been completed.

The current corpus contains 74 approved cards, all from creator opinion sources: 68 `experience` evidence labels and six `limited` labels. On 2026-10-11 an editorial metadata cleanup replaced 66 stale pending-state explanation sentences with the approved conservative-summary status and an explicit statement that approval does not upgrade evidence. Claims, source attribution, evidence labels and strategy membership stayed unchanged; the membership snapshot records this review basis. The audit detects future stale pending strings. Automated checks cannot establish efficacy, correct ASR errors, establish a safe dose, or substitute for professional assessment. Changes to the membership manifest and strategy artifact require an explicit editorial review and a new reproducible report.

# Retrieval evaluation

Approved cards: 74

Keyword baseline is the actual issue-aware KnowledgeContextService; TF-IDF is a lexical candidate, not an embedding model.

| Metric | Keyword | TF-IDF |
| --- | ---: | ---: |
| case_count | 14 | 14 |
| issue_count | 15 | 15 |
| preferred_collection_hit_rate | 1.0 | 1.0 |
| top3_coverage | 0.8666666666666667 | 0.6222222222222222 |
| misleading_recall_count | 0 | 6 |
| misleading_recall_rate | 0.0 | 0.13333333333333333 |
| unexpected_issue_count | 0 | 0 |
| missing_issue_count | 0 | 0 |
| unavailable_case_count | 0 | 0 |
| invalid_retrieval_case_count | 0 | 0 |
| cross_issue_overlap_cases | 2 | not assessed |
| cross_issue_dedup_success_rate | 1.0 | not assessed |
| duplicate_citations_saved | 2 | not assessed |

## Per-case results

| Case / issue | Method | Ranked cards | Expected top-3 coverage | Misleading cards |
| --- | --- | --- | ---: | --- |
| short-sleep / short_sleep | keyword | mvp-sleep_recovery-005, mvp-sleep_recovery-006, mvp-sleep_recovery-001 | 0.500 | none |
| health-sleep / short_sleep | keyword | mvp-sleep_recovery-005, mvp-sleep_recovery-006, mvp-sleep_recovery-001 | 0.500 | none |
| training-fatigue / training_fatigue | keyword | mvp-training-010, mvp-training-011, mvp-sleep_recovery-005 | 1.000 | none |
| food-recording / diet_adherence | keyword | mvp-diet_fat_loss-006, mvp-diet_fat_loss-016, mvp-diet_fat_loss-009, mvp-diet_fat_loss-015 | 0.333 | none |
| muscle-protein / diet_adherence | keyword | mvp-diet_fat_loss-006, mvp-diet_fat_loss-016, mvp-diet_fat_loss-009, mvp-diet_fat_loss-015 | 1.000 | none |
| confirmed-plateau / weight_trend | keyword | mvp-diet_fat_loss-010, mvp-diet_fat_loss-002 | 1.000 | none |
| confirmed-plateau / weight_plateau | keyword | mvp-diet_fat_loss-012, mvp-diet_fat_loss-002, mvp-diet_fat_loss-005, mvp-diet_fat_loss-008 | 0.667 | none |
| draft-is-not-plateau / weight_trend | keyword | mvp-diet_fat_loss-010, mvp-diet_fat_loss-002 | 1.000 | none |
| magnesium-vitamin-d / supplement_question | keyword | mvp-supplements-006, mvp-supplements-018, mvp-supplements-025 | 1.000 | none |
| omega-case-fold / supplement_question | keyword | mvp-supplements-017, mvp-supplements-019, mvp-supplements-011 | 1.000 | none |
| sleep-patch / supplement_question | keyword | couren-sleep-patch-20260914, mvp-supplements-019, mvp-supplements-011 | 1.000 | none |
| multiple-issues / short_sleep | keyword | mvp-sleep_recovery-005, mvp-sleep_recovery-006, mvp-sleep_recovery-001 | 1.000 | none |
| multiple-issues / training_fatigue | keyword | mvp-training-010, mvp-training-011, mvp-sleep_recovery-005 | 1.000 | none |
| multiple-issues / diet_adherence | keyword | mvp-diet_fat_loss-006, mvp-diet_fat_loss-016, mvp-diet_fat_loss-009, mvp-diet_fat_loss-015 | 1.000 | none |
| multiple-issues / supplement_question | keyword | mvp-supplements-018, couren-magnesium-deficiency-20260914, mvp-supplements-019 | 1.000 | none |
| unrelated-study | keyword | unexpected issues: [] | n/a | n/a |
| iron-metaphor | keyword | unexpected issues: [] | n/a | n/a |
| healthy-empty | keyword | unexpected issues: [] | n/a | n/a |
| short-sleep / short_sleep | tfidf | mvp-sleep_recovery-005, couren-sleep-patch-20260914, couren-magnesium-deficiency-20260914 | 0.500 | none |
| health-sleep / short_sleep | tfidf | couren-sleep-habits-first-20260914, mvp-sleep_recovery-005, couren-sleep-patch-20260914 | 0.500 | none |
| training-fatigue / training_fatigue | tfidf | mvp-supplements-022, mvp-training-010, mvp-supplements-028 | 0.500 | mvp-supplements-022, mvp-supplements-028 |
| food-recording / diet_adherence | tfidf | mvp-diet_fat_loss-007, mvp-diet_fat_loss-016, mvp-diet_fat_loss-015 | 1.000 | none |
| muscle-protein / diet_adherence | tfidf | mvp-diet_fat_loss-007, mvp-training-013, mvp-diet_fat_loss-009 | 0.500 | none |
| confirmed-plateau / weight_trend | tfidf | mvp-diet_fat_loss-002, mvp-diet_fat_loss-010, mvp-training-013 | 1.000 | none |
| confirmed-plateau / weight_plateau | tfidf | mvp-diet_fat_loss-002, mvp-training-013, mvp-diet_fat_loss-012 | 0.333 | none |
| draft-is-not-plateau / weight_trend | tfidf | mvp-diet_fat_loss-002, mvp-diet_fat_loss-010, mvp-diet_fat_loss-011 | 1.000 | none |
| magnesium-vitamin-d / supplement_question | tfidf | couren-vitamin-d-sleep-20260914, mvp-supplements-025, mvp-supplements-002 | 0.000 | none |
| omega-case-fold / supplement_question | tfidf | mvp-supplements-026, mvp-supplements-017, mvp-supplements-009 | 1.000 | none |
| sleep-patch / supplement_question | tfidf | couren-sleep-patch-20260914, couren-tart-cherry-sleep-20260914, couren-vitamin-d-sleep-20260914 | 1.000 | none |
| multiple-issues / short_sleep | tfidf | couren-magnesium-deficiency-20260914, mvp-sleep_recovery-005, couren-sleep-patch-20260914 | 1.000 | none |
| multiple-issues / training_fatigue | tfidf | mvp-supplements-022, mvp-training-010, couren-magnesium-deficiency-20260914 | 0.500 | mvp-supplements-022, couren-magnesium-deficiency-20260914 |
| multiple-issues / diet_adherence | tfidf | mvp-diet_fat_loss-007, mvp-diet_fat_loss-015, mvp-diet_fat_loss-009 | 0.000 | none |
| multiple-issues / supplement_question | tfidf | couren-magnesium-deficiency-20260914, mvp-training-010, mvp-diet_fat_loss-007 | 0.500 | mvp-training-010, mvp-diet_fat_loss-007 |
| unrelated-study | tfidf | unexpected issues: [] | n/a | n/a |
| iron-metaphor | tfidf | unexpected issues: [] | n/a | n/a |
| healthy-empty | tfidf | unexpected issues: [] | n/a | n/a |

## Embedding decision

No embedding benefit measured. Defer vector infrastructure.
TF-IDF is not learned semantic embedding evidence. The small synthetic regression suite is not a clinical/user benchmark.

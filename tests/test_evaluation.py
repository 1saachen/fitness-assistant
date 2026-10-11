import json
from importlib import import_module
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def evaluation():
    return import_module("fitness.evaluation")


def test_committed_cases_exercise_real_service_and_nontrivial_labels():
    module = evaluation()
    cases = module.load_cases(ROOT / "data/evaluation/retrieval-cases.json")
    report = module.evaluate_retrieval(ROOT / "data/knowledge", cases)
    assert report["corpus"]["approved_cards"] == 74
    assert report["keyword"]["metrics"]["issue_count"] >= 12
    assert {case.category for case in cases} >= {
        "sleep", "fatigue", "diet", "plateau", "supplements", "unrelated", "multi_issue",
    }
    assert all(case.split == "held_out" for case in cases)
    assert report["keyword"]["metrics"]["cross_issue_dedup_success_rate"] == 1
    assert report["keyword"]["metrics"]["misleading_recall_count"] == 0
    assert report["embedding_assessment"]["measured"] is False
    assert report["tfidf"]["is_embedding_model"] is False
    assert len(report["tfidf"]["cases"]) == len(cases)


def test_metrics_use_ranked_issues_not_manifest_order_and_count_unexpected_issues():
    from fitness.knowledge_context import KnowledgeContextResult, RetrievalIssue

    module = evaluation()
    case = module.EvaluationCase.model_validate({
        "id": "rank", "category": "diet", "raw_text": "", "feedback": {},
        "issues": [{"id": "diet_adherence", "preferred_collections": ["fat_loss"],
                    "expected_ids": ["good"], "forbidden_collections": ["supplements"]}],
    })
    result = KnowledgeContextResult(issues=(
        RetrievalIssue("diet_adherence", "diet", (), (), ("bad", "other", "third", "good")),
        RetrievalIssue("unexpected", "unexpected", (), (), ("bad",)),
    ))
    manifest = [{"id": item, "collection": collection} for item, collection in [
        ("good", "fat_loss"), ("bad", "supplements"), ("other", "training"), ("third", "training"),
    ]]
    scored = module.score_case(case, result, manifest)
    assert scored["issues"][0]["top3_coverage"] == 0
    assert scored["issues"][0]["preferred_collection_hit"] is False
    assert scored["issues"][0]["misleading_ids"] == ["bad"]
    assert scored["unexpected_issue_ids"] == ["unexpected"]


def test_labels_reject_missing_or_contradictory_ids(tmp_path):
    module = evaluation()
    cases = module.load_cases(ROOT / "data/evaluation/retrieval-cases.json")
    changed = cases[0].model_copy(deep=True)
    changed.issues[0].expected_ids = ["not-in-corpus"]
    with pytest.raises(ValueError, match="unknown labeled"):
        module.evaluate_retrieval(ROOT / "data/knowledge", [changed])
    changed.issues[0].expected_ids = ["mvp-sleep_recovery-005"]
    changed.issues[0].forbidden_collections = ["sleep_recovery"]
    with pytest.raises(ValueError, match="contradictory"):
        module.evaluate_retrieval(ROOT / "data/knowledge", [changed])


def test_tfidf_uses_only_corpus_and_query_no_expected_labels():
    module = evaluation()
    corpus = [{"id": "sleep", "text": "睡眠不足需要恢复"},
              {"id": "diet", "text": "蛋白质饮食记录"},
              {"id": "noise", "text": "无关项目"}]
    index = module.CharacterTfidf(corpus)
    assert index.search("睡眠恢复")[0] == "sleep"
    assert index.search("abcdefgh") == ()


def test_report_cli_writes_reproducible_json_and_markdown(tmp_path):
    cli = import_module("fitness.evaluation_cli")
    assert cli.main(["--knowledge-root", str(ROOT / "data/knowledge"),
                     "--cases", str(ROOT / "data/evaluation/retrieval-cases.json"),
                     "--membership", str(ROOT / "data/evaluation/membership.json"),
                     "--output-dir", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "retrieval-report.json").read_text(encoding="utf-8"))
    assert report["keyword"]["metrics"]["case_count"] >= 10
    markdown = (tmp_path / "retrieval-report.md").read_text(encoding="utf-8")
    assert "TF-IDF" in markdown and "embedding" in markdown
    assert "training-fatigue" in markdown
    assert (tmp_path / "governance-report.json").exists()


def test_cli_unavailable_does_not_leave_stale_retrieval_reports(tmp_path):
    cli = import_module("fitness.evaluation_cli")
    for name in ("retrieval-report.json", "retrieval-report.md"):
        (tmp_path / name).write_text("stale success", encoding="utf-8")
    assert cli.main(["--knowledge-root", str(tmp_path / "missing"),
                     "--output-dir", str(tmp_path)]) == 2
    assert not (tmp_path / "retrieval-report.json").exists()
    assert not (tmp_path / "retrieval-report.md").exists()


@pytest.mark.parametrize("content", ["{broken", "{}", "[]", '{"cases":[{"id":"bad"}]}'])
def test_cli_invalid_cases_returns_error_and_removes_stale_reports(tmp_path, content):
    cli = import_module("fitness.evaluation_cli")
    cases = tmp_path / "cases.json"
    cases.write_text(content, encoding="utf-8")
    for name in ("retrieval-report.json", "retrieval-report.md"):
        (tmp_path / name).write_text("stale success", encoding="utf-8")
    assert cli.main(["--knowledge-root", str(ROOT / "data/knowledge"),
                     "--membership", str(ROOT / "data/evaluation/membership.json"),
                     "--cases", str(cases), "--output-dir", str(tmp_path)]) == 2
    assert not (tmp_path / "retrieval-report.json").exists()
    assert not (tmp_path / "retrieval-report.md").exists()
    assert json.loads((tmp_path / "evaluation-error.json").read_text())["status"] == "invalid"


def test_unknown_retriever_id_is_invalid_result_not_key_error():
    from fitness.knowledge_context import KnowledgeContextResult, RetrievalIssue

    module = evaluation()
    case = module.EvaluationCase.model_validate({"id": "unknown", "category": "sleep", "issues": [
        {"id": "short_sleep", "preferred_collections": ["sleep_recovery"], "expected_ids": ["sleep"]},
    ]})
    result = KnowledgeContextResult(issues=(RetrievalIssue("short_sleep", "sleep", (), (), ("missing",)),))
    scored = module.score_case(case, result, [{"id": "sleep", "collection": "sleep_recovery"}])
    assert scored["status"] == "invalid_retrieval"
    assert scored["unknown_retrieval_ids"] == ["missing"]
    assert scored["issues"][0]["top3_coverage"] == 0

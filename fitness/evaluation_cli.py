"""Run local retrieval and governance reports without provider/network access."""

import argparse
import json
from pathlib import Path

from .evaluation import evaluate_retrieval, load_cases
from .governance import audit_knowledge


def retrieval_markdown(report: dict) -> str:
    lines = ["# Retrieval evaluation", "", f"Approved cards: {report['corpus']['approved_cards']}", "",
             "Keyword baseline is the actual issue-aware KnowledgeContextService; TF-IDF is a lexical candidate, not an embedding model.",
             "", "| Metric | Keyword | TF-IDF |", "| --- | ---: | ---: |"]
    for key, value in report["keyword"]["metrics"].items():
        lines.append(f"| {key} | {value} | {report['tfidf']['metrics'].get(key, 'not assessed')} |")
    lines.extend(["", "## Per-case results", "", "| Case / issue | Method | Ranked cards | Expected top-3 coverage | Misleading cards |",
                  "| --- | --- | --- | ---: | --- |"])
    for method in ("keyword", "tfidf"):
        for case in report[method]["cases"]:
            for issue in case["issues"]:
                lines.append(f"| {case['id']} / {issue['id']} | {method} | {', '.join(issue['ranked_ids'])} | {issue['top3_coverage']:.3f} | {', '.join(issue['misleading_ids']) or 'none'} |")
            if not case["issues"]:
                lines.append(f"| {case['id']} | {method} | unexpected issues: {case['unexpected_issue_ids']} | n/a | n/a |")
    lines.extend(["", "## Embedding decision", "", "No embedding benefit measured. Defer vector infrastructure.",
                  "TF-IDF is not learned semantic embedding evidence. The small synthetic regression suite is not a clinical/user benchmark.", ""])
    return "\n".join(lines)


def governance_markdown(report: dict) -> str:
    lines = ["# Knowledge governance", "", f"Status: {report['status']}", "",
             f"Strategy coverage: {report['coverage']}", ""]
    if report["status"] == "unavailable":
        return "\n".join(lines + report["errors"]) + "\n"
    for name, layer in report["provenance_layers"].items():
        lines.append(f"- {name}: {layer['description']}")
    lines.extend(["", f"Source types: {report['source_type_counts']}",
                  f"Evidence labels: {report['evidence_level_counts']}",
                  f"Membership changes: {report['membership_changes']}",
                  f"Strategy safety findings requiring human review: {report['strategy_safety_findings']}",
                  f"Approved cards retaining stale pending explanation: {len(report['stale_pending_explanation_ids'])}",
                  "", "Approval does not establish medical consensus. Automated checks do not verify efficacy or transcript accuracy.",
                  "", "## Supplement checklist", "", "| Card | Evidence | Metadata checks | Required human review |",
                  "| --- | --- | --- | --- |"])
    for row in report["supplement_reviews"]:
        lines.append(f"| {row['id']} | {row['evidence_level']} | {row['automated_checks']} | {'; '.join(row['requires_human_review'])} |")
    lines.extend(["", "## Limitations", ""] + [f"- {text}" for text in report["limitations"]])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-root", type=Path, default=Path("data/knowledge"))
    parser.add_argument("--cases", type=Path, default=Path("data/evaluation/retrieval-cases.json"))
    parser.add_argument("--membership", type=Path, default=Path("data/evaluation/membership.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/evaluation/reports"))
    args = parser.parse_args(argv)
    governance = audit_knowledge(args.knowledge_root, args.membership)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("retrieval-report.json", "retrieval-report.md", "evaluation-error.json"):
        (args.output_dir / name).unlink(missing_ok=True)
    (args.output_dir / "governance-report.json").write_text(json.dumps(governance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "governance-report.md").write_text(governance_markdown(governance), encoding="utf-8")
    if governance["status"] == "unavailable":
        for name in ("retrieval-report.json", "retrieval-report.md"):
            (args.output_dir / name).unlink(missing_ok=True)
        return 2
    try:
        report = evaluate_retrieval(args.knowledge_root, load_cases(args.cases))
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        diagnostic = {"status": "invalid", "error": f"{type(error).__name__}: {error}"}
        (args.output_dir / "evaluation-error.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        return 2
    (args.output_dir / "retrieval-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "retrieval-report.md").write_text(retrieval_markdown(report), encoding="utf-8")
    return 1 if governance["status"] == "review_required" else 0


if __name__ == "__main__":
    raise SystemExit(main())

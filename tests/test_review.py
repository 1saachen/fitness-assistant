import json
from pathlib import Path

import pytest

from fitness.knowledge import build_manifest, load_knowledge, load_sources
from fitness.review import ReviewService, ReviewValidationError


def candidate(card_id="supplements-001", collection="supplements"):
    return {
        "id": card_id,
        "collection": collection,
        "title": "肌酸与力量",
        "creator_statement": [{
            "statement": "作者认为肌酸可用于力量训练。",
            "source_claim_ids": ["bili:BVtest001:1"],
        }],
        "source_claim_ids": ["bili:BVtest001:1"],
        "source_bvids": ["BVtest001"],
        "uncertainty": "待复核",
        "safety_boundary": "不构成个人医疗建议。",
        "review_status": "pending",
    }


def write_fixture(tmp_path):
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(json.dumps({"cards": [candidate(), candidate("diet_fat_loss-001", "diet_fat_loss")]}, ensure_ascii=False), encoding="utf-8")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps({"videos": [{
        "bvid": "BVtest001", "url": "https://example.com/BVtest001",
        "title": "测试视频", "owner_name": "测试创作者", "published_date": "2026-09-20"
    }]}, ensure_ascii=False), encoding="utf-8")
    return ReviewService(candidate_path, tmp_path / "decisions.json", tmp_path / "knowledge", catalog_path)


def test_candidates_start_pending_and_decision_persists(tmp_path):
    service = write_fixture(tmp_path)
    assert service.summary()["pending"] == 2
    saved = service.review("supplements-001", "approved", "来源清晰")
    assert saved["status"] == "approved"
    reloaded = write_fixture(tmp_path)
    assert reloaded.summary()["approved"] == 1


def test_unknown_card_and_invalid_status_are_rejected(tmp_path):
    service = write_fixture(tmp_path)
    with pytest.raises(ReviewValidationError):
        service.review("missing", "approved", "")
    with pytest.raises(ReviewValidationError):
        service.review("supplements-001", "published", "")


def test_publish_materializes_only_approved_cards(tmp_path):
    service = write_fixture(tmp_path)
    before = service.publish()
    assert before["published_cards"] == 0
    service.review("supplements-001", "approved", "通过")
    result = service.publish()
    assert result["published_cards"] == 1
    items = json.loads((tmp_path / "knowledge" / "supplements" / "mvp-approved.json").read_text(encoding="utf-8"))
    assert len(items) == 1
    assert items[0]["review_status"] == "approved"
    assert json.loads((tmp_path / "knowledge" / "fat_loss" / "mvp-approved.json").read_text(encoding="utf-8")) == []


def test_real_candidates_publish_with_complete_video_traceability(tmp_path):
    project_root = Path(__file__).parents[1]
    candidate_path = (
        project_root
        / "data/ingest/bilibili-20260916/mvp-final-card-candidates.json"
    )
    catalog_path = (
        project_root
        / "data/ingest/bilibili-20260916/nutrition-era-catalog.json"
    )
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text(
        json.dumps(
            {
                "version": 1,
                "decisions": {
                    card["id"]: {"status": "approved", "note": "集成验证"}
                    for card in payload["cards"]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service = ReviewService(
        candidate_path,
        decisions_path,
        tmp_path / "knowledge",
        catalog_path,
    )

    result = service.publish()
    sources = load_sources(service.knowledge_root)
    items = load_knowledge(service.knowledge_root)
    manifest = build_manifest(service.knowledge_root)

    assert result == {"published_cards": 66, "published_sources": 66}
    assert len(sources) == len(items) == len(manifest) == 66
    cards_by_id = {card["id"]: card for card in payload["cards"]}
    for source_id, source in sources.items():
        card = cards_by_id[source_id.removeprefix("mvp-card-source-")]
        assert [video.bvid for video in source.videos] == card["source_bvids"]
        assert all(video.url.endswith(video.bvid) for video in source.videos)

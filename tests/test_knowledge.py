import json

import pytest

from fitness.knowledge import KnowledgeItem, build_manifest, load_knowledge, search_knowledge


def test_knowledge_item_requires_source_and_uses_collection():
    item = KnowledgeItem(
        id="training-001",
        collection="training",
        title="保留主要动作强度",
        claim="减脂期间保留主要动作的训练强度。",
        source_id="creator-a-video-001",
        source_type="creator_opinion",
        evidence_level="experience",
        review_status="approved",
        timestamp_start=84,
        timestamp_end=132,
        tags=["减脂", "力量保持"],
    )
    assert item.collection == "training"
    assert "保留主要动作" in item.embedding_text()


def test_sleep_recovery_is_a_supported_collection():
    item = KnowledgeItem(
        id="sleep-001", collection="sleep_recovery", title="睡眠与恢复",
        claim="睡眠会影响恢复。", source_id="creator-a-video-001",
        source_type="creator_opinion", evidence_level="experience",
    )
    assert item.collection == "sleep_recovery"


def test_unapproved_items_are_excluded_from_manifest(tmp_path):
    root = tmp_path / "knowledge"
    (root / "sources").mkdir(parents=True)
    (root / "training").mkdir()
    (root / "sources" / "creator-a-video-001.json").write_text(
        json.dumps({
            "id": "creator-a-video-001",
            "creator_name": "示例创作者",
            "video_url": "https://example.com/video/1",
            "video_title": "示例训练视频",
        }, ensure_ascii=False), encoding="utf-8"
    )
    (root / "training" / "items.json").write_text(json.dumps([
        {"id":"approved","collection":"training","title":"已审核","claim":"保留强度","source_id":"creator-a-video-001","source_type":"creator_opinion","evidence_level":"experience","review_status":"approved"},
        {"id":"pending","collection":"training","title":"待审核","claim":"暂不使用","source_id":"creator-a-video-001","source_type":"creator_opinion","evidence_level":"experience","review_status":"pending"},
    ], ensure_ascii=False), encoding="utf-8"
    )
    docs = load_knowledge(root)
    assert len(docs) == 2
    manifest = build_manifest(root)
    assert [row["id"] for row in manifest] == ["approved"]
    assert manifest[0]["source"]["video_url"] == "https://example.com/video/1"


def test_item_rejects_invalid_time_range():
    with pytest.raises(ValueError):
        KnowledgeItem(
            id="bad", collection="fat_loss", title="x", claim="y", source_id="s",
            source_type="creator_opinion", evidence_level="experience",
            timestamp_start=120, timestamp_end=60,
        )


def test_search_returns_approved_source_traceable_items(tmp_path):
    root = tmp_path / "knowledge"
    (root / "sources").mkdir(parents=True)
    (root / "supplements").mkdir()
    (root / "sources" / "s.json").write_text(json.dumps({
        "id": "s", "creator_name": "创作者", "video_url": "https://example.com",
        "video_title": "睡眠补剂"
    }, ensure_ascii=False), encoding="utf-8")
    (root / "supplements" / "i.json").write_text(json.dumps({
        "id": "i", "collection": "supplements", "title": "镁与睡眠",
        "claim": "缺镁相关的睡眠问题可能从补镁中获益", "source_id": "s",
        "source_type": "creator_opinion", "evidence_level": "limited",
        "review_status": "approved"
    }, ensure_ascii=False), encoding="utf-8")
    rows = search_knowledge(root, "镁 睡眠")
    assert rows[0]["id"] == "i"
    assert rows[0]["source"]["id"] == "s"

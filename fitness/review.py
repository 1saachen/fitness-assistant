"""Local review decisions and controlled publication for MVP knowledge cards."""

import json
from pathlib import Path


class ReviewValidationError(ValueError):
    pass


class ReviewNotFound(ReviewValidationError):
    pass


COLLECTION_MAP = {
    "supplements": "supplements",
    "diet_fat_loss": "fat_loss",
    "training": "training",
    "sleep_recovery": "sleep_recovery",
}


class ReviewService:
    def __init__(self, candidates: Path, decisions: Path, knowledge_root: Path, catalog: Path):
        self.candidates_path = Path(candidates)
        self.decisions_path = Path(decisions)
        self.knowledge_root = Path(knowledge_root)
        self.catalog_path = Path(catalog)

    def _candidates(self):
        data = json.loads(self.candidates_path.read_text(encoding="utf-8"))
        return data["cards"]

    def _decisions(self):
        if not self.decisions_path.exists():
            return {}
        return json.loads(self.decisions_path.read_text(encoding="utf-8")).get("decisions", {})

    def _write_json(self, path, value):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def cards(self):
        decisions = self._decisions()
        return [
            {
                **card,
                "review_status": decisions.get(card["id"], {}).get("status", "pending"),
                "review_note": decisions.get(card["id"], {}).get("note", ""),
            }
            for card in self._candidates()
        ]

    def summary(self):
        cards = self.cards()
        counts = {status: sum(card["review_status"] == status for card in cards)
                  for status in ("pending", "approved", "rejected")}
        return {"total": len(cards), **counts}

    def review(self, card_id, status, note=""):
        if status not in {"pending", "approved", "rejected"}:
            raise ReviewValidationError("审核状态无效")
        if card_id not in {card["id"] for card in self._candidates()}:
            raise ReviewNotFound("候选知识卡不存在")
        decisions = self._decisions()
        if status == "pending" and not note.strip():
            decisions.pop(card_id, None)
        else:
            decisions[card_id] = {"status": status, "note": note.strip()}
        self._write_json(self.decisions_path, {"version": 1, "decisions": decisions})
        return {"id": card_id, "status": status, "note": note.strip()}

    def publish(self):
        catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        videos = {video["bvid"]: video for video in catalog["videos"]}
        approved = [card for card in self.cards() if card["review_status"] == "approved"]
        source_records = []
        by_collection = {value: [] for value in COLLECTION_MAP.values()}
        for card in approved:
            source_id = f"mvp-card-source-{card['id']}"
            bvids = card["source_bvids"]
            first = videos[bvids[0]]
            source_records.append(
                {
                    "id": source_id,
                    "creator_name": first.get("owner_name") or "粗人-营养矩阵版",
                    "video_url": first.get("url")
                    or f"https://www.bilibili.com/video/{bvids[0]}",
                    "video_title": "；".join(
                        videos[bvid].get("title", bvid) for bvid in bvids
                    ),
                    "published_at": first.get("published_date"),
                    "videos": [
                        {
                            "bvid": bvid,
                            "title": videos[bvid].get("title") or bvid,
                            "url": videos[bvid].get("url")
                            or f"https://www.bilibili.com/video/{bvid}",
                            "published_at": videos[bvid].get("published_date"),
                        }
                        for bvid in bvids
                    ],
                }
            )
            statements = [row["statement"] for row in card["creator_statement"]]
            collection = COLLECTION_MAP[card["collection"]]
            by_collection[collection].append({
                "id": f"mvp-{card['id']}",
                "collection": collection,
                "title": card["title"],
                "claim": "\n".join(statements),
                "explanation": (
                    f"来源观点：{'；'.join(card['source_claim_ids'])}\n"
                    f"不确定性：{card['uncertainty']}\n安全边界：{card['safety_boundary']}"
                ),
                "source_id": source_id,
                "source_type": "creator_opinion",
                "evidence_level": "experience",
                "review_status": "approved",
                "review_note": card.get("review_note") or "经本地审核页面批准。",
                "tags": [card["title"], card["collection"]],
                "safety_level": card["safety_boundary"],
            })
        self._write_json(self.knowledge_root / "sources" / "mvp-approved.json", source_records)
        for collection, items in by_collection.items():
            self._write_json(self.knowledge_root / collection / "mvp-approved.json", items)
        return {"published_cards": len(approved), "published_sources": len(source_records)}

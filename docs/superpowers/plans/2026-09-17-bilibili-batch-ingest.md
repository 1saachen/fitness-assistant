# Bilibili Batch Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable Bilibili catalog, audio download, local transcription, and reporting pipeline for the selected fitness knowledge scope.

**Architecture:** Keep public catalog and selection logic in a focused batch module, reuse the proven per-video download/transcription module, and persist every stage as JSON files. WBI signing and selection are deterministic pure functions; network calls and ASR sit behind narrow functions so tests do not need live services.

**Tech Stack:** Python 3.13, standard library, `curl.exe`, PyAV, faster-whisper, pytest.

---

### Task 1: WBI signing and catalog normalization

**Files:**
- Create: `data/ingest/bilibili-20260916/test_bilibili_batch.py`
- Create: `data/ingest/bilibili-20260916/bilibili_batch.py`

- [ ] Write failing tests for the official WBI mix-key permutation, removal of forbidden characters, stable parameter ordering, and normalized catalog records.
- [ ] Run `\.venv\Scripts\python.exe -m pytest data/ingest/bilibili-20260916/test_bilibili_batch.py -q` and confirm failures are caused by missing functions.
- [ ] Implement `mix_key`, `sign_wbi`, and `normalize_catalog_item` with injected timestamps.
- [ ] Rerun the focused tests and confirm they pass.

### Task 2: Catalog pagination and persistence

**Files:**
- Modify: `data/ingest/bilibili-20260916/bilibili_batch.py`
- Modify: `data/ingest/bilibili-20260916/test_bilibili_batch.py`

- [ ] Write failing tests for page merging, BV-id deduplication, owner validation, and resuming from an existing catalog.
- [ ] Implement navigation-key retrieval, signed page fetches through `curl.exe`, bounded retry, and atomic `catalog.json` output.
- [ ] Run the focused tests, then execute `bilibili_batch.py catalog` against account `3537105504438769`.
- [ ] Verify the catalog contains unique BV ids, titles, descriptions, durations, and publication timestamps.

### Task 3: Deterministic selection and cross-platform candidates

**Files:**
- Modify: `data/ingest/bilibili-20260916/bilibili_batch.py`
- Modify: `data/ingest/bilibili-20260916/test_bilibili_batch.py`

- [ ] Write failing tests for topic keyword selection, exclusion of unrelated titles, and conservative candidate matching to `couren-selected-videos.json`.
- [ ] Implement normalized text matching and write `selection.json` with `pending` review status and explicit match scores.
- [ ] Run the focused tests and generate the real selection.
- [ ] Inspect counts and representative matches without promoting any candidate to a verified duplicate.

### Task 4: Resumable download and transcription queue

**Files:**
- Modify: `data/ingest/bilibili-20260916/bilibili_ingest.py`
- Modify: `data/ingest/bilibili-20260916/bilibili_batch.py`
- Modify: `data/ingest/bilibili-20260916/test_bilibili_batch.py`

- [ ] Write failing tests showing completed sources/transcripts are skipped and failures do not prevent later tasks from being selected.
- [ ] Expose reusable `download` and `transcribe` functions and add queue runners with `--limit`.
- [ ] Run the focused tests.
- [ ] Run a bounded two-video live batch and verify audio streams, durations, transcripts, and append-only events.

### Task 5: Status report and extraction handoff

**Files:**
- Modify: `data/ingest/bilibili-20260916/bilibili_batch.py`
- Modify: `data/ingest/bilibili-20260916/test_bilibili_batch.py`
- Create: `data/ingest/bilibili-20260916/report.md`
- Create: `data/ingest/bilibili-20260916/status.json`

- [ ] Write failing tests for stage counts and the invariant that downloader and ASR events report zero model API calls.
- [ ] Implement JSON and Markdown reporting with per-video status and failure details.
- [ ] Run all Bilibili batch tests and the existing curation tests.
- [ ] Generate final status artifacts and record the exact completed batch scope.

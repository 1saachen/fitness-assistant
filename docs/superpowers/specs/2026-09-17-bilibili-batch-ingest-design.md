# Bilibili Batch Ingest Design

## Goal

Build a resumable local pipeline for the Bilibili account `3537105504438769` that catalogs uploads, selects videos relevant to the existing fitness knowledge scope, downloads public audio, transcribes it locally, and exposes stable artifacts for the existing two-pass knowledge curation workflow.

## Source Strategy

The space playlist endpoint is useful for discovery but intermittently returns Bilibili risk-control codes `352` and `412`. The batch pipeline therefore uses Bilibili's public WBI space API for pagination. It obtains current WBI image keys from the public navigation endpoint, signs each catalog request locally, and uses the public view and playurl endpoints for per-video metadata and DASH audio URLs.

All API and media transfers run through the system `curl.exe`, which has already succeeded from this machine where Python HTTP clients and direct `yt-dlp` detail requests received `412`. No browser cookies are required or stored.

## Artifacts

The pipeline writes under `data/ingest/bilibili-20260916/`:

- `catalog.json`: normalized upload metadata for the account, with one record per BV id.
- `selection.json`: relevant uploads, their topic keywords, optional matches to the existing Douyin selection, and review status.
- `status.json` and `report.md`: stage counts, failures, and per-video progress.
- `media/<bvid>-source.json`: immutable source identity and download metadata.
- `media/<bvid>-audio.m4s`: highest-bandwidth public DASH audio stream.
- `media/<bvid>-transcript.json` and `.txt`: raw local ASR output.
- `usage.jsonl`: append-only download, ASR, failure, and future model-usage events.

Temporary downloads use `.partial` files and are renamed only after successful completion. Existing validated artifacts are reused.

## Selection

The first selection pass uses deterministic title and description keywords covering supplements, diet and fat loss, training and strength retention, sleep and fatigue, and information quality. It also compares normalized Bilibili titles with the existing curated Douyin metadata and records candidate cross-platform matches without claiming that similar titles prove identical content.

The generated selection remains `pending`. A video can be downloaded and transcribed while its cross-platform match remains unverified. Knowledge extraction uses the Bilibili URL and BV id as provenance, so uncertain matching cannot corrupt source identity.

## Execution

The command surface has independent resumable stages:

```text
catalog -> select -> download -> transcribe -> report
```

`run` executes the stages in order. `--limit` bounds expensive download and transcription work for smoke tests. Catalog and selection are deterministic local files once fetched, and reruns skip complete media and transcripts.

## Knowledge Integration

The downloader and ASR make no model API calls. A later extraction adapter will read the whole transcript, preserve raw terms and uncertainty, write Bilibili-specific claim ids such as `bili:BV...:1`, and append provider-reported token usage. These drafts remain `pending` and outside the approved RAG index until the existing second-pass synthesis, external evidence check, and human review are complete.

## Failure Handling

Catalog requests refresh WBI keys on a signature failure and stop after a bounded retry. Per-video failures are recorded and do not erase prior artifacts. A media file is accepted only when PyAV finds an audio stream and its duration is within five seconds of source metadata. Empty transcripts fail without creating completed output.

## Verification

Unit tests cover WBI signing, catalog normalization, topic selection, cross-platform candidate matching, and resumable task selection. Integration verification uses the already tested public fish-oil video and a bounded two-video batch before any larger run.

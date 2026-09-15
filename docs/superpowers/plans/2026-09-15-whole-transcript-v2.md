# Whole Transcript V2 Implementation Plan

**Goal:** Run one timestamp-free episode 133 comparison with auditable API usage.

**Architecture:** Add an isolated pilot script beside run_pilot.py. Read ordered text from existing transcript JSON segments, preserving the original files. Reuse existing inventory, JSON writer and append-only event logger. Save v2 requests, responses, extraction and comparison separately.

**Tech Stack:** Python, httpx, existing project Settings.

- [x] Implement extract_v2.py with prepare/run/report commands. Default and only allowed episode is 133 for this experiment. Construct plain text via `"\n".join(segment["text"] for segment in segments)`; no timing data enters the request.
- [x] Validate required fields, types, identity and pending provenance; reject truncated responses. Preserve raw/corrected names and flag quotes absent from the plain transcript.
- [x] Refuse another run after a v2 request-start event or existing response. Log usage before output parsing, including unknown usage on transport failure. No automatic retries.
- [x] Prepare request locally and verify its text exactly matches ordered transcript segments and old files are unchanged. Check syntax before any request.
- [x] Run episode 133 once. Generate comparison from saved artifacts with no further calls: input/output/total tokens, item count, null names, uncertainty and quote-match flags. Separate model self-confidence from verified accuracy.
- [x] Verify event/response totals and pending status. Report results and limitations without approving knowledge entries.

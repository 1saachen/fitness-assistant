# Strength baseline implementation plan

**Goal:** Remove the feedback trend panel, add optional strength references, and guide model-led load calibration from actual training feedback.

**Architecture:** Extend JSON-backed Training with a nullable-field StrengthBaseline object. Existing profile forms and training tasks carry it without migration. Model instructions keep baseline, prescriptions and actual performance distinct. Remove trend UI requests while retaining historical read tools.

**Tech stack:** Pydantic, FastAPI, SQLite JSON, plain JavaScript, pytest and Node tests.

- [x] Add failing model/API tests for optional references, positive 1RM, valid zero pull-ups and saved round trip; add a planning test that supplies baseline, planned weight and actual feedback independently.
- [x] Add StrengthBaseline and UI fields, notes and date. Update training/feedback prompts to prioritize comparable recent actual performance, label estimates, and preserve confirmed plans and profile.
- [x] Remove trend card, frontend state/render/load/listeners and refresh calls. Keep backend tools and historical tests.
- [x] Run focused and full tests, Ruff and JavaScript syntax checks. Restart existing live service and verify feedback/profile pages using read-only inspection; record actual outcomes.

Verified: 691 Python tests, 48 frontend tests, Ruff and JavaScript syntax checks passed. Browser verified optional blank strength fields and removal of the feedback trend panel. Live service restarted; existing personal profile/feedback unchanged. No real-model load-selection evaluation was performed for this change.

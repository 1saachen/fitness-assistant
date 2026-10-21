# Local data boundaries

The fitness assistant stores user records in a SQLite database selected by the
local application. The database uses WAL journaling and a monotonic
`PRAGMA user_version`; opening a database with a newer schema is rejected
before any migration runs. Migrations are additive and retain the four original
tables (`profiles`, `plans`, `feedback`, and `feedback_revisions`). The current
schema also contains `plan_changes`, `import_batches`, and `import_items`.
Schema version 4 adds `long_term_plans` and `daily_plans`. Existing weekly
`plans` and their adjustment history are retained; the migration does not
reinterpret an old seven-day plan as a new long-term strategy.

## Long-term strategy and daily execution

Long-term records contain the confirmed profile version, goals, cycle steps,
nutrition targets and review rules. Confirmation checks the current profile
and newer effective confirmed versions. Revisions of a strategy create a new
long-term record; previous daily records retain their original long-term ID.
Daily records are append-only revisions per date, with an input fingerprint
and generation trace. Generation checks profile, applicable long-term plan,
confirmed feedback and daily snapshots inside an immediate writer transaction.
Changed dependencies produce a conflict rather than overwriting newer facts.
Replaying identical generation inputs returns the current revision.

Cycle position follows actual confirmed training and explicit skip decisions,
independent of weekdays. An unfinished workout normally remains pending;
deferral does not count as completion. Confirmed completed training and meal
snapshots stay intact when unfinished portions of the day are regenerated.
An absent completion fact remains unknown. Daily food conditions never become
permanent profile preferences without the existing explicit confirmation flow.

Injury restrictions carry source dates and reasons and persist across days and
long-term versions. A new plan does not imply recovery. Explicit release uses
the current daily ID/revision, area and a 5–1000 character user confirmation;
the resulting revision preserves the release event for audit. Release records
a user statement and is not a diagnosis, rehabilitation prescription or medical
clearance. New injury reports may activate restrictions again. Release does not
silently regenerate training; the user can request a new daily evaluation.
Condition source times remain stable during automatic refresh. Explicitly
resubmitting a previously released condition counts as a new report; clearing
the text does not release injuries recorded in earlier daily revisions.
Feedback symptom fields retain their own last-change times from revision
history, so editing weight or food does not reactivate an unchanged old injury.

`GET /api/planning/state` is read-only. The browser explicitly requests today's
generation on opening the daily view and after relevant saved-state changes
while that view is open. There is no scheduler running while the application is
closed. History/future dates require an explicit generation request. Backups
must include both new tables, including source traces and release audit fields;
legacy weekly export endpoints retain their original scope.

Every write checks the expected profile version or feedback revision inside an
immediate transaction where the operation depends on a mutable snapshot.
Feedback advice also checks its expected update timestamp. Confirmed legacy weekly plans are immutable. A legacy weekly plan adjustment stores
an audit record containing the plan and feedback IDs, date, old and new values,
trigger issues, evidence, and the optimistic versions. Only a reduction in
exercise sets for the matching day of a seven-day plan is accepted. Repeating
the same adjustment is idempotent; it never mutates the original plan JSON.
The writer transaction also verifies that the selected plan remains the latest
confirmed plan for the current profile covering that date. Confirming a new
replacement plan after preview causes the old adjustment request to conflict.

## Import and backup boundaries

JSON, CSV, and Markdown feedback imports always have a preview step. The
preview validates each record with `FeedbackData`, computes a deterministic
batch ID and fact fingerprint, and reports invalid or draft records. A separate
explicit confirmation is required before writes. Imported files are untrusted:
only confirmed user facts are copied; status, advice, source IDs, and generation
trace from a file are ignored. Confirmed imports are transactional and
fingerprinted so retries do not create duplicate records.

Backups use SQLite's online backup API, which includes committed WAL frames in
a consistent snapshot. Backup and restore destinations are never overwritten
silently. Restore first previews source and target fingerprints and table
counts, then requires both fingerprints and an explicit confirmation. Existing
targets are preserved as a separate pre-restore backup. The CLI commands
(`import-preview`, `import-confirm`, `backup`, `restore-preview`, and
`restore-confirm`) expose these steps without hidden writes.

Source and target fingerprints represent the logical database contents,
including committed records still held in WAL. Restore rechecks the target
fingerprint under a SQLite writer lock. A new target and backup filename are
reserved exclusively so a file that appears after preview cannot be silently
overwritten. Restore validates schema columns, foreign keys, integrity and
supported versions before importing a snapshot, and writes the restored data
in a transaction. The rollback remains in effect if any table copy fails.
Backups may contain personal facts and raw feedback; local filesystem access
and disk encryption protect them, and they are not automatically uploaded.

The JSON format and fenced JSON blocks in Markdown preserve all validated
feedback facts. CSV accepts the feedback export columns. Older Markdown prose
exports expose only date, training summary, sleep, fatigue and raw feedback;
the preview makes these partial records reviewable and leaves absent fields
unknown. Facts cannot be reconstructed from advice prose. Invalid records
block the complete confirmation batch rather than partially importing it.

## Isolation and deployment

The database path is local to the selected application instance. A multi-user
deployment must assign a separate database or authenticated tenant namespace
per user; IDs and optimistic revisions are not an authorization boundary by
themselves. Cloud deployment requires encrypted storage, access control,
backups, and a migration job that checks the schema version before serving
traffic. Docker can package the application, but the SQLite volume must be
mounted on durable storage and backed up while the process is running.

The current local database has no user/tenant column or login system. Deploying
the process behind a public URL would not create user isolation. A future
schema migration should first introduce a stable user ID and attach it to
profiles, plans, feedback, revisions, adjustment audit and import batches;
every read/write must be scoped to the authenticated user. Idempotency keys
must be namespaced by that same user, and ownership must be checked before
following any plan or feedback foreign key. An authentication provider needs
server-side session verification, explicit logout and token expiry; browser
claims or record IDs alone cannot authorize access. Tests should exercise two
users attempting to read, confirm or adjust each other's records.

For a cloud or Docker evaluation, retain SQLite for a single process on one
durable local volume. Avoid ephemeral container filesystems and shared network
volumes used by multiple writers. Container images should contain application
code, not personal databases, API keys or cookies. Migrations run once before
traffic resumes; backups should be restored into a staging volume and checked
before promotion. Horizontal scaling requires a database designed for shared
writes and a migration preserving the version, revision and audit invariants.
No cloud resources or external deployments are created by this work.

The storage layer does not write to external fitness platforms. Apple Health
and Android Health Connect require their official, user-authorized APIs and
platform permissions. Private or reverse-engineered write endpoints are not
supported. A future integration should import only the measurements the user
selected, retain the source and timestamp as provenance, and run the same
validation and confirmation flow before they become confirmed assistant facts.

| Integration | Supported evaluation boundary | Next implementation requirement |
| --- | --- | --- |
| Apple Health / HealthKit | Native Apple app obtains permission for specific data types; a web/Python service does not have direct HealthKit access. | A native companion must obtain user authorization and export selected dated measurements. Preserve provenance, units and time zone before preview. |
| Android Health Connect | Android app requests per-record permissions and observes platform restrictions on history/background reads. | Native companion handles permissions, source IDs, record deduplication and revocation; the assistant validates selected facts before confirmation. |
| External fitness platform | Official documented export or OAuth API only; API availability depends on platform approval and scopes. | Establish documented scopes, rate limits, licensing, retention and revocation. Start with read-only imports. |
| Platform write-back | No adapter exists; an assistant suggestion is not authorization to alter a health platform record. | Separate explicit confirmation, official writable scopes, operation ID and audit record, retry deduplication and error reconciliation. |

Official entry points: [Apple HealthKit](https://developer.apple.com/documentation/healthkit)
and [Android Health Connect](https://developer.android.com/health-and-fitness/guides/health-connect).
The implementation does not call private write APIs, reuse app cookies for
health data, claim provider registration, or write to either platform.

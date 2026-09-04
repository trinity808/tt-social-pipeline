# TT Social Pipeline

Custom LangGraph-based pipeline for Trinity Tree's social media content drafting and publishing (LinkedIn, Instagram, Facebook), replacing the current n8n workflow.

**Status:** In development. n8n remains the live fallback until this is proven end-to-end.

## LinkedIn token renewal (annual)

LinkedIn's access token refreshes automatically every ~60 days — no action needed for that. The refresh token itself is valid for roughly 12 months and requires a one-time manual renewal before it expires. Watch for a warning surfaced once the pipeline is within ~30 days of that expiry (Phase 5's review channel, once built).

**Steps:**

1. Go to the [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps), open the app tied to the `LINKEDIN_CLIENT_ID` in `.env`.
2. Under the **Products** tab, confirm Community Management API / Share on LinkedIn access is still active.
3. Go to the standalone **Token Generator** tool (under Tools — not inside the Auth tab), logged in as an admin of TT's LinkedIn company page.
4. Select the `w_organization_social` scope and generate. This produces a new access token and a new refresh token.
5. Push **both** values to Secret Manager:
```bash
   echo -n "NEW_ACCESS_TOKEN" | gcloud secrets versions add linkedin-access-token --data-file=-
   echo -n "NEW_REFRESH_TOKEN" | gcloud secrets versions add linkedin-refresh-token --data-file=-
```
6. That's it — do not manually edit Firestore. The pipeline's next scheduled run will see the old stored expiry, trigger an automatic refresh using the newly-pushed refresh token, and update Firestore's expiry tracking on its own.

**Known gotcha:** `LINKEDIN_VERSION` in `.env` is a recurring source of confusing failures if it's ever left stale after LinkedIn rotates its supported API versions (`NONEXISTENT_VERSION` / HTTP 426 errors). If posting starts failing after a long gap with no code changes, check this value against LinkedIn's current API docs before assuming anything else is broken.

## Meta (Facebook/Instagram) token notes

The Page access token used for both Facebook and Instagram publishing does **not** need any refresh logic, unlike LinkedIn's. Confirmed via Meta's token debug tool: `expires_at: 0` and `data_access_expires_at: 0`, meaning it's genuinely non-expiring, not just long-lived.

**If this token is ever lost or invalidated** (revoked permission, app changes, etc.), regenerating it correctly requires two steps, not one:

1. Generate a fresh token from the `postautomationbot` System User (Business Suite → Settings → Users → System users → select it → Generate token, with the full scope set: `pages_show_list`, `business_management`, `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`, `pages_manage_posts`).
2. **This System User token cannot be used directly for posting** — `debug_token` will show `"type": "SYSTEM_USER"`, and Facebook's `/photos` endpoint (among others) will reject it with a generic, misleading permissions error. It must be exchanged for the Page's own token:

https://graph.facebook.com/v25.0/{FACEBOOK_PAGE_ID}?fields=access_token&access_token={SYSTEM_USER_TOKEN}

   The `access_token` field in that response is the real, `"type": "PAGE"` token — that's what goes into Secret Manager (`meta-access-token`), not the System User token itself.
3. Confirm with `debug_token` again before trusting it — should show `"type": "PAGE"` and both expiry fields still at `0`.

## Phase 5: human review gate

Full design (recipient model, approval mechanics, cadence-lock rule) lives in `phase5-review-gate-design.md`. This section covers operational knowledge for whoever maintains this later.

**Checkpointer setup is not straightforward -- `FirestoreSaver` cannot be instantiated directly.** Its constructor doesn't accept the same keyword arguments as its own `from_conn_info()` classmethod (confirmed by hitting a real `TypeError` testing this). The working pattern, used in `pipeline/graph.py`:
```python
checkpointer = FirestoreSaver.from_conn_info(
    project_id=GCP_PROJECT_ID,
    checkpoints_collection="checkpoints",
    writes_collection="checkpoint_writes",
).__enter__()
```
Calling `.__enter__()` manually (rather than a `with` block) keeps the checkpointer open for the module's lifetime -- a `with` block would close it the moment `build_graph()` returns, breaking every request after the first.

**Known, accepted limitation: the msgpack deserialization warning cannot currently be silenced.** LangGraph warns on every resume that `pipeline.state.SocialPostDraft`/`CriticVerdict` are "unregistered types" (related to CVE-2026-28277, unrestricted checkpoint deserialization). We attempted the documented fix -- passing an explicit `allowed_msgpack_modules` allowlist via a custom `JsonPlusSerializer` -- but it does not appear to actually take effect with this package's current version; the warning still fires. Left in place since it's harmless and may start working if the package updates. Real exposure requires write access to our Firestore checkpoint store, which is already tightly IAM-restricted.

**Idempotency requirement:** any code before an `interrupt()` call inside the same node re-executes in full on every resume. This is why the review gate is split into two nodes (`send_for_review` completes once and sends the email; `await_approval` contains only the `interrupt()` call) rather than one.

**Pending-review resolution is atomic, not read-then-write.** `resolve_pending_review()` uses a Firestore transaction to check status and mark it resolved in one step -- required for "first click wins" to actually hold under near-simultaneous clicks, same race-condition class as the run-lock fix.

**Supersede/skip logic runs at the very start of every pipeline invocation**, before any generation happens. A still-pending review within 48 hours causes the run to skip entirely (zero cost); a stale one gets marked `superseded` and the run proceeds. Tested by manually backdating a `pending_reviews` document's `generated_at` field in the Firestore console -- there's no way to trigger this via real elapsed time in dev testing.

**Two features are stubbed pending confirmation, not fully built:**
- 24-hour nudge reminders (`send_review_followup_email` already exists in `review/notifications.py` and works, but nothing currently calls it) -- pending Dr. Shelton confirming whether it's wanted at all.
- Superseded-thread notifications -- currently just a log line; `review/notifications.py` has no function for this decision type yet (`send_resolution_email` only supports approve/reject).

**`/review` is currently locked down the same way as `/run`** (`--no-allow-unauthenticated`). This works for local testing (both of us running on the same machine) but will not work in production -- a real reviewer clicking from their own device has no way to attach an auth token. Before going live: `/review` needs to allow public access while `/run` stays locked to Cloud Scheduler only, and `REVIEW_PUBLIC_BASE_URL` needs to point at the real deployed URL instead of `localhost:8080`.

## Graph Orchestration

The main workflow is defined in `pipeline/graph.py`.

```text
check_pending_review
→ load_topic
→ draft
→ critic
→ revise (if needed)
→ generate_image
→ send_for_review
→ await_approval
→ publish_post / handle_rejection
```

### Critic retry loop

The critic reviews the LinkedIn, Facebook, and Instagram drafts before the workflow continues.

If any draft is rejected, the graph routes to `revise`, where the writer receives the critic feedback and generates an updated version. The revised draft is then evaluated again.

The retry loop is intentionally limited:

```python
MAX_RETRIES = 1
```

This prevents the graph from repeatedly regenerating content indefinitely. After the allowed revision attempt, the workflow continues to image generation and human review.

### Review checkpointing

The workflow uses a Firestore-backed LangGraph checkpointer so the graph can pause during human review and resume later.

The detailed `FirestoreSaver.from_conn_info(...).__enter__()` setup, checkpoint persistence, and the reason `send_for_review` and `await_approval` are separate nodes are already documented in the **Phase 5** section of this README.

---

## Publishing

Publishing is coordinated by `publish_post` in `pipeline/graph.py` and the individual publisher modules:

```text
publishers/linkedin.py
publishers/facebook.py
publishers/instagram.py
```

### LinkedIn

LinkedIn publishing uploads the approved image first and then creates a company post containing the generated caption, hashtags, and image.

### Facebook

Facebook publishing sends the approved image and caption directly to the configured Trinity Tree Facebook Page using the Meta Graph API.

### Instagram

Instagram uses Meta's media-container workflow:

```text
Upload image to GCS
→ create Instagram media container
→ wait for processing
→ publish container
```

Token refresh and Meta Page-token configuration are documented elsewhere in the README.

### Independent platform publishing

Each platform is handled independently.

`publish_post` checks the stored cadence eligibility for LinkedIn, Facebook, and Instagram separately.

A platform can therefore be:

* `posted`
* `skipped_cadence`
* `failed`

A failure on one platform does not prevent the other eligible platforms from attempting publication.

---

## Posting Cadence

Posting schedules are defined in `pipeline/cadence.py`.

The current `POSTING_DAYS` configuration is:

| Platform  | Posting schedule          |
| --------- | ------------------------- |
| LinkedIn  | Monday, Wednesday, Friday |
| Facebook  | Daily                     |
| Instagram | Daily                     |

`should_post_today()` checks whether a platform is eligible to post on a given day.

If no date is provided, the function uses the current business date in:

```python
BUSINESS_TIMEZONE = "America/Phoenix"
```

This prevents the posting schedule from being affected by the timezone of the Cloud Run server.

The decision about when cadence eligibility becomes locked into a review is handled elsewhere in the pipeline; `cadence.py` only determines whether a platform is eligible for a particular date.

---

## Storage and Run Safety

### GCS image storage

`pipeline/storage.py` supports both uploading and downloading generated images.

```text
Generated image
→ upload to GCS
→ human review
→ download for publishing
```

Both directions are needed because Cloud Run's local filesystem is temporary. The original instance that generated the image may no longer exist when the review is approved.

GCS therefore provides durable image storage between generation, approval, and publishing.

It also provides the hosted image URL required by Instagram's publishing flow.

### Run lock

`pipeline/run_lock.py` uses Firestore transactions to prevent multiple scheduled pipeline runs from starting at the same time.

The transaction ensures that checking for an existing lock and acquiring the new lock happens atomically.

A stale-lock timeout is also included. If a run terminates unexpectedly without releasing its lock, an old lock can eventually be treated as stale so future scheduled runs are not blocked permanently.

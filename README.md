# TT Social Pipeline

A LangGraph-based multi-agent pipeline that automates Trinity Tree Psychological Services' social media presence end to end, replacing an earlier no-code (n8n) workflow.

Each day, the pipeline drafts a social media post grounded in the practice's actual website content, has it independently reviewed by a second AI model for factual accuracy before a human ever sees it, generates an accompanying image, and sends the whole package to a human reviewer for approval or rejection. Only after explicit human sign-off does anything actually publish — and even then, each platform (LinkedIn, Instagram, Facebook) only posts on its own configured cadence. Reviews that go unanswered are automatically nudged, and eventually superseded by a fresh draft, so nothing sits stale indefinitely and nothing publishes without a person deciding it should.

## Prerequisites & local setup

**System requirements:**
- Python 3.11 or later
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (needed for the rebuild/redeploy cycle — see Operational reference)
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install), authenticated to the `tt-social-pipeline` GCP project

**1. Clone and set up a virtual environment:**
```bash
git clone https://github.com/trinity808/tt-social-pipeline.git
cd tt-social-pipeline
python -m venv venv
source venv/Scripts/activate    # Windows Git Bash
# or: source venv/bin/activate  # Mac/Linux
pip install -r requirements.txt
```

**2. Copy `.env.example` to `.env` and fill in real values.** Most credentials come from one of these places:
- GCP-related values (`GCP_PROJECT_ID`, etc.) — the GCP Console, project settings
- LinkedIn values — the [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps) (see LinkedIn token renewal section below for the full walkthrough)
- Meta/Facebook/Instagram values — Meta Business Suite (see Meta token notes below)
- Secrets that are *not* in `.env` at all (API keys stored in Secret Manager, like `openai-api-key` and `review-gmail-app-password`) are fetched at runtime automatically — no local copy needed as long as you're authenticated (next step)

**3. Authenticate for local GCP access:**
```bash
gcloud auth application-default login
```
This lets local code (Firestore, Secret Manager, Vertex AI, Cloud Storage clients) authenticate the same way it does when deployed, without needing a downloaded service-account key file. Confirm the following APIs are enabled on the project: Firestore, Secret Manager, Vertex AI, Cloud Storage, Cloud Run, Cloud Scheduler.

**4. Confirm the setup works with a single, low-stakes local run:**
```bash
python -m pipeline.graph
```
This runs the full pipeline once — real draft, real critic review, real image generation — and pauses at the human review step, printing a thread ID. It costs a small amount in API usage but makes zero external posts and sends zero real emails unless the notification system is also fully configured. If this completes without error and pauses correctly, your local setup is working.

**Everything past this point — deployment, credential rotation, the rebuild/redeploy cycle — is covered in the Operational reference section below, not here.**

**Status:** In development. n8n remains the live fallback until this is proven end-to-end.

## Project structure

```
tt-social-pipeline/
├── .env.example
├── Dockerfile
├── README.md
├── requirements.txt
├── main.py                          # Cloud Run entrypoint (Flask): /run, /review, /review/confirm, /check-pending-reviews
├── agents/
│   ├── critic.py                    # Gemini-based factual review of each draft
│   ├── image_generator.py           # Generates and saves the accompanying post image
│   └── writer.py                    # GPT-based drafting and revision
├── content/
│   └── site_content.json            # Scraped source content per topic, used for grounding
├── pipeline/
│   ├── cadence.py                   # Per-platform posting-day rules
│   ├── graph.py                     # LangGraph node definitions and graph assembly
│   ├── logging_config.py            # Structured JSON logging setup
│   ├── meta_errors.py               # Shared Facebook/Instagram error classification
│   ├── prompts.py                   # All writer/critic/image prompt templates
│   ├── review.py                    # Pending-review Firestore lifecycle (create/resolve/expire/nudge)
│   ├── rotation.py                  # Topic selection and recency tracking
│   ├── run_lock.py                  # Prevents overlapping pipeline runs
│   ├── secrets.py                   # Secret Manager access helpers
│   ├── state.py                     # Shared LangGraph state schema
│   └── storage.py                   # GCS upload/download for generated images
├── publishers/
│   ├── facebook.py
│   ├── instagram.py
│   └── linkedin.py                  # Includes token refresh handling
├── review/
│   ├── emailer.py                   # SMTP sending, recipient configuration
│   └── notifications.py             # All four notification email templates
└── scripts/                         # Manual/one-off tools -- see below, not run automatically
    ├── classify_topic_list_length.py
    ├── fetch_site_content.py
    ├── run_bakeoff.py
    ├── test_cadence.py              # Genuine automated pytest suite
    ├── test_checkpointer.py
    ├── test_resume_review.py
    ├── test_review_gate.py
    └── ...                          # (see full listing/annotations below)
```

### `scripts/` reference

Manual, one-off tools -- not run automatically, not a pytest suite (aside from `test_cadence.py`). Several make real, live calls to external services; those are flagged below.

| File | What it does |
|---|---|
| `classify_topic_list_length.py` | One-time LLM classification tool that generated `TOPICS_WITH_LONG_LISTS` |
| `fetch_site_content.py` | Scrapes `site_content.json` from the live site; has a documented gotcha re: `/contact`'s dynamic "today's hours" widget freezing incorrectly |
| `run_bakeoff.py` | Phase 1 model bake-off script — the comparison that led to dropping Groq |
| `bakeoff_results.json` | Output data from the above |
| `gcs_lifecycle.json` | GCS bucket 60-day auto-delete policy config |
| `post_facebook_test.py` | ⚠️ Posts to the real Facebook page — hardcoded, confirmation-gated, not automated |
| `post_linkedin_test.py` | ⚠️ Posts to the real LinkedIn page, graph-based with image — hardcoded, confirmation-gated |
| `test_linkedin_publisher.py` | ⚠️ Posts to the real LinkedIn page via `publishers.linkedin` directly — hardcoded, confirmation-gated |
| `test_instagram_publisher.py` | ⚠️ Posts to the real Instagram account — hardcoded, confirmation-gated |
| `test_cadence.py` | Genuine automated `pytest` suite — safe to run freely, no live calls |
| `test_checkpointer.py` | Standalone LangGraph checkpointer pause/resume proof-of-concept, run as two separate manual invocations |
| `test_resume_review.py` | Manual harness for resuming a real paused review thread via `Command(resume=...)` against the actual graph |
| `test_review_gate.py` | Zero-cost hardcoded test of the full review-gate flow, reusing an existing local image to avoid generation cost |
| `test_followup_5min.py` | Manual nudge-timing test using a shortened 5-minute delay instead of the real 24 hours, with a file-touch trick to simulate an approval interrupting the wait |
| `test_resolution_email.py` | ⚠️ Sends a real resolution email — manual CLI test of `send_resolution_email()`, accepts approve/reject and an optional resolver-email argument |
| `test_smtp_connection.py` | Standalone SMTP credential check — prompts for a Gmail address and App Password directly, isolates auth issues from the rest of the notification system (likely built during the credential-typo debugging) |

## Operational reference: config, secrets, and deployment

**Where configuration actually lives, and the one rule that matters most.** Real secrets (API keys, tokens, the Gmail App Password) live in GCP Secret Manager, referenced at deploy time via `--set-secrets`. Everything else — project ID, model names, cadence settings, `SERVICE_ROLE`, recipient addresses — is a plain environment variable set directly on each Cloud Run service.

**Local `.env` and what's actually deployed are two completely separate things — never assume one reflects the other.** Nearly every real deployment issue hit in this project traced back to exactly this gap: a value correct locally but never actually pushed to one or both Cloud Run services (a missing `SERVICE_ROLE`, three different spellings of the same sender email across three different places, missing recipient variables entirely). Always verify directly against what's deployed (see point 4) rather than trusting local `.env` as a stand-in for it.

**Rebuild and redeploy cycle:**
```bash
docker build -t tt-social-pipeline .
docker tag tt-social-pipeline us-central1-docker.pkg.dev/tt-social-pipeline/tt-social-pipeline/tt-social-pipeline:latest
docker push us-central1-docker.pkg.dev/tt-social-pipeline/tt-social-pipeline/tt-social-pipeline:latest
```
Both `tt-social-pipeline` (private) and `tt-social-pipeline-review` (public) run the identical image — **both need redeploying**, not just one, since they're built from the same Dockerfile and share the same codebase.

**Critical: a bare `--image` redeploy can silently do nothing at all.** Cloud Run appears to compare the image *reference string*, not its actual content — redeploying with an unchanged `:latest` tag has, in practice, sometimes produced a successful-looking "Done" message while leaving the *previous* revision's code still running underneath. **Always redeploy using a full `--set-env-vars` restatement of every variable**, not a bare `--image`-only update — a complete environment replacement reliably forces Cloud Run to create a genuinely new revision:
```bash
gcloud run deploy tt-social-pipeline \
  --image=us-central1-docker.pkg.dev/tt-social-pipeline/tt-social-pipeline/tt-social-pipeline:latest \
  --region=us-central1 \
  --set-env-vars="<full list, see table below>" \
  --set-secrets="OPENAI_API_KEY=openai-api-key:latest"
```
Repeat for `tt-social-pipeline-review`, adding `--allow-unauthenticated` and setting `SERVICE_ROLE=public` instead of `private` in its env vars.

**Verifying a deploy actually worked — don't trust a successful CLI message alone.**
```bash
gcloud run services describe tt-social-pipeline --region=us-central1 --format="export"
gcloud run services describe tt-social-pipeline-review --region=us-central1 --format="export"
```
Check two things in the output: the `client.knative.dev/nonce` value has changed from before this deploy (proof a genuinely new revision was created, not a silent no-op per the warning above), and every expected environment variable is present with the correct value — not just "present," since a typo in a value is just as real a failure as a missing one.

**Sync with `main` before rebuilding from any branch — a stale branch will be faithfully rebuilt, missing anything, is missing.** A branch that hasn't pulled recent changes will deploy exactly what it has, silently omitting anything merged into `main` since it was last synced — this is exactly how a real security fix was once briefly absent from a live deployment, despite already being merged and available. Always run `git pull origin main` and merge it into your working branch before rebuilding, regardless of how recently that branch was last touched.

**Full current environment variable reference**, across both services (`P` = private service `tt-social-pipeline`, `R` = public/review service `tt-social-pipeline-review`):

| Variable | Private | Public | Notes |
|---|---|---|---|
| `GCP_PROJECT_ID` | ✅ | ✅ | |
| `VERTEX_AI_LOCATION` | ✅ | ✅ | |
| `LINKEDIN_VERSION` | ✅ | ✅ | See LinkedIn token renewal section for the version-rotation gotcha |
| `META_GRAPH_VERSION` | ✅ | ✅ | Now read consistently by both Facebook and Instagram publishers |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | ✅ | ✅ | |
| `LINKEDIN_ORG_URN` | ✅ | ✅ | |
| `LINKEDIN_CLIENT_ID` | ✅ | ✅ | |
| `FACEBOOK_PAGE_ID` | ✅ | ✅ | |
| `REVIEW_PUBLIC_BASE_URL` | ✅ | ✅ | Must point at the *public* service's URL on both |
| `SERVICE_ROLE` | `private` | `public` | Defense-in-depth guard on `/run` and `/check-pending-reviews` |
| `ENVIRONMENT` | ✅ | ✅ | Currently `development` on both — production recipient swap not yet done |
| `REVIEW_DEV_TO` / `REVIEW_DEV_CC` | ✅ | ✅ | |
| `REVIEW_PROD_TO` / `REVIEW_PROD_CC` | not yet set | not yet set | Needed before real production launch |
| `REVIEW_EMAIL_FROM` | ✅ | ✅ | Verify exact spelling — a mismatch here caused a real, confusing SMTP auth failure |
| `OPENAI_API_KEY` | via Secret Manager | via Secret Manager | |
| `WRITER_MODEL` / `CRITIC_MODEL` | not set (uses fallback) | not set (uses fallback) | Emergency escape hatch only — see model version dependencies section |

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

## Graph orchestration & checkpointer

The main workflow is defined in pipeline/graph.py.
check_pending_review
→ load_topic
→ draft
→ critic
→ revise (if needed)
→ generate_image
→ send_for_review
→ await_approval
→ publish_post / handle_rejection
Critic retry loop
The critic reviews the LinkedIn, Facebook, and Instagram drafts before the workflow continues.
If any draft is rejected, the graph routes to revise, where the writer receives the critic feedback and generates an updated version. The revised draft is then evaluated again.
The retry loop is intentionally limited:
MAX_RETRIES = 1
This prevents the graph from repeatedly regenerating content indefinitely. After the allowed revision attempt, the workflow continues to image generation and human review.
Review checkpointing
The workflow uses a Firestore-backed LangGraph checkpointer so the graph can pause during human review and resume later.
The detailed FirestoreSaver.from_conn_info(...).__enter__() setup, checkpointer lifecycle, interrupt/resume behavior, IAM and security considerations, and the reason send_for_review and await_approval are separate nodes are documented in the Phase 5 section of this README.

## Image generation

**Content density went through two failed extremes before landing on the current design.** The original prompt let the model treat a long service list as a checklist to visually enumerate — a 10-item topic produced ten individual mini-cards, each with its own heading and description, far too dense for a scrolling social audience. The first fix overcorrected: capping content too aggressively caused the model to silently drop items (10 down to 4) with no indication anything was cut. The current design allows a long list to be shown in full, but requires each item to carry minimal visual weight (a short icon and a one-line label, never a description or heading/subheading pair), with an explicit target of roughly 6-7 items for long-list topics.

**Four independent randomization axes exist specifically to keep repeat posts from looking identical.** `IMAGE_STYLES`, `IMAGE_COLOR_PALETTES`, `IMAGE_LAYOUTS`, and `IMAGE_GRAPHIC_TREATMENTS` are each sampled independently per generation via `random.choice()`, giving 256 possible combinations from a fairly small, hand-curated set of options.

**`TOPICS_WITH_LONG_LISTS` is a one-time, manually-maintained classification, not computed live.** Topic content in `content/site_content.json` is static, so classifying "does this topic have a long enumerable list" fresh on every run would be wasted API cost for something that essentially never changes. `scripts/classify_topic_list_length.py` is the one-time tool used to generate the current set. **This needs manual revisiting whenever a topic's content changes meaningfully** — not for wording tweaks, but if the actual number of enumerable items shifts. Nothing in the code detects or warns if this goes stale.

**`GRID_LAYOUT` is excluded specifically for long-list topics, not disliked in general.** Testing confirmed this one layout structurally pushes toward fewer, heavier items — presented as full cards rather than a lightweight list — and on a real 10-item topic it silently dropped 6 items with zero indication anything was missing. It's excluded from the random pool only when `topic_key` is in `TOPICS_WITH_LONG_LISTS`; for every other topic, it remains a fully valid option.

**All four color palettes are confirmed valid, based on real, isolated single-variable testing — not all generated together in one comparison.** An earlier round tested four palette candidates side by side in one ungrouped image grid, which made it impossible to reliably attribute a given result to a specific palette name; one option from that round was dropped as functionally redundant with another (near-identical accent coloring), not because it failed on its own merits. The remaining and current four (`terracotta wellness`, `sage and sunrise`, `soft botanical neutrals`, `forest and gold`) were each subsequently validated through proper controlled tests holding every other variable constant. `forest and gold` was proposed specifically since Trinity Tree's own branding (name, logo) is already tree/green-forward, and none of the other three options lean into that directly — it was reviewed and explicitly approved by Dr. Shelton before inclusion.

**Image generation receives all three platform captions, not just one, so a single image can stay consistent with any of them.** Since one generated image serves all three platforms, but each platform's caption independently summarizes a different subset of a topic's content (word-limit constraints mean no caption lists everything), the image and a given caption could otherwise visibly disagree — a viewer reading the LinkedIn caption might see different services mentioned than what the image shows. The fix guarantees every item mentioned across *any* of the three captions appears in the image, then fills remaining slots up to the ~6-7 item target from the source content directly. This is deliberately more generous than "only show what's in the captions" — an Instagram viewer who skips the caption entirely still gets standalone value from the image itself.

**`generate_post_image()` returns a local file path, not a durable URL.** The image is saved under `generated_images/` on whatever container happened to run the generation. Since a real review can be delayed for hours or days, and Cloud Run may recycle that container in the meantime, this local path is not reliable for anything downstream — durability (uploading to a permanent public URL, and re-fetching it later if needed for publishing) is handled separately in `pipeline/storage.py`.

**The image generation model is already correctly future-proofed.** `OPENAI_IMAGE_MODEL` reads from the environment with a sensible fallback (`gpt-image-2`), unlike the writer and critic models, which historically were hardcoded — see the version/model dependency notes below for the full picture across the project.

## External API & model version dependencies

Every version-pinned or model-pinned value across the project is now configurable via environment variable with a sensible fallback — this wasn't always consistent (Instagram's `GRAPH_API_VERSION` was hardcoded until this was caught and fixed), so worth confirming this table stays accurate if anything new gets added later.

| Value | Env var | Fallback | Used in |
|---|---|---|---|
| LinkedIn API version | `LINKEDIN_VERSION` | `202606` | `publishers/linkedin.py` |
| Meta Graph API version (Facebook) | `META_GRAPH_VERSION` | `v25.0` | `publishers/facebook.py` |
| Meta Graph API version (Instagram) | `META_GRAPH_VERSION` | `v25.0` | `publishers/instagram.py` |
| Image generation model | `OPENAI_IMAGE_MODEL` | `gpt-image-2` | `agents/image_generator.py` |
| Writer model | `WRITER_MODEL` | `gpt-5.5` | `agents/writer.py` |
| Critic model | `CRITIC_MODEL` | `gemini-3.5-flash` | `agents/critic.py` |

**Version strings and model names carry genuinely different risk, despite sharing the same technical pattern — worth treating them differently, not interchangeably.**

A version bump is a protocol-compatibility change, nothing more — same model, same behavior, just a different value in a header. If posting starts failing after a long gap with no code changes (see the LinkedIn `426` gotcha above), check the relevant version against current API docs, update the env var, redeploy. Low-risk, low-ceremony.

Swapping `WRITER_MODEL` or `CRITIC_MODEL` is a materially different kind of decision. Model choice directly affects output quality, tone, JSON-parsing reliability, and factual grounding — the exact reason the original model bake-off (Phase 1) existed in the first place, and why Groq was dropped from consideration entirely after it repeatedly fabricated an unsupported "board-certified" credential. **Treat these two env vars as an emergency escape hatch for a hard model deprecation, not a routine setting to casually tweak.** Changing either means re-verifying grounding behavior and JSON reliability before trusting it in production — effectively repeating the spirit of the original bake-off at a smaller scale, not just redeploying and moving on.

## Publish nodes

Publishing is coordinated by `publish_post` in `pipeline/graph.py` and the individual publisher modules:

```text
publishers/linkedin.py
publishers/facebook.py
publishers/instagram.py
```

**LinkedIn.** LinkedIn publishing uploads the approved image first and then creates a company post containing the generated caption, hashtags, and image.

**Facebook.** Facebook publishing sends the approved image and caption directly to the configured Trinity Tree Facebook Page using the Meta Graph API.

**Instagram.** Instagram uses Meta's media-container workflow:

```text
Upload image to GCS
→ create Instagram media container
→ wait for processing
→ publish container
```

Token refresh and Meta Page-token configuration are documented elsewhere in the README.

**Independent platform publishing.** Each platform is handled independently. `publish_post` checks the stored cadence eligibility for LinkedIn, Facebook, and Instagram separately.

Cadence eligibility is locked when the draft enters pending review: `create_pending_review` stores the per-platform eligibility, and `publish_post` later uses those stored values rather than re-checking cadence when the review is approved. This prevents a delayed approval from changing which platforms were eligible for that post. The full cadence-lock behavior is documented in **Phase 5**.

A platform can therefore be:

* `posted`
* `skipped_cadence`
* `failed`

A failure on one platform does not prevent the other eligible platforms from attempting publication.


## Posting cadence

Posting schedules are defined in pipeline/cadence.py.

The current POSTING_DAYS configuration is:

| Platform  | Posting schedule          |
| --------- | ------------------------- |
| LinkedIn  | Monday, Wednesday, Friday |
| Facebook  | Daily                     |
| Instagram | Daily                     |

should_post_today() checks whether a platform is eligible to post on a given day.

If no date is provided, the function uses the current business date in:

BUSINESS_TIMEZONE = "America/Phoenix"
This prevents the posting schedule from being affected by the timezone of the Cloud Run server.

The decision about when cadence eligibility becomes locked into a review is handled elsewhere in the pipeline; cadence.py only determines whether a platform is eligible for a particular date.

## Storage & run-safety

**GCS image storage.**

pipeline/storage.py supports both uploading and downloading generated images.

Generated image
→ upload to GCS
→ human review
→ download for publishing
Both directions are needed because Cloud Run's local filesystem is temporary. The original instance that generated the image may no longer exist when the review is approved.

GCS therefore provides durable image storage between generation, approval, and publishing.

It also provides the hosted image URL required by Instagram's publishing flow.

**Run lock.**

pipeline/run_lock.py uses Firestore transactions to prevent multiple scheduled pipeline runs from starting at the same time.

The transaction ensures that checking for an existing lock and acquiring the new lock happens atomically.

A stale-lock timeout is also included. If a run terminates unexpectedly without releasing its lock, an old lock can eventually be treated as stale so future scheduled runs are not blocked permanently.

## Email/notification system

**Recipient configuration switches on `ENVIRONMENT`, but only the development path is currently active.** `get_review_recipients()` reads `REVIEW_DEV_TO`/`REVIEW_DEV_CC` when `ENVIRONMENT` is set to development, or `REVIEW_PROD_TO`/`REVIEW_PROD_CC` in production. **Right now, only the dev configuration is live** — real notifications currently go to a development inbox, not to the actual clinical reviewers. Swapping to production recipients (Dr. Nguyen as primary, Dr. Shelton CC'd, per his own instruction in a team meeting) is a required step before this goes live for real, not something already done.

**SMTP authentication uses a Gmail App Password pulled from Secret Manager (`review-gmail-app-password`), with `REVIEW_EMAIL_FROM` as the sending identity — worth knowing the exact failure mode if this ever breaks again.** During deployment testing, three different spellings of the same practice email address (`trinitytreepysch@gmail.com`, `trinitytreepsych@gmail.com`, `trinitytreepysych@gmail.com`) ended up set independently across local `.env` and two separate deployed services. The result was a genuine `535 Bad Credentials` SMTP rejection — which reads exactly like a wrong or expired App Password, but was actually just a typo in the sending address. If this error ever recurs, check `REVIEW_EMAIL_FROM`'s exact spelling everywhere it's set before assuming the credential itself is bad.

**Four distinct email functions exist, each tied to a specific point in the review lifecycle — not one generic "send an email" function:**

| Function | Fires when | Called from |
|---|---|---|
| `send_review_email()` | A new draft is ready for review | `send_for_review` (`pipeline/graph.py`) |
| `send_review_followup_email()` | A review has been pending 24+ hours | `check_and_resolve_stale_review()` (`pipeline/review.py`) |
| `send_supersede_email()` | A review expired at 48 hours, unresolved | `check_and_resolve_stale_review()` (`pipeline/review.py`) |
| `send_resolution_email()` | A decision (approve/reject) was just resolved | `/review/confirm` (`main.py`) |

All four live in `review/notifications.py` and share the same underlying `send_email()` (`review/emailer.py`), plain-text-plus-HTML pattern.

**Approval links are shared, not personalized — deliberate, since only the outcome matters, not who specifically acted.** `build_review_links()` generates one Approve/Reject URL pair per review, sent identically to every recipient rather than a distinct link per person. Any recipient clicking either link resolves the review for everyone.

**`send_resolution_email()`'s `resolved_by_email` parameter is built for a future feature, currently unreachable in practice — worth understanding as forward-looking, not dead code.** If a resolver's identity were known, this parameter would exclude that person from the resolution notification, so only the non-clicking reviewer gets notified. Since links are currently shared and carry no identity information, there's genuinely no way to know who clicked — this parameter is always effectively `None` in real use today, and the function correctly falls back to notifying both recipients every time. This would only become active if a future personalized-link feature is built.

**The GET-request vulnerability that led to the current confirmation-page design is documented in full under Phase 5 / IAM & security below — this section only covers link generation, not the fix itself.**

**Two files that no longer exist are worth a brief historical note, so their absence in git history doesn't read as confusing.** `review/links.py` was early scaffolding for link generation, later found to duplicate logic already built into `notifications.py`'s own `build_review_links()` — removed once that duplication was caught. `review/gate.py` was an early placeholder from initial project planning that was never filled in; the review-gate logic it was meant to hold ended up living directly in `pipeline/graph.py`'s nodes instead. Both were confirmed unused (no imports anywhere in the codebase) before deletion.

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

**24-hour nudge and superseded-thread notifications are both fully built and confirmed working**. `send_review_followup_email()` and `send_supersede_email()` (both in `review/notifications.py`) are called from `check_and_resolve_stale_review()`. Verified live, end-to-end, unattended: a real pending thread correctly received a 24-hour nudge, correctly expired and superseded at 48 hours, and correctly triggered fresh content generation immediately afterward -- which then received its own nudge on schedule, confirming the cycle holds across repeated generations, not just once.

**Cloud Run's access control applies at the whole-service level, with no native way to make one route public while keeping others private.** This was confirmed directly against Google's own documentation before any architecture decision was made, rather than assumed: there is no per-route IAM mechanism in Cloud Run. Given `/review` needs to be reachable by a reviewer clicking a link from any device, while `/run` must never be triggered by anyone but Cloud Scheduler, a single service could not satisfy both requirements at once.

**The fix is running two separate Cloud Run services from the identical container image, not two different codebases.** `tt-social-pipeline` is the private service (`--no-allow-unauthenticated`) and handles `/run` and `/check-pending-reviews` — both meant to be triggered only by Cloud Scheduler's own service-account identity. `tt-social-pipeline-review` is the public service (`--allow-unauthenticated`) and handles all reviewer-facing traffic (`/review`, `/review/confirm`). Both are deployed from the exact same image; only their Cloud Run IAM setting differs.

**A `SERVICE_ROLE` environment variable (`private`/`public`) provides a second, application-level safeguard on top of the platform-level split.** Because both services share one image, `/run` and `/check-pending-reviews` technically still exist as real routes on the public service too — nothing at the code level prevents someone from hitting them there directly. Both routes check `SERVICE_ROLE` and return a clean `403` if it isn't `"private"`, regardless of what a request's URL happens to be. This is deliberately redundant with the IAM split: if the platform-level configuration is ever accidentally changed, this check still holds.

**A real vulnerability was found and fixed via live testing, not caught in review -- worth documenting in full detail elsewhere, summarized here.** The original `/review` design resolved a decision directly on a `GET` request. An institutional email security scanner pre-fetching links to check for malware silently triggered a real reject decision before a human ever opened the email -- confirmed twice, from actual production logs (a `HEAD`/`GET` request with a non-human user agent, arriving seconds after the email sent). Fixed by splitting into a read-only `GET /review` confirmation page and a `POST /review/confirm` action route, the latter only reachable via a genuine form submission.

**The vulnerability, in full detail: automated email link-scanning silently executed real review decisions before a human ever saw them.** The original `/review` route resolved a decision directly on a plain `GET` request — a URL that only needed to be *visited*, not deliberately submitted, to take effect. Many institutional email security systems automatically pre-fetch every link in an incoming message to check it for malware before the recipient ever opens it, treating that fetch as a routine safety check with no expectation that visiting a link could itself change anything. This is exactly what happened here: production logs showed a `HEAD`/`GET` request carrying a clearly non-human user agent, arriving mere seconds after a review email was sent — well before either intended recipient had opened it. That automated fetch silently executed a real reject decision. This wasn't caught in code review or local testing; it only surfaced because a live production email happened to be scanned this way, and the resulting Firestore record and Cloud Logging entries were traced back to confirm exactly what occurred. It was confirmed a second time on a separate occasion, with an identical signature, ruling out a one-off fluke.

**The fix separates a safe, read-only confirmation step from the actual decision-executing action.** `GET /review` now only renders a confirmation page — showing the topic and the pending decision, with a genuine "Confirm" button — and has no side effects at all, no matter how many times or how automatically it's requested. Only submitting that form issues a `POST /review/confirm`, which is where `resolve_pending_review()` and the actual graph resume now live. Automated scanners routinely fetch links but essentially never submit forms, which is precisely why this split closes the gap. A smaller usability fix rode along with this change: a real, non-scanner approval was found to take roughly 30 seconds end to end (publishing sequentially to three platforms), and a fully blank screen during that wait had led to a genuine accidental double-submission during testing. The confirmation page now shows immediate "Processing..." feedback the instant the button is pressed, and `/review/confirm` returns a proper human-readable success page instead of raw JSON.

**The vulnerability, in full detail: automated email link-scanning silently executed real review decisions before a human ever saw them.** The original `/review` route resolved a decision directly on a plain `GET` request — a URL that only needed to be *visited*, not deliberately submitted, to take effect. Many institutional email security systems automatically pre-fetch every link in an incoming message to check it for malware before the recipient ever opens it, treating that fetch as a routine safety check with no expectation that visiting a link could itself change anything. This is exactly what happened here: production logs showed a `HEAD`/`GET` request carrying a clearly non-human user agent, arriving mere seconds after a review email was sent — well before either intended recipient had opened it. That automated fetch silently executed a real reject decision. This wasn't caught in code review or local testing; it only surfaced because a live production email happened to be scanned this way, and the resulting Firestore record and Cloud Logging entries were traced back to confirm exactly what occurred. It was confirmed a second time on a separate occasion, with an identical signature, ruling out a one-off fluke.

**The fix separates a safe, read-only confirmation step from the actual decision-executing action.** `GET /review` now only renders a confirmation page — showing the topic and the pending decision, with a genuine "Confirm" button — and has no side effects at all, no matter how many times or how automatically it's requested. Only submitting that form issues a `POST /review/confirm`, which is where `resolve_pending_review()` and the actual graph resume now live. Automated scanners routinely fetch links but essentially never submit forms, which is precisely why this split closes the gap. A smaller usability fix rode along with this change: a real, non-scanner approval was found to take roughly 30 seconds end to end (publishing sequentially to three platforms), and a fully blank screen during that wait had led to a genuine accidental double-submission during testing. The confirmation page now shows immediate "Processing..." feedback the instant the button is pressed, and `/review/confirm` returns a proper human-readable success page instead of raw JSON.

**The vulnerability, in full detail: automated email link-scanning silently executed real review decisions before a human ever saw them.** The original `/review` route resolved a decision directly on a plain `GET` request — a URL that only needed to be *visited*, not deliberately submitted, to take effect. Many institutional email security systems automatically pre-fetch every link in an incoming message to check it for malware before the recipient ever opens it, treating that fetch as a routine safety check with no expectation that visiting a link could itself change anything. This is exactly what happened here: production logs showed a `HEAD`/`GET` request carrying a clearly non-human user agent, arriving mere seconds after a review email was sent — well before either intended recipient had opened it. That automated fetch silently executed a real reject decision. This wasn't caught in code review or local testing; it only surfaced because a live production email happened to be scanned this way, and the resulting Firestore record and Cloud Logging entries were traced back to confirm exactly what occurred. It was confirmed a second time on a separate occasion, with an identical signature, ruling out a one-off fluke.

**The fix separates a safe, read-only confirmation step from the actual decision-executing action.** `GET /review` now only renders a confirmation page — showing the topic and the pending decision, with a genuine "Confirm" button — and has no side effects at all, no matter how many times or how automatically it's requested. Only submitting that form issues a `POST /review/confirm`, which is where `resolve_pending_review()` and the actual graph resume now live. Automated scanners routinely fetch links but essentially never submit forms, which is precisely why this split closes the gap. A smaller usability fix rode along with this change: a real, non-scanner approval was found to take roughly 30 seconds end to end (publishing sequentially to three platforms), and a fully blank screen during that wait had led to a genuine accidental double-submission during testing. The confirmation page now shows immediate "Processing..." feedback the instant the button is pressed, and `/review/confirm` returns a proper human-readable success page instead of raw JSON.

**The vulnerability, in full detail: automated email link-scanning silently executed real review decisions before a human ever saw them.** The original `/review` route resolved a decision directly on a plain `GET` request — a URL that only needed to be *visited*, not deliberately submitted, to take effect. Many institutional email security systems automatically pre-fetch every link in an incoming message to check it for malware before the recipient ever opens it, treating that fetch as a routine safety check with no expectation that visiting a link could itself change anything. This is exactly what happened here: production logs showed a `HEAD`/`GET` request carrying a clearly non-human user agent, arriving mere seconds after a review email was sent — well before either intended recipient had opened it. That automated fetch silently executed a real reject decision. This wasn't caught in code review or local testing; it only surfaced because a live production email happened to be scanned this way, and the resulting Firestore record and Cloud Logging entries were traced back to confirm exactly what occurred. It was confirmed a second time on a separate occasion, with an identical signature, ruling out a one-off fluke.

**The fix separates a safe, read-only confirmation step from the actual decision-executing action.** `GET /review` now only renders a confirmation page — showing the topic and the pending decision, with a genuine "Confirm" button — and has no side effects at all, no matter how many times or how automatically it's requested. Only submitting that form issues a `POST /review/confirm`, which is where `resolve_pending_review()` and the actual graph resume now live. Automated scanners routinely fetch links but essentially never submit forms, which is precisely why this split closes the gap. A smaller usability fix rode along with this change: a real, non-scanner approval was found to take roughly 30 seconds end to end (publishing sequentially to three platforms), and a fully blank screen during that wait had led to a genuine accidental double-submission during testing. The confirmation page now shows immediate "Processing..." feedback the instant the button is pressed, and `/review/confirm` returns a proper human-readable success page instead of raw JSON.

**A separate, lightweight `/check-pending-reviews` endpoint exists specifically to decouple review-staleness checking from costly content generation — and its own design had a real bug, found and fixed through live testing.** Originally, only `/run` ever checked for stale or nudge-eligible reviews, meaning that check only ran once a day on a fixed schedule. Because real draft/critic/image-generation processing takes a consistent 1-2 minutes, a review's exact age at each daily check could land just barely on the wrong side of the 24- or 48-hour threshold — delaying a nudge or an expiry-triggered redraft by up to a full extra day. `/check-pending-reviews`, triggered hourly by its own Cloud Scheduler job, shrinks that worst-case gap from a day to under an hour, without incurring any generation cost on the (common) hourly ticks where nothing needs to happen. Building this endpoint initially introduced its own bug, though: the underlying check only ever returned a single signal (`"proceed"`) for both "nothing is currently pending" and "something just expired and needs replacing" — meaning *any* quick approve or reject, followed by the very next hourly check finding nothing pending, would also trigger an unwanted fresh draft. This was caught live in production (a new post appearing an hour after a fast rejection) and fixed by splitting the check's result into three distinct states — `skip`, `refill`, and `idle` — so fresh generation is only ever triggered by a genuine expiry, never by the routine, healthy state of "nothing to review right now." A separate, standalone daily Cloud Scheduler job for `/run` was added alongside this fix, since the system had never actually had one — it had been relying entirely on the (buggy) hourly check as its only source of new content.

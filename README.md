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

**`/review` and `/run` now run as two separate Cloud Run services**, since Cloud Run's IAM check applies at the whole-service level with no native per-route control. `tt-social-pipeline` (private, `--no-allow-unauthenticated`) handles `/run` and `/check-pending-reviews`; `tt-social-pipeline-review` (public, `--allow-unauthenticated`) handles reviewer-facing traffic. Both run the identical image -- a `SERVICE_ROLE` env var (`private`/`public`) is checked inside `/run` and `/check-pending-reviews` as defense-in-depth, in case the IAM split is ever misconfigured.

**A real vulnerability was found and fixed via live testing, not caught in review -- worth documenting in full detail elsewhere, summarized here.** The original `/review` design resolved a decision directly on a `GET` request. An institutional email security scanner pre-fetching links to check for malware silently triggered a real reject decision before a human ever opened the email -- confirmed twice, from actual production logs (a `HEAD`/`GET` request with a non-human user agent, arriving seconds after the email sent). Fixed by splitting into a read-only `GET /review` confirmation page and a `POST /review/confirm` action route, the latter only reachable via a genuine form submission.
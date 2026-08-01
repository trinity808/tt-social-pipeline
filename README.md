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
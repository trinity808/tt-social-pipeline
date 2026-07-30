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
# Match Hub API — Cloudflare Worker

Secure proxy: Webflow Match Hub -> this Worker -> SportMonks (token never leaves the
server). Lives inside the same repo as the existing SportMonks -> Webflow sync
(`../sync.py`), which this folder does not touch or depend on.

## Endpoint

```
GET /api/match/{sportmonksId}
```

Returns the JSON shape defined in `../contract.md`. `src/mapper.js` is the exact file
verified against real fixtures 19777719 (completed) and 19779165 (upcoming) on
2026-08-26 — see its header comments for what was confirmed directly from the API.

## Deploy via Cloudflare's Git integration (recommended)

1. Push this repo (including the `worker/` folder) to GitHub if it isn't already there.
2. In the Cloudflare dashboard: **Workers & Pages → Create → Import a repository** (or
   **Connect to Git** on an existing Worker), and select this repository.
3. When configuring the build:
   - **Root directory**: `worker`
   - **Build command**: `npm install`
   - **Deploy command**: `npx wrangler deploy`
4. Deploy. Cloudflare will redeploy automatically on every push to the connected
   branch — the existing GitHub Actions sync job is untouched and keeps running
   independently.
5. Add the secret (dashboard, not committed anywhere):
   **Workers & Pages → (this Worker) → Settings → Variables and Secrets → Add →
   Secret** — name `SPORTSMONKS_API_TOKEN`, value = your active SportMonks token.
6. (Optional) Update `MATCH_HUB_ALLOWED_ORIGIN` in `wrangler.toml` to your real
   Webflow custom domain once one is live, then redeploy.

## Deploy manually instead (if you'd rather not use Git integration)

```
cd worker
npm install
npx wrangler login
npx wrangler secret put SPORTSMONKS_API_TOKEN
npx wrangler deploy
```

## Test after deploy

```
curl https://<your-worker-subdomain>.workers.dev/api/match/19777719
```

Should return the full shaped JSON (teams, score, events, lineups, statistics) for
the completed Al Ittihad vs Al Kholood fixture. Then test an upcoming fixture:

```
curl https://<your-worker-subdomain>.workers.dev/api/match/19779165
```

Should return the same shape with `status: "Not Started"` and empty/null events,
lineups, and statistics — no errors.

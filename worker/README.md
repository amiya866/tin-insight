# Tin Insight Worker

Cloudflare Worker for the public tin dashboard.

## What it does

- Keeps the Zhiji API key in a Cloudflare encrypted secret.
- Serves GET /api/quotes with a 15-second edge cache.
- Falls back to a five-minute stale snapshot if the upstream call fails.
- Allows browser calls from https://wangziquan-del.github.io.
- Exposes GET /health for monitoring.

## Local checks

From the repository root:

```powershell
node worker/test-worker.mjs
npx wrangler deploy --dry-run --config worker/wrangler.toml
```

## One-time deployment

```powershell
npx wrangler login
npx wrangler secret put ZHIJI_API_KEY --config worker/wrangler.toml
npx wrangler deploy --config worker/wrangler.toml
```

Do not commit worker/.dev.vars or any API key.

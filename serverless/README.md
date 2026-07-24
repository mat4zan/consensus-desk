# Direct add/remove (no GitHub, no email)

By default the dashboard's add/remove open a one-click GitHub issue. Deploy this
tiny Cloudflare Worker once and it happens **directly from the dashboard** — no
GitHub visit, no notification emails. Free tier is plenty.

## 1. A GitHub token (repo-scoped)
GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate.
- Repository access: only `mat4zan/consensus-desk`
- Permissions: **Contents → Read and write** (that's all it needs)
- Copy the token.

## 2. Deploy the worker
- dash.cloudflare.com → **Workers & Pages** → Create → Worker → deploy the
  starter, then **Edit code** and paste `worker.js`. Save & deploy.
- **Settings → Variables**, add (encrypt the first two):
  - `GITHUB_TOKEN`  = the token from step 1
  - `MANAGE_SECRET` = any passphrase you choose
  - `REPO`          = `mat4zan/consensus-desk`
  - `ALLOWED_ORIGIN` = `https://mat4zan.github.io`  (optional)
- Copy the worker URL (e.g. `https://consensus-desk.<you>.workers.dev`).

## 3. Point the dashboard at it
Tell me the worker URL — I set `window.WORKER_URL` in `dashboard/index.html`
and redeploy. The first add/remove asks for your passphrase once (stored in the
browser); after that, add and swipe-to-remove are instant and silent.

The token never touches the public page — it lives only in the Worker.

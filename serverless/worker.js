/**
 * Consensus-desk management endpoint (Cloudflare Worker).
 *
 * Lets the dashboard add/remove topics WITHOUT visiting GitHub or getting
 * emails: it validates a passphrase, then triggers a repository_dispatch that
 * the add/remove workflows listen for. The GitHub token lives only here (never
 * in the public page).
 *
 * Set three Worker variables/secrets:
 *   GITHUB_TOKEN   — fine-grained PAT for the repo, "Contents: read & write"
 *   MANAGE_SECRET  — a passphrase you also type once into the dashboard
 *   REPO           — "mat4zan/consensus-desk"
 * Optionally ALLOWED_ORIGIN — "https://mat4zan.github.io" (defaults to *).
 */
export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "content-type",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });
    if (request.method !== "POST") return json({ error: "POST only" }, 405, cors);

    let body;
    try { body = await request.json(); } catch { return json({ error: "bad json" }, 400, cors); }
    const { action, secret, request: req, id } = body || {};

    if (!secret || secret !== env.MANAGE_SECRET) return json({ error: "unauthorized" }, 401, cors);

    let event_type, client_payload;
    if (action === "add" && req) {
      event_type = "topic-request";
      client_payload = { request: String(req).slice(0, 300) };
    } else if (action === "remove" && id) {
      event_type = "topic-remove";
      client_payload = { id: String(id).slice(0, 120) };
    } else {
      return json({ error: "bad action" }, 400, cors);
    }

    const gh = await fetch(`https://api.github.com/repos/${env.REPO}/dispatches`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "User-Agent": "consensus-desk-worker",
        "content-type": "application/json",
      },
      body: JSON.stringify({ event_type, client_payload }),
    });
    if (gh.status !== 204) {
      return json({ error: "github", status: gh.status, detail: (await gh.text()).slice(0, 200) }, 502, cors);
    }
    return json({ ok: true }, 200, cors);
  },
};

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status, headers: { "content-type": "application/json", ...cors },
  });
}

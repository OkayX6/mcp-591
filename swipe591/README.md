# 591 Swipe

A private, single-user "Tinder" for new 591 rental listings: save some searches,
a poller stores every new matching listing in Directus, and a mobile web app
deals them as cards to swipe (→ like, ← dislike, ↑ coup de cœur, ↶ undo).

```
591 BFF API ──(poller, every ~30 min)──▶ Directus apt_* ◀──(FastAPI /api)── PWA
```

- `mcp_591/rent.py`: the rent search and mapping logic, shared with the MCP server.
- `swipe591/poller.py`: for each active search, reads the first 3 result pages. It
  stores the listings it has never seen, each with its detail. `post_id` is the
  primary key, so a listing is fetched once.
- `swipe591/app.py`: the JSON API plus the static PWA (`swipe591/static/`).
- `swipe591/directus.py`: the only Directus calls the app makes, all on `apt_*`.
- `swipe591/schema.py`: the data model, applied by `swipe591/apply_schema.py`.

## Data model (Directus)

| Collection     | What                                                                                                                                                 |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apt_searches` | Saved criteria in 591's own names: `region` 桃園市, `section` 中壢區, `kind` 整層住家, `shape`, `pattern` 3房, `price_min`/`price_max` (NT$/month), `keywords`, `active` |
| `apt_listings` | One row per 591 post: the card fields, `photos`, `detail` (json), `first_seen`, `delisted`, and the verdict (`verdict` like/superlike/dislike/null, `decided_at`, `note`, `synced_591`) |

The verdict lives on the listing (there is one user), so the deck is simply
`verdict IS NULL AND NOT delisted ORDER BY first_seen DESC`.

To change the model, edit `schema.py` and re-apply with a temporary admin token.
Applying is additive and idempotent: renames and type changes are done by hand in
Directus.

```bash
DIRECTUS_URL=https://… DIRECTUS_ADMIN_TOKEN=… uv run python -m swipe591.apply_schema --dry-run
DIRECTUS_URL=https://… DIRECTUS_ADMIN_TOKEN=… uv run python -m swipe591.apply_schema --policy <apt-swipe policy id>
```

## Setup

1. **Check 591 answers from the droplet.** 591 sits behind Cloudflare, which can
   block datacenter IPs:

   ```bash
   uv run pytest -m integration
   ```

   If it is blocked, run only the `poller` service from a home machine (same
   image and `.env`). It only writes to Directus.
2. **Directus.**
   - Create a role and policy named `apt-swipe` and a user with a static token.
   - Run `apply_schema` with `--policy` (admin token, once).
   - The app's `DIRECTUS_TOKEN` is the `apt-swipe` user's token, never the admin one.
3. **Deploy.** `deploy/docker-compose.yml` sits next to the gateway on the
   droplet, with a `.env` that is never committed (the keys are listed in the
   compose file). An HTTPS reverse proxy forwards to `127.0.0.1:5290`. CI
   (`.github/workflows/swipe-image.yml`) builds and pushes to DOCR on every
   push to `main`. It needs, in this repo's GitHub settings:
   - the `DIGITALOCEAN_ACCESS_TOKEN` secret;
   - the `SWIPE_IMAGE` variable.

   The gateway's Watchtower updates the containers.
4. Open the site, sign in with `SWIPE_PASSWORD` and add a search under *Recherches*.

Locally:

```bash
uv sync --dev
DIRECTUS_URL=… DIRECTUS_TOKEN=… SWIPE_PASSWORD=… SWIPE_SESSION_SECRET=… SWIPE_COOKIE_SECURE=false \
  uv run uvicorn --factory swipe591.app:from_env --reload
uv run python -m swipe591.poller --once
```

## Phase 2: sync likes to the 591 account's favorites (not built yet)

No public source documents 591's login or favorites endpoints. Login probably
goes through addcn's OneID behind Cloudflare, with SMS codes and OAuth, so
**the login is not scripted**. Instead:

1. **Capture the endpoints once.** Sign in on m.591.com.tw with DevTools →
   Network open. Add a listing to 收藏, remove it, then open 我的收藏. Save the
   requests as a HAR file (it holds the session cookies: share it carefully, and
   sign out afterwards to invalidate it).
2. **`Client591Member`.** It reuses the pasted `Cookie` header from a
   "Connexion 591" page in the app, stored server-side. A like pushes the
   favorite and sets `synced_591`. A 401 asks for a fresh paste.

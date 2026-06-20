# WHOOP Policy Layer for AI Assistants

A small public service that turns WHOOP recovery and sleep data into deterministic AI interaction policy.

Instead of giving an assistant loose advice like “user seems low recovery,” this service returns a typed contract:

- whether the assistant may message
- what message type is allowed
- what behaviors are blocked
- the exact approved message
- the audit log status

This is not medical advice. It only changes assistant interaction behavior.

## Why This Exists

Most AI assistants improvise. If they see health context, they may still over-message, dump a huge task list, or later reconstruct why they acted without a real log.

This service makes the interaction policy explicit and auditable.

## Quickstart

```bash
git clone <your-repo-url>
cd whoop-policy-layer
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m whoop_policy_layer.server
```

Open:

```text
http://localhost:8080/demo/drift-risk
```

The demo works before WHOOP OAuth is configured.

## WHOOP Setup

1. Create a WHOOP app at the WHOOP Developer Portal.
2. Set your redirect URI:
   - Local: `http://localhost:8080/oauth/whoop/callback`
   - Railway: `https://YOUR-APP.up.railway.app/oauth/whoop/callback`
3. Add env vars:
   - `WHOOP_CLIENT_ID`
   - `WHOOP_CLIENT_SECRET`
   - `WHOOP_REDIRECT_URI`
   - `PUBLIC_BASE_URL`
   - `DATABASE_URL`
4. Visit `/oauth/whoop/start`.
5. Confirm `/health` returns `whoop_connected: true`.

## Main Endpoints

- `GET /health`
- `GET /token-status`
- `GET /oauth/whoop/start`
- `GET /oauth/whoop/callback`
- `GET /api/context`
- `GET /api/policy`
- `POST /api/record-outcome`
- `GET /demo/drift-risk`
- `POST /mcp`

## MCP Tools

- `get_whoop_context`
- `get_behavior_policy`
- `record_policy_outcome`
- `simulate_policy`

## Local Test

```bash
python -m unittest discover -s tests
```

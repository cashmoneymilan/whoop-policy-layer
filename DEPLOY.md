# Railway Deploy

## 1. Create WHOOP App

Create an app in the WHOOP Developer Portal and add this redirect URI:

```text
https://YOUR-RAILWAY-DOMAIN.up.railway.app/oauth/whoop/callback
```

## 2. Deploy

Create a new Railway project from this repository. Add a Postgres service if you want durable hosted logs.

## 3. Set Variables

```text
PUBLIC_BASE_URL=https://YOUR-RAILWAY-DOMAIN.up.railway.app
WHOOP_CLIENT_ID=...
WHOOP_CLIENT_SECRET=...
WHOOP_REDIRECT_URI=https://YOUR-RAILWAY-DOMAIN.up.railway.app/oauth/whoop/callback
DATABASE_URL=${{ Postgres.DATABASE_URL }}
```

## 4. Connect WHOOP

Visit:

```text
https://YOUR-RAILWAY-DOMAIN.up.railway.app/oauth/whoop/start
```

Then verify:

```text
https://YOUR-RAILWAY-DOMAIN.up.railway.app/health
```

Expected:

```json
{ "whoop_connected": true }
```

## 5. Add To Poke

Add the MCP endpoint:

```text
https://YOUR-RAILWAY-DOMAIN.up.railway.app/mcp
```

Then verify Poke sees:

```text
get_whoop_context
get_behavior_policy
record_policy_outcome
simulate_policy
```

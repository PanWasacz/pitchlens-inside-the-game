# Deploying PitchLens to Azure

The public demo runs on **Azure Static Web Apps** (the studio plus a managed
Python Function at `/api/explain`). The function's agents use a model deployed
in **Microsoft Foundry** (Azure OpenAI). Only the synthetic match is deployed:
real footage and CV output live in the git-ignored `match/` folder and are
never built.

```
browser (web/dist)  ──POST /api/explain──▶  Static Web App managed Function (api/)
                                              tools on api/data (synthetic match)
                                              Analyst → Explainer → Verifier → Personalizer
                                                          │
                                                          ▼
                                              Microsoft Foundry model deployment
```

## 1. Static Web App (public link)

1. [portal.azure.com](https://portal.azure.com) → **Create a resource** → **Static Web App**.
2. Plan **Free**, region **West Europe**.
3. Source **GitHub** → sign in → repository `pitchlens-inside-the-game`, branch `main`.
4. Build presets **Custom**:
   | field | value |
   |---|---|
   | App location | `web` |
   | Api location | `api` |
   | Output location | `dist` |
5. **Create**. Azure commits a GitHub Actions workflow
   (`.github/workflows/azure-static-web-apps-*.yml`) and runs the first deployment.
   Run `git pull` afterwards so you have it locally.
6. The site URL is on the resource's **Overview** page. Every push to `main` redeploys.

`web/staticwebapp.config.json` sets the Python 3.11 API runtime, the `.jsonl`
MIME type, cache headers for `/data/*` and the SPA fallback, and blocks `/local/*`.

Without model settings the site already works: `/api/explain` answers with
template explanations built from the same tools and checks (`engine: "fallback"`).

## 2. Model in Microsoft Foundry

1. [ai.azure.com](https://ai.azure.com) → create a project.
2. **Models + endpoints** → **Deploy model** → `gpt-4o-mini` (or the newest
   "mini" chat model offered; it needs tool calling and JSON output).
   Pick a region with quota, e.g. Sweden Central or East US.
3. Copy the **endpoint** (`https://<resource>.openai.azure.com/` or
   `https://<resource>.services.ai.azure.com/`), the **key** and the **deployment name**.
4. Portal → your Static Web App → **Settings → Environment variables** → add:
   | name | value |
   |---|---|
   | `AZURE_OPENAI_ENDPOINT` | the endpoint |
   | `AZURE_OPENAI_API_KEY` | the key |
   | `AZURE_OPENAI_DEPLOYMENT` | the deployment name, e.g. `gpt-4o-mini` |
   | `AZURE_OPENAI_API_VERSION` | optional, default `2024-10-21` |
5. **Apply**. The next request uses the model (`engine: "foundry"` in the response
   and in the "How this was produced" trace).

Keys exist only in Azure settings and in the git-ignored `api/local.settings.json`.
Set a budget alert on the subscription: the endpoint is public.

## 3. Check the deployment

```bash
curl -X POST https://<your-site>.azurestaticapps.net/api/explain -H "Content-Type: application/json" -d "{\"t\": 207, \"mode\": \"analyst\", \"lang\": \"en\"}"
```

Expect `"status": "ok"`, the offside of N. Pellegrue at 03:32 and four trace steps.

## Local development

```bash
python api/local_server.py      # agents on http://localhost:7071 (stdlib only)
cd web && npm run dev           # studio on http://localhost:5173, /api proxied to 7071
```

`start.bat` starts both. To use the model locally, copy
`api/local.settings.example.json` to `api/local.settings.json` and fill in the values.

Tests (no Azure needed; a scripted model exercises the Verifier's revision loop):

```bash
cd api
python -m unittest discover -s tests -v
```

After regenerating the synthetic match, refresh the function's copy:

```bash
python api/build_data.py
```

## How the agents work

| agent | job | model calls |
|---|---|---|
| Analyst | calls tools (max 6) and picks the 3 to 6 facts that matter | 1 to 3 |
| Explainer | 2 to 4 sentences on why the moment matters; every sentence cites fact ids | 1 (+1 revision) |
| Verifier | code checks every number, clock time and player name against the cited facts, then the model checks logic; one revision, then unsupported sentences are dropped | 1 to 2 |
| Personalizer | analyst or fan style, favourite team and player, EN / PL / ES; its output is checked again so it cannot add facts | 1 (+1 fix) |

Tools (`api/pitchlens_agents/tools.py`) compute every number: `get_events`,
`get_player_stats`, `get_team_shape`, `get_offside_state`, `get_possession`,
`get_zone_activity` (for zones the pundit drew). Each step falls back to
templates if the model fails, and the whole request stays under a 38 s budget
(Static Web Apps stops API calls at about 45 s). Answers are cached per
moment and audience.

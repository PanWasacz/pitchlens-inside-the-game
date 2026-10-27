# Deploying PitchLens to Azure

The public demo runs on **Azure App Service** (Linux, Python 3.11): one standard-library
process, `api/server.py`, serves the studio and `POST /api/explain`. The agents use a
model deployed in **Microsoft Foundry**. Only the synthetic match is deployed: real
footage and CV output live in the git-ignored `match/` folder and are never built.

```
browser ──GET /, /assets, /data──▶  App Service: python server.py ── static studio (web/dist, gzip)
        ──POST /api/explain────▶                                 └─ Analyst → Explainer → Verifier → Personalizer
                                                                     tools on api/data (synthetic match)
                                                                           │
                                                                           ▼
                                                             Microsoft Foundry model deployment
```

Use any region your subscription allows. App Service and Foundry models are available
in most European regions (for example `swedencentral` or `polandcentral`).

## 1. Model in Microsoft Foundry

1. [ai.azure.com](https://ai.azure.com) → create a project (this creates an AI Services resource).
2. **Models + endpoints** → **Deploy model** → `gpt-4.1-mini` (or `gpt-4o-mini`; it needs
   tool calling and JSON output). Reasoning models also work but are slower.
3. Note the resource **endpoint**, a **key** and the **deployment name**.

## 2. Web App

```powershell
$rg = "rg-pitchlens"; $loc = "swedencentral"; $app = "pitchlens-studio-<unique>"
az appservice plan create -n plan-pitchlens -g $rg -l $loc --is-linux --sku F1   # or B1
az webapp create -n $app -g $rg -p plan-pitchlens --runtime "PYTHON:3.11"
az webapp config set -n $app -g $rg --startup-file "python server.py"
az webapp config appsettings set -n $app -g $rg --settings `
  "AZURE_OPENAI_ENDPOINT=<endpoint>" "AZURE_OPENAI_API_KEY=<key>" "AZURE_OPENAI_DEPLOYMENT=gpt-4.1-mini" `
  "SCM_DO_BUILD_DURING_DEPLOYMENT=true"
az resource update -g $rg --name scm --namespace Microsoft.Web --resource-type basicPublishingCredentialsPolicies --parent "sites/$app" --set properties.allow=true
az webapp deployment list-publishing-profiles -n $app -g $rg --xml > publish-profile.xml
```

`AZURE_OPENAI_API_VERSION` is optional (default `2024-10-21`). Keys exist only in the
App Service settings and in the git-ignored `api/local.settings.json`. Set a budget alert
on the subscription: the endpoint is public.

## 3. Deploy from GitHub

In the repository: **Settings → Secrets and variables → Actions**
- secret `AZURE_WEBAPP_PUBLISH_PROFILE`: the content of `publish-profile.xml`;
- variable `AZURE_WEBAPP_NAME`: the app name.

Run **Actions → Deploy to Azure App Service → Run workflow** (or push to `main`). The
workflow runs the agent tests, builds `web/`, assembles the package with
`scripts/build_site.py` (server, agents, data, studio, gzip copies) and deploys it.
Until the secret and variable exist, the deploy step is skipped.

## 4. Check

```bash
curl -X POST https://<app>.azurewebsites.net/api/explain -H "Content-Type: application/json" -d "{\"t\": 210, \"mode\": \"analyst\", \"lang\": \"en\"}"
```

Expect `"engine": "foundry"`, the offside of N. Pellegrue at 03:32 and four trace steps.
Logs: `az webapp log tail -n <app> -g rg-pitchlens`.

## Monitoring (optional)

Web App → **Monitoring → Application Insights** → turn on. Each request logs one line
`pitchlens.explain {...}` with the moment type, engine, model calls, tokens, total time
and per-agent status and duration:

```kusto
traces | where message startswith "pitchlens.explain" | order by timestamp desc
```

## Precomputed answers

With the model settings in your environment or `api/local.settings.json`:

```bash
python api/precompute.py          # every key moment and a recap every 30 s, EN/PL/ES, analyst/fan
```

The answers (with their agent trace) go to `api/data/precomputed.json`; commit it and the
server returns them instantly. Anything else (favourite player, drawn zones) still runs
the agents live.

## Local development

```bash
python api/server.py            # agents on http://localhost:7071 (stdlib only)
cd web && npm run dev           # studio on http://localhost:5173, /api proxied to 7071
```

`start.bat` starts both. To run exactly what is deployed:

```bash
cd web && npm run build && cd ..
python scripts/build_site.py
python site/server.py           # studio and API on http://localhost:7071
```

Tests (no Azure needed; a scripted model exercises the Verifier's revision loop):

```bash
cd api
python -m unittest discover -s tests -v
```

After regenerating the synthetic match, refresh the agents' copy: `python api/build_data.py`.

## How the agents work

| agent | job | model calls |
|---|---|---|
| Analyst | calls tools (max 6, all in its first turn) and picks the 3 to 6 facts that matter | 1 to 2 |
| Explainer | 2 to 4 sentences on why the moment matters (3 to 5 for a recap); every sentence cites fact ids | 1 (+1 revision) |
| Verifier | code checks every number, clock time and player name against the cited facts, then the model checks logic; one revision, then unsupported sentences are dropped | 1 to 2 |
| Personalizer | analyst or fan style, favourite team and player, EN / PL / ES; its output is checked again so it cannot add facts | 1 (+1 fix) |

Tools (`api/pitchlens_agents/tools.py`) compute every number: `get_events`,
`get_player_stats`, `get_team_shape`, `get_offside_state`, `get_possession`,
`get_zone_activity`, `get_momentum`, `get_match_summary`. Each step falls back to
templates if the model fails, and a request stays within a 38 s budget. Answers are
cached per moment and audience.

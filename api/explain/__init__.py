"""POST /api/explain - multi-agent explanation of the current match moment."""

from __future__ import annotations

import json
import logging

import azure.functions as func

from pitchlens_agents.agents import explain
from pitchlens_agents.match import demo_match
from pitchlens_agents.request import BadRequest, parse_request


def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        return _json({"status": "error", "message": "Body must be JSON."}, 400)
    try:
        result = explain(parse_request(body, demo_match()))
    except BadRequest as e:
        return _json({"status": "error", "message": str(e)}, 400)
    except Exception:  # never leak internals, but keep them in the logs
        logging.exception("explain failed")
        return _json({"status": "error", "message": "The analyst is unavailable right now."}, 500)
    return _json(result, 200)


def _json(data: dict, status: int) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(data, ensure_ascii=False), status_code=status, mimetype="application/json", charset="utf-8")

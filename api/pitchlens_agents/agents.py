"""The explain pipeline: Analyst -> Explainer -> Verifier -> Personalizer.

All agents share one session state (the FactStore). Tools compute the numbers,
the model only selects, phrases and checks. Each step falls back to templates
when the model is missing or fails, so the endpoint always answers."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict

from . import fallback
from .llm import LLM, Budget, LLMError
from .match import DATA_DIR, Match, clock, demo_match
from .tools import TOOL_SCHEMAS, Fact, FactStore, match_context, player_index, run_tool, top_player
from .verify import Evidence, check_sentences, check_text

MAX_TOOL_CALLS = 6
ANALYST_ROUNDS = 2
RECAP_STEP_S = 30  # recaps are computed as of whole half-minutes, so they can be precomputed
REQUEST_BUDGET_S = 38.0
LANGS = {"en": "English", "pl": "Polish", "es": "Spanish"}

_cache: OrderedDict[str, dict] = OrderedDict()
CACHE_SIZE = 256


# ---------------------------------------------------------------- moment


def recap_moment(m: Match, t: float) -> dict:
    """The match so far, from kick-off until t."""
    score = m.score_at(t)
    leader = "home" if score["home"] > score["away"] else "away" if score["away"] > score["home"] else None
    return {
        "type": "recap", "event_id": None, "t": t, "clock": clock(t), "analysis_t": t,
        "team": leader, "team_short": m.short(leader), "defending": "home",
        "player_id": top_player(m, t), "names": {}, "benefits": m.short(leader), "window": [0.0, t],
    }


def resolve_moment(m: Match, t: float, event_id: int | None = None) -> dict:
    """The key moment (shot / offside) the viewer is looking at, else open play at t."""
    e = m.event(event_id) if event_id is not None else None
    if e is None or e["type"] not in ("shot", "offside"):
        near = [k for k in m.key_moments() if t - 12 <= k["t"] <= t + 8]
        e = min(near, key=lambda k: abs(k["t"] - t)) if near else None
    if e is None:
        fr = m.frame_at(t)
        team = fr.get("possession")
        return {
            "type": "open_play", "event_id": None, "t": t, "clock": clock(t), "analysis_t": t,
            "team": team, "team_short": m.short(team), "defending": m.other(team) if team else "home",
            "player_id": None, "names": {}, "benefits": m.short(team), "window": [max(0.0, t - 15), t],
        }
    team = e["team"]
    moment = {
        "event_id": e["id"], "t": e["t"], "clock": clock(e["t"]), "analysis_t": e["t"],
        "team": team, "team_short": m.short(team), "defending": m.other(team), "player_id": e["player"],
        "window": [max(0.0, e["t"] - 12), e["t"] + 2],
    }
    if e["type"] == "offside":
        p = m.offside_pass(e)
        moment.update(type="offside", pass_event_id=p["id"] if p else None, analysis_t=p["t"] if p else e["t"])
        moment["clock"] = clock(moment["analysis_t"])
        moment["names"] = {"receiver": m.name(e["player"])}
        moment["benefits"] = m.short(m.other(team))
        moment["window"] = [max(0.0, moment["analysis_t"] - 10), e["t"]]
        return moment
    follow = next((f for f in m.events if f["t"] >= e["t"] and f["t"] - e["t"] < 3 and f["type"] in ("goal", "save")), None)
    if e.get("outcome") == "goal":
        moment.update(type="goal", goal_event_id=follow["id"] if follow else None, benefits=m.short(team))
        moment["names"] = {"scorer": m.name(e["player"])}
    elif e.get("outcome") == "saved":
        moment.update(type="save", save_event_id=follow["id"] if follow else None, benefits=m.short(m.other(team)))
        moment["names"] = {"keeper": m.name(follow["player"]) if follow else "", "shooter": m.name(e["player"])}
    else:
        moment.update(type="shot", benefits=m.short(m.other(team)))
        moment["names"] = {"shooter": m.name(e["player"])}
    return moment


def plan_tools(moment: dict) -> list[tuple[str, dict]]:
    """Deterministic tool plan, used by the template Analyst and to top up the model's picks."""
    t = moment["analysis_t"]
    if moment["type"] == "recap":
        plan = [("get_momentum", {"t_from": 0.0, "t_to": t})] if t >= 60 else []
        if moment["player_id"]:
            plan.append(("get_player_stats", {"player_id": moment["player_id"], "t": t}))
        return plan
    if moment["type"] == "offside":
        return [
            ("get_offside_state", {"t": t, "defending": moment["defending"]}),
            ("get_team_shape", {"team": moment["defending"], "t": t}),
            ("get_player_stats", {"player_id": moment["player_id"], "t": t}),
        ]
    if moment["type"] == "open_play":
        return [
            ("get_possession", {"t_from": max(0.0, t - 60), "t_to": t}),
            ("get_team_shape", {"team": "home", "t": t}),
            ("get_team_shape", {"team": "away", "t": t}),
        ]
    plan = [
        ("get_team_shape", {"team": moment["defending"], "t": max(0.0, t - 2)}),
        ("get_player_stats", {"player_id": moment["player_id"], "t": t}),
    ]
    if moment["type"] == "goal" and t >= 90:
        # Who controlled the build-up: control vs chaos before the goal.
        plan.append(("get_momentum", {"t_from": t - 180, "t_to": t}))
    return plan


def moment_brief(m: Match, moment: dict) -> dict:
    out = {
        "type": moment["type"],
        "clock": moment["clock"],
        "t_seconds": round(moment["analysis_t"], 2),
        "team": moment["team"],
        "defending_team": moment["defending"],
        "main_player_id": moment["player_id"],
        "names": moment["names"],
        "teams": {"home": m.short("home"), "away": m.short("away")},
    }
    return {k: v for k, v in out.items() if v not in (None, {}, "")}


# ---------------------------------------------------------------- helpers


def _facts_json(facts: list[Fact]) -> str:
    return json.dumps([{"id": f.id, "tool": f.tool, "data": f.data} for f in facts], ensure_ascii=False)


class Trace:
    def __init__(self):
        self.steps: list[dict] = []
        self._t = time.monotonic()

    def add(self, agent: str, status: str, summary: str, details: list[str] | None = None):
        now = time.monotonic()
        self.steps.append({"agent": agent, "status": status, "summary": summary, "details": details or [], "ms": round(1000 * (now - self._t))})
        self._t = now


# ---------------------------------------------------------------- agents

ANALYST_SYSTEM = """You are the Analyst agent of PitchLens, a football TV studio tool.
Find out WHAT happened in one key moment of a synthetic match, using the tools.
- Tools compute all numbers. Never compute or guess numbers yourself.
- Make at most {max_calls} tool calls in total, ALL in your first turn (parallel tool calls);
  then answer. Ask for more only if a result was an error.
- Useful choices: get_offside_state at the pass time for offsides; get_team_shape of the
  defending team just before a shot; get_player_stats for the main player; get_momentum
  for who controlled the build-up (control vs chaos); get_possession for open play;
  get_zone_activity for zones the pundit drew.
- For type "recap" (the match so far): get_match_summary is already given; add
  get_momentum over the whole match and get_player_stats for the decisive players.
- Do not write a narrative.
When done, reply with JSON only:
{{"key_facts": ["f1", "..."], "finding": "one short English sentence: what happened"}}
key_facts: the 3 to 6 fact ids that best explain the moment."""

EXPLAINER_SYSTEM = """You are the Explainer agent of PitchLens. Using ONLY the facts given, explain in
2 to 4 English sentences WHY this moment matters (cause and effect, tactics).
If the moment type is "recap", instead tell the story of the match so far in 3 to 5
sentences: the score, the turning points with their times, who controlled play and why.
Rules:
- Every sentence cites the ids of the facts it uses.
- Every number, time (mm:ss) and player name must appear in the cited facts. You may
  round numbers, but keep the units given (m, km, km/h, %). Do not convert units.
- Use team short names (e.g. NBR, KBA) and player names exactly as in the facts.
- No invented details: no weather, crowd, injuries or events not in the facts.
- Put the fact ids ONLY in the "facts" list, never in the sentence text.
Reply with JSON only: {"sentences": [{"text": "...", "facts": ["f2", "f4"]}]}"""

VERIFIER_SYSTEM = """You are the Verifier agent of PitchLens. Numbers and names were already checked by code.
Check each sentence for LOGICAL errors against the facts: wrong team, roles swapped
(attacker vs defender), wrong event type (e.g. a tackle called an interception, a save
called a goal), wrong direction (ahead/behind the line), or a claim the facts contradict.
Do not flag style or missing detail.
Reply with JSON only: {"issues": [{"sentence": 0, "problem": "..."}]} (empty list if all fine)."""

PERSONALIZER_SYSTEM = """You are the Personalizer agent of PitchLens. Rewrite verified sentences for one viewer.
Never add facts: every number and player name must already be in the verified sentences
(or in the favourite player's facts, for the one extra sentence about them).
Style:
- analyst: precise, tactical terms, keep the key numbers, 2 to 4 sentences.
- fan: simple and emotional, at most ONE number, 2 or 3 sentences.
- favourite team given: tell it from their supporters' point of view, without changing facts.
- favourite player given and involved: add one sentence about them from their facts.
Write in {language}. Keep player names as written (Polish may inflect them).
Reply with JSON only: {{"title": "headline, max 8 words", "text": "..."}}"""


def analyst(m: Match, llm: LLM, budget: Budget, moment: dict, store: FactStore, zones: list[dict], trace: Trace) -> list[str]:
    calls: list[str] = []
    picked: list[str] = []
    finding = ""
    if llm.available:
        try:
            msgs = [
                {"role": "system", "content": ANALYST_SYSTEM.format(max_calls=MAX_TOOL_CALLS)},
                {"role": "user", "content": json.dumps({
                    "moment": moment_brief(m, moment),
                    "facts_so_far": json.loads(_facts_json(store.facts)),
                    "players": player_index(m),
                    "pundit_zones": zones,
                }, ensure_ascii=False)},
            ]
            for _ in range(ANALYST_ROUNDS):
                if not budget.allows(25):
                    break
                msg = llm.chat(msgs, tools=TOOL_SCHEMAS, max_tokens=400)
                tool_calls = msg.get("tool_calls") or []
                if not tool_calls:
                    out = _parse_or_none(msg.get("content"))
                    if out:
                        picked = [f for f in out.get("key_facts", []) if store.get(f)]
                        finding = str(out.get("finding", ""))[:300]
                    break
                msgs.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    try:
                        if len(calls) >= MAX_TOOL_CALLS:
                            raise ValueError("tool budget exhausted, answer now")
                        args = json.loads(fn.get("arguments") or "{}")
                        fact = run_tool(m, store, name, args, moment["analysis_t"])
                        calls.append(name)
                        result = {"fact_id": fact.id, "data": fact.data}
                    except Exception as e:  # tool errors go back to the model
                        result = {"error": str(e)}
                    msgs.append({"role": "tool", "tool_call_id": tc.get("id"), "content": json.dumps(result, ensure_ascii=False)})
            if not picked and calls and budget.allows(20):
                msgs.append({"role": "user", "content": "Answer now with the JSON (key_facts, finding)."})
                out = llm.chat_json(msgs, max_tokens=200)
                picked = [f for f in out.get("key_facts", []) if store.get(f)]
                finding = str(out.get("finding", ""))[:300]
        except LLMError as e:
            trace.add("Analyst", "error", f"Model failed ({e}); using the tool plan.")
    model_calls = len(calls)
    # Top up with the deterministic plan so templates always have what they need.
    for name, args in plan_tools(moment):
        if not any(f.tool == name and _same_args(f.args, args) for f in store.facts):
            try:
                run_tool(m, store, name, args, moment["analysis_t"])
            except ValueError:
                pass
    for z in zones[:1]:
        try:
            w = moment["window"]
            run_tool(m, store, "get_zone_activity", {**z, "t_from": w[0], "t_to": w[1]}, moment["analysis_t"])
        except (ValueError, TypeError):
            pass
    context_id = store.facts[0].id
    if not picked:
        picked = [f.id for f in store.facts if f.id != context_id]
    names = ", ".join(calls) if calls else "none"
    mode = "ok" if model_calls else "fallback"
    summary = f"Called {model_calls} tool(s): {names}. Picked {', '.join(picked)}." if model_calls else f"Tool plan: {', '.join(f.tool for f in store.facts[1:])}. Picked {', '.join(picked)}."
    trace.add("Analyst", mode, summary, [finding] if finding else [])
    return picked


def _same_args(a: dict, b: dict) -> bool:
    return all(a.get(k) == v for k, v in b.items() if k in ("team", "player_id", "defending"))


def _parse_or_none(text: str | None) -> dict | None:
    from .llm import parse_json

    try:
        return parse_json(text or "")
    except LLMError:
        return None


FACT_ID = re.compile(r"\b(?:f|fact)[\s_#-]?(\d+)\b", re.I)
INLINE_CITE = re.compile(r"\s*[\(\[]\s*(?:facts?\s*:?\s*)?f\d+(?:(?:\s*[,;&]\s*|\s+)(?:and\s+)?f\d+)*\s*[\)\]]", re.I)


def parse_sentence(s: dict) -> dict:
    """Normalise one Explainer sentence. Models sometimes write the citations into the
    text ("... (f4, f6).") or as one string ("f4, f6"); collect the ids from both."""
    text = str(s.get("text", "")).strip()
    raw = s.get("facts")
    if not raw:  # some models pick their own key: fact_ids, sources, citations, evidence...
        raw = next((v for k, v in s.items() if k != "text" and re.search(r"fact|source|cit|evid|ref", k, re.I)), [])
    if not isinstance(raw, list):
        raw = [raw]
    ids: list[str] = []
    for item in [*map(str, raw), *INLINE_CITE.findall(text)]:
        ids += [f"f{n}" for n in FACT_ID.findall(item) if f"f{n}" not in ids]
    text = INLINE_CITE.sub("", text).strip()
    return {"text": text, "facts": ids, "raw_facts": raw}


def explainer(llm: LLM, budget: Budget, moment_info: dict, facts: list[Fact], problems: list[dict] | None, draft: list[dict] | None) -> list[dict]:
    user = {"moment": moment_info, "facts": json.loads(_facts_json(facts))}
    if problems:
        user["previous_draft"] = draft
        user["problems_to_fix"] = problems
        user["instruction"] = "Rewrite the draft fixing every problem. Drop any claim the facts cannot support."
    out = llm.chat_json(
        [{"role": "system", "content": EXPLAINER_SYSTEM}, {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
        temperature=0.3,
        max_tokens=450,
        timeout=min(20.0, max(5.0, budget.left - 10)),
    )
    sentences = [parse_sentence(s) for s in out.get("sentences", []) if isinstance(s, dict) and s.get("text")]
    if not sentences:
        raise LLMError("Explainer returned no sentences")
    return sentences[: 5 if moment_info.get("type") == "recap" else 4]


def logic_check(llm: LLM, budget: Budget, facts: list[Fact], sentences: list[dict]) -> list[dict]:
    out = llm.chat_json(
        [
            {"role": "system", "content": VERIFIER_SYSTEM},
            {"role": "user", "content": json.dumps({"facts": json.loads(_facts_json(facts)), "sentences": [s["text"] for s in sentences]}, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=300,
        timeout=min(15.0, max(5.0, budget.left - 10)),
    )
    issues = []
    for i in out.get("issues", []):
        if isinstance(i, dict) and isinstance(i.get("sentence"), int) and 0 <= i["sentence"] < len(sentences):
            issues.append({"sentence": i["sentence"], "problem": str(i.get("problem", ""))[:200], "by": "model"})
    return issues


def personalizer(llm: LLM, budget: Budget, sentences: list[dict], audience: dict, fav: Fact | None, problems: list[str] | None) -> dict:
    user = {
        "verified_sentences": [s["text"] for s in sentences],
        "style": audience["mode"],
        "favourite_team": audience.get("team_short"),
        "favourite_player": fav.data if fav else None,
    }
    if problems:
        user["problems_to_fix"] = problems
    out = llm.chat_json(
        [
            {"role": "system", "content": PERSONALIZER_SYSTEM.format(language=LANGS[audience["lang"]])},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        temperature=0.5,
        max_tokens=400,
        timeout=min(15.0, max(5.0, budget.left - 5)),
    )
    text = str(out.get("text", "")).strip()
    if not text:
        raise LLMError("Personalizer returned no text")
    return {"title": str(out.get("title", "")).strip()[:80], "text": text}


# ---------------------------------------------------------------- pipeline


def _cache_key(req: dict) -> str:
    return hashlib.sha1(json.dumps(req, sort_keys=True).encode()).hexdigest()


def moment_key(req: dict, moment: dict) -> str | None:
    """Stable key of a request for precomputed answers (none for zones / favourite player)."""
    if req.get("zones") or req.get("player"):
        return None
    where = moment["event_id"] if moment["event_id"] is not None else round(moment["t"])
    return f"{req.get('task', 'moment')}|{where}|{req['mode']}|{req['lang']}|{req.get('team') or '-'}"


_precomputed: dict | None = None


def precomputed() -> dict:
    """Answers generated ahead of time with the real model (api/precompute.py)."""
    global _precomputed
    if _precomputed is None:
        path = DATA_DIR / "precomputed.json"
        _precomputed = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _precomputed


def explain(req: dict, m: Match | None = None, llm: LLM | None = None, use_precomputed: bool = True) -> dict:
    """req: {task, t, event_id?, mode: analyst|fan, team: home|away|None, player: id|None, lang, zones}"""
    m = m or demo_match()
    llm = llm or LLM()
    recap = req.get("task") == "recap"
    t = req["t"]
    if recap and t >= RECAP_STEP_S:
        t = (t // RECAP_STEP_S) * RECAP_STEP_S
    moment = recap_moment(m, t) if recap else resolve_moment(m, t, req.get("event_id"))
    mkey = moment_key(req, moment)
    if use_precomputed and m.is_demo and mkey and mkey in precomputed():
        return {**precomputed()[mkey], "cached": True, "precomputed": True}
    key = mkey or _cache_key(req)
    key = f"{key}|{llm.available}"
    if key in _cache:
        _cache.move_to_end(key)
        return {**_cache[key], "cached": True}

    budget = Budget(REQUEST_BUDGET_S)
    trace = Trace()
    audience = {"mode": req["mode"], "lang": req["lang"], "team_short": m.short(req.get("team"))}
    store = FactStore()
    ctx_data, ctx_label = match_context(m, moment["analysis_t"])
    context = store.add("match_context", {"t": moment["analysis_t"]}, ctx_data, ctx_label, moment["analysis_t"])
    w = moment["window"]
    if recap:
        run_tool(m, store, "get_match_summary", {"t": moment["t"]}, moment["t"])
    else:
        run_tool(m, store, "get_events", {"t_from": w[0], "t_to": w[1]}, moment["t"])

    # 1. Analyst: what happened
    picked = analyst(m, llm, budget, moment, store, req.get("zones", []), trace)
    facts = store.pick(picked)
    by_id = {f.id: f for f in store.facts}
    info = moment_brief(m, moment)
    points = fallback.build_points(moment, store)
    template_sentences = fallback.explainer_sentences(points)

    # 2. Explainer: why it matters
    used_model = False
    sentences: list[dict] = []
    if llm.available and budget.allows(20):
        try:
            sentences = explainer(llm, budget, info, facts + [context], None, None)
            used_model = True
            trace.add("Explainer", "ok", f"Wrote {len(sentences)} sentence(s) from {len(facts)} fact(s).", [s["text"] for s in sentences])
        except LLMError as e:
            trace.add("Explainer", "error", f"Model failed ({e}); using templates.")
    if not used_model:
        sentences = template_sentences
        trace.add("Explainer", "fallback", f"Template text from {len(points)} fact-backed point(s).", [s["text"] for s in sentences])

    # 3. Verifier: is it true (code checks, then model logic check, one revision)
    issues = check_sentences(m, sentences, by_id, context)
    if used_model and llm.available and budget.allows(15):
        try:
            issues += logic_check(llm, budget, facts + [context], sentences)
        except LLMError as e:
            trace.add("Verifier", "error", f"Logic check failed ({e}); code checks only.")
    details = [f"#{i['sentence'] + 1} ({i['by']}): {i['problem']}" for i in issues]
    if not issues:
        auto = [f"#{j + 1} cited automatically: {', '.join(s['facts']) or 'no numbers or names'}" for j, s in enumerate(sentences) if s.get("auto_cited")]
        trace.add("Verifier", "ok", f"All {len(sentences)} sentence(s) passed number, name and logic checks.", auto)
    elif used_model and budget.allows(15):
        trace.add("Verifier", "revise", f"{len(issues)} issue(s) found; sent back to the Explainer once.", details)
        draft = sentences
        try:
            sentences = explainer(llm, budget, info, facts + [context], issues, draft)
            issues = check_sentences(m, sentences, by_id, context)
            if budget.allows(12):
                issues += logic_check(llm, budget, facts + [context], sentences)
        except LLMError as e:
            trace.add("Explainer", "error", f"Revision failed ({e}).")
            sentences = draft
        bad = {i["sentence"] for i in issues}
        kept = [s for j, s in enumerate(sentences) if j not in bad]
        if bad:
            trace.add("Verifier", "dropped", f"Revision still had {len(bad)} unsupported sentence(s); dropped them.",
                      [f"#{i['sentence'] + 1} ({i['by']}): {i['problem']}" for i in issues])
        else:
            trace.add("Verifier", "ok", f"Revised text passed all checks ({len(kept)} sentence(s)).")
        sentences = kept
    else:
        bad = {i["sentence"] for i in issues}
        sentences = [s for j, s in enumerate(sentences) if j not in bad]
        trace.add("Verifier", "dropped", f"Dropped {len(bad)} sentence(s) that failed checks.", details)
    if not sentences:
        sentences = template_sentences
        used_model = False
        trace.add("Verifier", "fallback", "Nothing survived verification; using template text.")

    # 4. Personalizer: for whom
    fav = None
    fav_id = req.get("player")
    if fav_id in m.players:
        fav_name = m.name(fav_id)
        involved = any(fav_name in Evidence([f]).blob for f in facts)
        if involved:
            fav = next((f for f in store.facts if f.tool == "get_player_stats" and f.args.get("player_id") == fav_id), None)
            if fav is None:
                fav = run_tool(m, store, "get_player_stats", {"player_id": fav_id, "t": moment["analysis_t"]}, moment["analysis_t"])
    cited_facts = [by_id[fid] for s in sentences for fid in s["facts"] if fid in by_id]
    allowed = Evidence(facts + cited_facts + [context] + ([fav] if fav else []))
    final = None
    if llm.available and budget.allows(8):
        problems = None
        for attempt in range(2):
            try:
                out = personalizer(llm, budget, sentences, audience, fav, problems)
            except LLMError as e:
                trace.add("Personalizer", "error", f"Model failed ({e}).")
                break
            problems = check_text(m, out["text"], allowed)
            if not problems:
                final = out
                trace.add("Personalizer", "ok", f"{audience['mode'].title()} style, {LANGS[audience['lang']]}"
                          + (f", {audience['team_short']} perspective" if audience["team_short"] else "")
                          + (", favourite player sentence" if fav else "") + ("" if attempt == 0 else " (after one fix)") + ".")
                break
            trace.add("Personalizer", "revise", "Rewrite added unsupported details; asked for a fix.", problems)
            if not budget.allows(8):
                break
    if final is None:
        if not used_model:
            final = {"title": fallback.title(moment, audience["lang"]), "text": fallback.personalize(points, moment, audience, fav)}
            trace.add("Personalizer", "fallback", f"Template text in {LANGS[audience['lang']]}, {audience['mode']} style.")
        else:
            final = {"title": fallback.title(moment, "en"), "text": " ".join(s["text"] for s in sentences)}
            trace.add("Personalizer", "fallback", "Kept the verified English text.")

    cited = []
    for s in sentences:
        for fid in s["facts"]:
            if fid in by_id and fid not in cited and fid != context.id:
                cited.append(fid)
    evidence_ids = cited or [f.id for f in facts]
    result = {
        "status": "ok",
        "engine": "foundry" if llm.available and llm.calls else "fallback",
        "model": llm.deployment if llm.available else None,
        "moment": {"type": moment["type"], "event_id": moment["event_id"], "t": moment["t"], "clock": moment["clock"]},
        "title": final["title"] or fallback.title(moment, audience["lang"]),
        "text": final["text"],
        "evidence": [{"id": f.id, "label": f.label, "tool": f.tool, "t": f.t} for f in store.pick(evidence_ids)],
        "trace": trace.steps,
        "usage": {"model_calls": llm.calls, "tokens": llm.tokens},
        "cached": False,
        "precomputed": False,
    }
    # Do not keep answers damaged by a transient model error (e.g. a rate limit): the next
    # viewer should get a fresh attempt, not the degraded copy.
    if not (llm.available and any(s["status"] == "error" for s in trace.steps)):
        _cache[key] = result
        if len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return result

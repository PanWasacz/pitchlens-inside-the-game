"""Template explanations used when the model is not configured or fails.

Every value comes from the facts, so the text passes the same code checks as
model output. Points are rendered in English for the Explainer step and in the
viewer's language and style for the Personalizer step."""

from __future__ import annotations

from .tools import Fact, FactStore

T = {
    "en": {
        "goal": "{scorer} scored for {team} at {clock}, making it {score}; the chance was worth {xg_pct}% xG.",
        "assist": "The assist came from {assist}.",
        "def_line": "Just before the shot, {def_team} held their back line {line} m from their own goal, with the block {length} m deep.",
        "save": "{keeper} saved the shot from {shooter} at {clock}, a chance worth {xg_pct}% xG.",
        "shot_off_target": "{shooter} ({team}) shot wide at {clock} from {dist} m, a {xg_pct}% xG chance.",
        "shot_blocked": "{shooter} ({team}) had a shot blocked at {clock} from {dist} m, a {xg_pct}% xG chance.",
        "shooter_stats": "{shooter} has {shots} shots in the match so far, with a top speed of {top} km/h.",
        "offside": "{receiver} ({team}) was {margin} m beyond the offside line when {passer} played the ball at {clock}.",
        "offside_line": "The {def_team} line was set by {second_last}, {line} m from their goal, so the run came too early.",
        "offside_pass": "It was {kind} of {length} m.",
        "possession": "{team} have had {pct}% of the ball since {since}.",
        "open_shape": "The {team} back line is {line} m from their own goal, with the block {length} m deep and {width} m wide.",
        "fav": "{player} has covered {km} km so far, with a top speed of {top} km/h.",
        "fan_goal": "GOAL! {scorer} finds the net for {team}!",
        "fan_save": "What a stop! {keeper} keeps out {shooter}.",
        "fan_shot": "So close! {shooter} lets fly, but it does not go in.",
        "fan_offside": "Flag up! {receiver} went a fraction too early, {margin} m offside.",
        "fan_open": "{team} are on the ball and running the show.",
        "fan_fav": "{player} was right in the thick of it.",
        "good": "A great moment for {fav} fans.",
        "bad": "A tough moment for {fav} fans.",
        "kind_through_lofted": "a lofted through ball",
        "kind_through": "a through ball",
        "kind_pass": "a pass",
        "title_goal": "Goal: {scorer}",
        "title_save": "Save: {keeper}",
        "title_shot": "Shot: {shooter}",
        "title_offside": "Offside: {receiver}",
        "title_open_play": "Open play at {clock}",
    },
    "pl": {
        "goal": "{scorer} ({team}) strzela gola w {clock}, jest {score}; szansa była warta {xg_pct}% xG.",
        "assist": "Asystę zaliczył {assist}.",
        "def_line": "Tuż przed strzałem linia obrony {def_team} stała {line} m od własnej bramki, a blok miał {length} m głębokości.",
        "save": "{keeper} broni strzał, który oddał {shooter}, w {clock}; szansa była warta {xg_pct}% xG.",
        "shot_off_target": "{shooter} ({team}) pudłuje w {clock} z {dist} m; szansa była warta {xg_pct}% xG.",
        "shot_blocked": "Strzał, który oddał {shooter} ({team}) w {clock} z {dist} m, został zablokowany; szansa była warta {xg_pct}% xG.",
        "shooter_stats": "{shooter}: liczba strzałów w meczu {shots}, prędkość maksymalna {top} km/h.",
        "offside": "{receiver} ({team}) był {margin} m za linią spalonego, gdy {passer} zagrywał piłkę w {clock}.",
        "offside_line": "Linię {def_team} wyznaczał {second_last}, {line} m od bramki, więc wybieg był za wczesny.",
        "offside_pass": "Było to {kind} na {length} m.",
        "possession": "{team} ma {pct}% posiadania piłki od {since}.",
        "open_shape": "Linia obrony {team} jest {line} m od własnej bramki, blok ma {length} m głębokości i {width} m szerokości.",
        "fav": "{player} przebiegł dotąd {km} km, prędkość maksymalna {top} km/h.",
        "fan_goal": "GOOOL! {scorer} trafia dla {team}!",
        "fan_save": "Co za interwencja! {keeper} zatrzymuje strzał, który oddał {shooter}.",
        "fan_shot": "Blisko! {shooter} uderza, ale bez gola.",
        "fan_offside": "Chorągiewka w górze! {receiver} wystartował odrobinę za wcześnie, {margin} m spalonego.",
        "fan_open": "{team} przy piłce i dyktuje warunki.",
        "fan_fav": "{player} był w samym środku akcji.",
        "good": "Świetna chwila dla kibiców {fav}.",
        "bad": "Trudna chwila dla kibiców {fav}.",
        "kind_through_lofted": "prostopadłe podanie górą",
        "kind_through": "prostopadłe podanie",
        "kind_pass": "podanie",
        "title_goal": "Gol: {scorer}",
        "title_save": "Obrona: {keeper}",
        "title_shot": "Strzał: {shooter}",
        "title_offside": "Spalony: {receiver}",
        "title_open_play": "Gra w {clock}",
    },
    "es": {
        "goal": "{scorer} marca para {team} en el {clock}, {score}; la ocasión valía un {xg_pct}% de xG.",
        "assist": "La asistencia fue de {assist}.",
        "def_line": "Justo antes del disparo, {def_team} tenía su línea defensiva a {line} m de su portería y un bloque de {length} m de profundidad.",
        "save": "{keeper} detiene el disparo de {shooter} en el {clock}, una ocasión de un {xg_pct}% de xG.",
        "shot_off_target": "{shooter} ({team}) dispara fuera en el {clock} desde {dist} m, una ocasión de un {xg_pct}% de xG.",
        "shot_blocked": "Bloquean el disparo de {shooter} ({team}) en el {clock} desde {dist} m, una ocasión de un {xg_pct}% de xG.",
        "shooter_stats": "{shooter} suma {shots} disparos en el partido y una velocidad máxima de {top} km/h.",
        "offside": "{receiver} ({team}) estaba {margin} m por delante de la línea cuando {passer} jugó el balón en el {clock}.",
        "offside_line": "La línea de {def_team} la marcaba {second_last}, a {line} m de su portería, así que el desmarque llegó antes de tiempo.",
        "offside_pass": "Fue {kind} de {length} m.",
        "possession": "{team} ha tenido el {pct}% de la posesión desde el {since}.",
        "open_shape": "La línea defensiva de {team} está a {line} m de su portería, con un bloque de {length} m de profundidad y {width} m de anchura.",
        "fav": "{player} ha recorrido {km} km, con una velocidad máxima de {top} km/h.",
        "fan_goal": "¡GOOOL! ¡{scorer} marca para {team}!",
        "fan_save": "¡Paradón! {keeper} le niega el gol a {shooter}.",
        "fan_shot": "¡Uy! {shooter} lo intenta, pero no entra.",
        "fan_offside": "¡Bandera arriba! {receiver} salió un pelín antes, {margin} m en fuera de juego.",
        "fan_open": "{team} tiene el balón y manda en el partido.",
        "fan_fav": "{player} estuvo metido de lleno en la jugada.",
        "good": "Gran momento para la afición de {fav}.",
        "bad": "Momento duro para la afición de {fav}.",
        "kind_through_lofted": "un pase al espacio por alto",
        "kind_through": "un pase al espacio",
        "kind_pass": "un pase",
        "title_goal": "Gol: {scorer}",
        "title_save": "Parada: {keeper}",
        "title_shot": "Disparo: {shooter}",
        "title_offside": "Fuera de juego: {receiver}",
        "title_open_play": "Juego en el {clock}",
    },
}


def _num(v, lang: str) -> str:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return str(v)
    s = f"{v:g}" if isinstance(v, float) else str(v)
    return s.replace(".", ",") if lang in ("pl", "es") else s


def _find(store: FactStore, tool: str, **match) -> Fact | None:
    for f in store.facts:
        if f.tool == tool and all(f.args.get(k) == v for k, v in match.items()):
            return f
    return None


def _event(store: FactStore, event_id: int) -> tuple[dict | None, Fact | None]:
    for f in store.facts:
        if f.tool == "get_events":
            for row in f.data["events"]:
                if row["event_id"] == event_id:
                    return row, f
    return None, None


def build_points(moment: dict, store: FactStore) -> list[dict]:
    """Structured sentences (template key, values, cited fact ids)."""
    pts: list[dict] = []
    kind = moment["type"]

    def add(key: str, facts: list[Fact | None], **p):
        ids = [f.id for f in facts if f is not None]
        if ids:
            pts.append({"key": key, "p": p, "facts": ids})

    if kind in ("goal", "save", "shot"):
        row, ev = _event(store, moment["event_id"])
        if row is None:
            return pts
        shooter = row.get("player")
        if kind == "goal":
            goal, gf = _event(store, moment["goal_event_id"])
            add("goal", [ev, gf], scorer=shooter, team=row["team"], clock=row["clock"], score=goal["score"] if goal else "", xg_pct=row["xg_pct"])
            if row.get("assist"):
                add("assist", [ev], assist=row["assist"])
        elif kind == "save":
            save, sf = _event(store, moment["save_event_id"])
            add("save", [ev, sf], keeper=save["player"] if save else "", shooter=shooter, clock=row["clock"], xg_pct=row["xg_pct"])
        else:
            key = "shot_blocked" if row.get("outcome") == "blocked" else "shot_off_target"
            add(key, [ev], shooter=shooter, team=row["team"], clock=row["clock"], dist=row["distance_to_goal_m"], xg_pct=row["xg_pct"])
        shape = _find(store, "get_team_shape", team=moment["defending"])
        if shape:
            d = shape.data
            add("def_line", [shape], def_team=d["team"], line=d["defensive_line_m_from_own_goal"], length=d["block_length_m"])
        stats = _find(store, "get_player_stats", player_id=moment["player_id"])
        if stats and kind != "goal":
            add("shooter_stats", [stats], shooter=stats.data["player"], shots=stats.data["shots"], top=stats.data["top_speed_kmh"])
    elif kind == "offside":
        state = _find(store, "get_offside_state")
        row, ev = _event(store, moment["pass_event_id"])
        if state and row:
            me = next((a for a in state.data["deepest_attackers"] if a["player"] == row.get("receiver")), None)
            if me:
                add("offside", [state, ev], receiver=me["player"], team=state.data["attacking"], margin=me["metres_beyond_line"], passer=row["player"], clock=row["clock"])
            add("offside_line", [state], def_team=state.data["defending"], second_last=state.data["second_last_defender"], line=state.data["line_m_from_defending_goal"])
            kind_key = "kind_through_lofted" if row.get("through_ball") and row.get("lofted") else "kind_through" if row.get("through_ball") else "kind_pass"
            add("offside_pass", [ev], kind=kind_key, length=row["length_m"])
    else:
        poss = _find(store, "get_possession")
        if poss:
            team, pct = max(((k[:-4], v) for k, v in poss.data.items() if k.endswith("_pct")), key=lambda kv: kv[1])
            add("possession", [poss], team=team, pct=pct, since=poss.data["from"])
        for f in store.facts:
            if f.tool == "get_team_shape":
                d = f.data
                add("open_shape", [f], team=d["team"], line=d["defensive_line_m_from_own_goal"], length=d["block_length_m"], width=d["block_width_m"])
    return pts


def render_point(pt: dict, lang: str) -> str:
    t = T[lang]
    p = {k: (t[v] if k == "kind" else _num(v, lang)) for k, v in pt["p"].items()}
    return t[pt["key"]].format(**p)


def explainer_sentences(points: list[dict]) -> list[dict]:
    return [{"text": render_point(pt, "en"), "facts": pt["facts"]} for pt in points]


def title(moment: dict, lang: str) -> str:
    return T[lang]["title_" + moment["type"]].format(**moment["names"], clock=moment["clock"])


def personalize(points: list[dict], moment: dict, audience: dict, fav_stats: Fact | None) -> str:
    lang = audience["lang"]
    t = T[lang]
    names = moment["names"]
    if audience["mode"] == "fan" and points:
        first = points[0]
        fan_key = {"goal": "fan_goal", "save": "fan_save", "shot": "fan_shot", "offside": "fan_offside"}.get(moment["type"], "fan_open")
        values = {**names, **{k: _num(v, lang) for k, v in first["p"].items() if k != "kind"}}
        values.setdefault("team", moment.get("team_short") or "")
        parts = [t[fan_key].format(**values)]
    else:
        parts = [render_point(pt, lang) for pt in points]
    fav_team = audience.get("team_short")
    if fav_team:
        parts.append(t["good" if moment.get("benefits") == fav_team else "bad"].format(fav=fav_team))
    if fav_stats is not None:
        d = fav_stats.data
        if audience["mode"] == "fan":
            parts.append(t["fan_fav"].format(player=d["player"]))
        elif not any(pt["key"] == "shooter_stats" and pt["p"].get("shooter") == d["player"] for pt in points):
            parts.append(t["fav"].format(player=d["player"], km=_num(d["distance_km"], lang), top=_num(d["top_speed_kmh"], lang)))
    return " ".join(parts)

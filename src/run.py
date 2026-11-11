#!/usr/bin/env python3
"""Aktualisiert Daten, Prognose, Log und Ansicht. Aufruf: python3 src/run.py [--offline] [--all]"""
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artemis
import fetch
import model
import sources

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "log"
DIST = ROOT / "dist"


def append(path, row):
    with path.open("a") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_log(path):
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def record_observation(rows, seen):
    """Hält neue Zieldaten fest, damit der NET-Verlauf nicht verloren geht."""
    path = LOG / "observations.jsonl"
    latest = {}
    for r in read_log(path):
        latest[(r["flight"], r["source"])] = r["net"]
    for r in rows:
        key = (r["flight"], r["source"])
        if r.get("flight") and r.get("net") and latest.get(key) != r["net"]:
            append(path, {"flight": r["flight"], "seen": seen, "net": r["net"], "precision": r["precision"], "source": r["source"]})


def record_status(status, seen):
    """Notiert, wann ein Punkt der Checkliste umspringt; daraus entstehen künftig echte Daten."""
    path = LOG / "status_changes.jsonl"
    state = {}
    for row in read_log(path):
        state[(row["flight"], row["item"])] = row["confirmed"]
    for item in status["items"]:
        key = (status["flight"], item["title"])
        if state.get(key) != item["confirmed"]:
            append(path, {"flight": status["flight"], "item": item["title"], "confirmed": item["confirmed"], "seen": seen, "first_run": key not in state and not state})


def record_closures(tfr, starbase, seen):
    """Hält jede neue TFR und jedes neue Sperrfenster fest; die Quellen zeigen nur aktuelle Einträge."""
    path = LOG / "closures.jsonl"
    known = {r["key"] for r in read_log(path)}
    rows = [{"key": f"tfr:{t['id']}:{t['start']}:{t['end']}", "source": "FAA TFR", "kind": t["kind"], "id": t["id"], "rule": t["rule"],
             "start": t["start"], "end": t["end"]} for t in tfr or []]
    for kind in ("beach", "road"):
        rows += [{"key": f"{kind}:{w['start']}:{w['end']}", "source": "Starbase", "kind": kind, "label": w["label"],
                  "start": w["start"], "end": w["end"]} for w in (starbase or {}).get(kind, [])]
    for r in rows:
        if r["key"] not in known:
            append(path, {**r, "seen": seen})


def record_change(name, value, seen):
    """Schreibt einen Stand nur, wenn er sich gegenüber dem letzten Eintrag geändert hat."""
    path = LOG / f"{name}.jsonl"
    rows = read_log(path)
    if value is not None and (not rows or rows[-1]["value"] != value):
        append(path, {"seen": seen, "value": value})


def due(name, hours, now):
    """Teure Quellen nur alle paar Stunden abrufen, auch wenn der Lauf stündlich kommt."""
    path = fetch.CACHE / "fetched.json"
    stamps = json.loads(path.read_text()) if path.exists() else {}
    last = stamps.get(name)
    if last and now - datetime.fromisoformat(last) < timedelta(hours=hours) - timedelta(minutes=10):
        return False, last
    return True, last


def mark_fetched(name, now):
    path = fetch.CACHE / "fetched.json"
    stamps = json.loads(path.read_text()) if path.exists() else {}
    stamps[name] = now.isoformat(timespec="minutes")
    path.write_text(json.dumps(stamps, indent=0, sort_keys=True))


def update_sources(next_n, today, force_all):
    status = []
    now = datetime.now(timezone.utc)
    every = {"vehicles": 3, "wiki": 2, "wiki_vehicles": 6, "faa": 6, "artemis": 12}

    def attempt(name, label, url, fn):
        hours = every.get(name)
        if hours and not force_all:
            ok, last = due(name, hours, now)
            if not ok:
                status.append({"id": name, "label": label, "url": url, "ok": True, "detail": f"nicht fällig (alle {hours} Std.), zuletzt {last[:16].replace('T', ' ')} UTC"})
                return
        try:
            detail = fn()
            status.append({"id": name, "label": label, "url": url, "ok": True, "detail": detail})
            if hours:
                mark_fetched(name, now)
        except Exception as err:  # Eine ausgefallene Quelle darf den Lauf nicht beenden
            status.append({"id": name, "label": label, "url": url, "ok": False, "detail": f"{type(err).__name__}: {err}"[:200]})

    def vehicles():
        r = fetch.fetch_vehicles(force_all)
        return f"{r['vehicles']} Fahrzeuge, {r['updated']} geändert"

    def ll2():
        rows = fetch.fetch_ll2()
        day = [{"flight": r["flight"], "net": r["net"], "precision": "day" if r["precision"] in ("SEC", "MIN", "HR", "DAY", "S", "D") else r["precision"] or "unknown", "source": "Launch Library"} for r in rows if r["flight"]]
        record_observation(day, str(today))
        return f"{len(rows)} geplante Starts"

    def wiki():
        rows = fetch.fetch_wiki_net(range(next_n, next_n + 3))
        record_observation([{**r, "source": "Wikipedia"} for r in rows], str(today))
        return f"{len(rows)} Zieldaten"

    def checklist():
        status_now, detail = sources.fetch_status()
        record_status(status_now, str(today))
        return detail

    attempt("vehicles", "NextSpaceflight (Testereignisse)", "https://nextspaceflight.com/starship/", vehicles)
    attempt("ll2", "Launch Library 2 (Startliste)", "https://thespacedevs.com/llapi", ll2)
    attempt("wiki", "Wikipedia (Zieldaten)", "https://en.wikipedia.org/wiki/List_of_Starship_launches", wiki)
    attempt("status", "NextSpaceflight (Checkliste)", "https://nextspaceflight.com/starship/", checklist)
    attempt("wiki_vehicles", "Wikipedia (Fahrzeuglisten)", "https://en.wikipedia.org/wiki/List_of_Starship_vehicles", sources.fetch_wiki_vehicles)
    attempt("faa", "FAA (Mitteilungen)", "https://www.faa.gov/newsroom/statements/general-statements", sources.fetch_faa)
    attempt("feed", "NASASpaceflight (Überschriften)", "https://www.nasaspaceflight.com/", sources.fetch_feed)
    attempt("artemis", "Launch Library 2 (Artemis)", "https://thespacedevs.com/llapi", sources.fetch_artemis)
    got = {}

    def tfr():
        got["tfr"], detail = sources.fetch_tfr()
        return detail

    def starbase():
        got["starbase"], detail = sources.fetch_starbase()
        return detail

    def spacex():
        got["spacex"], detail = sources.fetch_spacex()
        return detail

    def ops():
        got["ops"], detail = sources.fetch_ops_plan()
        return detail

    attempt("tfr", "FAA (Luftraumsperrungen, TFR)", "https://tfr.faa.gov/", tfr)
    attempt("starbase", "Stadt Starbase (Strand und Highway 4)", sources.STARBASE_URL, starbase)
    attempt("spacex", "SpaceX (Termin auf spacex.com)", "https://www.spacex.com/launches/", spacex)
    attempt("ops_plan", "FAA (Betriebsplan, geplante Starts)", sources.OPS_PLAN, ops)
    seen = now.isoformat(timespec="minutes")
    record_closures(got.get("tfr"), got.get("starbase"), seen)
    record_change("spacex_targets", [{k: r[k] for k in ("flight", "date", "window_open", "window_close", "text")} for r in got["spacex"]] if "spacex" in got else None, seen)
    record_change("ops_plan", got["ops"]["items"] if "ops" in got else None, seen)
    return status


def vehicle_status(data, vehicle, n):
    prev = data.previous_flight_of(vehicle, n)
    events = data.events(vehicle)
    if prev:
        events = [e for e in events if model.d(e["date"]) > model.d(prev["date"])]
    cryo = [e for e in events if model.classify(e["name"]) == "cryo"]
    sf = [e for e in events if model.classify(e["name"]) == "sf" and e["status"] == 6]
    return {"name": vehicle, "reused": bool(prev), "cryo": cryo[0]["date"][:10] if cryo else None, "sf": sf[-1]["date"][:10] if sf else None,
            "last": ({"name": events[-1]["name"], "date": events[-1]["date"][:10]} if events else None)}


def stack_status(data, booster, ship):
    events = data.stacks.get((booster, ship), [])
    return {"wdr": next((e["date"][:10] for e in events if model.classify(e["name"]) == "wdr"), None),
            "attempts": [e["date"][:10] for e in events if model.classify(e["name"]) == "attempt"]}


def production_matrix(data):
    prod = model.load("production")
    def recent(prefix, floor, count):
        nums = sorted(int(v[1:]) for v in set(data.vehicles) | set(data.steps["steps"]) | {r["vehicle"] for r in prod["rows"]} if v[0] == prefix and int(v[1:]) >= floor)
        return [f"{prefix}{x}" for x in nums[-count:]]
    names = recent("S", 37, 10) + recent("B", 16, 8)
    steps = ["stack_start", "stack_done", "flaps", "engines", "heat_shield", "rollout_test", "rollout_pad", "cryo", "sf", "wdr", "flight"]
    labels = {**prod["steps"], "cryo": "Cryo-Test", "sf": "Static Fire", "wdr": "WDR", "flight": "Start"}
    rows = []
    for name in names:
        cells = {}
        for r in prod["rows"]:
            if r["vehicle"] == name and r["step"] in steps:
                cells[r["step"]] = {"date": r["date"], "kind": "manuell", "confidence": r["confidence"], "note": r["note"], "precision": r["precision"], "source": r["source"]}
        for step, value in data.steps["steps"].get(name, {}).items():
            current = cells.get(step)
            if step in steps and (not current or (value["precision"] == "day" and current["precision"] != "day")):
                cells[step] = {"date": value["date"], "kind": "auto", "confidence": "hoch" if value["precision"] == "day" else "mittel", "precision": value["precision"], "source": value["source"], "note": "Aus der Wikipedia-Fahrzeugliste"}
        cryo = data.cryo_first(name)
        if cryo:
            cells["cryo"] = {"date": str(cryo), "kind": "auto", "confidence": "hoch"}
        flights = [f for f in data.flights if name in (f["ship"], f["booster"])]
        sf = data.final_sf(name, flights[0]["n"] if flights else None)
        if sf:
            cells["sf"] = {"date": str(sf), "kind": "auto", "confidence": "hoch"}
        if flights:
            f = flights[0]
            cells["flight"] = {"date": f["date"], "kind": "auto", "confidence": "hoch", "note": f"Flug {f['n']}"}
            wdr = stack_status(data, f["booster"], f["ship"])["wdr"]
            if wdr:
                cells["wdr"] = {"date": wdr, "kind": "auto", "confidence": "hoch"}
        rows.append({"vehicle": name, "cells": cells})
    filled = sum(1 for r in rows for s in steps[:7] if s in r["cells"])
    return {"steps": steps, "labels": labels, "rows": rows, "manual_filled": filled, "manual_total": len(rows) * 7}


def track_for(data, n, log, start, end):
    """Verlauf eines Flugs: bis zum ersten Log-Eintrag zurückgerechnet, danach die veröffentlichten Stände."""
    by_day = {}
    for entry in log:
        hit = next((x for x in entry["flights"] if x["n"] == n), None)
        if hit and model.d(entry["as_of"]) <= end:
            by_day[entry["as_of"]] = hit  # Mehrere Stände am selben Tag: der letzte war der sichtbare
    issued = [{"as_of": day, "p10": x["p10"], "p50": x["p50"], "p90": x["p90"], "mode": x["mode"], "issued": True,
               "net": (model.net_as_of(data, n, model.d(day)) or {}).get("net")} for day, x in sorted(by_day.items())]
    until = min(end, model.d(issued[0]["as_of"]) - timedelta(days=1)) if issued else end
    return [{**p, "issued": False} for p in model.history_track(data, n, start, until)] + issued


def build_page(payload):
    template = (ROOT / "src" / "template.html").read_text()
    blob = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    DIST.mkdir(exist_ok=True)
    (DIST / "index.html").write_text(template.replace("/*__DATA__*/null", blob))
    (DIST / "data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=0))


def main():
    offline = "--offline" in sys.argv
    today = datetime.now(timezone.utc).date()
    LOG.mkdir(parents=True, exist_ok=True)
    probe = model.Data()
    status = []
    if not offline:
        status = update_sources(probe.flights[-1]["n"] + 1, today, "--all" in sys.argv)
    data = model.Data()
    cfg = data.cfg
    fingerprint = hashlib.sha256((json.dumps(data.vehicles, sort_keys=True) + json.dumps(data.net, sort_keys=True) + json.dumps(data.flights, sort_keys=True) + json.dumps(cfg, sort_keys=True) + json.dumps(data.status, sort_keys=True) + json.dumps(data.faa, sort_keys=True) + (ROOT / "data" / "manual" / "artemis.json").read_text()).encode()).hexdigest()[:16]
    seed = int(fingerprint[:8], 16)

    near, runs, _ = model.forecast_near(data, today, seed=seed)
    years = model.forecast_years(data, today, runs, seed=seed + 1)
    flight_days = years.pop("flight_days")
    moon = artemis.forecast(today, flight_days, seed=seed + 2)
    few_tankers = artemis.forecast(today, flight_days, seed=seed + 2, tankers=(6, 8))
    moon["few_tankers"] = {x["id"]: {"p50": x.get("p50"), "p_target": x.get("p_target")} for x in few_tankers["rows"]}
    bt = model.backtest(data)

    logpath = LOG / "forecasts.jsonl"
    log = read_log(logpath)
    days_since = (today - date.fromisoformat(log[-1]["as_of"])).days if log else 999
    flights_now = [{k: x[k] for k in ("n", "mode", "p10", "p25", "p50", "p75", "p90")} for x in near]
    # Auch ohne neue Daten kann sich die Prognose ändern, weil der Vorlauf bis zum NET schrumpft
    if not log or log[-1]["fingerprint"] != fingerprint or log[-1]["flights"] != flights_now or days_since >= 7:
        entry = {"as_of": str(today), "model_version": cfg["model_version"], "fingerprint": fingerprint,
                 "flights": flights_now,
                 "years": {y: years["cases"]["mit"][y]["p50"] for y in years["cases"]["mit"]},
                 "years_no_incident": {y: years["cases"]["ohne"][y]["p50"] for y in years["cases"]["ohne"]},
                 "artemis": {x["id"]: {"p50": x["p50"], "p_target": x["p_target"], "target": x["target"]} for x in moon["rows"] if x.get("p50")}}
        append(logpath, entry)
        log.append(entry)

    tracks = {}
    for f in data.flights[-3:]:
        launch = model.d(f["date"])
        prev = model.d(data.flight(f["n"] - 1)["date"])
        tracks[str(f["n"])] = {"actual": f["date"], "track": track_for(data, f["n"], log, max(prev + timedelta(days=1), launch - timedelta(days=84)), launch - timedelta(days=1))}
    last_flight = model.d(data.flights[-1]["date"])
    nxt = data.flights[-1]["n"] + 1
    open_track = track_for(data, nxt, log, last_flight + timedelta(days=1), today)
    if near[0]["n"] == nxt and open_track and open_track[-1]["as_of"] != str(today):
        # Unveränderte Prognose steht nicht erneut im Log; die Linie soll trotzdem bis heute reichen
        open_track.append({**open_track[-1], "as_of": str(today)})
    tracks[str(nxt)] = {"actual": None, "track": open_track}

    if status:
        append(LOG / "runs.jsonl", {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sources": [{"id": s["id"], "label": s["label"], "url": s["url"], "ok": s["ok"], "detail": s["detail"]} for s in status]})

    scored = []
    for entry in log:
        for x in entry["flights"]:
            f = data.flight(x["n"])
            if f:
                actual = model.d(f["date"])
                scored.append({"as_of": entry["as_of"], "n": x["n"], "model_version": entry["model_version"], "lead": (actual - model.d(entry["as_of"])).days,
                               "error": (model.d(x["p50"]) - actual).days, "mode_error": (model.d(x["mode"]) - actual).days,
                               "in50": x["p25"] <= f["date"] <= x["p75"], "in80": x["p10"] <= f["date"] <= x["p90"]})

    runs_log = read_log(LOG / "runs.jsonl")
    if not status and runs_log:
        status = runs_log[-1]["sources"]

    b, s, pad = data.assignment(nxt)
    matrix = production_matrix(data)
    feed = data._cache("feed", {"articles": []})["articles"][-8:]
    changes = read_log(LOG / "status_changes.jsonl")
    ops_now = data._cache("ops_plan", {"items": []})
    tfr_now = sources.refine_tfr(data._cache("tfr", {"items": []})["items"], ops_now)
    starbase_now = data._cache("starbase", {})
    closures = sources.classify_closures(starbase_now, tfr_now, datetime.now(timezone.utc))
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "as_of": str(today), "offline": offline, "model_version": cfg["model_version"],
        "status": status, "flights": data.flights, "gaps": model.gaps(data), "durations": model.durations(data), "near": near, "years": years,
        "net_current": {str(x["n"]): model.net_as_of(data, x["n"], today) for x in near},
        "next": {"n": nxt, "pad": pad, "booster": vehicle_status(data, b, nxt), "ship": vehicle_status(data, s, nxt), "stack": stack_status(data, b, s)},
        "following": [{"n": x["n"], "booster": vehicle_status(data, x["booster"], x["n"]), "ship": vehicle_status(data, x["ship"], x["n"])} for x in near[1:3]],
        "license": model.load("license"), "matrix": matrix, "trends": model.trends(data, matrix["rows"]), "artemis": moon,
        "checklist": data.status, "status_changes": [c for c in changes if not c.get("first_run")][-20:],
        "closures": closures, "tfr": [t for t in tfr_now if t["kind"] != "other"], "starbase_order": starbase_now.get("order"),
        "starbase_previous": starbase_now.get("previous_orders", [])[:12],
        "spacex": data._cache("spacex", []), "ops_plan": ops_now, "faa": data.faa[-8:], "open_mishap": data.open_mishap(), "news": feed[::-1], "license_cleared": data.license_cleared(nxt), "milestones": model.milestone_stats(), "falcon": model.load("falcon_years"),
        "backtest_summary": model.backtest_summary(bt), "tracks": tracks, "log": log[-60:], "log_count": len(log), "scored": scored,
        "assumptions": cfg, "upcoming": data.meta["upcoming"],
    }
    build_page(payload)
    for x in near:
        print(f"Flug {x['n']}: wahrscheinlichster Tag {x['mode']}, Mitte {x['p50']}, 80 % {x['p10']} bis {x['p90']}")
    for sx in status:
        print(("OK    " if sx["ok"] else "FEHLER"), sx["id"], sx["detail"])


if __name__ == "__main__":
    main()

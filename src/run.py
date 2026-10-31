#!/usr/bin/env python3
"""Aktualisiert Daten, Prognose, Log und Ansicht. Aufruf: python3 src/run.py [--offline] [--all]"""
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch
import model

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


def update_sources(next_n, today, force_all):
    status = []

    def attempt(name, label, url, fn):
        try:
            detail = fn()
            status.append({"id": name, "label": label, "url": url, "ok": True, "detail": detail})
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

    attempt("vehicles", "NextSpaceflight (Testereignisse)", "https://nextspaceflight.com/starship/", vehicles)
    attempt("ll2", "Launch Library 2 (Startliste)", "https://thespacedevs.com/llapi", ll2)
    attempt("wiki", "Wikipedia (Zieldaten)", "https://en.wikipedia.org/wiki/List_of_Starship_launches", wiki)
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
    names = ["S37", "S38", "S39", "S40", "S41", "S42", "S43", "S44", "B16", "B19", "B20", "B21", "B22", "B23"]
    steps = ["stack_done", "flaps", "engines", "heat_shield", "rollout_test", "rollout_pad", "cryo", "sf", "wdr", "flight"]
    labels = {**prod["steps"], "cryo": "Cryo-Test", "sf": "Static Fire", "wdr": "WDR", "flight": "Start"}
    rows = []
    for name in names:
        cells = {}
        for r in prod["rows"]:
            if r["vehicle"] == name and r["step"] in steps:
                cells[r["step"]] = {"date": r["date"], "kind": "manuell", "confidence": r["confidence"], "note": r["note"], "precision": r["precision"], "source": r["source"]}
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
    filled = sum(1 for r in rows for s in steps[:6] if s in r["cells"])
    return {"steps": steps, "labels": labels, "rows": rows, "manual_filled": filled, "manual_total": len(rows) * 6}


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
    fingerprint = hashlib.sha256((json.dumps(data.vehicles, sort_keys=True) + json.dumps(data.net, sort_keys=True) + json.dumps(data.flights, sort_keys=True) + json.dumps(cfg, sort_keys=True)).encode()).hexdigest()[:16]
    seed = int(fingerprint[:8], 16)

    near, runs, _ = model.forecast_near(data, today, seed=seed)
    years = model.forecast_years(data, today, runs, seed=seed + 1)
    bt = model.backtest(data)
    tracks = {}
    for f in data.flights[-3:]:
        launch = model.d(f["date"])
        prev = model.d(data.flight(f["n"] - 1)["date"])
        tracks[str(f["n"])] = {"actual": f["date"], "track": model.history_track(data, f["n"], max(prev + timedelta(days=1), launch - timedelta(days=84)), launch - timedelta(days=1))}
    last_flight = model.d(data.flights[-1]["date"])
    nxt = data.flights[-1]["n"] + 1
    tracks[str(nxt)] = {"actual": None, "track": model.history_track(data, nxt, last_flight + timedelta(days=1), today)}

    logpath = LOG / "forecasts.jsonl"
    log = read_log(logpath)
    days_since = (today - date.fromisoformat(log[-1]["as_of"])).days if log else 999
    if not log or log[-1]["fingerprint"] != fingerprint or days_since >= 7:
        entry = {"as_of": str(today), "model_version": cfg["model_version"], "fingerprint": fingerprint,
                 "flights": [{k: x[k] for k in ("n", "mode", "p10", "p25", "p50", "p75", "p90")} for x in near],
                 "years": {y: years["cases"]["mit"][y]["p50"] for y in years["cases"]["mit"]},
                 "years_no_incident": {y: years["cases"]["ohne"][y]["p50"] for y in years["cases"]["ohne"]}}
        append(logpath, entry)
        log.append(entry)
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
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "as_of": str(today), "offline": offline, "model_version": cfg["model_version"],
        "status": status, "flights": data.flights, "gaps": model.gaps(data), "durations": model.durations(data), "near": near, "years": years,
        "net_current": {str(x["n"]): model.net_as_of(data, x["n"], today) for x in near},
        "next": {"n": nxt, "pad": pad, "booster": vehicle_status(data, b, nxt), "ship": vehicle_status(data, s, nxt), "stack": stack_status(data, b, s)},
        "following": [{"n": x["n"], "booster": vehicle_status(data, x["booster"], x["n"]), "ship": vehicle_status(data, x["ship"], x["n"])} for x in near[1:3]],
        "license": model.load("license"), "matrix": production_matrix(data), "milestones": model.milestone_stats(), "falcon": model.load("falcon_years"),
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

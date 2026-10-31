"""Artemis-Meilensteine: offizielle Ziele gegen eine Abschätzung aus Verzugsfaktoren und Starship-Flugzahlen."""
import json
import math
import random
from bisect import bisect_right
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HORIZON = date(2036, 12, 31).toordinal()


def _d(s):
    return date.fromisoformat(s)


def _target(item, ll2):
    """Offizielles Ziel: die Datei, außer die Startliste nennt inzwischen einen späteren Termin."""
    target = item["target"]
    mission = item.get("ll2_mission")
    hits = [r for r in ll2 if mission and r["mission"] == mission and r["kind"] == "upcoming" and r["net"]]
    if hits and hits[0]["net"] > target:
        target = hits[0]["net"]
    return target


def _done(item, ll2):
    if item.get("done"):
        return item["done"]
    mission = item.get("ll2_mission")
    hits = [r for r in ll2 if mission and r["mission"] == mission and r["kind"] == "previous" and r["status"] == "Success"]
    return hits[0]["net"] if hits else None


def _reference(rng, item, target, as_of):
    """Termin aus dem Verzugsfaktor: angekündigter Vorlauf mal typischer Faktor."""
    announced = _d(item["announced"]).toordinal()
    lead = max(_d(target).toordinal() - announced, 30)
    factor = rng.lognormvariate(math.log(item["factor"]), item.get("sigma", 0.35))
    return max(announced + lead * max(factor, 1.0), as_of.toordinal() + 1)


def verdict(p):
    if p >= 0.5:
        return "realistisch"
    if p >= 0.2:
        return "knapp"
    if p >= 0.05:
        return "unwahrscheinlich"
    return "sehr unwahrscheinlich"


def forecast(as_of, flight_days, seed=11, tankers=None):
    cfg = json.loads((ROOT / "data" / "manual" / "artemis.json").read_text())
    path = ROOT / "data" / "cache" / "artemis_ll2.json"
    ll2 = json.loads(path.read_text()) if path.exists() else []
    items = {x["id"]: x for x in cfg["milestones"]}
    targets = {k: _target(v, ll2) for k, v in items.items() if v.get("target")}
    done = {k: _done(v, ll2) for k, v in items.items()}
    a = cfg["assumptions"]
    rng = random.Random(seed)
    results = {k: [] for k in items}
    low, high = tankers or (a["tankers_min"], a["tankers_max"])
    tankers_log = (math.log(low), math.log(high))

    def after(days, start, count):
        """Datum des count-ten Starship-Flugs nach start."""
        i = bisect_right(days, start) + int(count) - 1
        return days[i] if i < len(days) else HORIZON

    def lag(name):
        median, sigma = a[name]
        return rng.lognormvariate(math.log(median), sigma)

    def reference(key):
        if done.get(key):
            return _d(done[key]).toordinal()
        return _reference(rng, items[key], targets[key], as_of)

    for days in flight_days:
        tankers = math.exp(rng.uniform(*tankers_log))
        pt = reference("propellant")
        if len(days) > 2:
            pt = max(pt, days[2])
        a3 = reference("artemis3")
        landing_demo = max(pt + lag("transfer_to_demo_days"), after(days, pt, tankers + 3))
        spacex_crew = max(landing_demo + lag("demo_to_crew_days"), after(days, landing_demo, tankers + 2))
        blue = reference("blue_lander")
        pathfinder = reference("blue_pathfinder")
        blue = max(blue, pathfinder + lag("pathfinder_to_crew_days"))
        suit = _d(a["suit_sortie"]).toordinal() + rng.gauss(0, a["suit_sigma_days"]) if rng.random() < a["suit_sortie_share"] else _d(a["suit_late"]).toordinal() + rng.gauss(0, a["suit_sigma_days"])
        a4 = max(min(spacex_crew, blue), a3 + lag("a3_to_a4_days"), suit)
        a5 = a4 + lag("a4_to_a5_days")
        values = {"propellant": pt, "artemis3": a3, "landing_demo": landing_demo, "blue_pathfinder": pathfinder, "blue_lander": blue, "artemis4": a4, "artemis5": a5}
        for key, value in values.items():
            results[key].append(min(value, HORIZON))

    rows = []
    for key, item in items.items():
        row = {k: item.get(k) for k in ("id", "label", "official", "note", "source", "drivers", "history")}
        row["done"] = done.get(key)
        row["target"] = targets.get(key)
        samples = sorted(results[key])
        if samples and not row["done"]:
            q = lambda p: samples[min(len(samples) - 1, int(p * len(samples)))]
            to_iso = lambda x: str(date.fromordinal(int(x)))
            row.update({"p10": to_iso(q(.1)), "p50": to_iso(q(.5)), "p90": to_iso(q(.9))})
            limit = _d(row["target"]).toordinal()
            row["p_target"] = round(sum(1 for x in samples if x <= limit) / len(samples), 3)
            row["verdict"] = verdict(row["p_target"])
            row["official_slip_days"] = int(q(.5) - limit)
        rows.append(row)
    return {"rows": rows, "assumptions": a, "as_of": str(as_of), "sources": cfg["sources"]}

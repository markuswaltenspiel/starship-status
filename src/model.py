"""Prognosemodell: nahe Flüge aus Fahrzeugstand und NET, ferne Jahre aus Szenarien."""
import json
import math
import random
import re
import statistics
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / "data" / "manual"
CACHE = ROOT / "data" / "cache"


def d(s):
    return date.fromisoformat(s[:10])


def load(name):
    return json.loads((MANUAL / f"{name}.json").read_text())


def short(name):
    m = re.fullmatch(r"(Booster|Ship) (\d+)", name)
    return f"{m.group(1)[0]}{m.group(2)}" if m else None


def classify(name):
    low = name.lower()
    if "cryogenic" in low:
        return "cryo"
    if "single" in low and "static" in low:
        return "sf_single"
    if "static fire" in low:
        return "sf"
    if "wet dress" in low:
        return "wdr"
    if "launch attempt" in low:
        return "attempt"
    if low.startswith("starship flight"):
        return "flight"
    return "other"


class Data:
    def __init__(self):
        self.cfg = load("assumptions")
        meta = load("flights")
        self.meta = meta
        self.flights = list(meta["flights"])
        self.license = {x["n"]: x for x in load("license")}
        self.vehicles, self.stacks = {}, {}
        raw = json.loads((CACHE / "vehicles.json").read_text())
        for v in raw.values():
            key = short(v["name"])
            if key:
                self.vehicles[key] = v["events"]
            else:
                m = re.fullmatch(r"Booster (\d+)/Ship (\d+)", v["name"])
                if m:
                    self.stacks[(f"B{m.group(1)}", f"S{m.group(2)}")] = v["events"]
        self._merge_new_flights()
        self.all_flights = list(self.flights)
        self.net = self._net_history()

    def _merge_new_flights(self):
        """Neue Flüge erkennt das Programm selbst an den Ereignissen der Stapel."""
        known = {f["n"] for f in self.flights}
        for (b, s), events in self.stacks.items():
            for e in events:
                m = re.fullmatch(r"Starship Flight (\d+)", e["name"])
                if m and int(m.group(1)) not in known and e["status"] in (6, 7, 8):
                    outcome = {6: "success", 7: "partial", 8: "failure"}[e["status"]]
                    upcoming = self.meta["upcoming"].get(m.group(1), {})
                    self.flights.append({"n": int(m.group(1)), "date": e["date"][:10], "booster": b, "ship": s,
                                         "version": "V3", "pad": upcoming.get("pad", e["location"].split(",")[0]), "outcome": outcome, "auto": True})
        self.flights.sort(key=lambda f: f["n"])

    def _net_history(self):
        rows = list(load("net_history"))
        path = CACHE / "wiki_net.json"
        if path.exists():
            for n, series in json.loads(path.read_text()).items():
                for r in series:
                    if r["precision"] == "day":
                        rows.append({"flight": int(n), "seen": r["seen"], "net": r["net"], "precision": "day", "source": "Wikipedia-Historie"})
        obs = ROOT / "data" / "log" / "observations.jsonl"
        if obs.exists():
            for line in obs.read_text().splitlines():
                r = json.loads(line)
                if r.get("precision") == "day" and r.get("flight"):
                    rows.append(r)
        rows.sort(key=lambda r: r["seen"])
        return rows

    def next_flight_number(self):
        return self.flights[-1]["n"] + 1

    def events(self, vehicle, as_of=None):
        out = self.vehicles.get(vehicle, [])
        return [e for e in out if as_of is None or d(e["date"]) <= as_of]

    def flight(self, n):
        return next((f for f in self.flights if f["n"] == n), None)

    def previous_flight_of(self, booster, before):
        hits = [f for f in self.flights if f["booster"] == booster and f["n"] < before]
        return hits[-1] if hits else None

    def assignment(self, n):
        """Zuordnung aus der Datei, sonst das nächste ungeflogene Fahrzeug je Baureihe."""
        f = next((x for x in self.all_flights if x["n"] == n), None)
        if f:
            return f["booster"], f["ship"], f["pad"]
        up = self.meta["upcoming"].get(str(n))
        if up:
            return up["booster"], up["ship"], up["pad"]
        flown = {f["booster"] for f in self.all_flights} | {f["ship"] for f in self.all_flights}
        taken = {x for v in self.meta["upcoming"].values() for x in (v["booster"], v["ship"])}
        lost = set(self.meta.get("lost_vehicles", []))
        offset = n - max([int(k) for k in self.meta["upcoming"]] + [self.all_flights[-1]["n"]]) - 1

        def pick(prefix, floor):
            nums = sorted(int(v[1:]) for v in self.vehicles if v[0] == prefix)
            start = max(nums + [floor])
            used = flown | taken | lost
            free = [f"{prefix}{i}" for i in nums if i >= floor and f"{prefix}{i}" not in used]
            free += [f"{prefix}{start + i + 1}" for i in range(8)]
            return free[max(offset, 0)]

        return pick("B", 19), pick("S", 39), "Pad 2"

    def cryo_first(self, vehicle, as_of=None):
        hits = [e for e in self.events(vehicle, as_of) if classify(e["name"]) == "cryo"]
        return d(hits[0]["date"]) if hits else None

    def final_sf(self, vehicle, flight_n=None, as_of=None):
        """Letztes erfolgreiches Static Fire seit dem letzten Einsatz (status 6 = voll durchgeführt)."""
        hits = [e for e in self.events(vehicle, as_of) if classify(e["name"]) == "sf" and e["status"] == 6]
        if flight_n is not None:
            this = self.flight(flight_n)
            if this:
                hits = [e for e in hits if d(e["date"]) < d(this["date"])]
            prev = self.previous_flight_of(vehicle, flight_n)
            if prev:
                hits = [e for e in hits if d(e["date"]) > d(prev["date"])]
        return d(hits[-1]["date"]) if hits else None


def durations(data):
    """Dauer je Abschnitt für jedes Fahrzeug, das geflogen ist."""
    rows = []
    for f in data.flights:
        launch = d(f["date"])
        ship_sf = data.final_sf(f["ship"], f["n"])
        boost_sf = data.final_sf(f["booster"], f["n"])
        ship_cryo = data.cryo_first(f["ship"])
        boost_cryo = data.cryo_first(f["booster"]) if not data.previous_flight_of(f["booster"], f["n"]) else None
        last_sf = max([x for x in (ship_sf, boost_sf) if x], default=None)
        rows.append({
            "n": f["n"], "version": f["version"], "ship": f["ship"], "booster": f["booster"], "date": f["date"],
            "ship_cryo": str(ship_cryo) if ship_cryo else None, "ship_sf": str(ship_sf) if ship_sf else None,
            "booster_cryo": str(boost_cryo) if boost_cryo else None, "booster_sf": str(boost_sf) if boost_sf else None,
            "ship_cryo_sf": (ship_sf - ship_cryo).days if ship_sf and ship_cryo else None,
            "booster_cryo_sf": (boost_sf - boost_cryo).days if boost_sf and boost_cryo else None,
            "ship_sf_launch": (launch - ship_sf).days if ship_sf else None,
            "booster_sf_launch": (launch - boost_sf).days if boost_sf else None,
            "ship_cryo_launch": (launch - ship_cryo).days if ship_cryo else None,
            "last_sf_launch": (launch - last_sf).days if last_sf else None,
            "limit": "Ship" if ship_sf and boost_sf and ship_sf >= boost_sf else "Booster",
        })
    return rows


def gaps(data):
    out = []
    for a, b in zip(data.flights, data.flights[1:]):
        out.append({"n": b["n"], "gap": (d(b["date"]) - d(a["date"])).days, "version": b["version"], "transition": a["version"] != b["version"],
                    "excluded": data.meta["gap_excluded"].get(str(b["n"]))})
    return out


def recency_weight(cfg, n, before):
    """Jüngere Flüge zählen stärker; das Gewicht halbiert sich alle paar Flüge."""
    return 0.5 ** ((before - n) / cfg["recency_half_life_flights"])


def weighted_pool(rows, field, cfg, before=None, ignore=()):
    pool = []
    ref = before if before is not None else max((r["n"] for r in rows), default=0) + 1
    for r in rows:
        if r[field] is None or (before is not None and r["n"] >= before) or r["n"] in ignore:
            continue
        pool.append((r[field], recency_weight(cfg, r["n"], ref)))
    return pool


def draw(rng, pool, jitter=0.18):
    values, weights = zip(*pool)
    return rng.choices(values, weights)[0] * math.exp(rng.gauss(0, jitter))


# Flüge, deren Abstand Static Fire→Start von Lizenz, Unfall oder Fahrzeugverlust geprägt ist
IGNORE_SF_LAUNCH = (1, 2, 3, 4, 5)


def license_wait(rng, cfg, entry, as_of):
    c = cfg["license"]
    if entry and entry.get("license_date") and d(entry["license_date"]) <= as_of:
        return 0.0
    is_new = bool(entry and entry.get("new_profile"))
    if rng.random() >= (c["p_new_profile"] if is_new else c["p_normal"]):
        return 0.0
    return rng.lognormvariate(math.log(c["median_days_new"] if is_new else c["median_days_normal"]), c["sigma"])


def net_as_of(data, n, as_of):
    rows = [r for r in data.net if r["flight"] == n and d(r["seen"]) <= as_of]
    return rows[-1] if rows else None


def net_slip_pool(data, before, lead):
    """Wie weit lagen frühere Starts hinter dem NET, das bei ähnlichem Vorlauf galt?"""
    def bucket(x):
        return 0 if x <= 10 else 1 if x <= 30 else 2
    pool = []
    for r in data.net:
        f = data.flight(r["flight"])
        if not f or f["n"] >= before:
            continue
        this_lead = (d(r["net"]) - d(r["seen"])).days
        slip = (d(f["date"]) - d(r["net"])).days
        if this_lead >= 0 and slip >= -1 and bucket(this_lead) == bucket(lead):
            pool.append((max(slip, 0), recency_weight(data.cfg, f["n"], before)))
    return pool


def sample_flight(data, n, as_of, rng, table, prev_sample=None, gap_pool=None):
    """Ein simulierter Starttermin als Tage ab as_of (ohne schweren Zwischenfall)."""
    cfg = data.cfg
    booster, ship, pad = data.assignment(n)
    last = [f for f in data.flights if d(f["date"]) <= as_of]
    prior = (d(last[-1]["date"]) - as_of).days if last else -120
    before = n
    sfl = weighted_pool(table, "last_sf_launch", cfg, before, IGNORE_SF_LAUNCH) or weighted_pool(table, "last_sf_launch", cfg, before) or [(30, 1)]
    modern = tuple(range(1, 7))
    ship_c = weighted_pool(table, "ship_cryo_sf", cfg, before, modern) or weighted_pool(table, "ship_cryo_sf", cfg, before) or [(55, 1)]
    boost_c = weighted_pool(table, "booster_cryo_sf", cfg, before, modern) or weighted_pool(table, "booster_cryo_sf", cfg, before) or [(45, 1)]

    def ready(vehicle, pool):
        sf = data.final_sf(vehicle, n, as_of)
        if sf:
            return (sf - as_of).days
        cryo = data.cryo_first(vehicle, as_of)
        prev_use = data.previous_flight_of(vehicle, n)
        if prev_use and not sf:
            return max(1.0, draw(rng, [(45, 1), (60, 1), (30, 1)]) + (d(prev_use["date"]) - as_of).days)
        if cryo and not prev_use:
            return max(1.0, draw(rng, pool) + (cryo - as_of).days)
        # Noch kein Cryo-Test: Stacking-Ende bis Cryo dauerte zuletzt rund zwei bis fünf Wochen
        return draw(rng, pool) + rng.uniform(*cfg["before_cryo_days"])

    base = max(ready(ship, ship_c), ready(booster, boost_c))
    pipeline = base + draw(rng, sfl)
    for _ in range(30):
        if pipeline >= 1:
            break
        pipeline = base + draw(rng, sfl)
    if pipeline < 1:
        pipeline = 1 + rng.expovariate(1 / 5)

    # Solange ein Fahrzeug nicht fertig getestet ist, sagt der Flugabstand ähnlich viel wie die Pipeline
    both_done = data.final_sf(ship, n, as_of) and data.final_sf(booster, n, as_of)
    this_flight = next((f for f in data.all_flights if f["n"] == n), None)
    same_version = not last or (this_flight["version"] if this_flight else "V3") == last[-1]["version"]
    if not both_done and same_version and gap_pool and rng.random() < cfg["cadence_share"]:
        cadence = (prev_sample if prev_sample is not None else prior) + draw(rng, gap_pool, 0.2)
        if cadence >= 1:
            pipeline = cadence

    entry = data.license.get(n)
    pipeline += license_wait(rng, cfg, entry, as_of)

    up = data.meta["upcoming"].get(str(n), {})
    is_new_pad = pad == "LC-39A" and not any(f["pad"] == "LC-39A" for f in last)
    if is_new_pad and rng.random() < up.get("pad_probability", 1):
        pipeline += rng.lognormvariate(math.log(cfg["pad"]["new_pad_median_days"]), cfg["pad"]["new_pad_sigma"])

    floor = prior + cfg["pad"]["same_pad_floor_days"] if not is_new_pad else 1
    pipeline = max(pipeline, floor)

    result = pipeline
    net = net_as_of(data, n, as_of)
    if net:
        lead = (d(net["net"]) - as_of).days
        pool = net_slip_pool(data, n, lead)
        w = cfg["weights"]["net_near"] if lead <= cfg["weights"]["near_lead_days"] else cfg["weights"]["net_far"]
        if pool and rng.random() < w:
            result = max(lead + draw(rng, pool, 0.1) + rng.uniform(-1, 1), floor if floor > 1 else 1)
    if prev_sample is not None:
        result = max(result, prev_sample + 1)
    return max(result, 1.0)


def summarize(samples, as_of):
    s = sorted(samples)
    q = lambda p: s[min(len(s) - 1, int(p * len(s)))]
    hist = {}
    for x in s:
        hist[int(round(x))] = hist.get(int(round(x)), 0) + 1
    # Glättungsbreite wächst mit der Unsicherheit, sonst gewinnt bei breiten Verteilungen ein Zufallsgipfel
    width = max(3, int((q(.75) - q(.25)) / 6))
    kernel = [(k, width + 1 - abs(k)) for k in range(-width, width + 1)]
    norm = sum(w for _, w in kernel)
    best, best_score = int(round(q(0.5))), -1.0
    for day in range(int(s[0]), int(s[-1]) + 1):
        score = sum(hist.get(day + k, 0) * w for k, w in kernel)
        if score > best_score:
            best, best_score = day, score
    on_day = best_score / norm / len(s)
    to_date = lambda x: str(as_of + timedelta(days=round(x)))
    return {"mode": to_date(best), "mode_probability": round(on_day, 3), "p10": to_date(q(.1)), "p25": to_date(q(.25)),
            "p50": to_date(q(.5)), "p75": to_date(q(.75)), "p90": to_date(q(.9))}


def month_probabilities(samples, as_of, count=8):
    out, seen = [], date(as_of.year, as_of.month, 1)
    for _ in range(count):
        nxt = date(seen.year + (seen.month == 12), seen.month % 12 + 1, 1)
        cutoff = (nxt - as_of).days
        out.append({"month": seen.strftime("%Y-%m"), "p": round(sum(1 for x in samples if x < cutoff) / len(samples), 3)})
        seen = nxt
    return out


def forecast_near(data, as_of, count=4, sims=None, seed=1):
    sims = sims or data.cfg["simulations"]
    rng = random.Random(seed)
    table = durations(data)
    first = max([f["n"] for f in data.flights if d(f["date"]) <= as_of], default=0) + 1
    numbers = list(range(first, first + count))
    all_runs = []
    gap_pool = [(g["gap"], recency_weight(data.cfg, g["n"], first)) for g in gaps(data) if not g["excluded"] and not g["transition"] and g["n"] < first]
    for _ in range(sims):
        run, prev = [], None
        for i, n in enumerate(numbers):
            if i < 2 or data.final_sf(data.assignment(n)[1], n, as_of):
                prev = sample_flight(data, n, as_of, rng, table, prev, gap_pool)
            else:
                prev = prev + draw(rng, gap_pool, 0.2)
            run.append(prev)
        all_runs.append(run)
    out = []
    for i, n in enumerate(numbers):
        samples = [r[i] for r in all_runs]
        booster, ship, pad = data.assignment(n)
        out.append({"n": n, "booster": booster, "ship": ship, "pad": pad, **summarize(samples, as_of), "months": month_probabilities(samples, as_of)})
    return out, all_runs, numbers


def production_rate(data, as_of):
    """Getestete Ships pro Jahr, hochgerechnet aus den letzten neun Monaten (erster Cryo-Test)."""
    window = 270
    start = as_of - timedelta(days=window)
    firsts = []
    for name in data.vehicles:
        if re.fullmatch(r"S\d+", name):
            c = data.cryo_first(name, as_of)
            if c and c >= start:
                firsts.append(c)
    return round(len(firsts) * 365 / window, 1)


def target_rate_fn(cfg, multiplier, start):
    announced = date(2026, 10, 20)
    weekly = announced + timedelta(days=multiplier * (date(2027, 3, 31) - announced).days)
    twice = announced + timedelta(days=multiplier * (date(2027, 12, 31) - announced).days)

    def rate(day):
        if day <= start:
            return 6.0
        if day <= weekly:
            t = (day - start).days / max(1, (weekly - start).days)
            return math.exp(math.log(6) + t * (math.log(52) - math.log(6)))
        if day <= twice:
            t = (day - weekly).days / max(1, (twice - weekly).days)
            return math.exp(math.log(52) + t * (math.log(104) - math.log(52)))
        return 104 * 1.15 ** ((day - twice).days / 365)
    return rate


def forecast_years(data, as_of, runs, last_year=2032, seed=2):
    """Flüge je Jahr, je einmal mit und ohne schwere Zwischenfälle."""
    lt = data.cfg["long_term"]
    rng = random.Random(seed)
    current = 365 / statistics.median([g["gap"] for g in gaps(data) if g["version"] == "V3" and not g["transition"]] or [65])
    produced = max(production_rate(data, as_of), 3)
    years = list(range(as_of.year, last_year + 1))
    names = list(lt["scenario_weights"])
    by_case = {"mit": {y: [] for y in years}, "ohne": {y: [] for y in years}}
    by_scenario = {s: {y: [] for y in years} for s in names}
    flown_before = {f["n"] for f in data.flights if d(f["date"]) <= as_of}
    done_year = {y: sum(1 for f in data.flights if d(f["date"]).year == y and d(f["date"]) <= as_of) for y in years}
    horizon = date(last_year, 12, 31)
    for run in runs:
        scenario = rng.choices(names, [lt["scenario_weights"][s] for s in names])[0]
        if scenario == "falcon":
            g = lt["falcon_growth"] * math.exp(rng.gauss(0, .15))
            rate = lambda day, g=g: current * g ** ((day - as_of).days / 365)
        elif scenario == "production":
            g = lt["production_growth"] * math.exp(rng.gauss(0, .2))
            rate = lambda day, g=g: produced * g ** ((day - as_of).days / 365)
        else:
            rate = target_rate_fn(lt, lt["slip_multiplier"] * math.exp(rng.gauss(0, .25)), as_of)
        scale = math.exp(rng.gauss(0, .2))
        hazard_factor = math.exp(rng.gauss(0, .3))
        for case, incidents in (("mit", True), ("ohne", False)):
            count = dict(done_year)
            near = run[:2]
            for x in near:
                day = as_of + timedelta(days=round(x))
                if day.year in count:
                    count[day.year] += 1
            day = as_of + timedelta(days=round(near[-1]))
            n = len(flown_before) + len(near)
            local = random.Random(rng.random())
            while True:
                r = max(rate(day) * scale, 1.0)
                step = 365 / r * local.lognormvariate(0, lt["gap_sigma"])
                if incidents:
                    h = min(.5, lt["hazard_at_14"] * hazard_factor * (n / 14) ** lt["hazard_exponent"])
                    if local.random() < h:
                        step += local.choice(lt["stand_down_days"]) * (n / 14) ** -0.3
                day += timedelta(days=max(1, round(step)))
                n += 1
                if day > horizon:
                    break
                if day.year in count:
                    count[day.year] += 1
            for y in years:
                by_case[case][y].append(count[y])
                if incidents:
                    by_scenario[scenario][y].append(count[y])

    def stats(values):
        s = sorted(values)
        pick = lambda p: s[min(len(s) - 1, int(p * len(s)))]
        return {"p10": pick(.1), "p25": pick(.25), "p50": pick(.5), "p75": pick(.75), "p90": pick(.9)}

    out = {"current_rate": round(current, 1), "production_12m": produced, "cases": {}, "scenarios": {}, "cumulative": {}}
    for case, table in by_case.items():
        out["cases"][case] = {str(y): stats(v) for y, v in table.items()}
        total_before = sum(1 for f in data.flights if d(f["date"]).year < as_of.year)
        cum = [total_before] * len(runs)
        out["cumulative"][case] = {}
        for y in years:
            cum = [a + b for a, b in zip(cum, table[y])]
            out["cumulative"][case][str(y)] = stats(cum)
    for s, table in by_scenario.items():
        out["scenarios"][s] = {str(y): stats(v) for y, v in table.items() if v}
    return out


def backtest(data, sims=700):
    """Rechnet vergangene Flüge nur mit dem damaligen Wissen nach."""
    rows = []
    gap_all = gaps(data)
    for f in data.flights:
        if f["n"] < 7:
            continue
        launch = d(f["date"])
        for horizon in (60, 30, 14, 7):
            as_of = launch - timedelta(days=horizon)
            if as_of <= d(data.flight(f["n"] - 1)["date"]):
                continue
            past = data.flights
            data.flights = [x for x in past if d(x["date"]) <= as_of]
            try:
                fc, runs, numbers = forecast_near(data, as_of, count=1, sims=sims, seed=f["n"] * 100 + horizon)
            finally:
                data.flights = past
            samples = [r[0] for r in runs]
            s = sorted(samples)
            actual = horizon
            p10, p25, p50, p75, p90 = (s[int(p * len(s))] for p in (.1, .25, .5, .75, .9))
            net = net_as_of(data, f["n"], as_of)
            pool = [g["gap"] for g in gap_all if g["n"] < f["n"] and not g["excluded"] and not g["transition"]][-5:]
            cadence = (d(data.flight(f["n"] - 1)["date"]) + timedelta(days=statistics.median(pool)) - as_of).days if pool else None
            rows.append({"n": f["n"], "horizon": horizon, "error": round(p50 - actual, 1), "abs_error": round(abs(p50 - actual), 1),
                         "in50": p25 <= actual <= p75, "in80": p10 <= actual <= p90, "mode": fc[0]["mode"], "actual": f["date"],
                         "net_error": (d(net["net"]) - launch).days if net else None,
                         "cadence_error": cadence - actual if cadence is not None else None})
    return rows


def backtest_summary(rows):
    out = {}
    for h in (60, 30, 14, 7, "alle"):
        sel = [r for r in rows if h == "alle" or r["horizon"] == h]
        if not sel:
            continue
        nets = [abs(r["net_error"]) for r in sel if r["net_error"] is not None]
        model_for_net = [r["abs_error"] for r in sel if r["net_error"] is not None]
        cad = [abs(r["cadence_error"]) for r in sel if r["cadence_error"] is not None]
        out[str(h)] = {"count": len(sel), "model_mae": round(statistics.mean(r["abs_error"] for r in sel), 1),
                       "model_bias": round(statistics.mean(r["error"] for r in sel), 1),
                       "in50": round(sum(r["in50"] for r in sel) / len(sel), 2), "in80": round(sum(r["in80"] for r in sel) / len(sel), 2),
                       "net_mae": round(statistics.mean(nets), 1) if nets else None, "net_count": len(nets),
                       "model_mae_where_net": round(statistics.mean(model_for_net), 1) if model_for_net else None,
                       "cadence_mae": round(statistics.mean(cad), 1) if cad else None}
    return out


def history_track(data, n, start, end, step=7, sims=500):
    """Wie hätte das Modell einen Flug im Zeitverlauf gesehen?"""
    track, as_of = [], start
    past = data.flights
    while as_of <= end:
        data.flights = [x for x in past if d(x["date"]) <= as_of]
        try:
            fc, _, _ = forecast_near(data, as_of, count=1, sims=sims, seed=n * 10000 + as_of.toordinal() % 1000)
        finally:
            data.flights = past
        net = net_as_of(data, n, as_of)
        if fc and fc[0]["n"] == n:
            track.append({"as_of": str(as_of), "p10": fc[0]["p10"], "p50": fc[0]["p50"], "p90": fc[0]["p90"], "mode": fc[0]["mode"], "net": net["net"] if net else None})
        as_of += timedelta(days=step)
    return track


def milestone_stats():
    ms = load("milestones")
    today = date.today()
    done = []
    for m in ms["done"]:
        lead = (d(m["target"]) - d(m["announced"])).days
        actual = (d(m["actual"]) - d(m["announced"])).days
        done.append({**m, "lead": lead, "actual_lead": actual, "ratio": round(actual / lead, 2), "slip": (d(m["actual"]) - d(m["target"])).days})
    still = []
    for m in ms["open"]:
        lead = (d(m["target"]) - d(m["announced"])).days
        so_far = (today - d(m["announced"])).days
        still.append({**m, "lead": lead, "actual_lead": so_far, "ratio_min": round(so_far / lead, 2), "overdue": today > d(m["target"])})
    median = lambda seq: round(statistics.median(seq), 2) if seq else None
    groups = {
        "Lange Vorläufe (über 12 Monate)": [x["ratio"] for x in done if x["lead"] > 365],
        "Mittlere Vorläufe (3–12 Monate)": [x["ratio"] for x in done if 90 < x["lead"] <= 365],
        "Kurze Vorläufe (unter 3 Monaten)": [x["ratio"] for x in done if x["lead"] <= 90],
        "Falcon und Dragon, alle": [x["ratio"] for x in done if x["program"] != "Starship"],
        "Starship, alle": [x["ratio"] for x in done if x["program"] == "Starship"],
    }
    short_slips = [x["slip"] for x in done if x["kind"] == "kurz"]
    return {"done": done, "open": still, "groups": {k: {"median": median(v), "n": len(v)} for k, v in groups.items()},
            "short_slip_median": median(short_slips)}

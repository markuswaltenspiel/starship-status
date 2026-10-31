"""Holt die öffentlichen Quellen. Jeder Abruf ist anonym und darf einzeln scheitern."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
UA = "starship-prognose/1.0 (private, low-rate)"
EVENT_RE = re.compile(
    r'\{"id":(\d+),"name":"([^"]*)","notes":"((?:[^"\\]|\\.)*)","date":"([^"]*)","location":"([^"]*)",'
    r'"vid_url":"([^"]*)","info_url":"([^"]*)","status":(\d+),"starship_vehicle":(\d+),"thisType":"([^"]*)"'
)


def http_get(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as err:
            if err.code != 429 or attempt == retries - 1:
                raise
            time.sleep(int(err.headers.get("Retry-After") or 20) + 3)
    raise RuntimeError("unreachable")


def parse_vehicle(html):
    """Liest Name und Testereignisse aus dem eingebetteten Datenblock einer Fahrzeugseite."""
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    name = title.group(1).split("|")[0].strip() if title else ""
    body = html.replace('\\"', '"').replace("\\\\", "\\")
    events = []
    for e in EVENT_RE.findall(body):
        events.append({"name": e[1], "date": e[3], "location": e[4], "url": e[6], "status": int(e[7])})
    return {"name": name, "events": sorted(events, key=lambda x: x["date"])}


def fetch_vehicles(force_all=False):
    """Aktualisiert die Fahrzeugdaten; ältere, abgeschlossene Fahrzeuge nur bei force_all."""
    path = CACHE / "vehicles.json"
    known = json.loads(path.read_text()) if path.exists() else {}
    html = http_get("https://nextspaceflight.com/starship/")
    ids = sorted({int(x) for x in re.findall(r"/starship/hardware/(\d+)", html)})
    if not ids:
        raise ValueError("Keine Fahrzeuglinks gefunden: Seitenformat geändert?")
    newest = max(ids)
    todo = [i for i in range(1, newest + 4) if force_all or str(i) not in known or i >= newest - 12]
    changed = 0
    for i in todo:
        page = http_get(f"https://nextspaceflight.com/starship/hardware/{i}/")
        parsed = parse_vehicle(page)
        if parsed["name"] and parsed["name"] != "Next Spaceflight":
            if known.get(str(i)) != parsed:
                changed += 1
            known[str(i)] = parsed
        time.sleep(1.2)
    if not any(v["events"] for v in known.values()):
        raise ValueError("Keine Testereignisse gefunden: Seitenformat geändert?")
    path.write_text(json.dumps(known, indent=0, ensure_ascii=False))
    return {"vehicles": len(known), "updated": changed}


def fetch_ll2():
    url = "https://ll.thespacedevs.com/2.3.0/launches/upcoming/?search=starship&limit=10&mode=normal"
    data = json.loads(http_get(url))
    rows = []
    for item in data.get("results", []):
        m = re.search(r"Flight\s+(\d+)", item.get("name", ""))
        precision = (item.get("net_precision") or {}).get("abbrev", "")
        rows.append({"name": item.get("name"), "flight": int(m.group(1)) if m else None, "net": (item.get("net") or "")[:10],
                     "precision": precision, "status": (item.get("status") or {}).get("abbrev"), "updated": item.get("last_updated")})
    (CACHE / "ll2.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    return rows


def fetch_wiki_net(flights):
    """Aktuelles Zieldatum aus den Wikipedia-Flugseiten der nächsten Flüge."""
    from wiki_net import launch_field, parse_date
    rows = []
    for n in flights:
        params = {"action": "query", "format": "json", "prop": "revisions", "titles": f"Starship flight test {n}",
                  "rvprop": "timestamp|content", "rvslots": "main", "rvsection": 0, "rvlimit": 1, "redirects": 1}
        data = json.loads(http_get("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)))
        for page in data["query"]["pages"].values():
            for rev in page.get("revisions", []):
                parsed = parse_date(launch_field(rev["slots"]["main"].get("*", "")))
                if parsed:
                    rows.append({"flight": n, "net": parsed[0], "precision": parsed[1], "edited": rev["timestamp"][:10]})
        time.sleep(2)
    return rows

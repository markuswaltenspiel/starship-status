"""Zusätzliche Quellen: Checkliste, Wikipedia-Fahrzeuglisten, FAA, NSF-Feed und Artemis-Termine."""
import html
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date

from fetch import CACHE, http_get

MONTHS = "january february march april may june july august september october november december".split()
MON_RE = "January|February|March|April|May|June|July|August|September|October|November|December|Jan\\.?|Feb\\.?|Mar\\.?|Apr\\.?|Jun\\.?|Jul\\.?|Aug\\.?|Sept?\\.?|Oct\\.?|Nov\\.?|Dec\\.?"
DATE_RE = re.compile(rf"\b(?:(early|mid|late)[- ])?({MON_RE})(?:\s+(\d{{1,2}})(?:st|nd|rd|th)?)?(?:,?\s+(20\d\d))?\b")
VEHICLE_RE = re.compile(r"\b(?:Ship\s?|S)(\d{2})\b|\b(?:Booster\s?|B)(\d{1,2})\b")
RULES = [
    ("stack_start", re.compile(r"(stacking|assembly)[^.]{0,30}\b(began|begun|started)|\b(began|begun|started)\s+(stacking|assembly)", re.I)),
    ("stack_done", re.compile(r"(stacking|assembly)[^.]{0,30}\b(concluded|completed|complete|finished)|fully stacked|final stacking", re.I)),
    ("rollout_test", re.compile(r"\brolled?(?:\s+out)?\s+(?:back\s+)?(?:out\s+)?to\s+Massey", re.I)),
    ("rollout_pad", re.compile(r"\brolled?(?:\s+out)?\s+to\s+(?:the\s+)?(?:launch site|Pad)", re.I)),
    ("engines", re.compile(r"engines?\s+install|install\w*\s+(?:of\s+)?(?:its\s+|the\s+)?(?:\w+\s+){0,3}engines", re.I)),
    ("flaps", re.compile(r"\bflaps?\b[^.]{0,40}\b(install|attach|fitted|received)|\b(install|attach|received)\w*[^.]{0,40}\bflaps?\b", re.I)),
    ("heat_shield", re.compile(r"\b(tiling|tiles?|heat shield)\b[^.]{0,40}\b(complete|finish|install)", re.I)),
]


def month_number(token):
    return next(i + 1 for i, m in enumerate(MONTHS) if m.startswith(token.lower().rstrip(".")[:3]))


def plain_wikitext(text):
    text = re.sub(r"<ref[^>]*/>", "", text)
    text = re.sub(r"<ref.*?</ref>", "", text, flags=re.S)
    for _ in range(3):
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    return re.sub(r"'''?", "", text)


def vehicle_key(match):
    return f"S{match.group(1)}" if match.group(1) else f"B{match.group(2)}"


def resolve_dates(sentence, year):
    """Datumsangaben eines Satzes; fehlende Jahre folgen dem zuletzt genannten."""
    found = []
    for m in DATE_RE.finditer(sentence):
        if m.group(2) == "May" and not (m.group(3) or m.group(1) or m.group(4)):
            continue
        month = month_number(m.group(2))
        y = int(m.group(4)) if m.group(4) else year
        if m.group(3):
            day, precision = int(m.group(3)), "day"
        elif m.group(1):
            day, precision = {"early": 7, "mid": 15, "late": 24}[m.group(1)], "approx"
        else:
            day, precision = 15, "approx"
        found.append({"month": month, "day": day, "year": y, "explicit": bool(m.group(4)), "precision": precision, "start": m.start()})
    return found


def extract_steps(text, source, fallback_year=None, needs_vehicle_in_sentence=False):
    """Findet Produktionsschritte: Fahrzeug, Schlüsselwort und Datum im selben Satz."""
    out = {}
    for para in re.split(r"\n\s*\n", text):
        subject = VEHICLE_RE.search(para[:80])
        current = vehicle_key(subject) if subject else None
        year, last_month = fallback_year, None
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", para):
            named = VEHICLE_RE.search(sentence)
            if named and sentence.index(named.group(0)) < 25:
                current = vehicle_key(named)
            dates = resolve_dates(sentence, year)
            for dt in dates:
                if dt["explicit"]:
                    year = dt["year"]
                elif last_month and dt["month"] < last_month - 3 and year:
                    year += 1
                dt["year"] = year
                last_month = dt["month"]
            target = vehicle_key(named) if needs_vehicle_in_sentence and named else (None if needs_vehicle_in_sentence else current)
            if not target or not dates:
                continue
            for step, rule in RULES:
                hit = rule.search(sentence)
                if not hit:
                    continue
                best = min((x for x in dates if x["year"]), key=lambda x: abs(x["start"] - hit.start()), default=None)
                if not best:
                    continue
                iso = f"{best['year']:04d}-{best['month']:02d}-{best['day']:02d}"
                step_data = out.setdefault(target, {})
                # Erste Nennung gilt: spätere Rollouts desselben Typs sind Wiederholungen
                if step == "stack_done" and step_data.get("stack_start", {}).get("date") == iso:
                    continue
                step_data.setdefault(step, {"date": iso, "precision": best["precision"], "source": source})
    return out


def wiki_sections(page):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "parse", "page": page, "prop": "sections", "format": "json"})
    return json.loads(http_get(url))["parse"]["sections"]


def wiki_section_text(page, index):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "parse", "page": page, "section": index, "prop": "wikitext", "format": "json"})
    return plain_wikitext(json.loads(http_get(url))["parse"]["wikitext"]["*"])


def fetch_wiki_vehicles():
    """Fahrzeuggeschichte aus den beiden Wikipedia-Listen."""
    steps, versions = {}, {}
    for page in ("List_of_Starship_vehicles", "List_of_Super_Heavy_boosters"):
        url = f"https://en.wikipedia.org/wiki/{page}"
        for section in wiki_sections(page):
            m = re.match(r"Block (\d)", section["line"])
            if not m:
                continue
            text = wiki_section_text(page, section["index"])
            for vehicle, data in extract_steps(text, url).items():
                steps.setdefault(vehicle, {}).update(data)
            for para in re.split(r"\n\s*\n", text):
                head = VEHICLE_RE.search(para[:60])
                if head:
                    versions[vehicle_key(head)] = f"V{m.group(1)}"
            time.sleep(1.5)
    if not steps:
        raise ValueError("Keine Fahrzeugdaten erkannt: Seitenformat geändert?")
    (CACHE / "wiki_steps.json").write_text(json.dumps({"steps": steps, "versions": versions}, indent=0, ensure_ascii=False))
    return f"{len(steps)} Fahrzeuge, {sum(len(v) for v in steps.values())} Schritte"


def parse_status(page):
    """Checkliste des nächsten Flugs aus dem Datenblock der Starship-Seite."""
    body = page.replace('\\"', '"').replace("\\\\", "\\")
    head = re.search(r'"title":"Starship Flight (\d+)"(?:(?!"title":"Starship Flight).){0,800}?"thisType":"Status Manager"', body, re.S)
    if not head:
        raise ValueError("Checkliste nicht gefunden: Seitenformat geändert?")
    items = re.findall(r'\{"id":\d+,"title":"([^"]*)","confirmed":(true|false),"url":(?:null|"[^"]*"),"manager":\d+\}', body)
    if not items:
        raise ValueError("Checkliste leer: Seitenformat geändert?")
    return {"flight": int(head.group(1)), "items": [{"title": t.replace("&#x27;", "'"), "confirmed": c == "true"} for t, c in items]}


def fetch_status():
    status = parse_status(http_get("https://nextspaceflight.com/starship/"))
    (CACHE / "status.json").write_text(json.dumps(status, indent=0, ensure_ascii=False))
    done = sum(i["confirmed"] for i in status["items"])
    return status, f"Flug {status['flight']}: {done} von {len(status['items'])} Punkten bestätigt"


def clean_html(text):
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))


def fetch_faa():
    """Datierte FAA-Mitteilungen zu Starship: Untersuchungen und Freigaben."""
    text = clean_html(http_get("https://www.faa.gov/newsroom/statements/general-statements"))
    pattern = re.compile(rf"\b((?:{MON_RE})\s+\d{{1,2}},\s+20\d\d)\s+((?:FAA |SpaceX |Statement|License)[^.]{{0,170}}?Starship[^.]{{0,130}})")
    rows, seen = [], set()
    for m in pattern.finditer(text):
        parts = m.group(1).replace(",", "").split()
        iso = f"{parts[2]}-{month_number(parts[0]):02d}-{int(parts[1]):02d}"
        headline = m.group(2).strip()
        low = headline.lower()
        kind = "mishap_closed" if "clos" in low and "investigation" in low else "mishap_open" if "mishap" in low and ("requires" in low or "require" in low) else "approval" if re.search(r"licen[sc]e|approv|authoriz|can proceed", low) else "other"
        flight = re.search(r"Flight\s+(\d+)", headline)
        key = (iso, headline[:60])
        if key not in seen:
            seen.add(key)
            rows.append({"date": iso, "headline": headline[:150], "kind": kind, "flight": int(flight.group(1)) if flight else None})
    if not rows:
        raise ValueError("Keine Starship-Mitteilungen erkannt: Seitenformat geändert?")
    rows.sort(key=lambda r: r["date"])
    (CACHE / "faa.json").write_text(json.dumps(rows, indent=0, ensure_ascii=False))
    return f"{len(rows)} Mitteilungen, letzte {rows[-1]['date']}"


def fetch_feed():
    """NASASpaceflight-Feed: nur Überschriften, die Texterkennung war dort zu fehleranfällig."""
    root = ET.fromstring(http_get("https://www.nasaspaceflight.com/feed/"))
    path = CACHE / "feed.json"
    known = json.loads(path.read_text()) if path.exists() else {"articles": []}
    urls = {a["url"] for a in known["articles"]}
    added = 0
    for item in root.find("channel").findall("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        body = clean_html(item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "")
        if not re.search(r"Starship|Starbase|Super Heavy|Flight 1\d|Artemis", title + body[:600]):
            continue
        parts = (item.findtext("pubDate") or "").split()
        published = f"{parts[3]}-{month_number(parts[2]):02d}-{int(parts[1]):02d}" if len(parts) > 3 else None
        if link not in urls:
            known["articles"].append({"title": title, "url": link, "date": published})
            added += 1
    known["articles"] = sorted(known["articles"], key=lambda a: a["date"] or "")[-40:]
    path.write_text(json.dumps(known, indent=0, ensure_ascii=False))
    return f"{added} neue Berichte"


def fetch_artemis():
    """Termine und abgeschlossene Artemis-Flüge aus der Startliste."""
    rows = []
    for kind in ("upcoming", "previous"):
        data = json.loads(http_get(f"https://ll.thespacedevs.com/2.3.0/launches/{kind}/?search=artemis&limit=10&mode=list"))
        for item in data.get("results", []):
            m = re.search(r"\bArtemis (I{1,3}|IV|V)\b", item.get("name", ""))
            if m:
                rows.append({"mission": m.group(1), "kind": kind, "net": (item.get("net") or "")[:10], "status": (item.get("status") or {}).get("abbrev"),
                             "precision": (item.get("net_precision") or {}).get("abbrev", "")})
        time.sleep(1)
    (CACHE / "artemis_ll2.json").write_text(json.dumps(rows, indent=0, ensure_ascii=False))
    return f"{len(rows)} Artemis-Einträge"

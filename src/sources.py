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
    head = re.search(r'"title":"Starship Flight (\d+)[^"]*"(?:(?!"title":"Starship Flight).){0,1500}?"thisType":"Status Manager"', body, re.S)
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


# --- Primärquellen für Sperrungen: FAA-TFRs und die Stadt Starbase ---

TFR_LIST = "https://tfr.faa.gov/tfrapi/exportTfrList"
TFR_DETAIL = "https://tfr.faa.gov/download/detail_{}.xml"
TFR_NEAR = re.compile(r"STARBASE|BOCA CHICA|BROWNSVILLE", re.I)
STARBASE_URL = "https://www.starbase.texas.gov/beach-road-access"
WINDOW_RE = re.compile(
    rf"(?:(Primary|Alternate|Alternative|Backup)\s*(?:Date|Day)?\s*:?\s*)?({MON_RE})\s+(\d{{1,2}}),?\s+(?:(20\d\d),?\s+)?(\d{{1,2}}:\d\d\s*[AaPp]\.?[Mm]\.?)"
    rf"\s*(?:to|-|–|until)\s*(?:({MON_RE})\s+(\d{{1,2}}),?\s+(?:(20\d\d),?\s+)?)?(\d{{1,2}}:\d\d\s*[AaPp]\.?[Mm]\.?)")


def tags(xml, name):
    return [html.unescape(x).strip() for x in re.findall(rf"<{name}>(.*?)</{name}>", xml, re.S)]


def classify_tfr(codes, text):
    """91.143 ist der Luftraum für Raumfahrtbetrieb (Start), 91.137(a)(1) mit „High Energy Testing“ der für Bodentests."""
    if any(c.startswith("91.143") for c in codes):
        return "space_ops"  # Start oder Rückkehr; refine_tfr entscheidet mit dem FAA-Betriebsplan
    if any(c.startswith("91.137") for c in codes) and re.search(r"HIGH ENERGY|TESTING", text, re.I):
        return "ground_test"
    return "other"


def parse_tfr_detail(nid, xml):
    codes = tags(xml, "codeType")
    text = (tags(xml, "txtDescrTraditional") or tags(xml, "txtDescrUSNS") or [""])[0]
    both = " ".join(tags(xml, "txtDescrTraditional") + tags(xml, "txtDescrUSNS"))
    start, end = tags(xml, "dateEffective"), tags(xml, "dateExpire")
    upper = tags(xml, "valDistVerUpper")
    unit = tags(xml, "uomDistVerUpper")
    radius = re.search(r"(\d+(?:\.\d+)?)\s*NM RADIUS", text)
    return {"id": nid, "kind": classify_tfr(codes, both), "rule": next((c for c in codes if c[:2] == "91"), None),
            "start": start[0] + "Z" if start else None, "end": end[0] + "Z" if end else None,
            "upper": f"{upper[0]} {unit[0]}" if upper and unit else None, "radius_nm": float(radius.group(1)) if radius else None,
            "city": (tags(xml, "txtNameCity") or [None])[0], "text": re.sub(r"\s+", " ", text)[:700]}


def fetch_tfr():
    """Aktive TFRs der FAA rund um Starbase, mit Art (Start, Bodentest) aus der Detailmeldung."""
    rows = json.loads(http_get(TFR_LIST))
    if not isinstance(rows, list) or not rows:
        raise ValueError("TFR-Liste leer: Format geändert?")
    hits = [r for r in rows if r.get("facility") == "ZHU" and TFR_NEAR.search(r.get("description", ""))]
    items = []
    for r in hits:
        nid = r["notam_id"]
        items.append(parse_tfr_detail(nid, http_get(TFR_DETAIL.format(nid.replace("/", "_")))))
        time.sleep(0.5)
    items.sort(key=lambda x: x["start"] or "")
    (CACHE / "tfr.json").write_text(json.dumps({"items": items}, indent=0, ensure_ascii=False))
    count = {k: sum(i["kind"] == k for i in items) for k in ("space_ops", "ground_test", "other")}
    return items, f"{count['space_ops']} für Raumfahrtbetrieb (Start oder Rückkehr), {count['ground_test']} für Bodentests, {count['other']} sonstige"


def _year_for(month, day, today):
    """Die Seite nennt keine Jahre; das Jahr ist das, bei dem das Datum am nächsten an heute liegt."""
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            cand = date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((cand - today).days) < abs((best - today).days):
            best = cand
    return best


def _clock(text):
    m = re.match(r"(\d{1,2}):(\d\d)\s*([AaPp])", text)
    h = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return h, int(m.group(2))


def parse_windows(text, today):
    """Zeitfenster wie „Primary: Nov. 13 11:00 AM to Nov. 13 11:30 PM“ in Ortszeit (CT) und UTC."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    tz, out = ZoneInfo("America/Chicago"), []
    for m in WINDOW_RE.finditer(text):
        label, mon1, d1, y1, t1, mon2, d2, y2, t2 = m.groups()
        first = date(int(y1), month_number(mon1), int(d1)) if y1 else _year_for(month_number(mon1), int(d1), today)
        last = first
        if mon2:
            last = date(int(y2), month_number(mon2), int(d2)) if y2 else _year_for(month_number(mon2), int(d2), first)
        a = datetime(first.year, first.month, first.day, *_clock(t1), tzinfo=tz)
        b = datetime(last.year, last.month, last.day, *_clock(t2), tzinfo=tz)
        if b <= a:
            b += timedelta(days=1)
        utc = ZoneInfo("UTC")
        out.append({"label": (label or "").lower().replace("alternative", "alternate").replace("backup", "alternate") or None,
                    "start_local": a.strftime("%Y-%m-%dT%H:%M"), "end_local": b.strftime("%Y-%m-%dT%H:%M"),
                    "start": a.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "end": b.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return out


def _block(page, anchor):
    """Inhalt des Rich-Text-Felds nach einer Element-ID der Starbase-Seite."""
    i = page.find(f'id="{anchor}"')
    if i < 0:
        return None
    m = re.search(r'id="rich-notification"[^>]*>(.*?)</div>', page[i:i + 6000], re.S)
    return clean_html(m.group(1).replace("<br>", "\n")).strip() if m else ""


def parse_starbase(page, today):
    beach, road = _block(page, "beach-closure"), _block(page, "road-closure")
    if beach is None or road is None:
        raise ValueError("Abschnitte für Strand oder Straße nicht gefunden: Seitenformat geändert?")
    text = clean_html(page)
    order = re.search(r"Public Notice of Mayor's Order\s*(.*?)\s*(?:Previous Orders|OTHER BEACHES)", text, re.S)
    previous = re.findall(r'cms-big-text no-space">\s*([A-Z][a-z]+ \d{1,2}, 20\d\d)\s*<.*?href="([^"]+\.pdf)"', page, re.S)
    return {"beach": parse_windows(beach, today), "beach_text": beach[:500], "road": parse_windows(road, today), "road_text": road[:500],
            "order": order.group(1)[:900] if order else None,
            "previous_orders": [{"date": f"{x.split()[2]}-{month_number(x.split()[0]):02d}-{int(x.split()[1].rstrip(',')):02d}", "url": u} for x, u in previous]}


def fetch_starbase():
    """Strand- und Straßensperrungen der Stadt Starbase (seit 2025 zuständig, vorher Cameron County)."""
    data = parse_starbase(http_get(STARBASE_URL), date.today())
    (CACHE / "starbase.json").write_text(json.dumps(data, indent=0, ensure_ascii=False))
    return data, f"{len(data['beach'])} Strandsperrungen, {len(data['road'])} Straßenbehinderungen"


def classify_closures(starbase, tfr, now):
    """Ordnet die Sperrungen ein. Strandsperrung, die sich mit einem Start-TFR (91.143) überschneidet: Start.
    Ohne Start-TFR: Bodentest (Static Fire, WDR, Cryo), sobald sie keine 3 Tage mehr entfernt ist; davor noch offen,
    weil die FAA die Start-TFRs oft erst wenige Tage vorher veröffentlicht.
    Eine „Road Delay“ ist eine kurze Behinderung, in der Regel für Transporte zwischen Werk und Startplatz."""
    from datetime import timedelta
    launch_tfr = [t for t in tfr if t["kind"] == "launch" and t["start"] and t["end"]]
    soon = (now + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for w in starbase.get("beach", []):
        hit = [t["id"] for t in launch_tfr if t["start"] < w["end"] and t["end"] > w["start"]]
        purpose = "launch" if hit else "test" if w["start"] <= soon else "open"
        rows.append({**w, "type": "beach_closure", "purpose": purpose, "tfr": hit})
    for w in starbase.get("road", []):
        rows.append({**w, "type": "road_delay", "purpose": "transport", "tfr": []})
    return sorted(rows, key=lambda r: r["start"])


# --- SpaceX-Termin und FAA-Betriebsplan ---

SPACEX_TILES = "https://content.spacex.com/api/spacex-website/launches-page-tiles/upcoming"
SPACEX_MISSION = "https://content.spacex.com/api/spacex-website/missions/{}"
OPS_PLAN = "https://www.fly.faa.gov/adv/adv_spt"
SITE_TZ = [("Starbase", "America/Chicago"), ("Texas", "America/Chicago"), ("Florida", "America/New_York"), ("39A", "America/New_York")]


def _local_to_utc(day, clock, tzname):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if not day or not clock:
        return None
    a = datetime.fromisoformat(f"{day}T{clock[:5]}").replace(tzinfo=ZoneInfo(tzname))
    return a.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_spacex():
    """Termin, den SpaceX selbst auf spacex.com nennt (dieselben Daten wie die Startseite, aus dem CMS)."""
    tiles = json.loads(http_get(SPACEX_TILES))
    if not isinstance(tiles, list):
        raise ValueError("SpaceX-Startliste: Format geändert?")
    rows = []
    for t in tiles:
        m = re.search(r"Starship Flight (\d+)", t.get("title") or "")
        if not m:
            continue
        o = t.get("override") or {}
        tz = next((z for k, z in SITE_TZ if k in (t.get("launchSite") or "")), "America/Chicago")
        open_day, open_time = o.get("windowOpenDate") or o.get("date") or t.get("launchDate"), o.get("windowOpenTime") or o.get("time") or t.get("launchTime")
        close_day, close_time = o.get("windowCloseDate"), o.get("windowCloseTime")
        text = None
        try:
            mission = json.loads(http_get(SPACEX_MISSION.format(t.get("link"))))
            paras = [clean_html(p.get("content") or "").strip() for p in mission.get("paragraphs") or []]
            text = next((p for p in paras if re.search(r"as soon as|targeting|launch window|preparing to launch", p, re.I)), None)
        except Exception:  # Der Begleittext ist nur Zusatz
            pass
        rows.append({"flight": int(m.group(1)), "site": t.get("launchSite"), "status": t.get("missionStatus"),
                     "date": open_day, "window_open_local": f"{open_day}T{open_time[:5]}" if open_day and open_time else None,
                     "window_open": _local_to_utc(open_day, open_time, tz), "window_close": _local_to_utc(close_day, close_time, tz),
                     "text": text[:400] if text else None, "url": f"https://www.spacex.com/launches/{t.get('link')}"})
    (CACHE / "spacex.json").write_text(json.dumps(rows, indent=0, ensure_ascii=False))
    return rows, (", ".join(f"Flug {r['flight']}: {r['date'] or 'ohne Datum'}" for r in rows) or "kein Starship-Flug angekündigt")


def parse_ops_plan(page):
    """Abschnitt „PLANNED LAUNCH/REENTRY“ des aktuellen Betriebsplans der FAA-Verkehrszentrale (ATCSCC)."""
    from datetime import datetime, timedelta
    text = clean_html(page)
    head = re.search(r"ATCSCC ADVZY (\d+) \w+ (\d\d/\d\d/\d{4})", text)
    sec = re.search(r"PLANNED LAUNCH/REENTRY:\s*(.*?)\s*(?:FLIGHT CHECK|VIP MOVEMENT|NEXT PLANNING|$)", text, re.S)
    if not head or not sec:
        raise ValueError("Betriebsplan nicht erkannt: Seitenformat geändert?")
    rows = []
    entry = re.compile(r"(.+?)\s+PRIMARY:\s*(\d\d/\d\d/\d\d)\s+(\d{4})Z-(\d{4})Z(?:\s+BACKUP:\s*(\d\d/\d\d/\d\d)\s+(\d{4})Z-(\d{4})Z)?\s*")

    def window(day, a, b):
        start = datetime.strptime(f"{day} {a}", "%m/%d/%y %H%M")
        end = datetime.strptime(f"{day} {b}", "%m/%d/%y %H%M")
        if end <= start:
            end += timedelta(days=1)
        return {"start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": end.strftime("%Y-%m-%dT%H:%M:%SZ")}

    for m in entry.finditer(sec.group(1)):
        name = m.group(1).strip(" ,")
        if "STARSHIP" not in name.upper():
            continue
        flight = re.search(r"FLT-?\s*(\d+)", name)
        windows = [{"label": "primary", **window(*m.group(2, 3, 4))}]
        if m.group(5):
            windows.append({"label": "backup", **window(*m.group(5, 6, 7))})
        rows.append({"name": name, "flight": int(flight.group(1)) if flight else None,
                     "kind": "reentry" if "REENTRY" in name.upper() else "launch", "windows": windows})
    return {"advisory": int(head.group(1)), "issued": head.group(2), "items": rows}


def fetch_ops_plan():
    plan = parse_ops_plan(http_get(OPS_PLAN))
    (CACHE / "ops_plan.json").write_text(json.dumps(plan, indent=0, ensure_ascii=False))
    return plan, f"Advisory {plan['advisory']}: " + (", ".join(i["name"] for i in plan["items"]) or "keine Starship-Termine")


def refine_tfr(tfr, ops):
    """Eine 91.143-TFR ist Start oder Rückkehr; der FAA-Betriebsplan sagt, welches Fenster wofür gilt."""
    plan = [(i["kind"], i["flight"], w) for i in (ops or {}).get("items", []) for w in i["windows"]]
    out = []
    for t in tfr:
        t = dict(t)
        if t["kind"] in ("launch", "space_ops") and t["start"] and t["end"]:
            from datetime import datetime
            ts = datetime.fromisoformat(t["start"].replace("Z", "+00:00"))
            # Überschneiden sich mehrere Fenster (Ausweichtag Start = Haupttag Rückkehr), zählt der nächstgelegene Beginn
            hits = sorted((abs((datetime.fromisoformat(w["start"].replace("Z", "+00:00")) - ts).total_seconds()), k, f)
                          for k, f, w in plan if w["start"] < t["end"] and w["end"] > t["start"])
            t["kind"], t["flight"] = (hits[0][1], hits[0][2]) if hits else ("space_ops", None)
        out.append(t)
    return out

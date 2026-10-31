"""Rekonstruiert den NET-Verlauf je Flug aus der Wikipedia-Versionsgeschichte."""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
API = "https://en.wikipedia.org/w/api.php"
UA = "starship-prognose/0.1 (private, low-rate)"
MONTHS = {m: i + 1 for i, m in enumerate("january february march april may june july august september october november december".split())}

def get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 5:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 30) + 5)

def revisions(title, max_pages=8):
    out, cont = [], {}
    for _ in range(max_pages):
        j = get({"action": "query", "format": "json", "prop": "revisions", "titles": title, "rvprop": "timestamp|content",
                 "rvslots": "main", "rvsection": 0, "rvlimit": 50, "rvdir": "older", "redirects": 1, **cont})
        for page in j["query"]["pages"].values():
            for rev in page.get("revisions", []):
                out.append((rev["timestamp"], rev["slots"]["main"].get("*", "")))
        if "continue" not in j:
            break
        cont = j["continue"]
        time.sleep(4)
    return sorted(out)

def launch_field(text):
    m = re.search(r"\|\s*launch_date\s*=\s*(.*?)\n\s*\|", text, re.S)
    return m.group(1) if m else None

def parse_date(raw):
    """Gibt (ISO-Datum, Genauigkeit) zurueck; Genauigkeit day/month/quarter/year."""
    if not raw:
        return None
    s = re.sub(r"<!--.*?-->|<ref.*?(</ref>|/>)", " ", raw, flags=re.S)
    m = re.search(r"\{\{\s*(?:start[- ]date(?: and age)?|Start date and age|start-date)\s*\|([^}]*)\}\}", s, re.I)
    if m:
        nums = [p.strip() for p in m.group(1).split("|") if re.fullmatch(r"\d{1,4}", p.strip())]
        if len(nums) >= 3:
            return f"{int(nums[0]):04d}-{int(nums[1]):02d}-{int(nums[2]):02d}", "day"
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]|\{\{|\}\}", lambda x: x.group(1) or " ", s)
    s = s.replace(",", " ")
    m = re.search(r"(\d{1,2})\s+([A-Z][a-z]+)\s+(20\d\d)", s) 
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}", "day"
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2})\s+(20\d\d)", s)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}", "day"
    m = re.search(r"([A-Z][a-z]+)\s+(20\d\d)", s)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}-28", "month"
    return None

def history(n):
    series = []
    for ts, text in revisions(f"Starship flight test {n}"):
        p = parse_date(launch_field(text))
        if p and (not series or series[-1]["net"] != p[0]):
            series.append({"seen": ts[:10], "net": p[0], "precision": p[1]})
    return series

if __name__ == "__main__":
    out = json.load(open(sys.argv[3])) if os.path.exists(sys.argv[3]) else {}
    for n in range(int(sys.argv[1]), int(sys.argv[2]) + 1):
        if out.get(str(n)):
            continue
        try:
            out[str(n)] = history(n)
            json.dump(out, open(sys.argv[3], "w"), indent=1)
        except Exception as e:
            print("fehler", n, e, file=sys.stderr)
        print(n, len(out.get(str(n), [])), out.get(str(n), [])[-6:], flush=True)
        time.sleep(5)
    json.dump(out, open(sys.argv[3], "w"), indent=1)

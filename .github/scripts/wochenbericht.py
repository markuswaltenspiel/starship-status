"""Wochenübersicht der fehlgeschlagenen Läufe von "Prognose aktualisieren" als Issue.

Läuft in GitHub Actions (gh ist dort vorhanden, GH_TOKEN gesetzt).
Ohne Fehlschläge in den letzten 7 Tagen wird nichts angelegt.
Ältere offene Wochenberichte werden beim neuen geschlossen.
"""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

WORKFLOW = "update.yml"
TITEL_PREFIX = "Wochenbericht fehlgeschlagene Läufe"


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def fehlgeschlagener_schritt(run_id):
    jobs = json.loads(gh("run", "view", str(run_id), "--json", "jobs"))["jobs"]
    namen = []
    for job in jobs:
        for step in job.get("steps", []):
            if step.get("conclusion") == "failure":
                namen.append(f"{job['name']}: {step['name']}")
    return ", ".join(namen) or "unbekannt"


def main():
    jetzt = datetime.now(timezone.utc)
    seit = jetzt - timedelta(days=7)
    runs = json.loads(gh(
        "run", "list", "--workflow", WORKFLOW, "--limit", "300",
        "--created", f">={seit:%Y-%m-%d}",
        "--json", "databaseId,createdAt,conclusion,event,url",
    ))
    runs = [r for r in runs if r["createdAt"] >= seit.strftime("%Y-%m-%dT%H:%M:%SZ")]
    fehler = [r for r in runs if r["conclusion"] in ("failure", "timed_out", "startup_failure")]

    if not fehler:
        print(f"Keine fehlgeschlagenen Läufe seit {seit:%d.%m.%Y} ({len(runs)} Läufe).")
        return

    zeilen = [
        f"Zeitraum: {seit:%d.%m.%Y %H:%M} bis {jetzt:%d.%m.%Y %H:%M} UTC",
        f"Läufe insgesamt: {len(runs)}, davon fehlgeschlagen: {len(fehler)}",
        "",
        "| Zeitpunkt (UTC) | Auslöser | Fehlgeschlagener Schritt | Lauf |",
        "|---|---|---|---|",
    ]
    for r in sorted(fehler, key=lambda r: r["createdAt"]):
        zeit = datetime.strptime(r["createdAt"], "%Y-%m-%dT%H:%M:%SZ")
        zeilen.append(
            f"| {zeit:%d.%m.%Y %H:%M} | {r['event']} | {fehlgeschlagener_schritt(r['databaseId'])} "
            f"| [{r['databaseId']}]({r['url']}) |"
        )
    body = "\n".join(zeilen)

    alte = json.loads(gh(
        "issue", "list", "--state", "open", "--search", f'"{TITEL_PREFIX}" in:title',
        "--json", "number",
    ))
    for issue in [] if os.environ.get("DRY_RUN") else alte:
        gh("issue", "close", str(issue["number"]), "--comment", "Ersetzt durch den neuen Wochenbericht.")

    kw = (jetzt - timedelta(days=1)).isocalendar()  # Montags: die abgelaufene Woche
    titel = f"{TITEL_PREFIX} (KW {kw.week}/{kw.year})"
    if os.environ.get("DRY_RUN"):
        print(titel, body, sep="\n\n")
        return
    print(gh("issue", "create", "--title", titel, "--body", body))


if __name__ == "__main__":
    main()

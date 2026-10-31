# Starship-Prognose

Auswertung des Starship-Programms und Prognose der nächsten Starts. Läuft ohne KI und ohne eigenen Server.

**Ansicht:** https://markuswaltenspiel.github.io/starship-status/

## So läuft es

GitHub Actions startet alle sechs Stunden `src/run.py`. Das Programm holt die Daten, rechnet die Prognose,
ergänzt das Log und veröffentlicht die Seite. Fällt eine Quelle aus, nutzt es den letzten Stand und zeigt eine Warnung.

## Selbst ändern

Alles liegt in `data/manual/`. Nach dem Hochladen rechnet die Seite von selbst neu.

| Datei | Inhalt |
|---|---|
| `license.json` | Lizenzdaten und Wartezeiten, hier wird die Lizenz für Flug 15 eingetragen |
| `flights.json` | Fahrzeugzuordnung und Startplatz der nächsten Flüge |
| `production.json` | Produktionsschritte mit Quelle |
| `milestones.json` | SpaceX-Ankündigungen und tatsächliche Termine |
| `assumptions.json` | Annahmen des Modells; bei Änderungen `model_version` erhöhen |

`data/log/forecasts.jsonl` ist das Prognose-Log. Einträge werden nur angehängt und nie geändert.

## Lokal starten

```
python3 src/run.py            # mit Datenabruf
python3 src/run.py --offline  # nur neu rechnen
open dist/index.html
```

## Quellen

NextSpaceflight (Testereignisse), Launch Library 2 (Startliste), Wikipedia (Zieldaten und deren Verlauf) sowie
von Hand zusammengetragene Berichte von NASASpaceflight und anderen. Abrufe erfolgen selten und anonym.
Privates Projekt, nicht mit SpaceX verbunden.

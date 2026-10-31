# Starship-Prognose

Auswertung des Starship-Programms und Prognose der nächsten Starts. Läuft ohne KI und ohne eigenen Server.

**Ansicht:** https://markuswaltenspiel.github.io/starship-status/

## So läuft es

GitHub Actions startet alle sechs Stunden `src/run.py`. Das Programm holt die Daten, rechnet die Prognose,
ergänzt das Log und veröffentlicht die Seite. Fällt eine Quelle aus, nutzt es den letzten Stand und zeigt eine Warnung.

## Selbst ändern

Im Normalbetrieb ist nichts zu tun. Wer eingreifen möchte, findet alles in `data/manual/`. Nach dem Hochladen rechnet die Seite von selbst neu.

| Datei | Inhalt |
|---|---|
| `license.json` | Einschätzung früherer Lizenz-Wartezeiten; neue Freigaben kommen automatisch aus der Checkliste |
| `artemis.json` | Artemis-Meilensteine, Faktoren und Abhängigkeiten |
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

## Zur Wiedervorlage

**Nach Flug 17 die Prognose prüfen und eventuell feinjustieren** (Stand der Vereinbarung: 31.10.2026, Modell 1.2).
Zu prüfen: Trefferquote im Log, Fehler nach Vorlauf, Halbwertszeit der Gewichte, Anteil des Flugabstands,
im Flotten-Szenario Fertigungswachstum gegen den gemessenen Takt, Wartungszeiten gegen echte Wiederholungsflüge und die Termine der Startplätze.
Außerdem die festen 30, 45 oder 60 Tage für wiederverwendete Fahrzeuge bei den nahen Flügen (`src/model.py`, Funktion `sample_flight`). Die Seite zeigt ab Flug 17 einen Hinweis.

## Quellen

NextSpaceflight (Testereignisse, Checkliste), Launch Library 2 (Startliste, Artemis), Wikipedia (Zieldaten, Fahrzeuglisten),
FAA (Mitteilungen), NASASpaceflight (nur Überschriften) sowie von Hand zusammengetragene Berichte. Abrufe erfolgen selten und anonym.
Privates Projekt, nicht mit SpaceX verbunden.

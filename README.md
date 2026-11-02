# Starship-Prognose

Auswertung des Starship-Programms und Prognose der nächsten Starts. Läuft ohne KI und ohne eigenen Server.

**Ansicht:** https://markuswaltenspiel.github.io/starship-status/

## So läuft es

GitHub Actions startet alle sechs Stunden `src/run.py`. Das Programm holt die Daten, rechnet die Prognose,
ergänzt das Log und veröffentlicht die Seite. Fällt eine Quelle aus, nutzt es den letzten Stand und zeigt eine Warnung.

## So rechnet die Prognose

Aus dem Fahrzeugstand entsteht eine Glockenkurve für den Starttag: der letzte erreichte Schritt (WDR, sonst Static Fire, sonst früherer Testschritt oder Flugabstand) plus die früheren Abstände bis zum Start.
Sind beide Static Fires durch und ist das NET höchstens 21 Tage entfernt, wird sie mit einer zweiten Kurve aus NET plus früherem Verzug verrechnet; die schmalere zählt mehr, das NET doppelt.
Termine vor dem NET werden auf den NET-Tag gesetzt, oben steht die Mitte der Kurve.

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

## Entscheidung für Modell 1.8 (02.11.2026)

**Anlass:** Modell 1.6 sprang für Flug 15 ohne neue Daten vom 19.11. auf den 13.11. Ursachen waren feste Vergleichstöpfe beim NET-Vorlauf und eine Auslosung zwischen zwei Rechenwegen, die zwei inhaltlich nicht erklärbare Gipfel erzeugte.

**Vergleich** im Rückblick-Test (29 Zeitpunkte aus 8 Flügen), 1.7 war die lokal verbesserte Fassung von 1.6 und wurde nie veröffentlicht:

| | 1.7 | 1.8 |
|---|---|---|
| Fehler der Mitte | 9,3 Tage | 8,5 Tage |
| Fehler des Gipfels | 9,4 Tage | 6,3 Tage |
| Treffer im 80 %-Bereich (Ziel: 80 %) | 90 % | 83 % |

**Verworfen:** mehr Gewicht auf das Static Fire (Test schlechter), eine links abgeschnittene Glocke ohne Häufung am NET (eine Woche vorher nur 50 % im 80 %-Bereich), ein breiterer Bereich (Gipfel deutlich schlechter).

**Einschränkung:** Die Unterschiede sind mit so wenigen Flügen nicht belegbar, und das doppelte NET-Gewicht wurde an denselben Daten gewählt. Die Wahl beruht vor allem auf der Logik; prüfen können sie erst die echten Flüge im Log.
Bekannte Schwäche: Bei viel Vorlauf kann der Bereich sehr breit werden (im Test bis rund 150 Tage nach dem Start). Ein Deckel am spätesten simulierten Stand half nicht.

## Zur Wiedervorlage

**Nach Flug 17 die Prognose prüfen und eventuell feinjustieren** (Stand der Vereinbarung: 31.10.2026, Modell 1.2).
Zu prüfen: Trefferquote im Log, Fehler nach Vorlauf, Halbwertszeit der Gewichte, Anteil des Flugabstands,
im Flotten-Szenario Fertigungswachstum gegen den gemessenen Takt, Wartungszeiten gegen echte Wiederholungsflüge und die Termine der Startplätze.
Außerdem die festen 30, 45 oder 60 Tage für wiederverwendete Fahrzeuge bei den nahen Flügen (`src/model.py`, Funktion `sample_flight`). Die Seite zeigt ab Flug 17 einen Hinweis.

**Nach Flug 16 die Scrubs prüfen** (Stand der Vereinbarung: 02.11.2026). Scrubs sind bewusst nicht im Modell, weil sie vermutlich seltener werden.
Gibt es bei den Flügen 15 oder 16 noch Scrubs, kommen eine Wahrscheinlichkeit für einen Scrub und eine für eine anschließende Reparaturpause dazu.

## Quellen

NextSpaceflight (Testereignisse, Checkliste), Launch Library 2 (Startliste, Artemis), Wikipedia (Zieldaten, Fahrzeuglisten),
FAA (Mitteilungen), NASASpaceflight (nur Überschriften) sowie von Hand zusammengetragene Berichte. Abrufe erfolgen selten und anonym.
Privates Projekt, nicht mit SpaceX verbunden.

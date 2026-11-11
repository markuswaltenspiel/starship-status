# Starship-Prognose

Auswertung des Starship-Programms und Prognose der nächsten Starts. Läuft ohne KI und ohne eigenen Server.

**Ansicht:** https://markuswaltenspiel.github.io/starship-status/

## So läuft es

GitHub Actions startet stündlich `src/run.py` (GitHub verschiebt oder überspringt geplante Läufe gelegentlich). Das Programm holt die Daten, rechnet die Prognose,
ergänzt das Log und veröffentlicht die Seite. Fällt eine Quelle aus, nutzt es den letzten Stand und zeigt eine Warnung.
Checkliste, TFRs, FAA-Betriebsplan, SpaceX-Termin, Starbase-Sperrungen, Launch Library und Feed kommen bei jedem Lauf; die NextSpaceflight-Fahrzeugseiten alle 3 Stunden,
die Wikipedia-Zieldaten alle 2, Wikipedia-Fahrzeuglisten und FAA-Mitteilungen alle 6, Artemis alle 12 Stunden (Zeitstempel in `data/cache/fetched.json`).

**Sperrungen aus Primärquellen:** Luftraumsperrungen kommen aus der TFR-Liste der FAA (`tfr.faa.gov`, Detailmeldung als XML),
Strand- und Highway-4-Sperrungen von der Stadt Starbase (`starbase.texas.gov/beach-road-access`, seit 2025 zuständig statt Cameron County).
Einordnung: TFR nach 14 CFR 91.143 (Raumfahrtbetrieb, bis unbegrenzte Höhe) = Start oder Rückkehr des Ship; welches von beiden, steht im Betriebsplan der FAA-Verkehrszentrale (`fly.faa.gov/adv/adv_spt`, Abschnitt „PLANNED LAUNCH/REENTRY“ mit Haupt- und Ausweichfenster je Flug); TFR nach 91.137(a)(1) „High Energy Testing“ mit 3,5 NM Radius = Bodentests (Static Fire, Cryo, WDR), meist über Wochen ohne einzelne Testtage.
Eine Strandsperrung, die sich mit einer 91.143-TFR überschneidet, gilt als Start, ohne solche TFR ab 3 Tagen vorher als Bodentest, davor als offen.
Eine „Road Delay“ der Stadt ist eine kurze Behinderung, in der Regel ein Transport zwischen Werk und Startplatz.
Jede neue TFR und jedes neue Sperrfenster landet in `data/log/closures.jsonl`, weil die Quellen nur aktuelle Einträge zeigen; Änderungen am Betriebsplan in `data/log/ops_plan.jsonl`.

**Termin von SpaceX:** Den Punkt „Confirmation from SpaceX“ hakt NextSpaceflight ab, sobald SpaceX eine Startseite mit Datum veröffentlicht (Beleglink `spacex.com/launches/starship-flight-N`).
Das Programm liest dieselben Daten direkt aus dem CMS hinter spacex.com (`content.spacex.com/api/spacex-website/launches-page-tiles/upcoming`, Feld `override` mit Fensterbeginn und -ende in Ortszeit, dazu der Begleittext der Missionsseite)
und schreibt jede Änderung in `data/log/spacex_targets.jsonl`. Die Prognose nutzt den SpaceX-Termin, den Betriebsplan und die Sperrungen bisher nicht.
Nicht automatisch: Notices to Mariners (NGA blockiert automatische Abrufe, USCG nur als PDF) und NOTAMs außerhalb der TFR-Liste, etwa für den Wiedereintritt.

## So rechnet die Prognose

**Nächster Flug:** Aus dem Fahrzeugstand entsteht eine Glockenkurve für den Starttag: der letzte erreichte Schritt (WDR, sonst Static Fire, sonst früherer Testschritt oder Flugabstand) plus die früheren Abstände bis zum Start.
Sind beide Static Fires durch und ist das NET höchstens 21 Tage entfernt, wird sie mit einer zweiten Kurve aus NET plus früherem Verzug verrechnet; die schmalere zählt mehr, das NET doppelt. Termine vor dem NET werden auf den NET-Tag gesetzt, oben steht die Mitte der Kurve.

**Spätere Flüge:** Der letzte Test des Ships (Static Fire, sonst Cryo-Test) plus der frühere Abstand bis zum Start ergibt eine Kurve in Tagen. Ohne Test folgt das Ship dem Static-Fire-Takt seiner Baureihe, sonst dem Cryo-Takt, unabhängig von Startverzögerungen davor.
Termine vor dem NET und vor der Fertigstellung eines neuen Startplatzes rücken auf diesen Tag, ein früherer Flug blockiert nur denselben Startplatz, mindestens 10 Tage. Wechsel der Baureihe und Lizenzwartezeiten zählen hier nicht als normale Dauer.

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

## Ergänzung zu Modell 1.8 (02.11.2026, gleiche Versionsnummer)

Geändert wurden nur die Flüge nach dem nächsten und der Mindestabstand auf demselben Startplatz (10 statt 30 Tage). Der nächste Flug rechnet unverändert, der Rückblick-Test bleibt gleich. Die Versionsnummer blieb bewusst 1.8; das Log zeigt die Änderung am neuen `fingerprint` ab dem 02.11.2026.

**Grund:** Über den Flugabstand addierten sich Verzögerungen auf, obwohl Tests und Bau weiterlaufen. In 7 Testfällen ohne Baureihenwechsel fiel der Fehler bei späteren Flügen von 34 auf 13 Tage, bei gleich vielen Treffern (6 von 7) und schmaleren Bereichen. Das sind fast nur V2-Fälle, also ein schwacher Beleg.

**Verworfen:** Ein Entwurf 1.9 wollte auch den nächsten Flug umstellen. Dort war der Rückblick-Test schlechter (Gipfel-Fehler 9,0 statt 6,3 Tage, 72 % statt 83 % im 80 %-Bereich). Er liegt nur lokal auf dem Branch `modell-1.9-entwurf`.

## Zweite Ergänzung zu Modell 1.8 (02.11.2026, gleiche Versionsnummer)

Geändert wurden nur die Jahreswerte, die Flüge der nächsten Monate rechnen unverändert. Die Änderung zeigt sich im Log am `fingerprint`.

**Doppelzählung behoben:** Das Szenario „Wie Falcon 9“ wächst um 37 % pro Jahr, den Wert von Falcon 9 zwischen 2015 und 2025. Darin stecken die Pausen nach Zwischenfällen schon, deshalb zieht das Szenario sie nicht noch einmal ab. Es ist damit in beiden Ansichten (mit und ohne schwere Zwischenfälle) gleich. Es ergibt für 2032 nun rund 34 statt 24 Flüge, Falcon 9 hatte an der vergleichbaren Stelle (2020 und 2021) 25 und 31, also liegt es jetzt etwas darüber.

**Gewichte:** Falcon 20 % statt 35 %, Flotte 43 % statt 35 %, SpaceX-Ziel 37 % statt 30 %. Der Rest wurde im alten Verhältnis verteilt. Das Szenario passt für die nächsten Jahre gut, danach ist es eher der Fall „die Technik bremst länger als gedacht“: Falcon 9 hing lange an externen Kunden, Starship hat mit Starlink und Artemis eigenen Bedarf. Die 20 % sind eine Einschätzung ohne Daten, wie zuvor die 35 %.

## Zur Wiedervorlage

**Nach den nächsten zwei Starts (Flug 15 und 16, voraussichtlich Februar oder März 2027) prüfen:**

1. **NET-Faktoren 8-fach und 30-fach:** Sie sind nicht aktiv. Prüfen, ob sie den nächsten Flug kurz vor dem Start verbessern (ab 7 und ab 3 Tagen vor dem NET, Code im Entwurf 1.9). Vergleichswerte der Historie: am Tag vor dem NET rund 32 % genau auf dem NET-Tag, 60 % bis 2 Tage danach; Modell 1.8 rechnet für den 11.11.2026 bei unveränderten Daten nur mit 13 bis 14 % und rund 41 %.
2. **Entwurf 1.9 insgesamt:** Hat sich beim nächsten Flug die Rechnung in Tagen mit bereinigten Vergleichswerten bewährt? Sie war im Test 30 Tage vorher mit 38 % im 80 %-Bereich zu schmal.
3. **Hauptzahl:** Lag die Mitte oder der wahrscheinlichste Tag näher am echten Start? Die Tabelle „Bewertung der echten Prognosen“ zeigt beide Fehler.
4. **Scrubs:** Sie sind bewusst nicht im Modell, weil sie vermutlich seltener werden. Gibt es bei Flug 15 oder 16 noch Scrubs, kommen eine Wahrscheinlichkeit für einen Scrub und eine für eine Reparaturpause dazu.
5. **Spätere Flüge:** Traf der Takt? Der Static-Fire-Takt für V3 beruht bisher auf nur zwei Abständen (51 und 67 Tage). Prüfen, ob das Ship als Taktgeber stimmt und ob die schmaleren Bereiche halten.
6. **Startplatz-Abstand von 10 Tagen:** Er ist eine Einschätzung ohne Daten. Bisher gibt es nur Flugabstände je Pad (Pad 1 mindestens 37 Tage, Pad 2 bisher 63 und 66), keine Dauer der Pad-Arbeiten. Er gilt auch im Flottenmodell.
7. **LC-39A:** Die 60 % Wahrscheinlichkeit, der Plan vom 31.12.2026 und der Faktor 1,45 sind Annahmen. Sobald Flug 16 der nächste Flug ist, rechnet er mit dem alten Weg und im Median 30 Tagen Zuschlag ohne Beleg; diesen Bruch prüfen.
8. **Lizenz:** Spätere Flüge rechnen ohne Wartezeit, der nächste Flug noch mit (bei neuem Profil 25 % mit im Median 14 Tagen). Vereinheitlichen, wenn sich zeigt, dass ein NET die Lizenz schon einpreist.
9. **Quellen:** TFRs, FAA-Betriebsplan, SpaceX-Termin und Strand- und Straßensperrungen kommen seit dem 11.11.2026 direkt aus Primärquellen (siehe oben); Notices to Mariners nur aus der NextSpaceflight-Checkliste, das NET aus Wikipedia und Launch Library. Die Prognose nutzt Sperrungen noch nicht als Signal. Mit `data/log/closures.jsonl` prüfen, wie zuverlässig eine Start-TFR den Starttag anzeigt, und dann entscheiden, ob sie in die Prognose eingeht.

**Nach Flug 17 die Prognose prüfen und eventuell feinjustieren** (Stand der Vereinbarung: 31.10.2026, Modell 1.2).
Zu prüfen: Trefferquote im Log, Fehler nach Vorlauf, Halbwertszeit der Gewichte, Anteil des Flugabstands beim nächsten Flug,
im Flotten-Szenario Fertigungswachstum gegen den gemessenen Takt, Wartungszeiten gegen echte Wiederholungsflüge und die Termine der Startplätze.
Außerdem die festen 30, 45 oder 60 Tage für wiederverwendete Fahrzeuge bei den nahen Flügen (`src/model.py`, Funktion `sample_flight`), die im Test bis rund 150 Tage breiten Bereiche beim nächsten Flug bei viel Vorlauf und das Gewicht des NET. Die Seite zeigt ab Flug 17 einen Hinweis.

## Quellen

NextSpaceflight (Testereignisse, Checkliste), Launch Library 2 (Startliste, Artemis), Wikipedia (Zieldaten, Fahrzeuglisten),
SpaceX (spacex.com), FAA (Mitteilungen, TFR-Liste, Betriebsplan), Stadt Starbase (Strand und Highway 4), NASASpaceflight (nur Überschriften) sowie von Hand zusammengetragene Berichte. Abrufe erfolgen selten und anonym.
Privates Projekt, nicht mit SpaceX verbunden.

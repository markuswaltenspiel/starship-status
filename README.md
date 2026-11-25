# Starship-Prognose

Auswertung des Starship-Programms und Prognose der nächsten Starts. Läuft ohne KI und ohne eigenen Server.

**Ansicht:** https://markuswaltenspiel.github.io/starship-status/

## So läuft es

GitHub Actions startet stündlich `src/run.py` (GitHub verschiebt oder überspringt geplante Läufe gelegentlich). Das Programm holt die Daten, rechnet die Prognose,
ergänzt das Log und veröffentlicht die Seite. Fällt eine Quelle aus, nutzt es den letzten Stand und zeigt eine Warnung.
Das Veröffentlichen läuft als eigener Job `deploy` mit einem zweiten Versuch nach einer Minute: Im selben Job fand `deploy-pages` das eben hochgeladene Artefakt gelegentlich noch nicht (November 2026, vier Fehlschläge in einer Woche).
Fehlgeschlagene Läufe meldet der Workflow `wochenbericht.yml` montags um 06:30 UTC gesammelt als Issue, nur wenn es in den 7 Tagen davor welche gab.
Checkliste, TFRs, FAA-Betriebsplan, SpaceX-Termin, Starbase-Sperrungen, Launch Library und Feed kommen bei jedem Lauf; die NextSpaceflight-Fahrzeugseiten alle 3 Stunden,
die Wikipedia-Zieldaten alle 2, Wikipedia-Fahrzeuglisten und FAA-Mitteilungen alle 6, Artemis alle 12 Stunden (Zeitstempel in `data/cache/fetched.json`).

**Sperrungen aus Primärquellen:** Luftraumsperrungen kommen aus der TFR-Liste der FAA (`tfr.faa.gov`, Detailmeldung als XML),
Strand- und Highway-4-Sperrungen von der Stadt Starbase (`starbase.texas.gov/beach-road-access`, seit 2025 zuständig statt Cameron County).
Einordnung: TFR nach 14 CFR 91.143 (Raumfahrtbetrieb, bis unbegrenzte Höhe) = Start oder Rückkehr des Ship; welches von beiden, steht im Betriebsplan der FAA-Verkehrszentrale (`fly.faa.gov/adv/adv_spt`, Abschnitt „PLANNED LAUNCH/REENTRY“ mit Haupt- und Ausweichfenster je Flug); TFR nach 91.137(a)(1) „High Energy Testing“ mit 3,5 NM Radius = Bodentests (Static Fire, Cryo, WDR), meist über Wochen ohne einzelne Testtage.
Eine Strandsperrung, die sich mit einer 91.143-TFR überschneidet, gilt als Start, ohne solche TFR ab 3 Tagen vorher als Bodentest, davor als offen.
Eine „Road Delay“ der Stadt ist eine kurze Behinderung, in der Regel ein Transport zwischen Werk und Startplatz.
Jede neue TFR und jedes neue Sperrfenster landet in `data/log/closures.jsonl`, weil die Quellen nur aktuelle Einträge zeigen; Änderungen am Betriebsplan in `data/log/ops_plan.jsonl`.

**Erkennung geflogener Flüge:** Flüge 1 bis 14 stehen von Hand in `data/manual/flights.json` (aus der Wikipedia-Liste der Starship-Starts, Tage in UTC). Neue Flüge erkennt das Programm selbst, in dieser Reihenfolge:
1. NextSpaceflight, Ereignis „Starship Flight N“ des Stacks mit Ergebnis (Erfolg, Teilerfolg, Fehlschlag). Das Ergebnis schließt die Landung ein, steht aber oft erst viele Stunden nach dem Start fest; bis dahin führt NextSpaceflight den Flug mit Status 10, den es auch für abgebrochene Startversuche nutzt.
2. Launch Library 2, bei jedem Lauf: Status „In Flight“, „Success“, „Partial Failure“ oder „Failure“ mit sekundengenauer Startzeit. „Success“ heißt dort nur, dass der Aufstieg gelang; die Seite zeigt das Ergebnis deshalb als vorläufig, bis NextSpaceflight es bestätigt. Jede Meldung landet in `data/log/launches.jsonl`, damit ein erkannter Flug bei einem Ausfall der Quelle nicht verschwindet.
3. NextSpaceflight mit Status 10, wenn die Checkliste schon einen späteren Flug zeigt (Ergebnis offen).

Anlass: Flug 15 startete am 13.11.2026 um 22:47 UTC, NextSpaceflight trug bis zum nächsten Tag kein Ergebnis ein, und das Programm hatte damals nur Weg 1. Die Prognose zeigte den Flug deshalb noch fast einen Tag lang als offen. Der einzige Log-Eintrag aus dieser Zeit (14.11.2026, Flug 15 am 20.11.) wurde auf Wunsch aus `data/log/forecasts.jsonl` entfernt, als einzige Ausnahme vom Grundsatz, das Log nur anzuhängen. Prognosen nach dem Starttag zählen in der Bewertung ohnehin nicht. Schneller als der Lauf selbst ist die Erkennung nicht; GitHub startet ihn oft nur alle 4 bis 7 Stunden.

**Termin von SpaceX:** Den Punkt „Confirmation from SpaceX“ hakt NextSpaceflight ab, sobald SpaceX eine Startseite mit Datum veröffentlicht (Beleglink `spacex.com/launches/starship-flight-N`).
Das Programm liest dieselben Daten direkt aus dem CMS hinter spacex.com (`content.spacex.com/api/spacex-website/launches-page-tiles/upcoming`, Feld `override` mit Fensterbeginn und -ende in Ortszeit, dazu der Begleittext der Missionsseite)
und schreibt jede Änderung in `data/log/spacex_targets.jsonl`. Die Prognose nutzt den SpaceX-Termin, den Betriebsplan und die Sperrungen bisher nicht.
Nicht automatisch: Notices to Mariners (NGA blockiert automatische Abrufe, USCG nur als PDF) und NOTAMs außerhalb der TFR-Liste, etwa für den Wiedereintritt.

## So rechnet die Prognose

**Nächster Flug:** Aus dem Fahrzeugstand entsteht eine Glockenkurve für den Starttag: der letzte erreichte Schritt (WDR, sonst Static Fire, sonst früherer Testschritt oder Flugabstand) plus die früheren Abstände bis zum Start.
Sind beide Static Fires durch und ist das NET höchstens 21 Tage entfernt, wird sie mit einer zweiten Kurve aus NET plus früherem Verzug verrechnet; die schmalere zählt mehr, das NET doppelt. Termine vor dem NET werden auf den NET-Tag gesetzt, oben steht die Mitte der Kurve.

**Spätere Flüge:** Der letzte Test des Ships (Static Fire, sonst Cryo-Test) plus der frühere Abstand bis zum Start ergibt eine Kurve in Tagen. Ohne Test folgt das Ship dem Static-Fire-Takt seiner Baureihe, sonst dem Cryo-Takt, unabhängig von Startverzögerungen davor.
Termine vor dem NET und vor der Fertigstellung eines neuen Startplatzes rücken auf diesen Tag, ein früherer Flug blockiert nur denselben Startplatz, mindestens 10 Tage. Wechsel der Baureihe und Lizenzwartezeiten zählen hier nicht als normale Dauer.
Wartezeiten auf die FAA-Lizenz rechnet die Prognose nicht ein, auch nicht beim nächsten Flug; für den ersten Flug von LC-39A gibt es keinen Zuschlag.

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

## Modell 1.10 (16.11.2026)

Auf Wunsch von Markus entfernt, als Ausnahme von „bis Flug 16 keine Modelländerungen“. Anders als bei den Ergänzungen zu 1.8 ändern sich der nächste Flug und der Rückblick-Test, deshalb eine neue Versionsnummer. Sie heißt 1.10 und nicht 1.9, weil 1.9 der verworfene Entwurf auf dem Branch `modell-1.9-entwurf` ist.

**Keine Lizenz-Wartezeit mehr:** Der nächste Flug bekam bisher mit 5 % (neues Flugprofil 25 %) einen Zuschlag von im Median 7 (14) Tagen, solange die Checkliste keine Freigabe zeigte. Die Lizenz kam bei fast allen Flügen rechtzeitig, das Warten hat keine Relevanz.

**Kein Zuschlag für LC-39A:** Ist Flug 16 der nächste Flug, kamen mit 60 % im Median 30 Tage für den neuen Startplatz dazu, ohne Beleg. Der Startplatz sieht derzeit rechtzeitig fertig aus. Die 60 % für LC-39A statt Pad 2 bleiben; sie wirken beim nächsten Flug nicht mehr.

**Wirkung** (Stand 16.11.2026, gleiche Daten): Flug 16 Mitte vom 31.01.2027 auf den 10.01.2027, 80 %-Bereich 22.12.2026 bis 10.02.2027 statt 01.01. bis 22.03.2027. Die späteren Flüge rücken um wenige Tage nach vorn. Rückblick-Test: Fehler der Mitte über alles 8,1 statt 8,8 Tage, 84 % im 80 %-Bereich wie zuvor.

**Pausen nach Zwischenfällen neu (gleicher Änderungsdurchgang, noch 1.10):** Die Jahreswerte zogen bisher eine Pause aus der Liste 147, 26, 17, 178, 135 und 16 Tage. Die Liste war nicht begründet, 147 und 26 ließen sich keinem Ereignis zuordnen. Bei Flug 15 ergab das im Median 79 Tage Pause und im Mittel 16 Tage Verzug pro Flug. Falcon 9 stand seit 2024 nach Zwischenfällen nur 3 bis 15 Tage (Starlink 9-3, Starlink 8-6, Crew-9, Starlink 12-20, Starlink 17-32), Starship nach den Fehlschlägen von Flug 7 bis 9 grob 0 bis 40 Tage über dem normalen Abstand. Monate dauerte es nur 2015 und 2016 (CRS-7 177 Tage, AMOS-6 135 Tage) und nach Flug 1. Die Pause wird jetzt nach Schwere gelost (`stand_down` in `assumptions.json`, mit Belegen): 15 % 90 bis 180 Tage (Startplatz zerstört oder Umbau nötig), 55 % 7 bis 45 Tage (Fahrzeug verloren), 30 % 3 bis 10 Tage (Panne ohne Verlust), wie bisher mit steigender Flugzahl etwas kürzer. Das Risiko pro Flug bleibt bei der Starship-Bilanz (20 % bei Flug 14, Rückgang hoch −0,6), weil Starship deutlich schwieriger ist als Falcon 9.
Die Trennung „mit“ und „ohne schwere Zwischenfälle“ entfällt, es gibt nur noch eine Jahresprognose mit Pausen. Das Prognose-Log enthält deshalb ab dem 16.11.2026 kein Feld `years_no_incident` mehr.
**Wirkung** (Stand 16.11.2026): Flüge bis Ende 2030 im Median 112 statt 93, bis Ende 2032 292 statt 225 (ohne Zwischenfälle waren es 337). 2030 48 statt 35 Flüge, 2032 94 statt 70. Die nahen Flüge und der Rückblick-Test ändern sich nicht.
**Später prüfen:** ob das Risiko pro Flug schneller sinkt, wie bei Falcon 9 (im Test mit −1,0 statt −0,6 bis 2032 rund 15 % mehr Flüge), und ob mehrere Startplätze eine Pause verkürzen, wenn nur einer beschädigt ist.

## Zur Wiedervorlage

**Nach den nächsten zwei Starts (Flug 15 und 16, voraussichtlich Februar oder März 2027) prüfen:**

1. **NET-Faktoren 8-fach und 30-fach:** Sie sind nicht aktiv. Prüfen, ob sie den nächsten Flug kurz vor dem Start verbessern (ab 7 und ab 3 Tagen vor dem NET, Code im Entwurf 1.9). Vergleichswerte der Historie: am Tag vor dem NET rund 32 % genau auf dem NET-Tag, 60 % bis 2 Tage danach; Modell 1.8 rechnet für den 11.11.2026 bei unveränderten Daten nur mit 13 bis 14 % und rund 41 %.
2. **Entwurf 1.9 insgesamt:** Hat sich beim nächsten Flug die Rechnung in Tagen mit bereinigten Vergleichswerten bewährt? Sie war im Test 30 Tage vorher mit 38 % im 80 %-Bereich zu schmal.
3. **Hauptzahl:** Lag die Mitte oder der wahrscheinlichste Tag näher am echten Start? Die Tabelle „Bewertung der echten Prognosen“ zeigt beide Fehler.
4. **Scrubs:** Sie sind bewusst nicht im Modell, weil sie vermutlich seltener werden. Gibt es bei Flug 15 oder 16 noch Scrubs, kommen eine Wahrscheinlichkeit für einen Scrub und eine für eine Reparaturpause dazu.
5. **Spätere Flüge:** Traf der Takt? Der Static-Fire-Takt für V3 beruht bisher auf nur zwei Abständen (51 und 67 Tage). Prüfen, ob das Ship als Taktgeber stimmt und ob die schmaleren Bereiche halten.
6. **Startplatz-Abstand von 10 Tagen:** Er ist eine Einschätzung ohne Daten. Bisher gibt es nur Flugabstände je Pad (Pad 1 mindestens 37 Tage, Pad 2 bisher 63 und 66), keine Dauer der Pad-Arbeiten. Er gilt auch im Flottenmodell.
7. **LC-39A:** Die 60 % Wahrscheinlichkeit, der Plan vom 31.12.2026 und der Faktor 1,45 sind Annahmen. Der Zuschlag von im Median 30 Tagen beim nächsten Flug ist seit dem 16.11.2026 entfernt; prüfen, ob LC-39A wirklich rechtzeitig fertig war.
8. **Lizenz:** Seit dem 16.11.2026 rechnen alle Flüge ohne Wartezeit. Prüfen, ob eine fehlende Lizenz einen Start doch verzögert hat.
9. **Quellen:** TFRs, FAA-Betriebsplan, SpaceX-Termin und Strand- und Straßensperrungen kommen seit dem 11.11.2026 direkt aus Primärquellen (siehe oben); Notices to Mariners nur aus der NextSpaceflight-Checkliste, das NET aus Wikipedia und Launch Library. Die Prognose nutzt Sperrungen noch nicht als Signal. Mit `data/log/closures.jsonl` prüfen, wie zuverlässig eine Start-TFR den Starttag anzeigt, und dann entscheiden, ob sie in die Prognose eingeht.

**Nach dem nächsten Start (Flug 16) außerdem prüfen** (vereinbart am 15.11.2026): Gibt es eine neue Tendenz beim Abstand vom letzten Static Fire bis zum Flug, und sollte die Vorhersage deshalb korrigiert werden? Wird die Zeit zwischen Cryo-Test und Flug wirklich kürzer? Bis dahin keine weiteren Änderungen am Modell.

**Nach Flug 17 die Prognose prüfen und eventuell feinjustieren** (Stand der Vereinbarung: 31.10.2026, Modell 1.2).
Zu prüfen: Trefferquote im Log, Fehler nach Vorlauf, Halbwertszeit der Gewichte, Anteil des Flugabstands beim nächsten Flug,
im Flotten-Szenario Fertigungswachstum gegen den gemessenen Takt, Wartungszeiten gegen echte Wiederholungsflüge und die Termine der Startplätze.
Außerdem die festen 30, 45 oder 60 Tage für wiederverwendete Fahrzeuge bei den nahen Flügen (`src/model.py`, Funktion `sample_flight`), die im Test bis rund 150 Tage breiten Bereiche beim nächsten Flug bei viel Vorlauf und das Gewicht des NET. Die Seite zeigt ab Flug 17 einen Hinweis.

## Quellen

NextSpaceflight (Testereignisse, Checkliste, Flugergebnis), Launch Library 2 (Startliste, gestartete Flüge, Artemis), Wikipedia (Zieldaten, Fahrzeuglisten),
SpaceX (spacex.com), FAA (Mitteilungen, TFR-Liste, Betriebsplan), Stadt Starbase (Strand und Highway 4), NASASpaceflight (nur Überschriften) sowie von Hand zusammengetragene Berichte. Abrufe erfolgen selten und anonym.
Privates Projekt, nicht mit SpaceX verbunden.

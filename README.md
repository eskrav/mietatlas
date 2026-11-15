# Nettokaltmieten nach Kreisen (Zensus 2022)

Interaktive Karte der durchschnittlichen Nettokaltmiete je Quadratmeter für alle 400 Kreise und kreisfreien Städte, mit automatisierter Datenpipeline und Qualitätsprüfungen.

**Karte:** https://eskrav.github.io/mietatlas/

Ein kleiner Prototyp, entstanden als Arbeitsprobe: ein Indikator, eine räumliche Ebene, aber mit den Bausteinen, die ein größerer Datenatlas braucht.

## Daten

| Quelle | Inhalt | Stand | Lizenz |
|---|---|---|---|
| Zensus 2022, Tabelle 4000W-0004 | Durchschnittliche Nettokaltmiete (€/m²) je Kreis | Stichtag 15.05.2022 | dl-de/by-2-0, © Statistische Ämter des Bundes und der Länder |
| BKG, Verwaltungsgebiete 1:250 000 (VG250), Ebene Kreise | Kreisgrenzen | 31.12.2022 | dl-de/by-2-0, © BKG (2022) |

Wichtig für die Interpretation: Es handelt sich um **Bestandsmieten** aller vermieteten Wohnungen zum Zensusstichtag, nicht um aktuelle Angebotsmieten.

## Pipeline

`pipeline.py` lädt beide Quellen, prüft sie, verknüpft sie über den Amtlichen Gemeindeschlüssel (AGS) und schreibt die Daten für die Karte nach `docs/data/`. Jede Prüfung bricht den Build mit einer klaren Fehlermeldung ab:

- genau 400 Kreise, eindeutige 5-stellige AGS (als Text, damit führende Nullen erhalten bleiben)
- nur bekannte Qualitätskennzeichen, Werte in einem plausiblen Bereich
- nur Landflächen aus VG250 (GF = 4), keine Wasserflächen
- vollständiger Abgleich in beiden Richtungen: kein Kreis ohne Geometrie, keine Geometrie ohne Wert

Die Grenzen werden mit Coverage-Simplification vereinfacht, damit benachbarte Kreise exakt gemeinsame Grenzen behalten (keine Lücken oder Überlappungen).

Bei jedem Push führt ein GitHub-Actions-Workflow die Pipeline samt Prüfungen aus und veröffentlicht die Karte nur, wenn alle Prüfungen bestehen.

## Entscheidungen

- **Farbklassen: gleiche Intervalle über einen gekappten Wertebereich.** Der Bereich vom 2. bis zum 98. Perzentil wird in vier gleich breite Stufen geteilt; dazu kommen zwei offene Randstufen für die niedrigsten und höchsten Werte. Reine gleiche Intervalle über den gesamten Bereich hätten sich nach dem Extremwert München (12,89 €) gerichtet, sodass die beiden obersten Stufen nur 9 Kreise enthalten hätten. Quantile hätten Unterschiede von wenigen Cent in der breiten Mitte betont und alle teuren Regionen zusammengefasst; eine logarithmische Skala lohnt sich erst bei Werten über mehrere Größenordnungen. Das Verfahren ist datengetrieben und lässt sich ohne Anpassung auf andere Indikatoren übertragen (Parameter in `pipeline.py`: Anzahl der Stufen, Perzentile).
- **Kein Länderdurchschnitt aus Kreiswerten:** Ein einfacher Mittelwert der Kreiswerte wäre falsch, weil die Kreise sehr unterschiedlich viele Mietwohnungen haben. Der Bundesdurchschnitt (7,28 €/m²) stammt deshalb direkt aus derselben Zensus-Tabelle auf Deutschland-Ebene; er ist der Durchschnitt über alle vermieteten Wohnungen. Deshalb liegen rund drei Viertel der Kreise (297 von 400) unter dem Bundesdurchschnitt: Er wird von den Städten mit vielen und teureren Mietwohnungen geprägt.

## Erweiterung auf weitere Ebenen

Der AGS ist hierarchisch: Stellen 1–2 bezeichnen das Land, 1–5 den Kreis, 1–8 die Gemeinde. Dasselbe Datenmodell trägt daher von Bund und Ländern bis zu den Gemeinden; aggregiert wird über Präfixe, gewichtet oder mit amtlichen Werten der jeweiligen Ebene. Für einen Vollausbau würde ich:

- die Daten in PostgreSQL/PostGIS ablegen, mit einer Tabelle je räumlicher Ebene und gemeinsamen Indikator-Tabellen
- Gebietsstandsänderungen (Kreis- und Gemeindereformen) explizit versionieren
- die Quellen per API abrufen (Zensus-Datenbank, Regionalstatistik) statt per manuellem Export
- für Gemeinden Vektor-Tiles statt einer einzelnen GeoJSON-Datei verwenden

## Datenschutz

Die Karte lädt keine Inhalte von Drittanbietern: Schriftart (Fira Sans, SIL Open Font License) und Kartenbibliothek (MapLibre GL JS, BSD-3-Clause) liegen unter `docs/vendor/`, Lizenztexte jeweils dabei. Es gibt keine Cookies und kein Tracking; Impressum und Datenschutzhinweis unter `docs/impressum.html`. Die Seiten sind mit `noindex` für Suchmaschinen gekennzeichnet.

## Lokal ausführen

```bash
pip install -r requirements.txt
python pipeline.py
cd docs && python -m http.server   # dann http://localhost:8000
```

## Entstehung

<!-- Bitte an die tatsächliche Arbeitsweise anpassen -->
Mit Unterstützung von KI (Claude) entwickelt. Datenauswahl, Prüflogik und Ergebnisse habe ich geprüft und verifiziert.

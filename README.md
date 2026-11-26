# Nettokaltmieten nach Kreisen (Zensus 2022)

Interaktive Karte der durchschnittlichen Nettokaltmiete je Quadratmeter für alle 400 Kreise und kreisfreien Städte, mit automatisierter Datenpipeline, Qualitätsprüfungen und einem vereinfachten Beispielmodell zur Kappungsgrenze, dessen Szenarien sich auf der Karte umschalten lassen.

**Karte:** https://eskrav.github.io/mietatlas/

Ein kleiner Prototyp, entstanden als Arbeitsprobe: ein Indikator, eine räumliche Ebene, aber mit den Bausteinen, die ein größerer Datenatlas braucht.

## Daten

| Quelle | Inhalt | Stand | Lizenz |
|---|---|---|---|
| [Zensus 2022](https://ergebnisse.zensus2022.de), Tabelle 4000W-0004 | Durchschnittliche Nettokaltmiete (€/m²) je Kreis | Stichtag 15.05.2022 | [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0), © Statistische Ämter des Bundes und der Länder, Deutschland, 2026 |
| [BKG](https://www.bkg.bund.de), Verwaltungsgebiete 1:250 000 (VG250), Ebene Kreise | Kreisgrenzen | 31.12.2022 | [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0), © BKG (2026), [Datenquellen](https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_vg_nuts.pdf); Daten verändert (Grenzen vereinfacht und umprojiziert) |

Die Rohdaten liegen unverändert unter `data/raw/`. Die Zensus-Tabelle ruft `fetch_zensus.py` über die Schnittstelle (API) der Zensusdatenbank ab, die Kreisgrenzen lädt `fetch_vg250.py` vom Downloadserver des BKG.

Wichtig für die Interpretation: Es handelt sich um **Bestandsmieten** aller vermieteten Wohnungen zum Zensusstichtag, nicht um aktuelle Angebotsmieten.

## Pipeline

`fetch_zensus.py` ruft Tabelle 4000W-0004 auf Kreisebene ab, entpackt sie und ersetzt die Datei in `data/raw/` nur, wenn sie die Prüfungen in `zensus.py` besteht, die auch beim Laden in die Datenbank gelten; sonst bleibt die bisherige Datei unverändert.

`fetch_vg250.py` lädt das VG250-Archiv (Stand 31.12.2022) vom BKG, entnimmt nur die Kreisebene und ersetzt die Dateien in `data/raw/vg250/` ebenfalls erst, wenn sie die Prüfungen aus `pipeline.py` bestehen. Ein Konto ist dafür nicht nötig.

`load_db.py` lädt die geprüfte Zensus-Tabelle in eine PostgreSQL-Datenbank (siehe unten). `pipeline.py` liest die Mietwerte aus der Datenbank und die Kreisgrenzen aus `data/raw/vg250/`, prüft beide, verknüpft sie über den Amtlichen Gemeindeschlüssel (AGS) und schreibt die Daten für die Karte nach `docs/data/`. `run_model.py` berechnet das Beispielmodell (siehe unten); `pipeline.py` exportiert dessen veröffentlichte Szenarien zusätzlich nach `docs/data/szenarien.json`. Jede Prüfung bricht den Build mit einer klaren Fehlermeldung ab:

- genau 400 Kreise, eindeutige 5-stellige AGS in beiden Quellen (als Text, damit führende Nullen erhalten bleiben)
- nur bekannte Qualitätskennzeichen, Werte in einem plausiblen Bereich
- nur Landflächen aus VG250 (GF = 4), keine Wasserflächen
- vollständiger Abgleich in beiden Richtungen: kein Kreis ohne Geometrie, keine Geometrie ohne Wert

Der Code ist nach Aufgaben getrennt: `zensus.py` (Zensus-Tabelle lesen und prüfen), `db.py` (Lesen aus der Datenbank), `checks.py` (gemeinsame Fehlerklasse für Datenprüfungen) und `pipeline.py` (Geometrien, Karte, Export). Abruf, Laden und Modelllauf kommen dadurch ohne die Geo-Bibliotheken aus.

Die Grenzen werden mit Coverage-Simplification vereinfacht, damit benachbarte Kreise exakt gemeinsame Grenzen behalten (keine Lücken oder Überlappungen).

Bei jedem Push auf `main` startet ein GitHub-Actions-Workflow eine temporäre PostgreSQL-Datenbank, lädt die eingecheckten Rohdaten hinein, berechnet das Beispielmodell, führt die Pipeline samt Prüfungen aus und veröffentlicht die Karte nur, wenn alle Prüfungen bestehen. Die Datenbank existiert nur während des Laufs.

## Datenbank

`load_db.py` schreibt die geprüften Werte in eine PostgreSQL-Datenbank (Schema in `db/schema.sql`), aus der `pipeline.py` die Karte erzeugt:

- `regions`: eine gemeinsame Tabelle für Bund, Länder und Kreise, hierarchisch über `parent_id` verknüpft
- `observations`: eine lange Tabelle mit Wert, Status und Quelle je Gebiet, Indikator und Jahr; weitere Indikatoren oder Jahre kommen als neue Zeilen hinzu, nicht als neue Spalten oder Tabellen
- `indicators` und `sources`: Beschreibung, Einheit, Herkunft und Lizenz

Der Ladevorgang läuft in einer einzigen Transaktion und ersetzt die Werte der jeweiligen Quelle vollständig; er lässt sich also beliebig oft wiederholen. Die Rohdaten unter `data/raw/` bleiben dabei unverändert; aus ihnen lässt sich die Datenbank jederzeit neu aufbauen.

`db/queries.sql` enthält Beispielabfragen auf den geladenen Daten: der teuerste Kreis je Land mit seinem Abstand zum Bundeswert, die Spannweite der Mieten innerhalb der Länder und der Anteil der Kreise unter dem Bundeswert (297 von 400, weil der Bundeswert von den großen, teuren Städten geprägt ist). Dazu kommen Prüfabfragen, etwa auf Kreise ohne Wert oder eine falsche Zuordnung zum Land:

```bash
psql -d mietatlas -f db/queries.sql
```

### Wirkungsmodell (Struktur)

`db/model_schema.sql` legt fest, wie sich ein Wirkungsmodell („Maßnahme X → Effekt Y“) in derselben Datenbank ablegen lässt:

- `parameters`: jede Modellannahme mit Basiswert, Einheit, Art (politischer Hebel, Definition, empirischer Zusammenhang oder Annahme), Quelle und dem Wertebereich, für den das Modell geprüft ist
- `scenarios` und `scenario_overrides`: Szenarien speichern nur die Parameterwerte, die sie gegenüber der Basis ändern
- `model_runs` und `run_parameters`: jeder Modelllauf mit Modellversion, Datenstand und einer Kopie der verwendeten Parameterwerte
- `results`: die Ergebnisse je Lauf, Gebiet und Haushaltstyp; die Sicht `published_results` liefert nur den jeweils neuesten Lauf veröffentlichter Szenarien

So lässt sich jede veröffentlichte Zahl auf Lauf, Modellversion und Parameterwerte zurückführen, auch wenn sich Annahmen später ändern. Das Schema baut auf den Tabellen aus `db/schema.sql` auf:

```bash
python load_db.py
psql -d mietatlas -f db/model_schema.sql
```

### Beispiel: Kappungsgrenze

> **Ein stark vereinfachtes Demonstrationsmodell, kein realistisches Szenario.** Es soll nur zeigen, wie ein Wirkungsmodell in der Datenbank abgelegt, berechnet und nachvollziehbar veröffentlicht werden kann. Die Annahmen sind gesetzt, nicht geschätzt, und die Szenarien sind frei gewählt. Die Zahlen sagen nichts darüber aus, wie sich Mieten tatsächlich entwickeln oder wie eine Änderung der Kappungsgrenze wirken würde; dafür bräuchte es unter anderem Daten dazu, wie weit einzelne Mietverhältnisse unter der Vergleichsmiete liegen.

`db/model_kappung.sql` füllt diese Tabellen mit einem einfachen Modell zur [Kappungsgrenze](https://www.gesetze-im-internet.de/bgb/__558.html) für Mieterhöhungen in bestehenden Mietverhältnissen (§ 558 Abs. 3 BGB): Nach geltendem Recht darf die Miete bei Erhöhungen bis zur ortsüblichen Vergleichsmiete in drei Jahren um höchstens 20 % steigen (Erhöhungen wegen Modernisierung oder Betriebskosten zählen nicht mit). In Gemeinden oder Gemeindeteilen, die das jeweilige Land per Rechtsverordnung als angespannten Wohnungsmarkt bestimmt hat, sind es höchstens 15 %. Die Kappungsgrenze wirkt deshalb vor allem bei Mietverhältnissen, deren Miete deutlich unter der Vergleichsmiete liegt, etwa bei langen Mietverhältnissen ohne Erhöhung. Das Modell betrachtet je Kreis ein Beispiel-Mietverhältnis, das 2022 die Durchschnittsmiete des Kreises zahlt und um einen festen Abstand unter der Vergleichsmiete liegt, und rechnet dessen höchstmögliche Miete:

> Miete nach drei Jahren = Ausgangsmiete (Zensus 2022) × min(1 + Abstand zur Vergleichsmiete, 1 + Kappungsgrenze)

Zum Vergleich berechnet jeder Lauf auch die Miete bei durchschnittlicher Mietentwicklung, mit dem Anstieg der Nettokaltmieten im [Verbraucherpreisindex](https://www.destatis.de/DE/Presse/Pressemitteilungen/2025/01/PD25_020_611.html) (2,1 % im Jahr 2024). Bei diesem Tempo greift die Kappungsgrenze nicht; dieser Wert ist daher in allen Szenarien gleich, was eine eigene Prüfabfrage sicherstellt. Das ist auch inhaltlich die wichtigste Einschränkung: Änderungen der Kappungsgrenze dürften vor allem auf Mietverhältnisse mit großem Nachholbedarf wirken, kaum auf die Durchschnittsmiete.

Eingang sind die echten Kreiswerte aus `observations`; berechnet wird in der Datenbank, je Modelllauf aus den dort gespeicherten Parameterwerten. Neben dem geltenden Recht gibt es zwei frei gewählte Beispielszenarien, die zeigen, dass dieselbe Änderung je nach Ausgestaltung ganz andere Kreise trifft:

| Szenario | angespannte Märkte | übrige Kreise | betroffene Kreise |
|---|---|---|---|
| Geltendes Recht | 15 % | 20 % | – |
| Kappungsgrenze 10 % in angespannten Märkten | 10 % | 20 % | 103 |
| Kappungsgrenze 15 % überall | 15 % | 15 % | 297 |

Annahmen, als Parameter mit Art `assumption` gespeichert und damit änderbar und nachvollziehbar:

- **Abstand zur Vergleichsmiete** 20 %: wie weit die Miete des Beispiel-Mietverhältnisses 2022 unter der ortsüblichen Vergleichsmiete liegt
- **Angespannter Markt**: ein Kreis gilt als angespannt, wenn seine Miete mindestens dem Bundeswert entspricht (103 von 400 Kreisen). Das ist eine Näherung; tatsächlich bestimmen die Länder per Rechtsverordnung einzelne Gemeinden oder Gemeindeteile, nicht ganze Kreise nach ihrem Mietniveau; „geltendes Recht“ im Modell entspricht deshalb nicht überall der tatsächlichen Verordnungslage
- **Musterwohnung** 70 m²: für die Umrechnung in Euro pro Monat. Das Schema unterstützt Haushaltstypen, weil Wirkungsmodelle sie oft brauchen (etwa Energiekosten nach Haushaltstyp); hier hängt die Wirkung je m² aber nicht vom Haushalt ab, deshalb gibt es nur einen Musterhaushalt

Das Hauptergebnis ist eine **Obergrenze für ein Beispiel-Mietverhältnis, keine Prognose**: Es zeigt, wie viel die Miete höchstens steigen darf, nicht, wie viel sie tatsächlich steigt. Ein früherer Lauf mit 15 % Abstand zur Vergleichsmiete zeigt, wie geänderte Annahmen nachvollziehbar bleiben; ein unveröffentlichter Entwurf mit engerer Abgrenzung angespannter Märkte zeigt, dass nur freigegebene Szenarien in `published_results` erscheinen.

`run_model.py` legt die Modelltabellen an und berechnet das Modell. `pipeline.py` schreibt anschließend die veröffentlichten Szenarien nach `docs/data/szenarien.json`: je Kreis und Szenario die höchstmögliche Miete je m² und pro Monat sowie die Monatsmiete bei durchschnittlicher Entwicklung, dazu je Szenario Modellversion, Datenstand und die verwendeten Parameterwerte. Fehlt für einen Kreis der Karte ein Szenariowert, bricht der Build ab.

```bash
python run_model.py
psql -d mietatlas -f db/model_queries.sql
```

## Tests

`tests/` enthält Tests für den Parser (an kleinen Beispieltabellen im Format der Zensus-API), für die Prüfungen, die Farbklassen, die Datenbank, die Modelltabellen, den Export der Szenarien und die Abfragen in `db/queries.sql` und `db/model_queries.sql`: Wiederholtes Laden ergibt denselben Stand, ein fehlgeschlagener Ladevorgang ändert nichts, und die Datenbank liefert genau die Werte der Rohdatei. Die Datenbanktests laufen gegen eine eigene Testdatenbank und werden übersprungen, wenn keine erreichbar ist. Im GitHub-Workflow laufen alle Tests vor jedem Build.

```bash
createdb mietatlas_test   # einmalig, für die Datenbanktests
pytest
```

## Datenschutz

Die Karte lädt keine Inhalte von Drittanbietern: Schriftart (Fira Sans, SIL Open Font License) und Kartenbibliothek (MapLibre GL JS, BSD-3-Clause) liegen unter `docs/vendor/`, Lizenztexte jeweils dabei. Es gibt keine Cookies und kein Tracking; Impressum und Datenschutzhinweis unter `docs/impressum.html`. Die Seiten sind mit `noindex` für Suchmaschinen gekennzeichnet.

## Lokal ausführen

```bash
pip install -r requirements.txt
python fetch_zensus.py              # optional: Zensus-Tabelle neu abrufen (siehe unten)
python fetch_vg250.py               # optional: Kreisgrenzen neu abrufen
python load_db.py                   # Rohdaten in PostgreSQL laden (siehe unten)
python run_model.py                 # Beispielmodell berechnen
python pipeline.py
cd docs && python -m http.server   # dann http://localhost:8000
```

Für `fetch_zensus.py` braucht es ein kostenloses Konto bei der [Zensusdatenbank](https://ergebnisse.zensus2022.de/datenbank/online/). Das API-Token steht nach dem Anmelden unter „Webservice (API)“ und wird als Umgebungsvariable übergeben:

```bash
export ZENSUS_API_TOKEN=...
python fetch_zensus.py
```

Für `load_db.py`, `run_model.py` und `pipeline.py` braucht es eine laufende PostgreSQL-Datenbank (getestet mit Version 16). Die Verbindung kommt aus der Umgebungsvariable `DATABASE_URL`; ohne sie wird `postgresql:///mietatlas` verwendet. Einmalig anlegen:

```bash
createdb mietatlas
```

## Entstehung

Den Code habe ich mit Unterstützung von Claude Code geschrieben; die Entscheidungen zu Datenquellen, Prüfungen und Darstellung habe ich selbst getroffen und die Ergebnisse überprüft.

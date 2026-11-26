# Nettokaltmieten nach Kreisen (Zensus 2022)

Interaktive Karte der durchschnittlichen Nettokaltmiete je Quadratmeter für alle 400 Kreise und kreisfreien Städte, mit automatisierter Datenpipeline und Qualitätsprüfungen.

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

`fetch_zensus.py` ruft Tabelle 4000W-0004 auf Kreisebene ab, entpackt sie und ersetzt die Datei in `data/raw/` nur, wenn sie dieselben Prüfungen wie `pipeline.py` besteht; sonst bleibt die bisherige Datei unverändert.

`fetch_vg250.py` lädt das VG250-Archiv (Stand 31.12.2022) vom BKG, entnimmt nur die Kreisebene und ersetzt die Dateien in `data/raw/vg250/` ebenfalls erst, wenn sie die Prüfungen aus `pipeline.py` bestehen. Ein Konto ist dafür nicht nötig.

`pipeline.py` lädt beide Quellen, prüft sie, verknüpft sie über den Amtlichen Gemeindeschlüssel (AGS) und schreibt die Daten für die Karte nach `docs/data/`. Jede Prüfung bricht den Build mit einer klaren Fehlermeldung ab:

- genau 400 Kreise, eindeutige 5-stellige AGS in beiden Quellen (als Text, damit führende Nullen erhalten bleiben)
- nur bekannte Qualitätskennzeichen, Werte in einem plausiblen Bereich
- nur Landflächen aus VG250 (GF = 4), keine Wasserflächen
- vollständiger Abgleich in beiden Richtungen: kein Kreis ohne Geometrie, keine Geometrie ohne Wert

Die Grenzen werden mit Coverage-Simplification vereinfacht, damit benachbarte Kreise exakt gemeinsame Grenzen behalten (keine Lücken oder Überlappungen).

Bei jedem Push auf `main` führt ein GitHub-Actions-Workflow die Pipeline samt Prüfungen mit den eingecheckten Rohdaten aus und veröffentlicht die Karte nur, wenn alle Prüfungen bestehen.

## Datenschutz

Die Karte lädt keine Inhalte von Drittanbietern: Schriftart (Fira Sans, SIL Open Font License) und Kartenbibliothek (MapLibre GL JS, BSD-3-Clause) liegen unter `docs/vendor/`, Lizenztexte jeweils dabei. Es gibt keine Cookies und kein Tracking; Impressum und Datenschutzhinweis unter `docs/impressum.html`. Die Seiten sind mit `noindex` für Suchmaschinen gekennzeichnet.

## Lokal ausführen

```bash
pip install -r requirements.txt
python fetch_zensus.py              # optional: Zensus-Tabelle neu abrufen (siehe unten)
python fetch_vg250.py               # optional: Kreisgrenzen neu abrufen
python pipeline.py
cd docs && python -m http.server   # dann http://localhost:8000
```

Für `fetch_zensus.py` braucht es ein kostenloses Konto bei der [Zensusdatenbank](https://ergebnisse.zensus2022.de/datenbank/online/). Das API-Token steht nach dem Anmelden unter „Webservice (API)“ und wird als Umgebungsvariable übergeben:

```bash
export ZENSUS_API_TOKEN=...
python fetch_zensus.py
```

## Entstehung

Den Code habe ich mit Unterstützung von Claude Code geschrieben; die Entscheidungen zu Datenquellen, Prüfungen und Darstellung habe ich selbst getroffen und die Ergebnisse überprüft.

# alkis_toolbox

ArcGIS Pro Toolbox für die Verarbeitung von ALKIS-Daten

## Installation

1. Daten aus Github-Repository herunterladen und lokal speichern
2. Im ArcGIS Pro Katalog Rechtsklick auf 'Toolboxen'->'Toolbox hinzufügen'
3. zu heruntergeladenen Daten navigieren und die Datei 'ALKIS_WFS_DOWNLOAD.pyt' auswählen; dieses erscheint dann im ArcGIS Pro Katalog unter 'Toolboxen'
4. 'ALIKS_WFS_DOWNLOAD.pyt' aufklappen und 'wfs_download' mit Doppelklick öffnen

## Tools

### WFS Download

Dieses Tool lädt ALKIS-Daten des ALKIS-WFS des LGL BWs in einem definierten Bereich (Polygonlayer) als GeoJSON herunter und konvertiert diese in zweidimensionale Featureklassen in einer FGDB.

### Verschnitt Flurstück & Lagebezeichnung

Dieses Werkzeug ordnet Lagebezeichnungen (Hausnummern, Straßen, Gewanne) räumlich den Flurstücken zu und erstellt eine Verknüpfungstabelle (fsk_x_lage).

**Hintergrund:**
Die offizielle Zuordnungstabelle des LGL ist über den WFS nicht vollständig verfügbar. Dieses Tool berechnet die Zuordnungen daher räumlich neu.

**Ablauf:**

1. **Hausnummern zuordnen:** Lagebezeichnungspunkte werden ihren Gebäuden zugeordnet und dann mit den Flurstücken verschnitten. So erhalten Flurstücke ihre Hausnummern.

2. **Gewanne und Straßen zuordnen:** Für Flurstücke ohne Hausnummern werden Gewanne und Straßenpolygone verschnitten, um Gewann- oder Straßennamen zuzuweisen.

**Eingabedaten:**

- Flurstücke
- Gebäude
- Lagebezeichnungen (Punkte)
- Gewanne und Straßen (Polygone)

**Hinweis:**
Das Tool verwendet eigene räumliche Algorithmen, da einige Lagebezeichnungspunkte neben Gebäuden platziert sind. Dies kann zu einzelnen Abweichungen von der offiziellen Zuordnung in den NAS-Daten führen.

### Verschnitt Flurstück & Nutzung

Berechnet Schnittflächen (SFL) von den Flurstücken mit der tatsächlichen Nutzung.

### Verschnitt Flurstück & Bodenschätzung

Berechnet Schnittflächen (SFL) und Ertragsmesszahlen (EMZ) von den Flurstücken mit der Bodenschätzung und Bodenschätzungsbewertung.

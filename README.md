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

Verknüpft Lagebezeichnungen (Hausnummern, Straßen, Gewanne) mit Flurstücken und erstellt eine fsk_x_lage Tabelle.

Dieses Werkzeug berechnet räumlich Lagebezeichnungen zu jedem Flurstück. Hintergrund ist der, dass die bestehende Zuordnungstabelle beim LGL über den WFS nicht vollständig heruntergeladen kann und dadurch nicht einfach zum Verketten genutzt werden kann.
Dieses Werkzeug benötigt folgende Eingabequellen für die Berechnung:

- Flurstücke
- Gebäude
- Lagebezeichnungen (Punkte aus dem WFS-Dienst)
- Gewanne und Straßen (Polygone aus dem WFS-Dienst)

Zu Beginn werden die Lagebezeichnungspunkte räumlich ihren Gebäuden zugeordnet und anschließend mit den Flurstücken überschnitten, sodass alle Flurstücke mit einem Lagebezeichnungspunkt bereits eine Lagezuordnung haben. Die Zuordnung der Punkte zu ihren Gebäuden erfolgt über eine eigens berechnete uuid, weil die GML-ID des LGLs beim Verketten über arcpy nicht case-sensitive interpretiert wird und es dadurch zu falschen Verknüpfungen kommt. Zudem werden Lagebezeichnungen dann auf ihre Gebäudemittelpunkte gemappt, da einige Punkte neben den Gebäuden und dadurch auf anderen Flurstücken platziert sind.

Für die Flurstücke, die noch keine Lagebezeichnungen haben, werden anschließend die Gewanne und Straßenpolygone überschnitten, sodass sie Gewannnamen oder Straßennamen ohne Hausnummern erhalten.
Da durch diese eigenen Algorithmen versucht wird, die richtige Zuordnung herzustellen, kann es dementsprechend zu einzelnen Abweichungen im Vergleich zu der tatsächlichen Zuordnung aus den NAS-Daten kommen.

### Verschnitt Flurstück & Nutzung

Berechnet Schnittflächen (SFL) von den Flurstücken mit der tatsächlichen Nutzung.

### Verschnitt Flurstück & Bodenschätzung

Berechnet Schnittflächen (SFL) und Ertragsmesszahlen (EMZ) von den Flurstücken mit der Bodenschätzung und Bodenschätzungsbewertung.

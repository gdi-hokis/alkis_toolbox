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

**Eingabedaten:**
Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck)
- Gebäude (nora_v_al_gebaeude)
- Lagebezeichnungen (nora_v_al_lagebezeichnung) (Punkte)
- Gewanne und Straßen (nora_v_al_strasse_gewann)(Polygone)

**Ablauf:**

1. **Hausnummern zuordnen:** Lagebezeichnungspunkte werden ihren Gebäuden zugeordnet und dann mit den Flurstücken verschnitten. So erhalten Flurstücke ihre Hausnummern.

2. **Gewanne und Straßen zuordnen:** Für Flurstücke ohne Hausnummern werden Gewanne und Straßenpolygone verschnitten, um Gewann- oder Straßennamen zuzuweisen.

**Hinweis:**
Das Tool verwendet eigene räumliche Algorithmen, da einige Lagebezeichnungspunkte neben Gebäuden platziert sind. Dies kann zu einzelnen Abweichungen von der offiziellen Zuordnung in den NAS-Daten führen.

### Verschnitt Flurstück & Nutzung

Berechnet Schnittflächen (SFL) von den Flurstücken mit der tatsächlichen Nutzung und erstellt eine Verschnitt-Feature-Klasse fsk_x_nutzung.

**Eingabedaten:**
Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck)
- Tatsächliche Nutzung (nora_v_al_tatsaechliche_nutzung)

Weitere Voraussetzung ist die Installation des shapely-Moduls in der Python-Umgebung.
Hierfür wird empfohlen die Python-Umgebung zu klonen und über den Paketmanager in ArcGIS Pro zu arbeiten siehe https://pro.arcgis.com/de/pro-app/3.5/arcpy/get-started/add-a-package.htm

**Ablauf:**

1. Verschnitt Flurstücke und Nutzung
2. Filterung der Miniflächen und Verschmelzung dieser mit Nachbarflurstücken (mit shapely)
3. Berechnung der Schnittflächen und Deltakorrektur zur amtlichen Flurstücksfläche

**Hinweis:**
Die Ergebnisse wurden mit denen des LGLs verglichen und man kommt auf eine 99,5%-ige Übereinstimmung in den Stichproben. Die Unterschiede betragen +/- 1m² und lassen sich auf Rundungsungenauigkeiten zurückführen. Trotzdem kann es zu Unterschieden kommen, da der Algorithmus des LGLs nicht bekannt ist und somit Berechnungsunterschiede vorhanden sein werden.

### Verschnitt Flurstück & Bodenschätzung

Berechnet Schnittflächen (SFL) von den Flurstücken mit der Bodenschätzung und Bodenbewertung. Berechnet die EMZ der Bodenschätzungsflächen. Endergebnis ist eine Verschnitt-Feature-Klasse fsk_x_bodenschaetzung, in der sowohl Bodenschätzung als auch Bewertungsflächen enthalten sind (sonstige_angaben_id = 9999).

**Eingabedaten:**
Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck)
- Bodenschätzung (nora_v_al_bodenschaetzung)
- Bewertungsflächen (nora_v_al_bewertung)
- Nutzungsverschnitt (flst_x_nutzung - Ergebnis des Werkzeugs Verschnitt Flurstück & Nutzung)

Weitere Voraussetzung ist die Installation des shapely-Moduls in der Python-Umgebung.

**Ablauf:**

1. Verschnitt Flurstücke und Bodenschätzung - Dabei werden alle Nutzungsarten abgezogen, die keine Bodenschätzung haben, sowie alle Bewertungsflächen, die nicht zusätzliche Bodenschätzungsergebnisse vorweisen können

Relevante Nutzungsarten für Bodenschätzung: Landwirtschaft (43001), Heide (43004), Sumpf (43006), Unland (43007) , GFLF (41006 - 2700), BLW (41006 - 6800), BFW (41006 - 7600), Garten (41008 - 4460)

Bewertungen ohne Bodenschätzung - siehe VWVLK Anlage 1 (3100, 3105, 3200, 3411, 3480, 3481, 3482, 3490, 3510, 3520, 3530, 3600, 3610, 3611, 3612, 3613, 3614, 3615, 3616, 3710, 3999)

2. Verschnitt Flurstücke und Bewertungsflächen - Ebenfalls Abzug aller irrelevanten Nutzungsarten

relevante Nutzungsarten für Bewertung: Landwirtschaft (43001), Wald (43002), Gehölz (43003), Heide (43004), Moor (43005), Sumpf (43006), Unland (43007) , GFLF (41006 - 2700), BLW (41006 - 6800), BFW (41006 - 7600), Garten (41008 - 4460)

Für Fließgewässer (44001), Stehendes Gewässer (44006) findet eine Überprüfung für die Bewertungsarten 3480, 3481, 3482 und 3490 statt.

3. Filterung der Miniflächen und Verschmelzung dieser mit Nachbarflurstücken

4. Berechnung der Schnittflächen und Ertragsmesszahlen und Deltakorrektur zur berechneten Fläche aller relevanten Nutzungen auf dem Flurstück - Diese Deltakorrektur der Berechnung findet nur für die Bodenschätzungsflächen statt.

Bei den Bewertungen wird die gerundete Fläche aus Objektfläche\* Verbesserungsfaktor Flurstück berechnet. Der Verbesserungsfaktor Flurstück ergibt sich aus amtliche Fläche/geometrische Fläche des Flurstücks. EMZ ist 0.

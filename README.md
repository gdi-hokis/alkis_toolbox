# alkis_toolbox

ArcGIS Pro Toolbox für die Verarbeitung von ALKIS-Daten

## Installation

1. Daten aus Github-Repository herunterladen und lokal speichern
2. Im ArcGIS Pro Katalog Rechtsklick auf 'Toolboxen'->'Toolbox hinzufügen'
3. zu heruntergeladenen Daten navigieren und die Datei 'ALKIS_TOOLBOX.pyt' auswählen; dieses erscheint dann im ArcGIS Pro Katalog unter 'Toolboxen'
4. 'ALIKS_TOOLBOX.pyt' aufklappen und die verschiedenen Werkzeuge mit Doppelklick öffnen

## Tools

### WFS Download

Dieses Tool lädt ALKIS-Daten des ALKIS-WFS des LGL BWs in einem definierten Bereich (Polygonlayer) als GeoJSON herunter und konvertiert diese in zweidimensionale Feature-Classes in einer FGDB.

**Hintergrund**

Statt Daten manuell über Web-Oberflächen herunterzuladen und separat zu konvertieren, können ALKIS-Daten mit diesem Tool direkt aus dem WFS des LGL abgerufen werden. Die GeoJSON-Daten werden automatisch in zweidimensionale Feature-Classes konvertiert, wodurch eine unmittelbare Weiterverarbeitung in ArcGIS Pro ermöglicht wird. Dies spart Zeit, reduziert Fehler bei der manuellen Konvertierung und ermöglicht einen vereinfachten Workflow für regelmäßige Datenaktualisierungen.

**Eingabedaten**

- Eine Polygon-Feature-Class oder ein Shape-File, das den räumlichen Bereich definiert, für den ALKIS-Daten abgerufen werden sollen. Der Bereich muss sich innerhalb des Versorgungsgebietes des ALKIS-WFS des LGL befinden.
- Ziel-Geodatabase (File oder Enterprise), in der die heruntergeladenen Feature-Classes gespeichert werden
- Arbeits-Geodatabase für temporäre Daten während des Download- und Konvertierungsprozesses
- Lokal verfügbarer Ordner für die temporären GeoJSON-Dateien

**Ablauf:**

1. **Grid-Erstellung:** Das Eingabe-Polygon wird in quadratische Kacheln unterteilt (konfigurierbare Kantenlänge, Standard: 20 km)
2. **WFS-Download:** Für jede Kachel werden die verfügbaren ALKIS-Layer als GeoJSON heruntergeladen und lokal gespeichert
3. **Konvertierung:** GeoJSON-Daten werden in zweidimensionale Feature-Classes konvertiert
4. **Duplikat-Entfernung:** Überschneidungen zwischen Kacheln werden entfernt
5. **Filterung:** Geometrien außerhalb des Eingabe-Polygons werden gelöscht
6. **Bereinigung:** Temporäre Daten werden optional entfernt

### FLSTKEY berechnen

**Hintergrund:**

Der FLSTKEY (Flurstückskennzeichen-Schlüssel) ist ein eindeutiger, strukturierter Identifier für Flurstücke, der sich aus der Gemarkung, Flurnummer und Flurstücksnummer zusammensetzt. Diese standardisierte Schreibweise (z.B. 271-0-2344) erleichtert Verknüpfungen zwischen verschiedenen Datensätzen und ermöglicht eine eindeutige Referenzierung von Flurstücken in Datenbanken und GIS-Analysen.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck) mit den Feldern: gemarkung_id, flurnummer, flurstueckstext

**Ablauf:**

1. Das Tool extrahiert die Gemarkungs-ID, Flurnummer und Flurstückstext aus den Eingabedaten
2. Diese Komponenten werden nach dem Schema "gemarkung_id-flurnummer-flurstueckstext" kombiniert
3. Das berechnete FLSTKEY wird in das Feld "FLSTKEY" der Feature-Class geschrieben

### FSK berechnen

**Hintergrund:**

Die FSK (Flurstückskennzeichen-Kurzform) ist eine verkürzte und lesbar gestaltete Schreibweise des vollständigen Flurstückskennzeichens. Sie ersetzt führende Nullen in bestimmten Positionen durch Unterstriche und entfernt abschließende Ziffern, um eine kompaktere und lesbarere Darstellung zu ermöglichen. Dies ist besonders für die kartografische Beschriftung und die Anzeige in Karten relevant.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck) mit dem Feld: flurstueckskennzeichen

**Ablauf:**

1. Das Tool liest das vollständige Flurstückskennzeichen aus dem Eingabe-Feld
2. Führende Nullen an Position [6:9] werden durch "___" ersetzt
3. Führende Nullen an Position [14:18] werden durch "____" ersetzt
4. Die letzten zwei Ziffern werden entfernt
5. Das berechnete FSK wird in das Feld "fsk" der Feature-Class geschrieben

### Flurnummer-ID berechnen

**Hintergrund:**

Die Flurnummer-ID (flurnummer_l) ist ein standardisierter Identifier, der eine Flur eindeutig identifiziert. Sie wird aus einer festen Präfix-Struktur mit der Gemarkungs-ID und Flurnummer konstruiert. Dieses Format ermöglicht eine konsistente, landesweite eindeutige Identifikation von Fluren und wird häufig für Verknüpfungen mit anderen ALKIS-Layern (z.B. Flurnamen) verwendet.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck) oder Fluren (nora_v_al_flur) mit den Feldern: gemarkung_id, flurnummer

**Ablauf:**

1. Das Tool liest die Gemarkungs-ID und Flurnummer aus den Eingabedaten
2. Nach dem Muster "080" + gemarkung_id + "00" + flurnummer wird die Flurnummer-ID konstruiert
3. Das Ergebnis wird in das Feld "flurnummer_l" der Feature-Class geschrieben
4. Beispiel: Gemarkung-ID 12345, Flurnummer 678 → Flurnummer-ID: 08012345006780

### Flurnamen zu Flurstücken zuordnen

**Hintergrund:**

Verknüpft lokale Flurnamen mit Flurstücken über die eindeutige Flurnummer-ID, um eine bessere räumliche Orientierung zu ermöglichen.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck)
- Fluren (nora_v_al_flur)

**Ablauf:**

1. Prüfung und ggf. Berechnung der Flurnummer-ID in beiden Feature-Classes
2. Join der Flurstücke mit den Fluren über flurnummer_l
3. Übernahme des Feldes "flurname" in die Flurstück-FC
4. Aufräumen temporärer Felder

### Lagebeschriftung Bodenschätzung berechnen

**Hintergrund:**

Berechnet ein strukturiertes Beschriftungsfeld für die kartografische Darstellung von Bodenschätzungsflächen mit Bodenart, Klassifizierungen und Wertezahlen.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Bodenschätzung (nora_v_al_bodenschaetzung_f) mit den Klassifizierungsfeldern

**Ablauf:**

1. Extraktion von Bodenart, Nutzungsart, Klassifizierungen und Wertezahlen
2. Formatierung nach Nutzungsart (Acker, Grünland oder Grünland-Acker)
3. Zusammenstellung in strukturierter Beschriftung (mit Zeilenumbrüchen)
4. Speicherung im Feld "label"

### Locator Place berechnen

**Hintergrund:**

Bestimmt einen aussagekräftigen Ortsnamen für Flurstücke mit Priorität auf lokale Flurnamen vor übergeordneten Gemarkungsnamen für bessere Orientierung.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck) mit den Feldern: flurname, gemarkung_name

**Ablauf:**

1. Prüfung der erforderlichen Felder (flurname, gemarkung_name)
2. Wenn vorhanden: Flurname verwenden
3. Ansonsten: Gemarkungsname verwenden
4. Speicherung im Feld "locator_place"

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

Berechnet Schnittflächen (SFL) von den Flurstücken mit der tatsächlichen Nutzung und erstellt eine Verschnitt-Feature-Class fsk_x_nutzung.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck)
- Tatsächliche Nutzung (nora_v_al_tatsaechliche_nutzung)

**Ablauf:**

1. Verschnitt Flurstücke und Nutzung
2. Filterung der Miniflächen und Verschmelzung dieser mit Nachbarflurstücken (mit shapely)
3. Berechnung der Schnittflächen und Deltakorrektur zur amtlichen Flurstücksfläche

**Hinweis:**

Die Ergebnisse wurden mit denen des LGLs verglichen und man kommt auf eine 99,5%-ige Übereinstimmung in den Stichproben. Die Unterschiede betragen +/- 1m² und lassen sich auf Rundungsungenauigkeiten zurückführen. Trotzdem kann es zu Unterschieden kommen, da der Algorithmus des LGLs nicht bekannt ist und somit Berechnungsunterschiede vorhanden sein werden.

### Verschnitt Flurstück & Bodenschätzung

Berechnet Schnittflächen (SFL) von den Flurstücken mit der Bodenschätzung und Bodenbewertung. Berechnet die EMZ der Bodenschätzungsflächen. Endergebnis ist eine Verschnitt-Feature-Class fsk_x_bodenschaetzung, in der sowohl Bodenschätzung als auch Bewertungsflächen enthalten sind (sonstige_angaben_id = 9999).

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck)
- Bodenschätzung (nora_v_al_bodenschaetzung)
- Bewertungsflächen (nora_v_al_bewertung)
- Nutzungsverschnitt (flst_x_nutzung - Ergebnis des Werkzeugs Verschnitt Flurstück & Nutzung)

**Ablauf:**

1. Verschnitt Flurstücke und Bodenschätzung - Dabei werden alle Nutzungsarten abgezogen, die keine Bodenschätzung haben, sowie alle Bewertungsflächen, die nicht zusätzliche Bodenschätzungsergebnisse vorweisen können

2. Verschnitt Flurstücke und Bewertungsflächen - Ebenfalls Abzug aller irrelevanten Nutzungsarten

3. Filterung der Miniflächen und Verschmelzung dieser mit Nachbarflurstücken

4. Berechnung der Schnittflächen und Ertragsmesszahlen und Deltakorrektur zur berechneten Fläche aller relevanten Nutzungen auf dem Flurstück - Diese Deltakorrektur der Berechnung findet nur für die Bodenschätzungsflächen statt.

Bei den Bewertungen wird die gerundete Fläche aus Objektfläche\* Verbesserungsfaktor Flurstück berechnet. Der Verbesserungsfaktor Flurstück ergibt sich aus amtliche Fläche/geometrische Fläche des Flurstücks. EMZ ist 0.

**Hinweis:**

Relevante Nutzungsarten für Bodenschätzung: Landwirtschaft (43001), Heide (43004), Moor (43005), Sumpf (43006), Unland (43007), Garten (41008 - 4460)

relevante Nutzungsarten für Bewertung: Landwirtschaft (43001), Wald (43002), Gehölz (43003), Heide (43004), Moor (43005), Sumpf (43006), Unland (43007) , GFLF (41006 - 2700), BLW (41006 - 6800), BFW (41006 - 7600), Garten (41008 - 4460)

Für Fließgewässer (44001), Stehendes Gewässer (44006) findet eine Überprüfung für die Bewertungsarten 3480, 3481, 3482 und 3490 statt.

Bewertungen ohne Bodenschätzung - siehe VWVLK Anlage 1 (3100, 3105, 3200, 3411, 3480, 3481, 3482, 3490, 3510, 3520, 3530, 3600, 3610, 3611, 3612, 3613, 3614, 3615, 3616, 3710, 3999)

### Veränderungsnummern aus NAS auslesen

Dieses Werkzeug liest Veränderungsnummern von Flurstücken und Gebäuden aus NAS-XML-Dateien aus und erstellt zwei Verknüpfungstabellen (fsk_x_vn und geb_x_vn).

**Hintergrund:**

Veränderungsnummern (VN) dokumentieren Änderungen an ALKIS-Objekten und sind über den WFS nicht verfügbar. Sie sind jedoch in den NAS-Dateien als Fachdatenverbindungen (AA_Fachdatenverbindung) gespeichert.

**Eingabedaten:**

- NAS-XML-Dateien mit AX_Flurstueck und AX_Gebaeude Objekten

**Ablauf:**

1. Durchsuchen aller XML-Dateien im angegebenen NAS-Verzeichnis
2. Extraktion der Veränderungsnummern (nur VN mit Endung 'F' oder 'V') aus den Fachdatenverbindungen
3. Erstellung von CSV-Tabellen mit den Zuordnungen: GML-ID zu Veränderungsnummern
4. Optional: Speicherung der Ergebnisse in einer Geodatabase als Tabellen fsk_x_vn (mit Flurstückskennzeichen) und geb_x_vn

**Hinweis:**

Es werden nur Veränderungsnummern mit den Endungen 'F' (Fortführungsriss) oder 'V' (Fortführungsnachweis) extrahiert. Bei mehreren Veränderungsnummern pro Objekt werden diese mit '|' getrennt gespeichert.
Beachten Sie: Die Verknüpfung der Gebäude mit den Veränderungsnummern läuft über die GML-ID. File Geodatabases unterscheiden bei Textvergleichen nicht zwischen Groß-/Kleinschreibung, was zu Fehlverknüpfungen führen kann. Für zuverlässige Ergebnisse sollte eine Enterprise Geodatabase mit case-sensitiver Einstellung verwendet werden.

# alkis_toolbox

ArcGIS Pro Toolbox für die Verarbeitung von ALKIS-Daten

## Installation

1. Daten aus Github-Repository herunterladen und lokal speichern
2. Im ArcGIS Pro Katalog Rechtsklick auf 'Toolboxen'->'Toolbox hinzufügen'
3. zu heruntergeladenen Daten navigieren und die Datei 'ALKIS_TOOLBOX.pyt' auswählen; dieses erscheint dann im ArcGIS Pro Katalog unter 'Toolboxen'
4. 'ALKIS_TOOLBOX.pyt' aufklappen und die verschiedenen Werkzeuge mit Doppelklick öffnen

## Empfohlene Reihenfolge der Schritte

1. WFS-Download

**Eigentümer**

1. FSK berechnen - Voraussetzung für Eigentümer-CSV
2. Eigentümer-CSV formatieren

**Flurstücksverschnitte**

1. Verschnitt Flurstück und Lage
2. Verschnitt Flurstück und Nutzung - Voraussetzung für Verschnitt Bodenschätzung
3. Verschnitt Flurstück und Bodenschätzung

**Locator**

1. Flurnamen zuordnen - Voraussetzung für Ortsnamen berechnen
2. Ortsnamen berechnen - Voraussetzung für Locator
3. Locator erstellen/aktualisieren

**sonstige Werkzeuge (Reihenfolge egal)**

- FLSTKEY berechnen (optional)
- Beschriftung Bodenschätzung berechnen (optional)
- Veränderungsnummern aus NAS auslesen (optional)

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

### Eigentümer-CSV formatieren

Dieses Werkzeug formatiert die Eigentümer-CSV des LGLs, indem es überflüssige Zeilen entfernt, die Sonderzeichen "&" und "'" decodiert und neue Felder hinzufügt:

- "gemeinde" (für Suchen)
- "gemeinden_puffer" (für Sichten - enthält, alle Gemeindenamen kommasepariert, die in einem bestimmten Radius um das Flurstück liegen)
- "abrufdatum" (aus der CSV-Tabelle übernommen)
- "fsk" (für die Verknüpfung mit den Flurstücken) - Format aus dem Werkzeug "FSK berechnen"

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck) mit dem Feld "fsk" (Berechnung über das Werkzeug "FSK berechnen" möglich)
- Gemeinden (nora_v_al_gemeinde) mit dem Feld "gemeinde_name"
- Eigentümer-CSV des LGLs
- Pufferradius

### FLSTKEY berechnen

Dieses Werkzeug berechnet ein Feld "FLSTKEY" für die Flurstücke. Der FLSTKEY (Flurstückskennzeichen-Schlüssel) ist ein eindeutiger, strukturierter Identifier für Flurstücke, der sich aus der Gemarkung, Flurnummer und Flurstücksnummer zusammensetzt. Beispiel: 271-0-2344/2

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck) mit den Feldern: gemarkung_id, flurnummer, flurstueckstext

### FSK berechnen

Dieses Werkzeug berechnet ein Feld "FSK" für die Flurstücke.
Die FSK (Flurstückskennzeichen) ist eine verkürzte und lesbar gestaltete Schreibweise des vollständigen Flurstückskennzeichens. Sie wird ohne Flurstücksfolge berechnet.
Beispiel: 080271\_\_\_023440002

**Hintergrund:**
Für die Verknüpfung von Eigentümerdaten oder anderen Daten mit den Flurstücken ist es notwendig eine einheitliche ID zu generieren.
In diesen Tabellen wird die FSK im gleichen Format berechnet. Eine Berechnung ohne Flurstücksfolge ermöglicht auch eine Verknüpfung, wenn sich bei Aktualisierungen nur die Folgennummer geändert hat.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck) mit dem Feld: flurstueckskennzeichen

### Flur-ID berechnen

Dieses Werkzeug berechnet ein Feld "flur_id" für die Flurstücke und/oder die Fluren.

**Hintergrund:**

Die Flur-ID (flur_id) ist ein Identifikator, der aus Gemarkungs-ID und Flurnummer zusammengesetzt wird. Da in den Flurstücken keine Flurnamen enthalten sind, wird er für die eindeutige Verknüpfung der Flurstücke mit ihren Flurnamen benötigt.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck) oder Fluren (nora_v_al_flur) mit den Feldern: gemarkung_id, flurnummer

### Flurnamen zu Flurstücken zuordnen

Dieses Werkzeug berechnet ein Feld "flurname" für die Flurstücke. Hierzu verbindet es die Flurstücke mit den Fluren über einen eindeutigen flur_id-Identifikator aus Gemarkungs- und Flurnummer. Wenn dieses Feld noch nicht existiert, wird es zusätzlich berechnet und, wenn gewünscht, anschließend auch wieder gelöscht.

**Hintergrund:**

Da in den Flurstücken keine Flurnamen enthalten sind, müssen diese explizit berechnet werden, um diese ohne anderweitige Verbindung anzeigen zu können.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck)
- Fluren (nora_v_al_flur)

**Ablauf:**

1. Prüfung und ggf. Berechnung der "flur_id" in beiden Feature-Classes
2. Übernahme des Feldes "flurname" in die Flurstück-FC über Join der Fluren mit der flur_id
3. Löschen der flur_id, wenn sie nicht weiter benötigt wird

### Beschriftung (Label) für Bodenschätzung berechnen

Dieses Werkzeug berechnet ein Feld "label" für die Bodenschätzungsflächen. In diesem Feld werden Bodenart, Klassifizierungen und Wertzahlen mit Zeilenumbrüchen berechnet, angelehnt an die Beschriftung in der ALKIS-Karte nach VWVLK Baden-Württemberg.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Bodenschätzung (nora_v_al_bodenschaetzung_f) mit den Klassifizierungsfeldern

### Locator Place berechnen

Dieses Werkzeug erstellt ein Feld 'locator_place'. In diesem Feld steht mit erster Priorität der Flurname, wenn es einen gibt, anderenfalls der Gemarkungsname.

**Hintergrund:**
Die Flurnamen aus ALKIS sind unvollständig, da nur Flurnamen geführt werden, wenn es in der Gemarkung auch Fluren gibt. Für die Erstellung eines Flurstücks-Locators kann nur ein Feld mit Daten zu jedem Datensatz verwendet werden. In diesem Werkzeug wird ein solches Feld, was auch die Flurnamen berücksichtigt erstellt.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck) mit den Feldern: flurname, gemarkung_name

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
2. Filterung der Miniflächen und Verschmelzung dieser mit Nachbarflurstücken
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

### Flurstücks-Locator erstellen/überschreiben

Dieses Werkzeug erstellt oder aktualisiert einen Locator für ALKIS-Flurstücke, der das Suchen nach Flurstücken ermöglicht. Optional kann der Locator auch im Portal als Geocode Service veröffentlicht werden.

**Hintergrund:**
Wenn die ALKIS-Daten aktualisiert werden, wird der Locator nicht automatisch mitaktualisiert. Dieses Werkzeug ermöglicht einen standardisierten Workflow für die regelmäßige Locator-Aktualisierung.

**Eingabedaten:**

Schema aus dem WFS des LGLs

- Flurstücke (nora_v_al_flurstueck) mit den Feldern: flurstueckstext, gemeinde_name, gemarkung_id, gemarkung_name, flurname, locator_place

**Ablauf:**

1. Locator erstellen/aktualisieren: Entweder wird ein komplett neuer Locator erstellt oder, wenn der Locator bereits lokal abgelegt ist und sich nur die Daten der gleichen Datenquelle geändert haben, es wird ein Reindexing des vorhandenen Locators durchgeführt.

2. Portal-Veröffentlichung (optional): Der Locator wird in das verbundene Portal als Geocode Service "Flurstuecke_Locator" hochgeladen oder ein vorhandener Service wird überschrieben

3. Optional: Öffentliche Freigabe des Services

**Hinweis:**
Beim Update eines Geocoding Service werden Freigabeeinstellungen auf privat zurückgesetzt. Das Werkzeug bietet eine Checkbox zur automatischen öffentlichen Freigabe – so entfällt die manuelle Neukonfiguration.

### Veränderungsnummern aus NAS auslesen

Dieses Werkzeug liest Veränderungsnummern von Flurstücken und Gebäuden aus NAS-XML-Dateien aus und erstellt zwei Verknüpfungstabellen (fsk_x_vn und geb_x_vn).

**Hintergrund:**

Veränderungsnummern (VN) dokumentieren Änderungen an ALKIS-Objekten und sind über den WFS nicht verfügbar. Sie sind jedoch in den NAS-Dateien als Fachdatenverbindungen (AA_Fachdatenverbindung) gespeichert.

**Eingabedaten:**

- NAS-XML-Dateien mit AX_Flurstueck und AX_Gebaeude Objekten

**Ablauf:**

1. Durchsuchen aller XML-Dateien im angegebenen NAS-Verzeichnis
2. Extraktion der Veränderungsnummern (nur VN mit Endung 'F' oder 'V') aus den Fachdatenverbindungen
3. Erstellung von CSV-Tabellen mit den Zuordnungsschlüsseln fsk - vn (Flurstücke), gmlId - vn (Gebäude)
4. Optional: Speicherung der Ergebnisse in einer Geodatabase als Tabellen fsk_x_vn (mit Flurstückskennzeichen) und geb_x_vn

**Hinweis:**

Es werden nur Veränderungsnummern mit den Endungen 'F' (Fortführungsriss) oder 'V' (Fortführungsnachweis) extrahiert. Bei mehreren Veränderungsnummern pro Objekt werden diese mit '|' getrennt gespeichert.
Beachten Sie: Die Verknüpfung der Gebäude mit den Veränderungsnummern läuft über die GML-ID. File Geodatabases unterscheiden bei Textvergleichen nicht zwischen Groß-/Kleinschreibung, was zu Fehlverknüpfungen führen kann. Für zuverlässige Ergebnisse sollte eine Enterprise Geodatabase mit case-sensitiver Einstellung verwendet werden.

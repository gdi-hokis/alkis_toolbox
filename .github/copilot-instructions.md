# Copilot Instructions für ALKIS Toolbox

## Projekt-Kontext

Dieses Projekt ist eine ArcGIS Python Toolbox für die Verarbeitung von ALKIS-Daten (Amtliches Liegenschaftskataster-Informationssystem). Die Toolbox wird in ArcGIS Pro verwendet.

## Coding-Richtlinien

### Sprache und Dokumentation

- **Englische Sprache** für alle Variablennamen, Funktionsnamen
- **Deutsche Sprache** für alle Tool-Labels, Tool-Parameter, Kommentare und Docstrings
- **Deutsche Fehlermeldungen** für Benutzer-Feedback
- Klare, aussagekräftige Variablennamen verwenden (z.B. `polygon_fc`, `target_gdb`)

### Python-Stil

- Python 3.x Syntax verwenden
- PEP 8 Konventionen für Code-Struktur (Einrückung, Zeilenumbrüche)
- F-Strings für String-Formatierung bevorzugen: `f"Schritt {i} von {total}"`
- Type Hints nur bei Bedarf, nicht zwingend erforderlich

### ArcGIS/arcpy Spezifisch

#### Moderne arcpy-Methoden

- **IMMER** `arcpy.da.UpdateCursor`, `arcpy.da.InsertCursor`, `arcpy.da.SearchCursor` verwenden
- **NIEMALS** veraltete Cursor-Methoden (`arcpy.UpdateCursor`) nutzen
- `arcpy.management.*` für Management-Operationen explizit verwenden

#### Fortschrittsmeldungen

- Einteilung des Tool-Fortschritts in sinnvolle Abschnitte (2-5 Schritte)
- Abschnittsanzeige mit Trennlinien in der Zeile davor und danach: `arcpy.AddMessage("-"*40)`
- Abschnittsanzeige: `f"Schritt {current} von {total} -- Beschreibung..."`
- `arcpy.AddMessage("- text...")` für normale Fortschrittsmeldungen und Informationen
- `arcpy.AddWarning("text...")` für Warnungen (z.B. fehlgeschlagene Downloads, nicht durchführbare Operationen)
- `arcpy.AddError("text...")` für kritische Fehler

#### Environment Settings

- `arcpy.env.overwriteOutput = True` setzen, wenn Überschreiben erlaubt sein soll
- `arcpy.env.workspace` für Arbeitsdatenbank setzen
- `arcpy.env.outputZFlag` und `arcpy.env.outputMFlag` für 2D-Konvertierungen

#### Ressourcen-Management

- Tool-Parameter "Verarbeitungsdaten behalten?" implementieren
- Temporäre Layer und Feature Classes mit `arcpy.Delete_management()` aufräumen, wenn Parameter unchecked
- Feature Layer mit `arcpy.MakeFeatureLayer_management()` erstellen
- `arcpy.Exists()` prüfen bevor Features gelöscht werden

### Projekt-spezifische Konventionen

#### Toolbox-Struktur (ALKIS_WFS_DOWNLOAD.pyt)

Die Python Toolbox enthält mehrere Tools für verschiedene ALKIS-Operationen. Jedes Tool ist als Klasse implementiert:

**Tool-Klassen-Struktur:**

- `__init__()`: Tool-Metadaten definieren
  - `self.label`: **Deutscher Titel** des Tools (wird in ArcGIS Pro angezeigt)
  - `self.description`: Deutsche Beschreibung
- `getParameterInfo()`: Tool-Parameter als `arcpy.Parameter`-Objekte zurückgeben
- `isLicensed()`: Lizenzprüfung (üblicherweise `return True`)
- `updateParameters()`: Dynamische Parameter-Anpassungen bei Benutzer-Eingaben
  - Nicht zu exzessiv validieren (Zielgruppe: GIS-Administratoren mit Kenntnissen)
- `updateMessages()`: Validierungsnachrichten für Parameter setzen
- `execute()`: **Nur** Parameter laden und an externe Funktion übergeben
  - Kein umfangreicher Code im execute
  - Funktionsaufruf mit importiertem Modul
- `postExecute()`: Nachbearbeitung

**Code-Organisation:**

- Toolbox-Datei: `ALKIS_TOOLBOX.pyt` (nur Tool-Klassen)
- Implementierung: Separate Python-Module in thematischen Ordnern
- Import mit `importlib.reload()` für Entwicklung

**Beispiel:**

```python
class wfs_download:
    def __init__(self):
        self.label = "WFS-Daten herunterladen"  # Deutsch!
        self.description = "Lädt ALKIS-Daten über WFS herunter"

    def execute(self, parameters, messages):
        # Nur Parameter laden
        polygon_fc = parameters[0].value
        target_gdb = parameters[1].valueAsText

        # Funktion aus externem Modul aufrufen
        import wfs.download
        wfs.download.wfs_download(polygon_fc, target_gdb, ...)
```

### Fehlerbehandlung

- Try-Except für externe Operationen (Requests, Feldberechnungen)
- Bei Fehlern: `arcpy.AddError()` mit aussagekräftiger Meldung
- Nicht-kritische Fehler sollen Workflow nicht stoppen
- HTTP-Statuscodes prüfen: `if not response.status_code == 200:`

### Best Practices für dieses Projekt

#### Performance

- Feldoperationen bündeln: `arcpy.management.AddFields()` statt mehrere `AddField()` Aufrufe
- Batch-Operationen für Löschen: `arcpy.DeleteField_management(fc, ";".join(fields))`
- UpdateCursor für mehrere Feldaktualisierungen gleichzeitig nutzen

### Coordinate System

- Standard-Projektion: **EPSG:25832** (ETRS89 / UTM zone 32N)
- CRS in GeoJSON: `"urn:ogc:def:crs:EPSG::25832"`

## Zu vermeidende Patterns

- ❌ Veraltete Cursor-Methoden ohne `.da`
- ❌ String-Formatierung mit `%s` oder `.format()` wenn F-Strings möglich sind
- ❌ Englische Kommentare oder Variablennamen
- ❌ Hardcodierte Pfade oder URLs (immer aus Config lesen)
- ❌ Fehlende Fortschrittsmeldungen bei langwierigen Operationen
- ❌ Nicht-aufgeräumte temporäre Daten

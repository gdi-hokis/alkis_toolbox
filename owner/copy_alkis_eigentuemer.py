from datetime import datetime
import os
import arcpy
from utils import add_step_message


def copy_alkis_eigentuemer(
    alkis_csv,
    fc_gemeinden,
    fc_flurstuecke,
    output_table,
    buffer_size,
    cfg,
    keep_temp_data,
    num_leading_lines,
    num_trailing_lines,
    access_date,
    output_csv=None,
):
    """
    Hauptlogik zum Kopieren der ALKIS-Eigentümerdaten aus der CSV in eine ArcGIS-Tabelle
    :param alkis_csv: Pfad zur ALKIS-Eigentümer-CSV-Datei
    :param fc_gemeinden: Feature Class der Gemeinden
    :param fc_flurstuecke: Feature Class der Flurstücke
    :param output_table: Pfad zur Ausgabe-Eigentümer-Tabelle in der Geodatabase
    :param buffer_size: Puffergröße in Metern für die räumliche Verknüpfung
    :param cfg: Konfigurationsparameter
    :param keep_temp_data: Bool, ob temporäre Daten behalten werden sollen
    :param num_leading_lines: Anzahl der zu entfernenden Zeilen am Anfang der CSV
    :param num_trailing_lines: Anzahl der zu entfernenden Zeilen am Ende der CSV
    :param access_date: Abrufdatum als datetime-Objekt oder None
    :param output_csv: Optionaler Pfad zur Ausgabe-CSV-Datei (wird aus der GDB-Tabelle exportiert)
    """
    # Pfad in GDB und Tabellenname zerlegen
    output_gdb = os.path.dirname(output_table)
    output_table_name = os.path.basename(output_table)

    arcpy.env.workspace = output_gdb

    arcpy.SetProgressor("default", "CSV vorbereiten...")

    # Schritt 1: csv bereinigen
    add_step_message("CSV vorbereiten", 1, 4)
    prepared_csv, abrufdatum = prepare_csv(alkis_csv, num_leading_lines, num_trailing_lines, access_date, cfg)

    # Schritt 2: Eigentümer-Tabelle erstellen
    add_step_message("Eigentümer-Tabelle erstellen", 2, 4)
    make_eigentuemer_table(prepared_csv, output_gdb, output_table_name, abrufdatum, cfg)

    # Schritt 3: räumliche Verknüpfung mit Flurstücken und Gemeinden
    add_step_message("Räumliche Verknüpfung mit Flurstücken und Gemeinden", 3, 4)
    spatial_join_gem_flst(fc_gemeinden, fc_flurstuecke, output_table_name, buffer_size, cfg)

    # Schritt 4: Ergebnis als CSV exportieren
    add_step_message("Ergebnis als CSV exportieren", 4, 4)
    if output_csv:
        arcpy.SetProgressorLabel(f"Exportiere Tabelle nach '{output_csv}'...")
        arcpy.ExportTable_conversion(output_table_name, output_csv)

    if not keep_temp_data:
        arcpy.SetProgressorLabel("Zwischenergebnisse löschen...")
        arcpy.Delete_management("buffer")
        arcpy.Delete_management("v_al_flurstueck_SpatialJoin")
        os.remove(prepared_csv)
        if output_csv and arcpy.Exists(output_table):
            arcpy.Delete_management(output_table)

    arcpy.ResetProgressor()


def _infer_column_types(data_lines, delimiter, num_cols, col_names=None, forced_text_cols=None, sample_size=30):
    """
    Bestimmt den Feldtyp pro Spalte anhand einer Stichprobe aus Anfang, Mitte und Ende.
    - Spalten in forced_text_cols                          → immer Text
    - Spalten mit datumsähnlichen Werten (DD.MM.YYYY)      → Text
    - Spalten mit nur ganzzahligen Werten                  → Long
    - Spalten mit nur numerischen Werten                   → Double
    - Alles andere                                         → Text
    """
    import re

    date_pattern = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$")
    int_pattern = re.compile(r"^-?\d+$")
    float_pattern = re.compile(r"^-?\d+[.,]\d+$")
    forced_text_cols = {c.lower() for c in (forced_text_cols or [])}

    # Stichprobe gleichmäßig über Anfang, Mitte und Ende verteilen
    n = len(data_lines)
    step = max(1, n // sample_size)
    sampled = data_lines[::step][:sample_size]

    # Spaltenwerte sammeln (nur nicht-leere Werte)
    col_values = [[] for _ in range(num_cols)]
    for line in sampled:
        parts = line.rstrip("\n").split(delimiter)
        for i in range(num_cols):
            val = parts[i].strip().strip('"') if i < len(parts) else ""
            if val:
                col_values[i].append(val)

    types = []
    for idx, vals in enumerate(col_values):
        col_name = col_names[idx] if col_names and idx < len(col_names) else ""
        if not vals:
            types.append("Text")
        elif col_name.lower() in forced_text_cols:
            types.append("Text")
        elif any(date_pattern.match(v) for v in vals):
            types.append("Text")
        elif all(int_pattern.match(v) for v in vals):
            types.append("Long")
        elif all(int_pattern.match(v) or float_pattern.match(v) for v in vals):
            types.append("Double")
        else:
            types.append("Text")
    return types


def prepare_csv(input_csv, num_leading_lines, num_trailing_lines, access_date, cfg):
    """
    entfernt die erste und die letzten fünf Zeilen (header und Codeerklärungen)
    speichert die bereinigte CSV in einer temporären Datei (im gleichen Verzeichnis wie input_csv)
    :param input_csv: Pfad zur Eingabe-CSV-Datei
    :param num_leading_lines: Anzahl der zu entfernenden Zeilen am Anfang der CSV
    :param num_trailing_lines: Anzahl der zu entfernenden Zeilen am Ende der CSV
    :param access_date: Abrufdatum als datetime-Objekt oder None
    :param cfg: Konfigurationsparameter
    """
    encoding = "utf-8"

    # Temporäre CSV vorbereiten
    output_csv = os.path.join(os.path.dirname(input_csv), "prepared_" + os.path.basename(input_csv))

    with open(input_csv, "r", encoding=encoding) as f:
        lines = f.readlines()

    # Extrahiere Abrufdatum aus der ersten Zeile
    if not access_date:
        try:
            abrufdatum = lines[0][19:29]
            # Validiere Datumsformat DD.MM.YYYY
            datetime.strptime(abrufdatum, "%d.%m.%Y")
        except:
            arcpy.AddError(
                "Fehler beim Auslesen des Abrufdatums aus der CSV-Datei. Bitte füllen Sie den Parameter 'Abrufdatum'."
            )
            raise
    else:
        abrufdatum = access_date.strftime("%d.%m.%Y")
    # Entferne die Anfangs- und letzten End-Zeilen
    end_lines_index = -num_trailing_lines
    lines = lines[num_leading_lines:end_lines_index]

    # Bestimme die erwartete Anzahl von Semikolons aus der Header-Zeile
    header_line = lines[0].rstrip("\r\n")
    expected_semicolon_count = header_line.count(";")

    # Extrahiere Delimiter und Spaltennamen aus dem Header
    delimiter = ";" if ";" in header_line else ","
    col_names = [col.strip('"') for col in header_line.split(delimiter)]

    # Ersetze fehlerhafte HTML-Entity-Kodierungen und Encoding-Fehler
    decoded_lines = []
    for line_idx, line in enumerate(lines):
        # HTML-Entities - sowohl mit als auch ohne Semikolon
        line = line.rstrip("\r\n")
        
        # Liste der zu ersetzenden Zeichen (mit Semikolon, erfordern Semikolon-Prüfung)
        entities_with_semicolon = [
            ("&apos;", "'"),
            ("&amp;", "&"),
            ("&quot;", "'"),
        ]
        
        # Liste der zu ersetzenden Zeichen (mit Leerzeichen, keine Semikolon-Prüfung)
        entities_without_semicolon = [
            ("&apos ", "'"),
            ("&amp ", "&"),
            ("&quot ", "'"),
        ]
        
        # Prüfe, ob die Zeile überhaupt eine der kritischen Ersetzungen benötigt
        needs_processing = any(entity in line for entity, _ in entities_with_semicolon)
        
        if needs_processing:
            # Verarbeite jede kritische Ersetzung einzeln mit Semikolon-Prüfung
            for entity, replacement in entities_with_semicolon:
                while entity in line:
                    # Test: Ersetze einmal und zähle Semikolons danach
                    test_line = line.replace(entity, replacement, 1)
                    semicolons_after_test = test_line.count(";")
                    
                    # Ersetze mit Semikolon nur wenn danach noch zu wenige Semikolons vorhanden sind
                    # Sonst ersetze ohne Semikolon (auch wenn dabei eines verloren geht)
                    if semicolons_after_test < expected_semicolon_count:
                        line = line.replace(entity, replacement + ";", 1)
                    else:
                        line = line.replace(entity, replacement, 1)
            
            
            # Nach alle Ersetzungen: Prüfe ob die Semikolon-Anzahl passt
            final_semicolon_count = line.count(";")
            if final_semicolon_count != expected_semicolon_count:
                arcpy.AddWarning(
                    f"Zeile {line_idx + 1 + num_leading_lines}: Semikolon-Anzahl stimmt nicht überein. "
                    f"Erwartet: {expected_semicolon_count}, Gefunden: {final_semicolon_count}"
                )
            
            # Prüfe Geburtsdatum-Feld: Warnung wenn Wert nicht mit "*" beginnt und nicht leer ist
            geburtsdatum_field = cfg["eigentuemer"]["geburtsdatum"]
            if line_idx > 0:  # Überspringe Header
                parts = line.split(";")
                if col_names:
                    try:
                        geburtsdatum_idx = [c.lower() for c in col_names].index(geburtsdatum_field.lower())
                        if geburtsdatum_idx < len(parts):
                            geburtsdatum_value = parts[geburtsdatum_idx].strip()
                            if geburtsdatum_value and not geburtsdatum_value.startswith("*"):
                                arcpy.AddWarning(
                                    f"Zeile {line_idx + 1 + num_leading_lines}: {geburtsdatum_field} hat ungültigen Wert '{geburtsdatum_value}' (erwartet: leer oder mit '*' beginnend). | {line} | CSV-Datei an dieser Stelle manuell korrigieren (Semikolon ersetzen und an die richtige Stelle schieben, damit die Spaltenanzahl stimmt)"
                                )
                    except (ValueError, IndexError):
                        pass
        
        # Ersetze die Zeichen ohne Semikolon (normal, ohne Prüfung)
        for entity, replacement in entities_without_semicolon:
            if entity in line:
                while entity in line:
                    line = line.replace(entity, replacement, 1)

        # UTF-8 als Latin-1 interpretiert - nur für Öffnen der CSV in Excel notwendig, im ArcGIS Pro eig. nicht benötigt
        mojibake_map = {"Ã¼": "ü", "Ã¶": "ö", "Ã¤": "ä", "ÃŸ": "ß", "Ã": "Ü", "Ã–": "Ö", "Ã„": "Ä", "Â": " "}
        for wrong, correct in mojibake_map.items():
            line = line.replace(wrong, correct)

        decoded_lines.append(line + "\n")

    # Dummy-Zeile einfügen, damit ArcGIS Enterprise beim CSV-Import die richtigen Feldtypen inferiert.
    # ArcGIS Enterprise analysiert die ersten Zeilen der CSV
    # Die Dummy-Zeile enthält je nach inferiertem Typ einen typischen Wert ('__dummy__', 0, 0.0)
    arcpy.SetProgressorLabel("Dummy-Zeile für Feldtypen einfügen ...")

    # Feldnamen die zwingend als Text importiert werden müssen aus der Config lesen
    hausnummer_field = cfg["eigentuemer"]["hausnummer"]
    if hausnummer_field.lower() not in [c.lower() for c in col_names]:
        arcpy.AddError(
            f"Feld '{hausnummer_field}' (config: eigentuemer.hausnummer) wurde nicht in der CSV gefunden. "
            f"Bitte die Spaltenüberschriften der CSV-Datei prüfen. Gefundene Spalten: {', '.join(col_names)}"
        )
    forced_text_cols = [hausnummer_field]
    col_types = _infer_column_types(decoded_lines[1:], delimiter, len(col_names), col_names, forced_text_cols)

    _dummy_values = {"Text": "x", "Long": "0", "Double": "0.0"}
    dummy_row = delimiter.join(_dummy_values[t] for t in col_types) + "\n"
    decoded_lines.insert(1, dummy_row)

    with open(output_csv, "w", encoding=encoding, newline="") as f:
        f.writelines(decoded_lines)
    return output_csv, abrufdatum


def make_eigentuemer_table(prepared_csv, gdb, owner_table, abrufdatum, config):
    """
    konvertiert die Eigentümer-csv in eine ArcGIS-Tabelle
    berechnet die Felder FSK, FLSTKEY, Abrufdatum
    :param prepared_csv: Pfad zur bereinigten CSV-Datei
    :param gdb: Pfad zur Geodatabase (für die Zwischenergebnisse)
    :param owner_table: Name der zu erstellenden Tabelle
    :param abrufdatum: Abrufdatum als String im Format 'DD.MM.YYYY'
    :param config: Konfigurationsparameter
    """
    arcpy.SetProgressorLabel("Erstelle Eigentümer-Tabelle ...")
    # erstellt Tabelle aus csv und speichert in gdb
    arcpy.TableToTable_conversion(prepared_csv, gdb, owner_table)

    # Lösche leere Felder die von TableToTable fälschlicherweise erzeugt wurden (z.B. Field20)
    fields = arcpy.ListFields(owner_table)
    fields_to_delete = []

    for field in fields:
        # Prüfe auf generische Feldnamen wie Field1, Field20 etc.
        if field.name.startswith("Field") and field.name[5:].isdigit():
            # Prüfe ob das Feld komplett leer ist
            is_empty = True
            with arcpy.da.SearchCursor(owner_table, [field.name]) as cursor:
                for row in cursor:
                    if row[0]:
                        is_empty = False
                        break

            if is_empty:
                fields_to_delete.append(field.name)
                arcpy.SetProgressorLabel(f"Enferne '{field.name}'...")

    if fields_to_delete:
        arcpy.DeleteField_management(owner_table, fields_to_delete)

    input_field = config["eigentuemer"]["fkz"]
    output_field = config["eigentuemer"]["fsk"]

    # Feld 'FSK' berechnen aus 'FKZ' und Tabelle hinzufügen
    arcpy.SetProgressorLabel("Berechne FSK...")
    arcpy.CalculateField_management(
        in_table=owner_table,
        field=output_field,
        expression=f"replaceZerosInFSK(!{input_field}![1:-1])",
        expression_type="PYTHON3",
        code_block="""def replaceZerosInFSK(flstId):
        fsk = flstId
        if fsk[6:9] == "000":
            fsk = fsk[:6] + "___" + fsk[9:]
        if fsk[14:18] == "0000":
            fsk = fsk[:14] + "____" + fsk[18:]
        fsk = fsk[:-2]
        return fsk
        """,
        field_type="TEXT",
        enforce_domains="NO_ENFORCE_DOMAINS",
    )

    # Abrufdatum setzen
    arcpy.SetProgressorLabel("Setze Abrufdatum...")
    arcpy.CalculateField_management(owner_table, "abrufdatum", f'"{abrufdatum}"', "PYTHON3", field_type="DATE")


def spatial_join_gem_flst(gem, flst, owner_table, buffer_size, config):
    """
    Erstellt einen Puffer (der Größe des Parameters 'buffer_size') um die Gemeinden
    des gewählten Gebiets und verknüpft diese räumlich mit den Flurstücken.
    Anschließend werden zwei Gemeindefelder zur Eigentümer-Tabelle hinzugefügt:
    - 'gemeinde': Gemeindename für Flurstücke innerhalb der Gemeindegrenze
    - 'gemeinden_puffer': Gemeindennamen für Flurstücke im Pufferbereich (können mehrere Einträge haben)

    :param gem: Feature Class der Gemeinden mit Feld 'gemeinde_name'
    :param flst: Feature Class der Flurstücke mit Feld 'flstkey'
    :param gdb: Pfad zur Geodatabase
    :param owner_table: Name der ArcGIS-Eigentümer-Tabelle
    :param buffer_size: Größe des Puffers in Metern
    :param config: Konfigurationsparameter
    """
    # Puffer
    # makefeaturelayer, damit ein Originallayer unverändert bleibt und Funktion mit shapefiles funktioniert
    arcpy.SetProgressorLabel("Pufferlayer erstellen...")
    arcpy.MakeFeatureLayer_management(gem, "gemeinden_layer")
    arcpy.Buffer_analysis("gemeinden_layer", "buffer", f"{buffer_size} METER")

    # Spatial Join Flurstücke - Puffer
    join_field = config["eigentuemer"]["fsk"]
    arcpy.SetProgressorLabel("Räumliche Verknüpfung durchführen...")
    arcpy.SpatialJoin_analysis(
        target_features=flst,
        join_features="buffer",
        out_feature_class="v_al_flurstueck_SpatialJoin",
        join_operation="JOIN_ONE_TO_ONE",
        join_type="KEEP_ALL",
        field_mapping=f'{join_field} "Flurstückskey" true true false 512 Text 0 0,First,#,{flst},{join_field},0,512;gemeinden_puffer "Gemeinden (Puffer)" true true false 100 Text 0 0,Join,", ",buffer,{config["gemeinde"]["gemeinde_name"]},0,50',
        match_option="INTERSECT",
        search_radius=None,
        distance_field_name="",
    )

    # Gemeinde-Felder zur Eigentümer-Tabelle hinzufügen
    arcpy.SetProgressorLabel("Gemeindefelder zur Eigentümer-Tabelle hinzufügen...")
    # Gemeinde von Flurstücken joinen
    arcpy.JoinField_management(owner_table, join_field, flst, join_field, ["gemeinde_name"])
    # Gemeinden aus Spatial Join hinzufügen
    arcpy.JoinField_management(owner_table, join_field, "v_al_flurstueck_SpatialJoin", join_field, ["gemeinden_puffer"])

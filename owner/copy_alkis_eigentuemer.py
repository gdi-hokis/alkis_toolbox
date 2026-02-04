from datetime import datetime
import os
import arcpy
from utils import add_step_message


def copy_alkis_eigentuemer(alkis_csv, fc_gemeinden, fc_flurstuecke, output_table, buffer_size, cfg, keep_temp_data):
    """
    Hauptlogik zum Kopieren der ALKIS-Eigentümerdaten aus der CSV in eine ArcGIS-Tabelle
    :param alkis_csv: Pfad zur ALKIS-Eigentümer-CSV-Datei
    :param fc_gemeinden: Feature Class der Gemeinden
    :param fc_flurstuecke: Feature Class der Flurstücke
    :param output_table: Pfad zur Ausgabe-Eigentümer-Tabelle in der Geodatabase
    :param buffer_size: Puffergröße in Metern für die räumliche Verknüpfung
    :param cfg: Konfigurationsparameter
    :param keep_temp_data: Bool, ob temporäre Daten behalten werden sollen
    """
    # Pfad in GDB und Tabellenname zerlegen
    output_gdb = os.path.dirname(output_table)
    output_table_name = os.path.basename(output_table)

    arcpy.env.workspace = output_gdb

    # Schritt 1: csv bereinigen
    add_step_message("CSV vorbereiten", 1, 3)
    prepared_csv, abrufdatum = prepare_csv(alkis_csv)

    # Schritt 2: Eigentümer-Tabelle erstellen
    add_step_message("Eigentümer-Tabelle erstellen", 2, 3)
    make_eigentuemer_table(prepared_csv, output_gdb, output_table_name, abrufdatum, cfg)

    # Schritt 3: räumliche Verknüpfung mit Flurstücken und Gemeinden
    add_step_message("Räumliche Verknüpfung mit Flurstücken und Gemeinden", 3, 3)
    spatial_join_gem_flst(fc_gemeinden, fc_flurstuecke, output_table_name, buffer_size, cfg)

    if not keep_temp_data:
        # Zwischengespeicherte feature classes löschen
        arcpy.AddMessage("- Zwischenergebnisse löschen...")
        arcpy.Delete_management("buffer")
        arcpy.Delete_management("v_al_flurstueck_SpatialJoin")
        os.remove(prepared_csv)


def prepare_csv(input_csv):
    """
    entfernt die erste und die letzten fünf Zeilen (header und Codeerklärungen)
    speichert die bereinigte CSV in einer temporären Datei (im gleichen Verzeichnis wie input_csv)
    :param input_csv: Pfad zur Eingabe-CSV-Datei
    """
    encoding = "utf-8"

    # Temporäre CSV vorbereiten
    output_csv = os.path.join(os.path.dirname(input_csv), "prepared_" + os.path.basename(input_csv))

    with open(input_csv, "r", encoding=encoding) as f:
        lines = f.readlines()

    # Extrahiere Abrufdatum aus der ersten Zeile
    try:
        abrufdatum = lines[0][19:29]
        # Validiere Datumsformat DD.MM.YYYY
        datetime.strptime(abrufdatum, "%d.%m.%Y")
    except:
        arcpy.AddError("Fehler beim Auslesen des Abrufdatums aus der CSV-Datei.")
        raise
    # Entferne die erste und letzten fünf Zeilen
    lines = lines[1:-5]

    # Ersetze fehlerhafte HTML-Entity-Kodierungen und Encoding-Fehler
    decoded_lines = []
    for line in lines:
        # HTML-Entities - sowohl mit als auch ohne Semikolon
        line = line.rstrip("\r\n")
        line = line.replace("&apos;", "'")
        line = line.replace("&apos ", "'")
        line = line.replace("&amp;", "&")
        line = line.replace("&amp ", "&")

        # Encoding-Fehler beheben: Direkte Ersetzung der fehlerhaften Muster
        # UTF-8 als Latin-1 interpretiert
        mojibake_map = {"Ã¼": "ü", "Ã¶": "ö", "Ã¤": "ä", "ÃŸ": "ß", "Ã": "Ü", "Ã–": "Ö", "Ã„": "Ä", "Â": " "}
        for wrong, correct in mojibake_map.items():
            line = line.replace(wrong, correct)

        decoded_lines.append(line + "\n")

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
    arcpy.AddMessage("- Erstelle Eigentümer-Tabelle ...")
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
                arcpy.AddMessage(f"- Leeres Feld '{field.name}' wird entfernt...")

    if fields_to_delete:
        arcpy.DeleteField_management(owner_table, fields_to_delete)

    input_field = config["eigentuemer"]["fkz"]
    output_field = config["eigentuemer"]["fsk"]

    # Feld 'FSK' berechnen aus 'FKZ' und Tabelle hinzufügen
    arcpy.AddMessage("- Berechne FSK...")
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

    # neues Feld 'Abrufdatum' setzen
    arcpy.AddMessage("- Setze Abrufdatum...")
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
    arcpy.AddMessage("- Pufferlayer erstellen...")
    arcpy.MakeFeatureLayer_management(gem, "gemeinden_layer")
    arcpy.Buffer_analysis("gemeinden_layer", "buffer", f"{buffer_size} METER")

    # Spatial Join Flurstücke - Puffer
    join_field = config["eigentuemer"]["fsk"]
    arcpy.AddMessage("- Räumliche Verknüpfung durchführen...")
    arcpy.SpatialJoin_analysis(
        target_features=flst,
        join_features="buffer",
        out_feature_class="v_al_flurstueck_SpatialJoin",
        join_operation="JOIN_ONE_TO_ONE",
        join_type="KEEP_ALL",
        field_mapping=f'{join_field} "Flurstückskey" true true false 512 Text 0 0,First,#,{flst},{join_field},0,512;gemeinden_puffer "Gemeinden (Puffer)" true true false 100 Text 0 0,Join,", ",buffer,{config['gemeinde']['gemeinde_name']},0,50',
        match_option="INTERSECT",
        search_radius=None,
        distance_field_name="",
    )

    # Gemeindefelder hinzufügen und umbenennen wie in der Hosted Table
    # gemeinde: Gemeinde in der das Flurstück liegt
    # gemeinden_puffer: Gemeinden im Pufferbereich (mehrere Einträge möglich)
    arcpy.AddMessage("- Gemeindefelder zur Eigentümer-Tabelle hinzufügen...")

    # Gemeinde von Flurstücken joinen
    arcpy.JoinField_management(owner_table, join_field, flst, join_field, ["gemeinde_name"])
    arcpy.AlterField_management(owner_table, "gemeinde_name", new_field_name="gemeinde", new_field_alias="Gemeinde")

    # Gemeinden aus Spatial Join hinzufügen
    arcpy.JoinField_management(owner_table, join_field, "v_al_flurstueck_SpatialJoin", join_field, ["gemeinden_puffer"])

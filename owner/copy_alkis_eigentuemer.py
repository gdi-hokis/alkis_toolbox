import os
import arcpy
from datetime import datetime

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
    arcpy.AddMessage("-"*40)
    arcpy.AddMessage("Schritt 1 von 3 -- CSV vorbereiten ...")
    arcpy.AddMessage("-"*40)
    prepared_csv, abrufdatum = prepare_csv(alkis_csv)

    # Schritt 2: Eigentümer-Tabelle erstellen
    arcpy.AddMessage("-"*40)
    arcpy.AddMessage("Schritt 2 von 3 -- Eigentümer-Tabelle erstellen ...")
    arcpy.AddMessage("-"*40)
    make_eigentuemer_table(
        prepared_csv,
        output_gdb,
        output_table_name,
        abrufdatum,
        cfg
    )

    # Schritt 3: räumliche Verknüpfung mit Flurstücken und Gemeinden
    arcpy.AddMessage("-"*40)
    arcpy.AddMessage("Schritt 3 von 3 -- Räumliche Verknüpfung mit Flurstücken und Gemeinden ...")
    arcpy.AddMessage("-"*40)
    spatial_join_gem_flst(
        fc_gemeinden,
        fc_flurstuecke,
        output_gdb,
        output_table_name,
        buffer_size,
        cfg,
        keep_temp_data
    )

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

    with open(output_csv, "w", encoding=encoding, newline="") as f:
        f.writelines(lines)
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

    fld_flst = config["eigentuemer"]["flst"]

    # Feld 'flurstueck' umformatieren zu 'flstkey' und Tabelle hinzufügen
    arcpy.AddMessage("- Berechne FLSTKEY...")
    arcpy.CalculateField_management(
        in_table=owner_table,
        field="flstkey",
        expression=f"calcFLSTKEY(!{fld_flst}!)",
        expression_type="PYTHON3",
        code_block="""def calcFLSTKEY(s):
        teile = s.split("-")
        gemarkung = str(int(teile[0][2:]))             # "080237" → "237"
        flur = str(int(teile[1]))            # "000" → "0"
        zaehler, nenner = teile[2].split("/")  # z.B. "00023/0006"
        zaehler = str(int(zaehler))
        if nenner.strip() == "0000":
            return f"{gemarkung}-{flur}-{zaehler}"
        else:
            nenner = str(int(nenner))
            return f"{gemarkung}-{flur}-{zaehler}/{nenner}"
        """,
        field_type="TEXT",
        enforce_domains="NO_ENFORCE_DOMAINS"
    )

    fld_fkz = config["eigentuemer"]["fkz"]

    # Feld 'FSK' berechnen aus 'FKZ' und Tabelle hinzufügen
    arcpy.AddMessage("- Berechne FSK...")
    arcpy.CalculateField_management(
        in_table= owner_table,
        field = "FSK",
        expression=f"replaceZerosInFSK(!{fld_fkz}![1:-1])",
        expression_type="PYTHON3",
        code_block="""def replaceZerosInFSK(flstId):
        fsk = flstId
        if fsk[6:9] == "000":
            fsk = fsk[:6] + "___" + fsk[9:]
        if fsk[14:18] == "0000":
            fsk = fsk[:14] + "____" + fsk[18:]
        return fsk
        """,
        field_type="TEXT",
        enforce_domains="NO_ENFORCE_DOMAINS",
    )

    # neues Feld 'Abrufdatum' setzen
    arcpy.AddMessage("- Setze Abrufdatum...")
    arcpy.CalculateField_management(
        owner_table,
        "abrufdatum",
        f'"{abrufdatum}"',
        "PYTHON3",
        field_type="DATE"
    )

def spatial_join_gem_flst(gem, flst, gdb, owner_table, buffer_size, config, keep_temp_data):
    """   
    Erstellt einen Puffer (der Größe des Parameters 'buffer_size') um die Gemeinden
    des gewählten Gebiets und verknüpft diese räumlich mit den Flurstücken. 
    Anschließend werden zwei Gemeindefelder zur Eigentümer-Tabelle hinzugefügt:
    - 'gemeinde': Gemeindename für Flurstücke innerhalb der Gemeindegrenze
    - 'gemeinde_name': Gemeindename für Flurstücke im Pufferbereich (können mehrere Einträge haben)
    
    :param gem: Feature Class der Gemeinden mit Feld 'gemeinde_name'
    :param flst: Feature Class der Flurstücke mit Feld 'flstkey'
    :param gdb: Pfad zur Geodatabase
    :param owner_table: Name der ArcGIS-Eigentümer-Tabelle
    :param buffer_size: Größe des Puffers in Metern
    :param config: Konfigurationsparameter
    :param keep_temp_data: Bool, ob temporäre Daten behalten werden sollen
    """
    # Puffer
    # makefeaturelayer, damit ein Originallayer unverändert bleibt und Funktion mit shapefiles funktioniert
    arcpy.AddMessage("- Pufferlayer erstellen...")
    arcpy.MakeFeatureLayer_management(gem, "gemeinden_layer")
    arcpy.Buffer_analysis("gemeinden_layer", "buffer", f"{buffer_size} METER")

    # Spatial Join Flurstücke - Puffer
    fld_flstkey = config["flurstueck"]["flstkey"]
    arcpy.AddMessage("- Räumliche Verknüpfung durchführen...")
    arcpy.SpatialJoin_analysis(
        target_features=flst,
        join_features="buffer",
        out_feature_class="v_al_flurstueck_SpatialJoin",
        join_operation="JOIN_ONE_TO_ONE",
        join_type="KEEP_ALL",
        field_mapping=f'{fld_flstkey} "Flurstückskey" true true false 512 Text 0 0,First,#,{gdb}\\v_al_flurstueck,{fld_flstkey},0,512;gemeinde_name_1 "Gemeinde" true true false 100 Text 0 0,Join,", ",buffer,gemeinde_name,0,50',
        match_option="INTERSECT",
        search_radius=None,
        distance_field_name="",
    )

    # Gemeindefelder hinzufügen und umbenennen wie in der Hosted Table
    # gemeinde_name: Gemeinde in der das Flurstück liegt
    # gemeinde: Gemeinde im Pufferbereich (mehrere Einträge möglich)
    arcpy.AddMessage("- Gemeindefelder zur Eigentümer-Tabelle hinzufügen...")
    arcpy.JoinField_management(owner_table, "flstkey", flst, "flstkey", ["gemeinde_name"])
    arcpy.AlterField_management(owner_table, "gemeinde_name", new_field_name="gemeinde")
    arcpy.DeleteField_management(owner_table,"gemeinde_name")
    arcpy.JoinField_management(owner_table, "flstkey", "v_al_flurstueck_SpatialJoin", "flstkey", ["gemeinde_name_1"])
    arcpy.AlterField_management(owner_table, "gemeinde_name_1", new_field_name="gemeinde_name")
    arcpy.DeleteField_management(owner_table,"gemeinde_name_1")

    if not keep_temp_data:
        # Zwischengespeicherte feature classes löschen
        arcpy.AddMessage("- Zwischenergebnisse löschen...")
        arcpy.Delete_management("buffer")
        arcpy.Delete_management("v_al_flurstueck_SpatialJoin")

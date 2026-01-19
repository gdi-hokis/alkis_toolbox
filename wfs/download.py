import arcpy
import os
import json
import time
import requests
from datetime import datetime

def wfs_download(polygon_fc, checked_layers, target_gdb, workspace_gdb, work_dir, checkbox, cell_size, timeout, verify, cfg):
    if timeout == 0:
        timeout = None

    req_settings = [timeout, verify]

    # Prüfen ob Layernamen des wfs geändert wurden
    layer_list = checked_layers.split(";")
    if not layer_list[0].startswith("nora:"):
        arcpy.AddMessage("!!!Achtung!!! Die Layernamen im Dienst wurden geändert. Bitte beachten!")

    arcpy.AddMessage(f"Ziel-Geodatabase ausgewählt: {target_gdb}")
    arcpy.AddMessage(f"Temporärer Workspace ausgewählt: {workspace_gdb}")
    arcpy.AddMessage(f"Layer ausgewählt: {layer_list}")

    process_fc = []
    i = 2 if checkbox else 3

    # Schritt 1: Bounding Boxen erstellen
    arcpy.AddMessage("-"*40)
    arcpy.AddMessage(f"Schritt 1 von {i} -- Download-Grids erstellen ...")
    arcpy.AddMessage("-"*40)
    grid = create_grid_from_polygon(polygon_fc, workspace_gdb, cell_size, process_fc)

    # Schritt 2: Wfs im Bereich der Bounding Boxen downloaden
    arcpy.AddMessage("-"*40)
    arcpy.AddMessage(f"Schritt 2 von {i} -- WFS-Daten herunterladen ...")
    arcpy.AddMessage("-"*40)
    process_data, process_fc = download_wfs(grid, layer_list, target_gdb, workspace_gdb, work_dir, req_settings, polygon_fc, cfg, process_fc)

    # Schritt 3: Verarbeitungsdaten wieder entfernen
    if checkbox is False:
        arcpy.AddMessage("-"*40)
        arcpy.AddMessage(f"Schritt 3 von {i} -- Verarbeitungsdaten entfernen ...")
        arcpy.AddMessage("-"*40)
        # Verarbeitungsdaten aus geodatabase entfernen
        for fc in process_fc:
            if arcpy.Exists(fc):
                arcpy.Delete_management(fc, "")

        # Verarbeitungsdaten aus lokalem Ordner entfernen
        for json_file in process_data:
            os.remove(json_file)


def create_grid_from_polygon(polygon_fc, gdb, cell_size, process_fc):
    """
    Erstellt ein Grid aus quadratischen Extents innerhalb eines Polygons.
    Dabei werden drei Fälle unterschieden:
    1. Wenn beide Kantenlängen (x und y) kleiner als cell_size sind,
        wird der Extent übernommen.
    2. Wenn nur eine Dimension kleiner als cell_size ist, wird in dieser Richtung
        nur eine Zelle erzeugt, in der anderen Richtung volle Zellen (cell_size)
        und ggf. eine Restzelle.
    3. Wenn beide Dimensionen größer als cell_size sind, werden volle Zellen plus
        ggf. Restzellen erzeugt.


    :param polygon_fc: Feature-Class des Eingabe-Polygons
    :param gdb: Geodatabase in die die Bounding Box gespeichert wird
    :param cell_size: Seitenlänge der vollen Zellen in Metern (Standard: 20000m)
    """

    # Spatial Reference übernehmen
    spatial_ref = arcpy.Describe(polygon_fc).spatialReference

    # Output-Feature-Class in definierter gdb neu anlegen
    arcpy.AddMessage("- Bounding Box Feature Class wird erstellt...")
    fc_name = arcpy.Describe(polygon_fc).name
    if "." in fc_name:
        fc_name = fc_name.split(".")[0]
    bbox_name = fc_name + "_bbox"
    bbox_fc = os.path.join(gdb, bbox_name)

    # bei Nichtanhaken Löschen der temporären Daten
    process_fc.append(bbox_name)

    arcpy.management.MinimumBoundingGeometry(
        in_features=polygon_fc,
        out_feature_class=bbox_fc,
        geometry_type="ENVELOPE",
        group_option="ALL",
        group_field=None,
        mbg_fields_option="NO_MBG_FIELDS",
    )

    desc = arcpy.Describe(bbox_fc)
    extent = desc.extent
    polygon_extent = arcpy.Extent(extent.lowerLeft.X, extent.lowerLeft.Y, extent.upperRight.X, extent.upperRight.Y)

    # Extent-Koordinaten des Eingabe-Polygons
    min_x, min_y, max_x, max_y = extent.lowerLeft.X, extent.lowerLeft.Y, extent.upperRight.X, extent.upperRight.Y
    edge_x = max_x - min_x  # Kantenlängen
    edge_y = max_y - min_y

    # Liste zur Speicherung der Extents-Strings
    bboxes = []

    arcpy.AddMessage(f"- Erstelle Grid mit Zellen der Kantenlänge {cell_size}m...")

    # Fall 1: Beide Kantenlängen kleiner als cell_size → gesamter Extent
    if edge_x < cell_size and edge_y < cell_size:
        num_x = 1
        num_y = 1

    # Fall 2 und 3
    else:
        # Ermittlung der Anzahl Zellen in X- und Y-Richtung
        if edge_x <= cell_size:
            num_x = 1
        else:
            num_x = int(edge_x // cell_size)
            if edge_x % cell_size > 0:
                num_x += 1

        if edge_y <= cell_size:
            num_y = 1
        else:
            num_y = int(edge_y // cell_size)
            if edge_y % cell_size > 0:
                num_y += 1

    arcpy.AddMessage(f"- Grid mit {num_x * num_y} Zellen wird erstellt...")

    # Grid-Zellen erzeugen und Extents als String speichern
    with arcpy.da.InsertCursor(bbox_fc, ["SHAPE@"]) as insert_cursor:
        for i in range(num_x):
            # Für alle außer des letzten Grids: cell_size, sonst Restlänge
            current_width = cell_size if i < num_x - 1 else (edge_x - i * cell_size)
            for j in range(num_y):
                # Für alle außer des letzten Grids: cell_size, sonst Restlänge
                current_height = cell_size if j < num_y - 1 else (edge_y - j * cell_size)
                x1 = min_x + i * cell_size
                y1 = min_y + j * cell_size
                x2 = x1 + current_width
                y2 = y1 + current_height

                square = arcpy.Polygon(
                    arcpy.Array(
                        [
                            arcpy.Point(x1, y1),
                            arcpy.Point(x2, y1),
                            arcpy.Point(x2, y2),
                            arcpy.Point(x1, y2),
                            arcpy.Point(x1, y1),
                        ]
                    ),
                    spatial_ref,
                )

                # Füge die Zelle nur hinzu, wenn sie das Input-Polygon schneidet
                # if square.overlaps(polygon_geom) or square.within(polygon_geom) or polygon_geom.contains(square):
                if not square.disjoint(polygon_extent):
                    insert_cursor.insertRow([square])
                    # Extents-String für das aktuelle Rechteck
                    bboxes.append(f"{x1},{y1},{x2},{y2}")

    return bboxes

def download_wfs(grid, layer_list, target_gdb, workspace_gdb, work_dir, req_settings, polygon_fc, cfg, process_fc):
    """
    Führt den Download von Layern vom WFS in Form von json-Dateien im durch die Bounding Boxen begrenzten Bereich durch
    und speichert diese in Feature Klassen in der übergebenen gdb

    :param grid: Feature Class des Bereichs als Rechteck(e)
    :param layer_list: Liste der zu downloadenden Layer
    :param target_gdb: Geodatabase in die die Endergebnisse gespeichert werden
    :param workspace_gdb: Arbeitsdatenbank für temporäre Daten
    :param work_dir: lokal ausgewählter Ordner für die json-files
    :param req_settings: Liste mit Einstellungen zum Request: [timeout(int), verify(boolean)]
    :param polygon_fc: Feature-Class des Eingabe-Polygons (zum Löschen von vollständig außerhalb liegenden Polygonen)
    """

    process_data = []

    # Bounding Boxen
    arcpy.env.overwriteOutput = True

    list_lenght = len(layer_list)
    i = 1

    # Layer downloaden
    for layer in layer_list:
        arcpy.AddMessage(f"Layer {i}/{list_lenght}: {layer}...")
        wildcards = []

        for index, bbox in enumerate(grid):
            layer_files, process_data, process_fc = downloadJson(bbox, layer, work_dir, index, req_settings, cfg, process_data, process_fc, workspace_gdb)

            if layer_files:
                # für Filtern der Merge Feature Klassen und Benennung
                for layer_file in layer_files:
                    wildcard = "*" + layer_file + "_*"
                    if not wildcard in wildcards:
                        wildcards.append(wildcard)

        # Merge pro Geometrietyp durchführen
        arcpy.env.workspace = workspace_gdb
        for wildcard in wildcards:
            fc = arcpy.ListFeatureClasses(wildcard)
            # Extrahiere den Ausgabename ohne Geometrietyp bei gleichen Typen
            parts = wildcard.rsplit("_", 2)
            output_fc = parts[0][1:]
            # Mit Geometrietyp
            if len(wildcards) > 1:
                output_fc = wildcard[1:-2]

            output_fc_path = os.path.join(workspace_gdb, output_fc)
            arcpy.Merge_management(fc, output_fc_path)

        # Alle Felder auflisten
        fields = arcpy.ListFields(output_fc)
        field_names = [field.name for field in fields]

        identify_fields = ["Shape"]
        for identity_field in cfg["wfs_config"]["identify_fields"]:
            if identity_field in field_names:
                identify_fields.append(identity_field)

        param = ";".join(identify_fields)
        arcpy.DeleteIdentical_management(output_fc, "{0}".format(param))

        arcpy.AddField_management(in_table=output_fc, field_name="Abrufdatum", field_type="DATE")

        shorten_string_fields(output_fc, fields)

        output_fc_2D = output_fc + "_tmp"
        arcpy.env.outputZFlag = "Disabled"
        arcpy.env.outputMFlag = "Disabled"

        arcpy.AddMessage("- 2D-Konvertierung...")
        arcpy.FeatureClassToFeatureClass_conversion(in_features=output_fc, out_path=target_gdb, out_name=output_fc_2D)

        arcpy.Delete_management(output_fc)
        
        # Ab hier in target_gdb arbeiten
        arcpy.AddMessage("- Z-Werte entfernen...")
        output_fc_final = os.path.join(target_gdb, output_fc_2D)
        output_fc_target = os.path.join(target_gdb, output_fc)
        arcpy.Rename_management(output_fc_final, output_fc_target)

        arcpy.AddMessage("- vollständig außerhalb des Eingabepolygons liegende Geometrien entfernen...")
        intersect(polygon_fc, output_fc_target)

        # Feldberechnungen für spezifische Layer durchführen
        perform_field_calculations(output_fc, target_gdb)
        i += 1
    return process_data, process_fc

def getDifferentGeometryTypes(json_file):
    """
    Teilt Layer mit verschiedenen Geometrietypen auf
    """
    geometry_types = []
    with open(json_file, "r", encoding="utf-8") as geojson_file:
        geojson_data = json.load(geojson_file)
        for feature in geojson_data["features"]:
            geometry_type = feature["geometry"]["type"]
            if not geometry_type in geometry_types:
                geometry_types.append(geometry_type)
    return {"geometry_types": geometry_types, "geojson_data": geojson_data}

def saveExtraJson(layer_name, geojson_data, geometry_type, work_dir):
    """
    Bei mehreren Geometrietypen werden die JSON-Daten separat gespeichert
    """
    json_data = {
        "type": "FeatureCollection",
        "features": [],
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::25832"}},
    }
    for feature in geojson_data["features"]:
        if feature["geometry"]["type"] == geometry_type:
            json_data["features"].append(feature)

    with open(work_dir + os.sep + "{0}.json".format(layer_name), "w", encoding="utf-8") as geometry_file:
        json.dump(json_data, geometry_file)

def downloadJson(bbox, layer, work_dir, index, req_settings, cfg, process_data, process_fc, workspace_gdb):
    """
    Führt den Download eines Rechteckes durch

    :param bbox: Bounding Box eines Rechteckes
    :param layer: zu downloadender Layer
    :param work_dir: lokal ausgewählter Ordner für die json-files
    :param index: iterieren der Dateinamen (bei mehr als einem Rechteck notwendig)
    :param workspace_gdb: Geodatabase für Zwischenergebnisse
    """
    url = cfg["wfs_config"]["wfs_url"]

    params = cfg["wfs_config"]["params_feature"]
    params["typename"] = layer
    params["bbox"] = bbox

    timeout = req_settings[0]
    verify = req_settings[1]

    # Request ausführen
    response = requests.get(url, params=params, timeout=timeout, verify=verify)

    v_al_layer = layer.replace(":", "_")  # Doppelpunkt in Dateipfad unzulässig
    layer_name = v_al_layer + "_" + str(index)

    if not response.status_code == 200:
        arcpy.AddWarning(f"Error {response.status_code}: {response.reason} beim Downloadversuch des Layers {layer}")
        return

    # Datei speichern
    json_file = work_dir + os.sep + "{0}.json".format(layer_name)
    process_data.append(json_file)
    with open(json_file, "wb") as f:
        f.write(response.content)

    # verschiedene Geometrietypen im JSON finden und auftrennen, wenn nötig --> v_al_vergleichsstueck
    layer_files = []
    geometry_info = getDifferentGeometryTypes(json_file)
    geometry_types = geometry_info["geometry_types"]
    geojson_data = geometry_info["geojson_data"]
    if len(geometry_types) > 1:
        arcpy.AddMessage(f"- Der Layer {v_al_layer} enthält mehrere Geometrietypen: {geometry_types}. Diese werden aufgetrennt...")

    for geometry_type in geometry_types:
        layer_name_geometry = v_al_layer + "_" + geometry_type + "_" + str(index)
        output_fc_path = os.path.join(workspace_gdb, layer_name_geometry)
        
        if len(geometry_types) == 1:
            arcpy.JSONToFeatures_conversion(json_file, output_fc_path)
            layer_files.append(layer_name_geometry.rsplit("_", 1)[0])

        # in getrennte Dateien schreiben und dann erst in Feature Class konvertieren
        elif len(geometry_types) > 1:
            saveExtraJson(layer_name_geometry, geojson_data, geometry_type, work_dir)

            arcpy.JSONToFeatures_conversion(
                work_dir + os.sep + "{0}.json".format(layer_name_geometry), output_fc_path
            )
            # Dateiname für später ohne Bounding Box Info (nötig, weil sonst der Zusatz Geometrietyp fehlt)
            layer_files.append(layer_name_geometry.rsplit("_", 1)[0])

            # Ursprünglich Downgeloadete Daten mit beiden FeatureTypes löschen, sonst Verwirrung
            arcpy.Delete_management(layer_name)

        # fügt Namen der erzeugten Feature Class einer Liste hinzu, zum Löschen (je nach Checkbox) der temporären Daten
        process_fc.append(layer_name_geometry)

    return layer_files, process_data, process_fc

def shorten_string_fields(output_fc, fields):
    arcpy.AddMessage("- String-Feldlängen kürzen")
    # Liste für die Feldzuordnung
    field_mappings = []

    # Feldlänge der Felder mit Dateityp String von 20000000 auf 255 kürzen
    e = 0
    # neues temp-Feld anlegen und Layername zu Liste hinzufügen
    # Felder sammeln, die hinzugefügt werden sollen (nur neue Temp-Felder)
    fields_to_add = []

    for field in fields:
        if field.type == "String" and field.length > 255:
            new_field = field.name + "_temp"

            # AddFields erwartet: [name, type, precision, scale, length]
            fields_to_add.append([new_field, "TEXT", "", 255])

            # Deine bestehende Zuordnung bleibt unverändert
            field_mappings.append((field.name, new_field))

            e += 1
    if fields_to_add:
        arcpy.management.AddFields(output_fc, fields_to_add)

    if field_mappings:
        cursor_fields = []
        for field, field_temp in field_mappings:
            cursor_fields.extend([field, field_temp])
        cursor_fields.append("Abrufdatum")

        row_count = 0
        with arcpy.da.UpdateCursor(output_fc, cursor_fields) as cursor:
            for row in cursor:
                # Für jedes Paar (new_field, old_field) wird der Wert vom alten in das neue Feld kopiert.
                for i in range(0, len(cursor_fields) - 1, 2):
                    row[i + 1] = row[i]
                row[-1] = datetime.now()
                cursor.updateRow(row)
                row_count += 1

        # alte Felder löschen, temp-Felder umbenennen
        fields_to_delete = [field for field, _ in field_mappings]
        arcpy.DeleteField_management(output_fc, ";".join(fields_to_delete))  # EINE Operation!

        # Dann umbenennen (leider muss das einzeln, aber schneller weil FC kleiner):
        for field, field_temp in field_mappings:
            arcpy.AlterField_management(output_fc, field_temp, new_field_name=field)

def perform_field_calculations(output_fc, gdb):
    """
    Führt spezifische Feldberechnungen für die heruntergeladenen Layer durch.
    Behandelt:
    - v_al_flurstueck: Flurnummer-ID, FSK, FLSTKEY, locator_place
    - v_al_bodenschaetzung_f: Label-Beschriftung
    - v_al_gebaeude: object_id UUID

    :param output_fc: Name der Feature Class
    :param gdb: Geodatabase-Pfad
    """
    try:
        import wfs.field_calculations

        output_fc_path = os.path.join(gdb, output_fc)

        # Flurstücke - Feldberechnungen
        if output_fc == "nora_v_al_flurstueck":
            arcpy.AddMessage("- Starte Feldberechnungen für Flurstücke...")

            # Flurnummer-Berechnung benötigt auch v_al_flur
            if arcpy.Exists(os.path.join(gdb, "nora_v_al_flur")):
                flur_fc_path = os.path.join(gdb, "nora_v_al_flur")
                wfs.field_calculations.calculate_flurnummer_l(flur_fc_path, output_fc_path)
                wfs.field_calculations.join_flurnamen(output_fc_path, flur_fc_path)
                wfs.field_calculations.calculate_locator_place(output_fc_path)
                wfs.field_calculations.clean_up_flur_fields(flur_fc_path)

            # FSK und FLSTKEY
            wfs.field_calculations.calculate_fsk(output_fc_path)
            wfs.field_calculations.calculate_flstkey(output_fc_path)

        # Bodenschätzung - Label-Berechnung
        elif output_fc == "nora_v_al_bodenschaetzung_f":
            arcpy.AddMessage("- Starte Feldberechnungen für Bodenschätzung...")
            wfs.field_calculations.calculate_label_bodensch(output_fc_path)

        # Gebäude - object_id Generierung
        elif output_fc == "nora_v_al_gebaeude":
            arcpy.AddMessage("- Starte Feldberechnungen für Gebäude...")
            wfs.field_calculations.calculate_gebaeude_object_id(output_fc_path)

    except Exception as e:
        arcpy.AddWarning(f"Feldberechnungen für {output_fc} konnten nicht durchgeführt werden: {str(e)}")

def intersect(polygon_fc, output_fc):
    """
    Löscht alle Polygone des outputs des wfs, die vollständig außerhalb des Eingabe-Fensters liegen
    (Aufgrund des Abrufs der wfs-Daten mit der Bounding-Box wird in der Regel deutlich über den Eingabe-Bereich abgerufen und gedownloaded)

    :param polygon_fc: Feature-Class des Eingabe-Polygons
    :param output_fc: Feature-Class des Downloads des WFS
    """
    input_lyr = "lyr_input_tmp"
    arcpy.MakeFeatureLayer_management(polygon_fc, input_lyr)
    output_lyr = "lyr_output_tmp"
    arcpy.MakeFeatureLayer_management(output_fc, output_lyr)

    arcpy.SelectLayerByLocation_management(
        in_layer=output_lyr,
        overlap_type="INTERSECT",
        select_features=input_lyr,
        selection_type="NEW_SELECTION",
        invert_spatial_relationship="INVERT",
    )

    arcpy.DeleteFeatures_management(output_lyr)
    arcpy.Delete_management(input_lyr)
    arcpy.Delete_management(output_lyr)

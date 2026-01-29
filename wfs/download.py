import os
import json
import time
from datetime import datetime
import arcpy
import requests
from utils import add_step_message


def wfs_download(
    polygon_fc, checked_layers, target_gdb, workspace_gdb, work_dir, checkbox, cell_size, timeout, verify, cfg
):
    if not timeout:
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

    # Schritt 1: Bounding Boxen erstellen
    add_step_message("Download-Grids erstellen", 1, 2)
    grid = create_grid_from_polygon(polygon_fc, workspace_gdb, cell_size, process_fc)

    # Schritt 2: Wfs im Bereich der Bounding Boxen downloaden
    add_step_message("WFS-Daten herunterladen", 2, 2)
    process_data, process_fc = download_wfs(
        grid, layer_list, target_gdb, workspace_gdb, work_dir, req_settings, polygon_fc, cfg, process_fc
    )

    # Schritt 3: Verarbeitungsdaten wieder entfernen
    if checkbox is False:
        add_step_message("CLEANUP -- Lösche Verarbeitungsdaten")

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
    arcpy.AddMessage("- Bounding Box Feature-Class wird erstellt...")
    fc_name = arcpy.Describe(polygon_fc).name
    if "." in fc_name:
        fc_name = fc_name.split(".")[0]
    bbox_name = fc_name + "_bbox"
    bbox_fc = os.path.join(gdb, bbox_name)

    arcpy.MinimumBoundingGeometry_management(
        in_features=polygon_fc,
        out_feature_class=bbox_fc,
        geometry_type="ENVELOPE",
        group_option="ALL",
        group_field=None,
        mbg_fields_option="NO_MBG_FIELDS",
    )

    desc = arcpy.Describe(bbox_fc)
    ext = desc.extent
    polygon_ext = arcpy.Extent(ext.lowerLeft.X, ext.lowerLeft.Y, ext.upperRight.X, ext.upperRight.Y)

    # Extent-Koordinaten des Eingabe-Polygons
    min_x, min_y, max_x, max_y = ext.lowerLeft.X, ext.lowerLeft.Y, ext.upperRight.X, ext.upperRight.Y
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
                if not square.disjoint(polygon_ext):
                    insert_cursor.insertRow([square])
                    # Extents-String für das aktuelle Rechteck
                    bboxes.append(f"{x1},{y1},{x2},{y2}")

    # bei Nichtanhaken Löschen der temporären Daten
    process_fc.append(bbox_fc)
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
    arcpy.env.overwriteOutput = True

    # Spatial Reference für Template-Feature-Classes
    spatial_ref = arcpy.Describe(polygon_fc).spatialReference

    list_lenght = len(layer_list)
    i = 1

    # Layer downloaden
    for layer in layer_list:
        arcpy.AddMessage(f"Layer {i}/{list_lenght}: {layer}...")

        # Template-FC Dictionary für diesen Layer (wird beim ersten Download erstellt)
        template_fcs = None
        v_al_layer = layer.replace(":", "_")

        # Dictionary zum Sammeln aller temp FCs pro Geometrietyp
        all_temp_fcs = {}

        for index, bbox in enumerate(grid):
            json_file = download_json(bbox, layer, work_dir, index, req_settings, cfg, process_data, v_al_layer)
            if json_file is None:
                continue

            # Beim ersten erfolgreichen Download: Template-Feature-Class erstellen
            if template_fcs is None:
                arcpy.AddMessage("- Erstelle Template Feature-Class...")
                template_fcs = create_template_fc(json_file, v_al_layer, target_gdb, spatial_ref)

                if not template_fcs:
                    arcpy.AddWarning(f"- Konnte kein Template für {layer} erstellen")
                    break

            # Temp FCs erstellen und sammeln (noch nicht appenden!)
            temp_fcs = prepare_for_merge(json_file, template_fcs, spatial_ref, workspace_gdb, target_gdb, v_al_layer)

            # Temp FCs nach Geometrietyp sammeln
            for geom_type, fc_list in temp_fcs.items():
                if geom_type not in all_temp_fcs:
                    all_temp_fcs[geom_type] = []
                all_temp_fcs[geom_type].extend(fc_list)

        # Nach allen Downloads: Temp FCs per Merge zusammenfassen und dann in Template appenden
        if template_fcs and all_temp_fcs:
            arcpy.AddMessage("- Füge alle vorbereiteten Features zusammen...")

            for geom_type, temp_fc_list in all_temp_fcs.items():
                if geom_type in template_fcs:
                    template_fc = template_fcs[geom_type]
                    total_features = sum(int(arcpy.GetCount_management(fc)[0]) for fc in temp_fc_list)

                    arcpy.AddMessage(
                        f"- Merge von {len(temp_fc_list)} temporären FCs mit insgesamt {total_features} Features..."
                    )

                    # Erst alle temp FCs mergen (um Feldlängen zu erhalten)
                    merged_temp_fc = os.path.join(workspace_gdb, f"merged_temp_{geom_type}_{int(time.time())}")
                    arcpy.Merge_management(temp_fc_list, merged_temp_fc)

                    # Dann in Template FC appenden
                    arcpy.AddMessage(f"- Appende {total_features} Features in Template FC...")
                    arcpy.Append_management(merged_temp_fc, template_fc, "NO_TEST")

                    # Gemergte temp FC zur Löschliste hinzufügen
                    process_fc.append(merged_temp_fc)
                    process_fc.extend(temp_fc_list)

        # Duplikate entfernen und Geometrien außerhalb des Eingabepolygons löschen
        if template_fcs:
            for geom_type, fc_path in template_fcs.items():
                # Duplikate entfernen
                fields = arcpy.ListFields(fc_path)
                field_names = [field.name for field in fields]

                identify_fields = ["Shape"]
                for identity_field in cfg["wfs_config"]["identify_fields"]:
                    if identity_field in field_names:
                        identify_fields.append(identity_field)

                param = ";".join(identify_fields)
                arcpy.AddMessage("- Duplikate entfernen...")
                arcpy.DeleteIdentical_management(fc_path, f"{param}")

                # Geometrien außerhalb des Eingabepolygons entfernen
                arcpy.AddMessage("- vollständig außerhalb des Eingabepolygons liegende Geometrien entfernen...")
                intersect(polygon_fc, fc_path)

        i += 1
    return process_data, process_fc


def download_json(bbox, layer, work_dir, index, req_settings, cfg, process_data, v_al_layer):
    """
    Führt den Download eines Rechteckes durch und speichert als JSON-Datei
    :param bbox: Bounding Box eines Rechteckes
    :param layer: zu downloadender Layer
    :param work_dir: lokal ausgewählter Ordner für die json-files
    :param index: iterieren der Dateinamen (bei mehr als einem Rechteck notwendig)
    :param v_al_layer: Layer-Name mit ersetztem Doppelpunkt
    :return: Pfad zur JSON-Datei oder None bei Fehler
    """
    url = cfg["wfs_config"]["wfs_url"]

    params = cfg["wfs_config"]["params_feature"]
    params["typename"] = layer
    params["bbox"] = bbox

    timeout = req_settings[0]
    verify = req_settings[1]

    # Request ausführen
    response = requests.get(url, params=params, timeout=timeout, verify=verify)

    layer_name = v_al_layer + "_" + str(index)

    if not response.status_code == 200:
        arcpy.AddWarning(f"Error {response.status_code}: {response.reason} beim Downloadversuch des Layers {layer}")
        return None

    # Datei speichern
    json_file = work_dir + os.sep + f"{layer_name}.json"
    process_data.append(json_file)
    with open(json_file, "wb") as f:
        f.write(response.content)

    return json_file


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


def get_arcgis_geometry_type(geojson_type):
    """
    Konvertiert GeoJSON-Geometrietyp zu ArcGIS-Geometrietyp
    """
    mapping = {
        "Point": "POINT",
        "MultiPoint": "MULTIPOINT",
        "LineString": "POLYLINE",
        "MultiLineString": "POLYLINE",
        "Polygon": "POLYGON",
        "MultiPolygon": "POLYGON",
    }
    arcgis_geom_type = mapping.get(geojson_type, None)
    if arcgis_geom_type is None:
        arcpy.AddWarning(f"- Unbekannter Geometrietyp {geojson_type}, wird übersprungen")
    return arcgis_geom_type


def infer_field_type(value):
    """
    Leitet Feldtyp und -länge aus Beispielwert ab
    """
    if value is None:
        return "TEXT", 255
    elif isinstance(value, bool):
        return "SHORT", None
    elif isinstance(value, int):
        return "LONG", None
    elif isinstance(value, float):
        return "DOUBLE", None
    else:
        return "TEXT", 255


def create_template_fc(json_file, layer_name, target_gdb, spatial_ref, force_suffix=False):
    """
    Erstellt Template-Feature-Class(es) basierend auf JSON-Schema.
    Felder werden direkt mit korrekter Länge angelegt.
    Feature-Class wird direkt in 2D erstellt.

    :param json_file: Pfad zur JSON-Datei
    :param layer_name: Name des Layers (ohne Geometrietyp-Suffix)
    :param target_gdb: Ziel-Geodatabase
    :param spatial_ref: epsg-code
    :param force_suffix: Erzwingt Geometrietyp-Suffix auch bei nur einem Geometrietyp
    :return: Dictionary {geometry_type: feature_class_path}
    """
    with open(json_file, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    if not geojson["features"]:
        arcpy.AddWarning(f"- Keine Features in {json_file} gefunden")
        return {}

    # Verschiedene Geometrietypen sammeln
    geometry_types = set()
    properties_by_geom = {}

    for feature in geojson["features"]:
        geom_type = feature["geometry"]["type"]
        geometry_types.add(geom_type)
        if geom_type not in properties_by_geom:
            properties_by_geom[geom_type] = feature["properties"]

    # Benutzer informieren wenn mehrere Geometrietypen vorhanden
    if len(geometry_types) > 1:
        arcpy.AddMessage(
            f"- Der Layer {layer_name} enthält mehrere Geometrietypen: {list(geometry_types)}. Diese werden aufgetrennt..."
        )

    # Template für jeden Geometrietyp erstellen
    template_fcs = {}

    # 2D-Flags setzen
    arcpy.env.outputZFlag = "Disabled"
    arcpy.env.outputMFlag = "Disabled"

    for geom_type in geometry_types:
        # Feature Class Name (mit Suffix wenn mehrere Geometrietypen oder force_suffix=True)
        if len(geometry_types) > 1 or force_suffix:
            fc_name = f"{layer_name}_{geom_type}"
        else:
            fc_name = layer_name

        # Feature Class erstellen
        arcgis_geom_type = get_arcgis_geometry_type(geom_type)
        if arcgis_geom_type is None:
            continue

        arcpy.CreateFeatureclass_management(
            out_path=target_gdb, out_name=fc_name, geometry_type=arcgis_geom_type, spatial_reference=spatial_ref
        )

        # Vollständiger Pfad zur gerade erstellten FC
        template_fc = os.path.join(target_gdb, fc_name)

        # Felder aus Properties ableiten und hinzufügen
        properties = properties_by_geom[geom_type]
        fields_to_add = []

        for field_name, value in properties.items():
            # von ArcGIS reservierte Feldnamen überspringen
            if field_name.upper() in ["OBJECTID", "SHAPE", "FID", "OID"]:
                continue

            field_type, field_length = infer_field_type(value)

            if field_type == "TEXT":
                fields_to_add.append([field_name, field_type, "", field_length])
            else:
                fields_to_add.append([field_name, field_type])

        # Abrufdatum hinzufügen
        fields_to_add.append(["Abrufdatum", "DATE"])

        if fields_to_add:
            arcpy.AddFields_management(template_fc, fields_to_add)

        template_fcs[geom_type] = template_fc
        arcpy.AddMessage(f"- Template-FC erstellt: {fc_name} (Geometrietyp: {geom_type})")

    return template_fcs


def prepare_for_merge(json_file, template_fc_dict, spatial_ref, workspace_gdb, target_gdb, layer_name):
    """
    Fügt Features aus JSON-Datei in entsprechende Template-Feature-Classes ein.
    Verwendet JSONToFeatures für korrekte Geometrie-Konvertierung.
    Temporäre FCs werden gesammelt und später per Merge eingefügt.
    Erstellt fehlende Templates dynamisch, wenn neue Geometrietypen auftauchen.

    :param json_file: Pfad zur JSON-Datei
    :param template_fc_dict: Dictionary {geometry_type: feature_class_path}
    :param spatial_ref: Spatial Reference für Geometrien
    :param workspace_gdb: Arbeitsdatenbank für temporäre FC
    :param target_gdb: Ziel-Geodatabase für neue Templates
    :param layer_name: Name des Layers für neue Templates
    :return: Dictionary {geometry_type: [temp_fc_paths]} für späteres Mergen
    """
    with open(json_file, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    features = geojson.get("features", [])

    if not features:
        return {}

    # Features nach Geometrietyp gruppieren
    features_by_geom = {}
    for feature in features:
        geom_type = feature["geometry"]["type"]
        if geom_type not in features_by_geom:
            features_by_geom[geom_type] = []
        features_by_geom[geom_type].append(feature)

    # Dictionary zum Sammeln der temp FCs pro Geometrietyp
    temp_fcs_by_geom = {}

    # Für jeden Geometrietyp temporäre FC erstellen
    for geom_type, features in features_by_geom.items():
        # Fehlendes Template dynamisch erstellen wenn neuer Geometrietyp auftaucht
        if geom_type not in template_fc_dict:
            arcpy.AddMessage(f"- Neuer Geometrietyp {geom_type} gefunden, erstelle zusätzliches Template...")

            # Temporäre JSON mit Features dieses Geometrietyps erstellen
            temp_json_for_template = {
                "type": "FeatureCollection",
                "features": features,
                "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::25832"}},
            }
            temp_json_path = os.path.join(
                os.path.dirname(json_file), f"template_{geom_type}_{os.path.basename(json_file)}"
            )
            with open(temp_json_path, "w", encoding="utf-8") as f:
                json.dump(temp_json_for_template, f)

            # Template über bestehende Funktion erstellen (force_suffix=True da bereits anderer Geometrietyp existiert)
            new_templates = create_template_fc(temp_json_path, layer_name, target_gdb, spatial_ref, force_suffix=True)

            # Neue Templates zum Dictionary hinzufügen
            template_fc_dict.update(new_templates)

            # Temporäre JSON löschen
            os.remove(temp_json_path)

        # temp GeoJSON für diesen Geometrietyp erstellen (JSONToFeatures kann nur mit einem Geometrietyp umgehen)
        temp_json = {
            "type": "FeatureCollection",
            "features": features,
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::25832"}},
        }

        temp_json_file = os.path.join(os.path.dirname(json_file), f"temp_{geom_type}_{os.path.basename(json_file)}")
        with open(temp_json_file, "w", encoding="utf-8") as f:
            json.dump(temp_json, f)

        # Temporäre FC aus JSON erstellen
        temp_fc_name = f"temp_{geom_type}_{int(time.time() * 1000)}"  # Millisekunden für Eindeutigkeit
        temp_fc = os.path.join(workspace_gdb, temp_fc_name)

        try:
            arcpy.AddMessage(
                f"- Konvertiere {len(features)} Features aus {os.path.basename(json_file)} in Feature-Class..."
            )
            arcpy.JSONToFeatures_conversion(temp_json_file, temp_fc)

            # Abrufdatum-Feld hinzufügen und setzen
            arcpy.AddField_management(temp_fc, "Abrufdatum", "DATE")
            with arcpy.da.UpdateCursor(temp_fc, ["Abrufdatum"]) as cursor:
                for row in cursor:
                    row[0] = datetime.now()
                    cursor.updateRow(row)

            # Temp FC zur Liste hinzufügen statt sofort zu appenden
            if geom_type not in temp_fcs_by_geom:
                temp_fcs_by_geom[geom_type] = []
            temp_fcs_by_geom[geom_type].append(temp_fc)

            # Temporäre JSON-Datei löschen
            os.remove(temp_json_file)

        except Exception as e:
            arcpy.AddWarning(f"- Fehler beim Vorbereiten: {str(e)}")
            if os.path.exists(temp_json_file):
                os.remove(temp_json_file)

    return temp_fcs_by_geom

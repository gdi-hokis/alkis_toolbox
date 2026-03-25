# -*- coding: utf-8 -*-
import arcpy
import math
import os
from collections import defaultdict
from utils import add_step_message

class SpatialGridIndex:
    # Räumlicher Grid-Index zur schnellen Nachbarschaftssuche
    def __init__(self, cell_size):
        self.cell_size = cell_size
        self.grid = defaultdict(list)

    def _cell(self, x, y):
        return (int(x // self.cell_size), int(y // self.cell_size))

    def insert(self, x, y, obj):
        self.grid[self._cell(x, y)].append(obj)

    def query(self, x, y):
        cx, cy = self._cell(x, y)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for obj in self.grid.get((cx + dx, cy + dy), []):
                    yield obj

def normalize_part(value):
    """
    Normalisiert Zähler oder Nenner eines Flurstücks.
    - Entfernt Leerzeichen
    - Wandelt numerische Strings in Integerstrings um
    - Leere Werte werden zu None
    """
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    if value.isdigit():
        return str(int(value))
    return value

def parse_parcel_text(text):
    """
    Zerlegt einen Flurstückstext in Zähler und Nenner.
    Beispiele:
    "123/4" -> ("123","4")
    "123"   -> ("123",None)
    "/4"    -> (None,"4")
    """
    if not text:
        return (None, None)
    stripped_text = str(text).strip()
    if "/" in stripped_text:
        parts = stripped_text.split("/")
        if len(parts) == 2:
            return normalize_part(parts[0]), normalize_part(parts[1])
        return (None, None)
    if stripped_text.startswith("/"):
        return (None, normalize_part(stripped_text[1:]))
    return normalize_part(stripped_text), None

def parcel_match_score(parcel_counter, parcel_denominator, label_counter, label_denominator):
    # Bewertungsfunktion für Übereinstimmung von Flurstücken
    if label_counter and label_denominator:
        if parcel_counter == label_counter and parcel_denominator == label_denominator:
            return 3
        return 0
    if label_counter and not label_denominator:
        if parcel_counter == label_counter:
            return 2
        return 0
    if label_denominator and not label_counter:
        if parcel_denominator == label_denominator:
            return 2
        return 0
    return 0

def semantic_match_parts(parcel_counter, parcel_denominator, label_point_counter, label_point_denominator):
    # Prüft semantische Übereinstimmung zwischen Beschriftung und Flurstückstextinhalt
    if label_point_counter and label_point_denominator:
        return parcel_counter == label_point_counter and parcel_denominator == label_point_denominator
    if label_point_counter and not label_point_denominator:
        return parcel_counter == label_point_counter
    if label_point_denominator and not label_point_counter:
        return parcel_denominator == label_point_denominator
    return False

def label_match_priority(label):
    # Priorisierung von Beschriftungen -> Vollständige Flurstücksangabe wird zuerst verarbeitet
    counter = label["zaehler"]
    denominator = label["nenner"]
    if counter and denominator:
        return 3
    if counter:
        return 2
    if denominator:
        return 1
    return 0

def dist(x1, y1, x2, y2):
    # Distanzberechnung zwischen zwei Punkten
    return math.hypot(x2 - x1, y2 - y1)

def load_labels(config, label_fc):
    # Laden der Beschriftungspunkte
    labels = []
    where = "art = 'ZAE_NEN'"
    with arcpy.da.SearchCursor(label_fc, ["OID@", "SHAPE@", config["beschriftungspunkte"]["inhalt"], config["beschriftungspunkte"]["drehwinkel"], config["beschriftungspunkte"]["referenz_gml_id"]], where) as search_cursor:
        for objectid, geometry, text, rotation, gml in search_cursor:
            point = geometry.firstPoint
            counter, denominator = parse_parcel_text(text)
            labels.append({
                "oid": objectid,
                "geometry": geometry,
                "x": point.X,
                "y": point.Y,
                "zaehler": counter,
                "nenner": denominator,
                "drehwinkel": rotation,
                "referenz_gml_id": gml,
                "text": text
            })
    return labels

def load_parcels(config, parcel_fc):
    # Laden der Flurstücke
    parcels = []
    with arcpy.da.SearchCursor(parcel_fc, ["OID@", "SHAPE@", config["flurstueck"]["flurstueckstext"]]) as cursor:
        for objectid, geometry, text in cursor:
            centroid = geometry.labelPoint
            counter, denominator = parse_parcel_text(text)
            parcels.append({
                "oid": objectid,
                "geometry": geometry,
                "centroid": centroid,
                "cx": centroid.X,
                "cy": centroid.Y,
                "zaehler": counter,
                "nenner": denominator,
                "text": text,
                "area": geometry.area,
                "perimeter": geometry.length
            })
    return parcels

def build_parcel_indices(parcels):
    # Erstellung verschiedener Lookup-Indizes für schnelle Abfragen
    index_full = defaultdict(list)
    index_counter = defaultdict(list)
    index_denominator = defaultdict(list)
    index_objectid = {}
    for parcel in parcels:
        counter = parcel["zaehler"]
        denominator = parcel["nenner"]
        if counter and denominator:
            index_full[(counter, denominator)].append(parcel)
        if counter:
            index_counter[counter].append(parcel)
        if denominator:
            index_denominator[denominator].append(parcel)
        index_objectid[parcel["oid"]] = parcel
    return {
        "full": index_full,
        "zaehler": index_counter,
        "nenner": index_denominator,
        "oid": index_objectid
    }

def build_label_indices(labels):
    # Index der Beschriftungspunkte nach referenz_gml_id
    index_gml = defaultdict(list)
    for label in labels:
        gml = label["referenz_gml_id"]
        if gml:
            index_gml[gml].append(label)
    return index_gml

def build_spatial_index(parcels, search_distance):
    # Erstellung des Spatial Index für Flurstücke
    index = SpatialGridIndex(search_distance)
    for parcel in parcels:
        index.insert(parcel["cx"], parcel["cy"], parcel)
    return index

def spatial_join_labels_to_parcels(label_fc, parcel_fc):
    # Ermittlung, welche Beschriftungen in welchem Flurstück liegen
    temp_join_layer = "in_memory\\parcel_label_join"
    parcel_feature_layer = "parcels"
    label_feature_layer = "labels"
    mapping = defaultdict(list)
    try:
        arcpy.management.MakeFeatureLayer(parcel_fc, parcel_feature_layer)
        arcpy.management.MakeFeatureLayer(label_fc, label_feature_layer, "art = 'ZAE_NEN'")
        arcpy.analysis.SpatialJoin(parcel_feature_layer, label_feature_layer, temp_join_layer, "JOIN_ONE_TO_MANY", match_option="CONTAINS")
        with arcpy.da.SearchCursor(temp_join_layer, ["TARGET_FID", "JOIN_FID"]) as cursor:
            for parcel_objectid, label_objectid in cursor:
                if label_objectid != -1:
                    mapping[label_objectid].append(parcel_objectid)
    finally:
        for dataset in (temp_join_layer, parcel_feature_layer, label_feature_layer):
            if arcpy.Exists(dataset):
                arcpy.management.Delete(dataset)
    return mapping

def build_parcels_with_labels(label_to_parcel):
    # Ermittelt alle Flurstücke mit vorhandenen Labels
    parcels_with_labels = set()
    for parcel_list in label_to_parcel.values():
        for parcel_oid in parcel_list:
            parcels_with_labels.add(parcel_oid)
    return parcels_with_labels

def check_label_inside_matching_parcel(label, label_to_parcel, parcel_indices):
    # Prüft ob ein Label bereits im korrekten Flurstück liegt
    label_objectid = label["oid"]
    if label_objectid not in label_to_parcel:
        return False
    for parcel_objectid in label_to_parcel[label_objectid]:
        parcel = parcel_indices["oid"].get(parcel_objectid)
        if not parcel:
            continue
        if semantic_match_parts(parcel["zaehler"], parcel["nenner"], label["zaehler"], label["nenner"]):
            return True
    return False

def find_nearest_matching_parcel(label, spatial_index, label_to_parcel, parcels_with_labels, used_parcels):
    # Sucht das nächste passende Flurstück
    x_coordinate = label["x"]
    y_coordinate = label["y"]
    inside = label_to_parcel.get(label["oid"])
    best = None
    best_score = -1
    best_distance = float("inf")
    for parcel in spatial_index.query(x_coordinate, y_coordinate):
        if parcel["oid"] in used_parcels:
            continue
        if parcel["oid"] in parcels_with_labels and (not inside or parcel["oid"] not in inside):
            continue
        score = parcel_match_score(parcel["zaehler"], parcel["nenner"], label["zaehler"], label["nenner"])
        if score == 0:
            continue
        distance = dist(x_coordinate, y_coordinate, parcel["cx"], parcel["cy"])
        if (score > best_score) or (score == best_score and distance < best_distance):
            best = parcel
            best_score = score
            best_distance = distance
    return best

def find_nearest_1000_label(label_2000, idx_1000_gml):
    # Findet zu einem Beschriftungspunkt aus dem DKKM 2000 den Beschriftungspunkt aus DKKM 1000 anhand der referenz_gml_id
    gml = label_2000["referenz_gml_id"]
    if not gml:
        return None
    candidates = idx_1000_gml.get(gml)
    if not candidates:
        return None
    x_coordinate = label_2000["x"]
    y_coordinate = label_2000["y"]
    best = None
    best_distance = float("inf")
    for label_point in candidates:
        distance = dist(x_coordinate, y_coordinate, label_point["x"], label_point["y"])
        if distance < best_distance:
            best = label_point
            best_distance = distance
    return best

def create_output_featureclass(workspace, fc_name, spatial_reference):
    # Erstellung der Ausgabe FeatureClass
    arcpy.env.overwriteOutput = True
    fc_path = os.path.join(workspace, fc_name)
    required_fields = [
        ("scale", "TEXT", 100, "Maßstab"),
        ("referenz_gml_id", "TEXT", 100, "Referenz GML ID")
    ]
    if arcpy.Exists(fc_path):
        arcpy.management.TruncateTable(fc_path)
    else:
        arcpy.management.CreateFeatureclass(workspace, fc_name, "POLYLINE", spatial_reference=spatial_reference)
    existing_fields = [field.name for field in arcpy.ListFields(fc_path)]
    for field_name, field_type, field_length, field_alias in required_fields:
        if field_name not in existing_fields:
            arcpy.management.AddField(fc_path, field_name, field_type, field_length=field_length, field_alias=field_alias)
    return fc_path

def create_label_bbox(label, font_size, scale, buffer, spatial_reference):
    # Erstellt eine BoundingBox um die Beschriftung
    point_to_mm = 0.352778
    mm_to_m = 0.001
    average_char_width_factor = 0.7
    text = str(label["text"]).strip()
    width_units = 0
    for c in text:
        if c.isdigit():
            width_units += 0.9
        elif c == "/":
            width_units += 0.5
        else:
            width_units += 1
    width_units = max(width_units, 2.5)
    text_width_point = width_units * font_size * average_char_width_factor
    text_height_point = font_size
    text_width_mm = text_width_point * point_to_mm
    text_height_mm = text_height_point * point_to_mm
    text_width_map = text_width_mm * mm_to_m * scale
    text_height_map = text_height_mm * mm_to_m * scale
    text_width_map *= buffer
    text_height_map *= buffer
    half_width = text_width_map / 2
    half_height = text_height_map / 2
    corners = [
        (-half_width, -half_height),
        ( half_width, -half_height),
        ( half_width,  half_height),
        (-half_width,  half_height),
        (-half_width, -half_height)
    ]
    theta = math.radians(360 - label["drehwinkel"])
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    points = []
    for cx, cy in corners:
        rx = cx * cos_theta - cy * sin_theta
        ry = cx * sin_theta + cy * cos_theta
        points.append(arcpy.Point(label["x"] + rx, label["y"] + ry))
    return arcpy.Polygon(arcpy.Array(points), spatial_reference)

def segment_intersection(p1, p2, p3, p4):
    # Berechnet Schnittpunkt zwischen Basis Zuordnungspfeil und BoundingBox für den Startpunkt
    x1, y1 = p1.X, p1.Y
    x2, y2 = p2.X, p2.Y
    x3, y3 = p3.X, p3.Y
    x4, y4 = p4.X, p4.Y
    denom = (x1-x2)*(y3-y4) - (y1-y2)*(x3-x4)
    if abs(denom) < 1e-9:
        return None
    t = ((x1-x3)*(y3-y4) - (y1-y3)*(x3-x4)) / denom
    u = -((x1-x2)*(y1-y3) - (y1-y2)*(x1-x3)) / denom
    if 0 <= t <= 1 and 0 <= u <= 1:
        ix = x1 + t * (x2 - x1)
        iy = y1 + t * (y2 - y1)
        return arcpy.Point(ix, iy)
    return None

def compute_offset_using_bbox(start_point, end_point, label, font_size, scale, buffer, spatial_reference):
    # Berechnet Startversatz des Pfeils außerhalb der Labelbox
    bbox = create_label_bbox(label, font_size, scale, buffer, spatial_reference)
    parts = bbox.boundary().getPart(0)
    edges = []
    for i in range(parts.count - 1):
        edges.append((parts.getObject(i), parts.getObject(i+1)))
    intersections = []
    for e_start, e_end in edges:
        ip = segment_intersection(start_point, end_point, e_start, e_end)
        if ip:
            intersections.append(ip)
    if not intersections:
        return 0
    best = min(intersections, key=lambda p: dist(start_point.X, start_point.Y, p.X, p.Y))
    return dist(start_point.X, start_point.Y, best.X, best.Y)

def compute_form_index(parcel):
    # Berechnet FormIndex eines Flurstückes
    area = parcel["area"]
    perimeter = parcel["perimeter"]
    if perimeter == 0:
        return 1
    return (4 * math.pi * area) / (perimeter * perimeter)

def set_start_and_end(start_point, end_point, parcel, minimum_form_index_for_compact_parcels, maximum_distance_between_compact_parcel_points, buffer_distance_compact_parcels, buffer_distance_narrow_parcels):
    # Bestimmt Start und Endpunkt des Zuordnungspfeiles
    distance_between = dist(start_point.X, start_point.Y, end_point.X, end_point.Y)
    form_index = compute_form_index(parcel)
    if form_index > minimum_form_index_for_compact_parcels:
        if distance_between < maximum_distance_between_compact_parcel_points:
            return start_point, end_point   
        else: 
           parcel_inner_buffer = parcel["geometry"].buffer(buffer_distance_compact_parcels) 
    else:
        parcel_inner_buffer = parcel["geometry"].buffer(buffer_distance_narrow_parcels)
    if parcel_inner_buffer and parcel_inner_buffer.area > 0:
        inner_boundary = parcel_inner_buffer.boundary()
    else:
        inner_boundary = parcel["geometry"].boundary()
    start_geometry = arcpy.PointGeometry(start_point, parcel["geometry"].spatialReference)
    nearest_point, _, _, _ = inner_boundary.queryPointAndDistance(start_geometry)
    nearest_point = nearest_point.firstPoint
    distance_between_new = dist(start_point.X, start_point.Y, nearest_point.X, nearest_point.Y)
    if distance_between_new > distance_between:
        return start_point, end_point
    else:
        return start_point, nearest_point   

def generate_assignment_arrows(config, label_points_1000_fc, label_points_2000_fc, parcels_fc, MATCHING_SEARCH_DISTANCE, MIN_ARROW_LENGTH, MAX_ARROW_LENGTH, output_workspace):
    arcpy.env.overwriteOutput = True
    parcels = load_parcels(config, parcels_fc)
    labels_1000 = load_labels(config, label_points_1000_fc)
    labels_2000 = load_labels(config, label_points_2000_fc)
    labels_1000 = sorted(labels_1000, key=label_match_priority, reverse=True)
    labels_2000 = sorted(labels_2000, key=label_match_priority, reverse=True)
    parcel_indices = build_parcel_indices(parcels)
    spatial_index = build_spatial_index(parcels, MATCHING_SEARCH_DISTANCE)
    idx_1000_gml = build_label_indices(labels_1000)
    label1000_to_parcel = spatial_join_labels_to_parcels(label_points_1000_fc, parcels_fc)
    label2000_to_parcel = spatial_join_labels_to_parcels(label_points_2000_fc, parcels_fc)
    parcels_with_labels_1000 = build_parcels_with_labels(label1000_to_parcel)
    parcels_with_labels_2000 = build_parcels_with_labels(label2000_to_parcel)
    spatial_reference=arcpy.Describe(parcels_fc).spatialReference
    FONT_SIZE_250 = 9.0
    BUFFER_FACTOR_250 = 1.25
    FONT_SIZE_500 = 9.0
    BUFFER_FACTOR_500 = 1.2
    FONT_SIZE_1000 = 8.0
    BUFFER_FACTOR_1000 = 1.15
    FONT_SIZE_2000 = 7.0
    BUFFER_FACTOR_2000 = 1.1
    SCALE_CONFIG = [
        (250, labels_1000, label1000_to_parcel, parcels_with_labels_1000, FONT_SIZE_250, BUFFER_FACTOR_250),
        (500, labels_1000, label1000_to_parcel, parcels_with_labels_1000, FONT_SIZE_500, BUFFER_FACTOR_500),
        (1000, labels_1000, label1000_to_parcel, parcels_with_labels_1000, FONT_SIZE_1000, BUFFER_FACTOR_1000),
        (2000, labels_2000, label2000_to_parcel, parcels_with_labels_2000, FONT_SIZE_2000, BUFFER_FACTOR_2000)
    ]
    arrow_gml_tracking = {}
    out_fc_name = "Zuordnungspfeile"
    out_fc = create_output_featureclass(output_workspace, out_fc_name, spatial_reference)
    for step, (scale, labels, label_map, parcels_with_labels, font_size, buffer) in enumerate(SCALE_CONFIG, 1):
        add_step_message(f"Generiere Zuordnungspfeile für den Maßstab 1:{scale}", step, 4)
        used_parcels = set()
        count = 0
        with arcpy.da.InsertCursor(out_fc, ["SHAPE@", "scale", "referenz_gml_id"]) as insert_cursor:
            for label in labels:
                if check_label_inside_matching_parcel(label, label_map, parcel_indices):
                    continue
                parcel = find_nearest_matching_parcel(label, spatial_index, label_map, parcels_with_labels, used_parcels)
                if not parcel:
                    continue
                start_point = label["geometry"].firstPoint
                gml = label["referenz_gml_id"]
                if scale == 2000:
                    if gml and gml in arrow_gml_tracking:
                        end_point = arrow_gml_tracking[gml]
                    else:
                        nearest_label = find_nearest_1000_label(label, idx_1000_gml)
                        if not nearest_label:
                            continue
                        end_point = nearest_label["geometry"].firstPoint
                else:
                    end_point = parcel["centroid"]
                MINIMUM_FORM_INDEX_FOR_COMPACT_PARCELS = 0.2
                MAXIMUM_DISTANCE_BETWEEN_COMPACT_PARCEL_POINTS = 20
                BUFFER_DISTANCE_COMPACT_PARCELS = -1.0
                BUFFER_DISTANCE_NARROW_PARCELS = -0.2
                start_point, end_point = set_start_and_end(start_point, end_point, parcel, MINIMUM_FORM_INDEX_FOR_COMPACT_PARCELS, MAXIMUM_DISTANCE_BETWEEN_COMPACT_PARCEL_POINTS, BUFFER_DISTANCE_COMPACT_PARCELS, BUFFER_DISTANCE_NARROW_PARCELS)
                offset = compute_offset_using_bbox(start_point, end_point, label, font_size, scale, buffer, spatial_reference)
                if offset <= 0:
                    continue
                arrow_length = dist(start_point.X, start_point.Y, end_point.X, end_point.Y)
                if arrow_length > MAX_ARROW_LENGTH:
                    continue
                remaining_length = arrow_length - offset
                if remaining_length <= MIN_ARROW_LENGTH:
                    continue
                base = arcpy.Polyline(arcpy.Array([start_point, end_point]))
                start_point = base.positionAlongLine(offset, False).firstPoint
                arrow = arcpy.Polyline(arcpy.Array([start_point, end_point]), spatial_reference)
                insert_cursor.insertRow([arrow, scale, gml])
                used_parcels.add(parcel["oid"])
                if scale != 2000:
                    if gml and gml not in arrow_gml_tracking:
                        arrow_gml_tracking[gml] = end_point
                count += 1
        arcpy.AddMessage(f"- {count} Zuordnungspfeile wurden für den Maßstab 1:{scale} generiert.")

            





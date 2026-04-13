# -*- coding: utf-8 -*-
import arcpy
import math
import os
from collections import defaultdict
from utils import add_step_message
from PIL import ImageFont

# ------------------------- #
# --- Globale Variablen --- #
# ------------------------- #
LABEL_WHERE = "art = 'ZAE_NEN'"
MINIMUM_FORM_INDEX_FOR_COMPACT_PARCELS = 0.2
MAXIMUM_LENGTH_FOR_OTHER_CALCULATION = 25
BUFFER_DISTANCE_COMPACT_PARCELS = -1.0
BUFFER_DISTANCE_NARROW_PARCELS = -0.2
POINT_TO_MM = 0.352778
MM_TO_M = 0.001
FONT_SIZES = {
    250: 9.0, 
    500: 9.0, 
    1000: 8.0, 
    2000: 7.0
}
FONT_CACHE = {}
FSK_TO_ENDPOINT = {}

class SpatialGridIndex:
    # Räumlicher Grid-Index zur schnellen Nachbarschaftssuche
    def __init__(self, cell_size):
        """
        Initialisiert den räumlichen Grid-Index mit gegebener Zellengröße.
        """
        self.cell_size = cell_size
        self.grid = defaultdict(list)

    def _cell(self, x, y):
        """
        Gibt die Zellkoordinate für einen Punkt zurück.
        """
        return (int(x // self.cell_size), int(y // self.cell_size))

    def insert(self, x, y, obj):
        """
        Fügt ein Objekt an der Position (x, y) in den Grid-Index ein.
        """
        self.grid[self._cell(x, y)].append(obj)

    def query(self, x, y):
        """
        Gibt alle Objekte in der Nachbarschaft der Zelle (x, y) zurück.
        """
        cx, cy = self._cell(x, y)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for obj in self.grid.get((cx + dx, cy + dy), []):
                    yield obj

def normalize_part(value):
    """
    Normalisiert einen Zähler oder Nenner eines Flurstücks.
    Entfernt Leerzeichen, wandelt numerische String in Integer-Strings um und gibt None für leere Werte zurück.
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
    Gibt ein Tupel (zaehler, nenner) zurück.
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

def load_labels(config, label_fc):
    """
    Lädt Beschriftungspunkte aus einer Feature-Class.
    Gibt eine Liste von Dictionaries mit Label-Informationen zurück.
    """
    labels = []
    with arcpy.da.SearchCursor(
        label_fc, 
        [
            "OID@", 
            "SHAPE@", 
            config["beschriftungspunkte"]["inhalt"], 
            config["beschriftungspunkte"]["drehwinkel"], 
            config["beschriftungspunkte"]["referenz_gml_id"]
        ], 
        LABEL_WHERE
    ) as search_cursor:
        for oid, geometry, text, rotation, gml_id in search_cursor:
            point = geometry.firstPoint
            zaehler, nenner = parse_parcel_text(text)
            labels.append({
                "oid": oid,
                "geometry": geometry,
                "x": point.X,
                "y": point.Y,
                "text": text,
                "zaehler": zaehler,
                "nenner": nenner,
                "drehwinkel": rotation,
                "referenz_gml_id": gml_id                
            })
    labels.sort(key=label_match_priority, reverse=True)
    return labels

def load_parcels(config, parcel_fc):
    """
    Lädt Flurstücke aus einer Feature-Class.
    Gibt eine Liste von Dictionaries mit Flurstücks-Informationen zurück.
    """
    parcels = []
    with arcpy.da.SearchCursor(
        parcel_fc, 
        [
            "OID@", 
            "SHAPE@", 
            config["flurstueck"]["flurstueckskennzeichen"], 
            config["flurstueck"]["flurstueckstext"], 
            config["flurstueck"]["gemarkung_name"], 
            config["flurstueck"]["gemeinde_name"]
        ]
    ) as cursor:
        for oid, geometry, fsk, text, gemarkung, gemeinde in cursor:
            centroid = geometry.labelPoint
            zaehler, nenner = parse_parcel_text(text)
            parcels.append({
                "oid": oid,
                "geometry": geometry,
                "centroid": centroid,
                "cx": centroid.X,
                "cy": centroid.Y,
                "area": geometry.area,
                "perimeter": geometry.length,
                "fsk": fsk,
                "text": text,
                "zaehler": zaehler,
                "nenner": nenner,
                "gemarkung": gemarkung,
                "gemeinde": gemeinde                
            })
    return parcels

def label_match_priority(label):
    """
    Bestimmt die Priorität einer Beschriftung basierend auf der Vollständigkeit der Flurstücksangabe.
    Gibt einen Integer-Wert für die Sortierung zurück.
    """
    if label["zaehler"] and label["nenner"]:
        return 3
    if label["zaehler"]:
        return 2
    if label["nenner"]:
        return 1
    return 0

def build_parcel_indices(parcels):
    """
    Erstellt Lookup-Indizes für Flurstücke zur schnellen Abfrage nach Zähler, Nenner und ObjectID.
    Gibt ein Dictionary mit verschiedenen Indizes zurück.
    """
    index_full = defaultdict(list)
    index_zaehler = defaultdict(list)
    index_nenner = defaultdict(list)
    index_oid = {}
    for parcel in parcels:
        zaehler = parcel["zaehler"]
        nenner = parcel["nenner"]
        if zaehler and nenner:
            index_full[(zaehler, nenner)].append(parcel)
        if zaehler:
            index_zaehler[zaehler].append(parcel)
        if nenner:
            index_nenner[nenner].append(parcel)
        index_oid[parcel["oid"]] = parcel
    return {
        "full": index_full,
        "zaehler": index_zaehler,
        "nenner": index_nenner,
        "oid": index_oid
    }

def build_spatial_index(parcels, search_distance):
    """
    Erstellt einen räumlichen Grid-Index für Flurstücke zur effizienten Nachbarschaftssuche.
    Gibt ein SpatialGridIndex-Objekt zurück.
    """
    index = SpatialGridIndex(search_distance)
    for parcel in parcels:
        index.insert(parcel["cx"], parcel["cy"], parcel)
    return index

def spatial_join_labels_to_parcels(label_fc, parcel_fc):
    """
    Führt einen Spatial Join zwischen Beschriftungspunkten und Flurstücken durch.
    Gibt ein Mapping von Label-ObjectIDs zu Flurstück ObjectIDs zurück.
    """
    scratch_gdb = arcpy.env.scratchGDB
    temp_join_layer = os.path.join(scratch_gdb, "parcel_label_join")
    parcel_feature_layer = "parcels"
    label_feature_layer = "labels"
    mapping = defaultdict(list)
    try:
        arcpy.MakeFeatureLayer_management(parcel_fc, parcel_feature_layer)
        arcpy.MakeFeatureLayer_management(label_fc, label_feature_layer, LABEL_WHERE)
        arcpy.SpatialJoin_analysis(parcel_feature_layer, label_feature_layer, temp_join_layer, "JOIN_ONE_TO_MANY", match_option="CONTAINS")
        with arcpy.da.SearchCursor(temp_join_layer, ["TARGET_FID", "JOIN_FID"]) as cursor:
            for parcel_oid, label_oid in cursor:
                if label_oid != -1:
                    mapping[label_oid].append(parcel_oid)
    finally:
        for dataset in (temp_join_layer, parcel_feature_layer, label_feature_layer):
            if arcpy.Exists(dataset):
                arcpy.Delete_management(dataset)
    return mapping

def build_parcels_with_labels(label_to_parcel):
    """
    Ermittelt alle Flurstücke, denen mindestens ein Label zugeordnet ist.
    Gibt eine Menge von Flurstück ObjectIDs zurück.
    """
    parcels_with_labels = set()
    for parcel_list in label_to_parcel.values():
        for parcel_oid in parcel_list:
            parcels_with_labels.add(parcel_oid)
    return parcels_with_labels

def create_output_featureclass(workspace, fc_name, spatial_reference):
    """
    Erstellt die Ausgabe Feature-Class für Zuordnungspfeile.
    Legt erforderliche Felder an und gibt den Pfad zur Feature-Class zurück.
    """
    arcpy.env.overwriteOutput = True
    fc_path = os.path.join(workspace, fc_name)
    required_fields = [
        ("scale", "TEXT", 100, "Maßstab"),
        ("flurstueck", "TEXT", 100, "Flurstück"),
        ("gemeinde", "TEXT", 250, "Gemeinde"),
        ("gemarkung", "TEXT", 250, "Gemarkung"), 
        ("referenz_gml_id", "TEXT", 100, "Referenz GML ID")        
    ]
    if arcpy.Exists(fc_path):
        arcpy.TruncateTable_management(fc_path)
    else:
        arcpy.CreateFeatureclass_management(workspace, fc_name, "POLYLINE", spatial_reference=spatial_reference)
    existing_fields = [field.name for field in arcpy.ListFields(fc_path)]
    for field_name, field_type, field_length, field_alias in required_fields:
        if field_name not in existing_fields:
            arcpy.AddField_management(fc_path, field_name, field_type, field_length=field_length, field_alias=field_alias)
    return fc_path
    
def scale_arrow_length(length, scale):
    """
    Skaliert die Mindest- und Maximallänge eines Zuordnungspfeiles abhängig vom Maßstab.
    Gibt die angepasste Mindest-/Maximallänge zurück.
    """
    scaled_length = length * (scale / 1000)
    if scaled_length < length:
        return length
    else:
        return scaled_length
    
def semantic_match_parts(parcel_zaehler, parcel_nenner, label_zaehler, label_nenner):
    """
    Prüft, ob Zähler und Nenner von Flurstück und Label semantisch übereinstimmen.
    Gibt True bei Übereinstimmung, sonst False zurück.
    """
    if label_zaehler and label_nenner:
        return parcel_zaehler == label_zaehler and parcel_nenner == label_nenner
    if label_zaehler and not label_nenner:
        return parcel_zaehler == label_zaehler
    if label_nenner and not label_zaehler:
        return parcel_nenner == label_nenner
    return False
    
def check_label_inside_matching_parcel(label, label_to_parcel, parcel_indices):
    """
    Prüft, ob ein Label bereits im passenden Flurstück liegt.
    Gibt ein Tupel zurück.
    """
    label_oid = label["oid"]
    if label_oid not in label_to_parcel:
        return False, None, None, None, None
    for parcel_oid in label_to_parcel[label_oid]:
        parcel = parcel_indices["oid"].get(parcel_oid)
        if not parcel:
            continue
        if semantic_match_parts(parcel["zaehler"], parcel["nenner"], label["zaehler"], label["nenner"]):
            return True, parcel["fsk"], parcel["zaehler"], parcel["nenner"], parcel["oid"]
    return False, None, None, None, None

def append_fsk_to_endpoint_dict(fsk, point, zaehler, nenner):
    FSK_TO_ENDPOINT.setdefault(fsk, []).append({
        "point": point,
        "zaehler": zaehler,
        "nenner": nenner
    })

def parcel_match_score(parcel_zaehler, parcel_nenner, label_zaehler, label_nenner):
    """
    Bewertet die Übereinstimmung zwischen Flurstück und Label anhand von Zähler und Nenner.
    Gibt einen Score für die Priorisierung zurück.
    """
    if label_zaehler and label_nenner:
        if parcel_zaehler == label_zaehler and parcel_nenner == label_nenner:
            return 3
        return 0
    if label_zaehler and not label_nenner:
        if parcel_zaehler == label_zaehler:
            return 2
        return 0
    if label_nenner and not label_zaehler:
        if parcel_nenner == label_nenner:
            return 2
        return 0
    return 0

def find_nearest_matching_parcel(label, spatial_index, label_to_parcel, parcels_with_labels, used_parcels):
    """
    Sucht das nächstgelegende passende Flurstück für ein Label.
    Gibt das beste Parcel-Dictionary zurück.
    """
    x = label["x"]
    y = label["y"]
    inside = label_to_parcel.get(label["oid"])
    best_parcel = None
    highest_score = -1
    shortest_distance = float("inf")
    for parcel in spatial_index.query(x, y):
        if parcel["oid"] in used_parcels:
            continue
        if parcel["oid"] in parcels_with_labels and (not inside or parcel["oid"] not in inside):
            continue
        score = parcel_match_score(parcel["zaehler"], parcel["nenner"], label["zaehler"], label["nenner"])
        if score == 0:
            continue
        distance = math.hypot(parcel["cx"] - x, parcel["cy"] - y)
        if (score > highest_score) or (score == highest_score and distance < shortest_distance):
            best_parcel = parcel
            highest_score = score
            shortest_distance = distance
    return best_parcel

def set_start_and_end(start_point, end_point, parcel, max_arrow_length):
    """
    Bestimmt Start- und Endpunkt des Zuordnungspfeils, unter Berücksichtigung der Flurstücksform. 
    Gibt ein Tupel (start_point, end_point) zurück.
    """
    distance_between = math.hypot(end_point.X - start_point.X, end_point.Y - start_point.Y)
    area = parcel["area"]
    perimeter = parcel["perimeter"]
    form_index = (4 * math.pi * area) / (perimeter * perimeter) if perimeter != 0 else 1
    if form_index > MINIMUM_FORM_INDEX_FOR_COMPACT_PARCELS:
        if distance_between < max_arrow_length:
            return start_point, end_point
        else:
            parcel_inner_buffer = parcel["geometry"].buffer(BUFFER_DISTANCE_COMPACT_PARCELS)
    else:
        parcel_inner_buffer = parcel["geometry"].buffer(BUFFER_DISTANCE_NARROW_PARCELS)
    if parcel_inner_buffer and parcel_inner_buffer.area > 0:
        inner_boundary = parcel_inner_buffer.boundary()
    else:
        inner_boundary = parcel["geometry"].boundary()
    start_geom = arcpy.PointGeometry(start_point, parcel["geometry"].spatialReference)
    nearest_point, _, _, _ = inner_boundary.queryPointAndDistance(start_geom)
    nearest_point = nearest_point.firstPoint
    distance_between_new = math.hypot(nearest_point.X - start_point.X, nearest_point.Y - start_point.Y)
    if distance_between_new > distance_between:
        return start_point, end_point
    else:
        return start_point, nearest_point

def create_label_bbox(label, font_size, scale, spatial_reference):
    """
    Erstellt eine BoundingBox um die Beschriftung basierend auf Schriftgröße und Maßstab.
    Gibt die BoundingBox als Polygon-Objekt zurück.
    """
    if font_size not in FONT_CACHE:
        FONT_CACHE[font_size] = ImageFont.truetype("arial.ttf", int(font_size))
    font = FONT_CACHE[font_size]
    text = str(label["text"]).strip()
    left, top, right, bottom = font.getbbox(text)
    half_width_px = max(abs(left), abs(right))
    half_height_px = max(abs(top), abs(bottom))
    text_width_px = 2 * half_width_px
    text_height_px = 2 * half_height_px
    text_width_map = (text_width_px / 1.333) * POINT_TO_MM * MM_TO_M * scale
    text_height_map = (text_height_px / 1.333) * POINT_TO_MM * MM_TO_M * scale
    half_width = text_width_map / 2
    half_height = text_height_map / 2
    corners = [
        (-half_width, -half_height),
        ( half_width, -half_height),
        ( half_width,  half_height),
        (-half_width,  half_height),
        (-half_width, -half_height)
    ]
    theta = math.radians(360 - (label["drehwinkel"] if label["drehwinkel"] else 0))
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    points = [
        arcpy.Point(label["x"] + cx * cos_theta - cy * sin_theta,
                    label["y"] + cx * sin_theta + cy * cos_theta)
        for cx, cy in corners
    ]
    return arcpy.Polygon(arcpy.Array(points), spatial_reference)

def segment_intersection(p1, p2, p3, p4):
    """
    Berechnet den Schnittpunkt zweier Liniensegmente.
    Gibt den Schnittpunkt als Punkt oder sofern kein Schnittpunkt vorhanden ist als None zurück.
    """
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
    
def compute_offset_using_bbox(start_point, end_point, label, font_size, scale, spatial_reference):
    """
    Berechnet den Startversatz des Zuordnungspfeils außerhalb der Label-BoundingBox.
    Gibt die Distanz als Float zurück.
    """
    bbox = create_label_bbox(label, font_size, scale, spatial_reference)
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
    best = min(intersections, key=lambda p: math.hypot(p.X - start_point.X, p.Y - start_point.Y))
    return math.hypot(best.X - start_point.X, best.Y - start_point.Y)

def find_best_endpoint_for_label(parcel):
    """
    Findet den besten Endpunkt für einen Zuordnungspfeil basierend auf dem Flurstückskennzeichen.
    Gibt einen Punkt oder None zurück.
    """
    candidates = FSK_TO_ENDPOINT.get(parcel["fsk"])
    if not candidates:
        return None
    for candidate in candidates:
       if semantic_match_parts(candidate["zaehler"], candidate["nenner"], parcel["zaehler"], parcel["nenner"]):
           return candidate["point"]
    else:
       return None
 
def build_arrow_for_label(label, parcel, scale, font_size, spatial_reference, min_arrow_length, max_arrow_length):
    """
    Erzeugt einen Zuordnungspfeile zwischen einem Label und einem Flurstück.
    Gibt eine Polyline zurück oder None, falls kein Pfeil erzeugt werden muss.
    """
    label_point = label["geometry"].firstPoint
    if scale == 2000:
        end_point = find_best_endpoint_for_label(parcel)
        if end_point is None:
            end_point = parcel["centroid"]
    else:
        end_point = parcel["centroid"]
    start_point, adjusted_end_point = set_start_and_end(label_point, end_point, parcel, max_arrow_length)
    offset = compute_offset_using_bbox(start_point, adjusted_end_point, label, font_size, scale, spatial_reference)
    # Offset muss vorhanden sein, damit der Pfeil nicht in die Beschriftung ragt
    if offset <= 0:
        return None, adjusted_end_point
    # Pfeillänge muss innerhalb der Mindest-/Maximallänge für den jeweiligen Maßstab liegen
    arrow_length = math.hypot(adjusted_end_point.X - start_point.X, adjusted_end_point.Y - start_point.Y)
    if arrow_length > max_arrow_length:
        return None, adjusted_end_point
    remaining_length = arrow_length - offset
    if remaining_length <= min_arrow_length:
        return None, adjusted_end_point
    base = arcpy.Polyline(arcpy.Array([start_point, adjusted_end_point]))
    arrow_start = base.positionAlongLine(offset, False).firstPoint
    arrow = arcpy.Polyline(arcpy.Array([arrow_start, adjusted_end_point]), spatial_reference)
    if arrow.within(parcel["geometry"]):
        return None, adjusted_end_point
    return arrow, adjusted_end_point

def generate_assignment_arrows(config, label_points_1000_fc, label_points_2000_fc, parcels_fc, matching_search_distance, min_arrow_length, output_workspace):
    """
    Hauptfunktion zur Berechnung und Ausgabe der Zuordnungspfeile für Beschriftungspunkte.
    Führt alle Schritte der Zuordnung, Berechnung und Ausgabe durch.
    """
    arcpy.env.overwriteOutput = True
    labels_1000 = load_labels(config, label_points_1000_fc)
    arcpy.AddMessage("Beschriftungspunkte DKKM 1000 wurden erfolgreich eingelesen und nach Vollständigkeit der Flurstücksangabe sortiert.")
    labels_2000 = load_labels(config, label_points_2000_fc)
    arcpy.AddMessage("Beschriftungspunkte DKKM 2000 wurden erfolgreich eingelesen und nach Vollständigkeit der Flurstücksangabe sortiert.")
    parcels = load_parcels(config, parcels_fc)
    arcpy.AddMessage("Flurstücke wurden erfolgreich eingelesen.")   
    parcel_indices = build_parcel_indices(parcels)
    spatial_index = build_spatial_index(parcels, matching_search_distance)
    label1000_to_parcel = spatial_join_labels_to_parcels(label_points_1000_fc, parcels_fc)
    label2000_to_parcel = spatial_join_labels_to_parcels(label_points_2000_fc, parcels_fc)
    parcels_with_labels_1000 = build_parcels_with_labels(label1000_to_parcel)
    parcels_with_labels_2000 = build_parcels_with_labels(label2000_to_parcel)
    spatial_reference=arcpy.Describe(parcels_fc).spatialReference
    SCALE_CONFIG = [
        (250, labels_1000, label1000_to_parcel, parcels_with_labels_1000),
        (500, labels_1000, label1000_to_parcel, parcels_with_labels_1000),
        (1000, labels_1000, label1000_to_parcel, parcels_with_labels_1000),
        (2000, labels_2000, label2000_to_parcel, parcels_with_labels_2000)
    ]
    out_fc_name = "zuordnungspfeile"
    out_fc = create_output_featureclass(output_workspace, out_fc_name, spatial_reference)
    for step, (scale, labels, label_map, parcels_with_labels) in enumerate(SCALE_CONFIG, 1):
        add_step_message(f"Generiere Zuordnungspfeile für den Maßstab 1:{scale}", step, 4)
        font_size = FONT_SIZES[scale]
        used_parcels = set()
        count = 0
        min_arrow = scale_arrow_length(min_arrow_length, scale)
        max_arrow = scale_arrow_length(MAXIMUM_LENGTH_FOR_OTHER_CALCULATION, scale)
        with arcpy.da.InsertCursor(out_fc, ["SHAPE@", "scale", "flurstueck", "gemeinde", "gemarkung", "referenz_gml_id"]) as insert_cursor:
            for label in labels:
                inside, fsk, zaehler, nenner, oid = check_label_inside_matching_parcel(label, label_map, parcel_indices)
                if inside:
                    if scale != 2000:
                        append_fsk_to_endpoint_dict(fsk, label["geometry"].firstPoint, zaehler, nenner)
                    used_parcels.add(oid)
                    continue
                parcel = find_nearest_matching_parcel(label, spatial_index, label_map, parcels_with_labels, used_parcels)
                if not parcel:
                    continue
                arrow, adjusted_end_point = build_arrow_for_label(label, parcel, scale, font_size, spatial_reference, min_arrow, max_arrow)
                if scale != 2000:
                    append_fsk_to_endpoint_dict(parcel["fsk"], adjusted_end_point, parcel["zaehler"], parcel["nenner"])            
                if arrow is not None:
                    insert_cursor.insertRow([arrow, scale, parcel["text"], parcel["gemeinde"], parcel["gemarkung"], label["referenz_gml_id"]])
                    count += 1
                used_parcels.add(parcel["oid"])
        arcpy.AddMessage(f"- {count} Zuordnungspfeile wurden für den Maßstab 1:{scale} generiert.")

            





# -*- coding: utf-8 -*-

# Copyright (c) 2024, Jana Muetsch, LRA Hohenlohekreis
# All rights reserved.

# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.

# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS
# BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
# GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
# DAMAGE.
import os
from collections import defaultdict
import arcpy


def calculate_lage(work_gdb, gdb_path):
    """
    REFAKTORIERTE VERSION - Verknüpft Lagebezeichnungen (Hausnummern, Straßen, Gewanne) mit Flurstücken
    und erstellt eine Navigation_Lage Tabelle mit geometry_source-Tracking.

    Vereinfachter Workflow:
    1. Lagebezeichnungspunkte korrigieren (Gebäude-Fallback)
    2. Spatial Join 1: Flurstücke ← Lagebezeichnungspunkte
    3. Spatial Join 2: Flurstücke ← Strasse/Gewann-Polygone
    4. Union der beiden Spatial-Join-Ergebnisse
    5. Cursor-basierte Deduplication pro Flurstück
    6. Ergebnisse in navigation_lage & navigation_lage_table schreiben

    :param work_gdb: Arbeitsdatenbank für temporäre Daten
    :param gdb_path: Ziel-Geodatabase mit den ALKIS-Daten
    :return: Boolean - True bei erfolgreicher Ausführung, False bei Fehler
    """

    try:
        arcpy.AddMessage("=" * 80)
        arcpy.AddMessage("CALCULATE_LAGE_REFACTORED - STARTET")
        arcpy.AddMessage("=" * 80)

        # Set workspace
        arcpy.env.workspace = work_gdb
        arcpy.env.overwriteOutput = True

        # ============================================================================
        # STEP 1: Lagebezeichnungspunkte vorbereiten & korrigieren
        # ============================================================================
        arcpy.AddMessage("\n[STEP 1] Lagebezeichnungspunkte vorbereiten & Gebäude-Fallback-Geometrie...")

        lage_point = os.path.join(gdb_path, "nora_v_al_lagebezeichnung")
        gebaeude = os.path.join(gdb_path, "nora_v_al_gebaeude")
        flurstueck = os.path.join(gdb_path, "nora_v_al_flurstueck")
        lage_polygon = os.path.join(gdb_path, "nora_v_al_strasse_gewann")

        # Filter: nur Lagebezeichnungen mit Hausnummern kopieren
        arcpy.FeatureClassToFeatureClass_conversion(gebaeude, work_gdb, "gebaeude_work")
        arcpy.FeatureClassToFeatureClass_conversion(
            lage_point, work_gdb, "lage_work", "hausnummer <> ' ' And hausnummer IS NOT NULL"
        )

        # Punkte außerhalb ihrer Gebäude identifizieren
        arcpy.MakeFeatureLayer_management("lage_work", "lage_work_VIEW")
        arcpy.SelectLayerByLocation_management(
            "lage_work_VIEW", "INTERSECT", "gebaeude_work", "0 Meters", "NEW_SELECTION", "INVERT"
        )
        arcpy.FeatureClassToFeatureClass_conversion("lage_work_VIEW", work_gdb, "lage_outside_geb")

        # Gebäude-Link für außerhalb liegende Punkte
        arcpy.JoinField_management(
            "lage_outside_geb", "lage_id", "gebaeude_work", "lage_id", "object_id;gebaeudefunktion_name"
        )

        # Gebäude-Mittelpunkte für Punkte mit Gebäude-Link
        arcpy.MakeFeatureLayer_management("lage_outside_geb", "lage_mit_gebid", "object_id IS NOT NULL")
        arcpy.JoinField_management(
            "gebaeude_work", "object_id", "lage_mit_gebid", "object_id", "lage_id;lagebezeichnung;hausnummer"
        )
        arcpy.MakeFeatureLayer_management("gebaeude_work", "gebaeude_to_convert", "lage_id_1 IS NOT NULL")
        arcpy.FeatureToPoint_management("gebaeude_to_convert", "gebaeude_point", "INSIDE")

        # Geometrien updaten mit Gebäude-Mittelpunkten
        arcpy.JoinField_management("lage_work", "lage_id", "gebaeude_point", "lage_id_1", "lage_id_1")

        update_geometries = {}
        pts_corrected = 0
        with arcpy.da.SearchCursor("gebaeude_point", ["lage_id_1", "SHAPE@"]) as cursor:
            for row in cursor:
                if row[0] is not None:
                    update_geometries[row[0]] = row[1]

        with arcpy.da.UpdateCursor("lage_work", ["lage_id", "SHAPE@"], "lage_id_1 IS NOT NULL") as cursor:
            for row in cursor:
                if row[0] in update_geometries:
                    row[1] = update_geometries[row[0]]
                    cursor.updateRow(row)
                    pts_corrected += 1

        arcpy.AddMessage(f"  ✓ {pts_corrected} Lagebezeichnungen via Gebäude-Mittelpunkt korrigiert")

        # ============================================================================
        # STEP 2: Spatial Join 1 - Flurstücke ← Lagebezeichnungspunkte
        # ============================================================================
        arcpy.AddMessage("\n[STEP 2] Spatial Join 1: Flurstücke ← Lagebezeichnungspunkte...")
        arcpy.SpatialJoin_analysis(flurstueck, "lage_work", "flst_lage_punkte", "JOIN_ONE_TO_MANY", "KEEP_ALL")
        pts_count = arcpy.GetCount_management("flst_lage_punkte")[0]
        arcpy.AddMessage(f"  ✓ {pts_count} Flurstück-Lage-Kombinationen aus Punkten erzeugt")

        # ============================================================================
        # STEP 3: Spatial Join 2 - Flurstücke ← Strasse/Gewann-Polygone (mit negativem Puffer)
        # ============================================================================
        arcpy.AddMessage("\n[STEP 3] Spatial Join 2: Flurstücke ← Strasse/Gewann-Polygone...")

        # Erstelle negativen Puffer der Gewanne
        arcpy.analysis.PairwiseBuffer(lage_polygon, "lage_polygon_buffered", buffer_distance_or_field="-0.1 Meters")

        buffered_count = arcpy.GetCount_management("lage_polygon_buffered")[0]
        arcpy.AddMessage(f"  ✓ {buffered_count} gepufferte Gewann-Geometrien erstellt (-0.1 Meters)")

        # Spatial Join mit gepufferten Gewannen
        arcpy.SpatialJoin_analysis(
            flurstueck,
            "lage_polygon_buffered",
            "flst_lage_polygon",
            "JOIN_ONE_TO_MANY",
            "KEEP_ALL",
            match_option="INTERSECT",
        )
        poly_count = arcpy.GetCount_management("flst_lage_polygon")[0]
        arcpy.AddMessage(f"  ✓ {poly_count} Flurstück-Gewann-Kombinationen aus gepufferten Polygonen erzeugt")

        # ============================================================================
        # STEP 3a: Überprüfung - Flurstücke ohne Gewann-Überschneidung
        # ============================================================================
        # Zähle Flurstücke mit JOIN_COUNT = 0 (keine Überschneidung nach Puffer)
        arcpy.FeatureClassToFeatureClass_conversion(
            "flst_lage_polygon", work_gdb, "flst_no_gewann_match", "JOIN_COUNT = 0"
        )
        no_match_count = arcpy.GetCount_management("flst_no_gewann_match")[0]

        if int(no_match_count) > 0:
            arcpy.AddWarning(
                f"  ⚠ {no_match_count} Flurstücke haben u.U. KEINE Lagebezeichnung. Siehe Layer flst_no_gewann_match."
            )

        # ============================================================================
        # STEP 4: Kombiniere Punkte + Polygone mit JOIN_COUNT-Filter
        # ============================================================================
        arcpy.AddMessage("\n[STEP 4] Kombiniere Punkte (JOIN_COUNT>0) + Polygone (JOIN_COUNT>0)...")

        # Filter: Punkte mit JOIN_COUNT > 0 (= haben einen Lage-Match)
        arcpy.FeatureClassToFeatureClass_conversion(
            "flst_lage_punkte", work_gdb, "flst_lage_pts_matched", "JOIN_COUNT > 0"
        )

        # Filter: Polygone mit JOIN_COUNT > 0 (= haben einen Lage-Match)
        arcpy.FeatureClassToFeatureClass_conversion(
            "flst_lage_polygon", work_gdb, "flst_lage_poly_matched", "JOIN_COUNT > 0"
        )

        # Markiere Quelle: Punkte = "original", Polygone = "polygon"
        if not arcpy.ListFields("flst_lage_pts_matched", "geometry_source"):
            arcpy.AddField_management("flst_lage_pts_matched", "geometry_source", "TEXT", field_length=50)
        arcpy.CalculateField_management("flst_lage_pts_matched", "geometry_source", "'original'", "PYTHON3")
        arcpy.AddMessage("  ✓ geometry_source='original' für Punkte gesetzt")

        if not arcpy.ListFields("flst_lage_poly_matched", "geometry_source"):
            arcpy.AddField_management("flst_lage_poly_matched", "geometry_source", "TEXT", field_length=50)
        arcpy.CalculateField_management("flst_lage_poly_matched", "geometry_source", "'polygon'", "PYTHON3")
        arcpy.AddMessage("  ✓ geometry_source='polygon' für Polygone gesetzt")

        # Felder, die nicht in den Merge gehen sollen (temporäre Join-Felder)
        exclude_from_merge = {"FID_flst_lage_punkte", "FID_flst_lage_polygon"}

        # Hole Feldlisten (ausschließen der Felder die enden mit _1 oder in exclude_from_merge sind)
        pts_fields = {
            f.name: f
            for f in arcpy.ListFields("flst_lage_pts_matched")
            if f.type not in ["OID", "Geometry"] and f.name not in exclude_from_merge and not f.name.endswith("_1")
        }
        poly_fields = {
            f.name: f
            for f in arcpy.ListFields("flst_lage_poly_matched")
            if f.type not in ["OID", "Geometry"] and f.name not in exclude_from_merge and not f.name.endswith("_1")
        }

        # Erstelle Field Mapping Object
        field_mapping = arcpy.FieldMappings()

        # Für alle Felder die in BEIDEN existieren: Punkte + Polygon kombinieren
        common_fields = set(pts_fields.keys()) & set(poly_fields.keys())
        for field_name in common_fields:
            field_map = arcpy.FieldMap()
            # Punkte zuerst hinzufügen (Hauptquelle)
            field_map.addInputField("flst_lage_pts_matched", field_name)
            # Polygon als Fallback (wird verwendet wenn Punkte-Wert null ist)
            field_map.addInputField("flst_lage_poly_matched", field_name)
            # Merge Rule setzen: First Not Null
            field_map.mergeRule = "First"
            output_field = field_map.outputField
            output_field.name = field_name
            field_map.outputField = output_field
            field_mapping.addFieldMap(field_map)

        # Punkte-spezifische Felder hinzufügen (nur in Punkte)
        for field_name in pts_fields:
            if field_name not in common_fields:
                field_map = arcpy.FieldMap()
                field_map.addInputField("flst_lage_pts_matched", field_name)
                field_mapping.addFieldMap(field_map)

        # Polygon-spezifische Felder hinzufügen (nur in Polygon)
        for field_name in poly_fields:
            if field_name not in common_fields:
                field_map = arcpy.FieldMap()
                field_map.addInputField("flst_lage_poly_matched", field_name)
                field_mapping.addFieldMap(field_map)

        # Merge mit Field Mapping
        arcpy.Merge_management(["flst_lage_pts_matched", "flst_lage_poly_matched"], "flst_lage_combined", field_mapping)
        combined_count = arcpy.GetCount_management("flst_lage_combined")[0]
        arcpy.AddMessage(f"  ✓ {combined_count} kombinierte Einträge (Punkte bevorzugt, Polygon als Fallback)")

        # ============================================================================
        # STEP 5: Deduplication per Cursor-Iteration
        # ============================================================================
        arcpy.AddMessage("\n[STEP 5] Deduplication pro Flurstück...")

        # Hole Spatial Reference von der Quell-Feature Class
        source_fc = "flst_lage_combined"
        sr = arcpy.Describe(source_fc).spatialReference

        # Temporäre Deduplizierungs-FC erstellen MIT Koordinatensystem
        arcpy.CreateFeatureclass_management(work_gdb, "navigation_lage_deduplicated", "POLYGON", spatial_reference=sr)

        # Felder kopieren von flst_lage_combined (alle außer OID/SHAPE-Feldern)
        union_fields = arcpy.ListFields("flst_lage_combined")
        field_mapping = {}  # Zur Verfolgung verfügbarer Felder

        # Felder, die nicht kopiert werden sollen (OID, SHAPE und abgeleitete Felder)
        exclude_fields = {
            "OBJECTID",
            "SHAPE",
            "SHAPE_Length",
            "FID_flst_lage_punkte",
            "FID_flst_lage_polygon",
        }

        fields_to_add = []

        for field in union_fields:
            if field.name not in exclude_fields and field.type != "OID" and field.type != "Geometry":
                field_type = "TEXT" if field.type == "String" else field.type
                field_length = field.length if field.type == "String" else None

                field_mapping[field.name] = field.type

                # Füge Feldspezifikation zur Liste hinzu
                if field.type == "String" and field_length:
                    fields_to_add.append([field.name, field_type, "", field_length, None])
                else:
                    fields_to_add.append([field.name, field_type])

        # Erstelle alle Felder auf einmal
        if fields_to_add:
            try:
                arcpy.AddFields_management("navigation_lage_deduplicated", fields_to_add)
                arcpy.AddMessage(f"  ✓ {len(field_mapping)} Felder für Deduplication vorbereitet")
            except Exception as field_error:
                # Bei ArcgisPro 3.1 und geringer
                arcpy.AddWarning(f"  Fehler beim Erstellen von Feldern: {str(field_error)}")
                # Fallback: Erstelle Felder einzeln bei Fehler
                for field_spec in fields_to_add:
                    arcpy.AddField_management("navigation_lage_deduplicated", *field_spec)

        # Deduplication-Logik mit Cursor
        arcpy.AddMessage("  Lese alle Einträge und gruppiere nach Flurstück...")

        # Dictionary: (flurstueckskennzeichen, lagebezeichnung) -> True
        # Enthält alle Kombinationen von Flurstück + Lagebezeichnung die in v_al_lagebezeichnung räumlich zusammenpassen
        flst_lage_lookup = {}

        # Mache einen Spatial Join: Flurstücke mit ALLEN Lagebezeichnungspunkten (auch ohne Hausnummer)
        arcpy.SpatialJoin_analysis(
            flurstueck,
            lage_point,
            "flst_all_lage_validation",
            "JOIN_ONE_TO_MANY",
            "KEEP_ALL",
            match_option="INTERSECT",
        )

        # Lese die Kombinationen ein
        with arcpy.da.SearchCursor(
            "flst_all_lage_validation", ["flurstueckskennzeichen", "lagebezeichnung"], "JOIN_COUNT > 0"
        ) as cursor:
            for row in cursor:
                flst_kz = row[0]
                lage_bez = row[1]
                if flst_kz and lage_bez:
                    # Speichere die Kombination als True
                    key = (flst_kz, lage_bez)
                    flst_lage_lookup[key] = True

        lookup_count = len(flst_lage_lookup)
        arcpy.AddMessage(f"  ✓ {lookup_count} Flurstück-Lagebezeichnung-Kombinationen geladen")

        # ALLE Felder aus flst_lage_combined lesen (außer OID/SHAPE)
        exclude_fields = {"OBJECTID", "SHAPE", "SHAPE_Length", "SHAPE_Area"}
        all_source_fields = [
            f.name
            for f in arcpy.ListFields("flst_lage_combined")
            if f.type not in ["OID", "Geometry"] and f.name not in exclude_fields
        ]

        # Diese Liste wird ÜBERALL verwendet - beim Lesen und beim Schreiben
        cursor_fields = ["SHAPE@"] + all_source_fields

        # Index-Mapping DIREKT aus cursor_fields erstellen
        field_index = {all_source_fields[i]: i + 1 for i in range(len(all_source_fields))}
        field_index["SHAPE@"] = 0

        # Gruppiere nach Flurstück
        flst_data = defaultdict(list)
        total_entries = 0

        with arcpy.da.SearchCursor("flst_lage_combined", cursor_fields) as cursor:
            for row in cursor:
                total_entries += 1

                # Baue entry-Dictionary mit ALLEN Feldern
                entry = {"geom": row[0]}  # SHAPE@
                for i, field_name in enumerate(all_source_fields):
                    entry[field_name] = row[i + 1]

                # Zusätzlich die Dedup-Keys extrahieren für die Logik
                entry["flst"] = entry.get("flurstueckskennzeichen", None)
                entry["lage_bez"] = entry.get("lagebezeichnung", None)
                entry["ges_schluessel"] = entry.get("gesamtschluessel", None)
                entry["hausnummer"] = entry.get("hausnummer", None)
                entry["lage_id"] = entry.get("lage_id", None)
                entry["geom_source"] = entry.get("geometry_source", "unknown")

                # Gruppiere nach Flurstück
                flst_key = entry.get("flurstueckskennzeichen")
                if flst_key:
                    flst_data[flst_key].append(entry)

        arcpy.AddMessage(f"  ✓ {total_entries} Einträge gelesen für {len(flst_data)} Flurstücke")

        # Dedupliziere pro Flurstück
        arcpy.AddMessage("  Starte Deduplication...")

        deduplicated_count = 0
        processed_flst = 0
        flst_with_multiple = 0
        streets_removed_by_validation = 0

        for flst_key in list(flst_data.keys()):
            entries = flst_data[flst_key]
            processed_flst += 1

            # Deduplication mit vereinfachter Logik
            deduplicated_entries = []
            seen = {}  # Dict für schnelle Lookups: key -> entry

            for entry in entries:
                # Erstelle Dedup-Key: (lagebezeichnung, gesamtschluessel, hausnummer)
                dedup_key = (
                    entry["lage_bez"],
                    entry["ges_schluessel"],
                    entry["hausnummer"],
                )

                # REGEL 1: Wenn bereits gesehen → überspringe (oder ersetze mit Punkt)
                if dedup_key in seen:
                    existing = seen[dedup_key]
                    # Ersetze Polygon mit Punkt-Geometrie, wenn Punkt besser ist
                    if entry["geom_source"] == "original" and existing["geom_source"] == "polygon":
                        deduplicated_entries.remove(existing)
                        deduplicated_entries.append(entry)
                        seen[dedup_key] = entry
                    # Sonst: behalte existing, überspringe entry
                    continue

                # REGEL 2: Verwerfe Einträge ohne Hausnummer, wenn gleiche mit Hausnummer existiert
                hausnum = entry["hausnummer"]
                if not hausnum or (isinstance(hausnum, str) and hausnum.strip() == ""):
                    # Prüfe, ob eine Version mit Hausnummer existiert
                    has_with_number = any(
                        e["lage_bez"] == entry["lage_bez"]
                        and e["ges_schluessel"] == entry["gesamtschluessel"]
                        and e["hausnummer"]
                        and (isinstance(e["hausnummer"], str) and e["hausnummer"].strip() != "")
                        for e in entries
                    )
                    if has_with_number:
                        continue  # Überspringe diese Einheit ohne Hausnummer

                # Eintrag ist nicht dupliziert und erfüllt Regel 1+2 → hinzufügen
                deduplicated_entries.append(entry)
                seen[dedup_key] = entry

            # NACH REGEL 1+2: Prüfe ob noch mehrere Einträge vorhanden sind
            # Nur dann REGEL 3 anwenden (Validierung von Straßen ohne Y)
            if len(deduplicated_entries) > 1:
                # Prüfe ob es mindestens einen "original" Punkt gibt
                has_original_point = any(e.get("geom_source") == "original" for e in deduplicated_entries)

                if has_original_point:
                    final_entries = []
                    for entry in deduplicated_entries:
                        # REGEL 3 (NEU): Für Polygon-Einträge OHNE Y im gesamtschluessel prüfen,
                        # ob diese Lagebezeichnung räumlich auf diesem Flurstück liegt
                        if entry["geom_source"] == "polygon":  # Nur für Straßen/Gewanne aus Polygonen
                            current_lage_bez = entry.get("lage_bez")
                            current_flst = entry.get("flst")
                            current_ges_schluessel = entry.get("ges_schluessel", "")

                            # Nur validieren, wenn kein Y im gesamtschluessel (Y = Gewann, ok zu behalten)
                            if current_ges_schluessel and "Y" not in current_ges_schluessel:
                                # Räumliche Validierung: Prüfe ob diese Lagebezeichnung auf diesem Flurstück liegt
                                lookup_key = (current_flst, current_lage_bez)
                                lage_exists_on_flst = lookup_key in flst_lage_lookup

                                # Wenn diese Straße NICHT räumlich auf diesem Flurstück liegt, verwerfen
                                if not lage_exists_on_flst:
                                    streets_removed_by_validation += 1
                                    continue

                        # Eintrag erfüllt REGEL 3 oder ist nicht relevant → hinzufügen
                        final_entries.append(entry)

                    deduplicated_entries = final_entries
                # else: keine Lagepunkte → behalte alle Straßen, wende REGEL 3 nicht an
            # else: nur ein Eintrag → alle Regeln erfüllt, nicht ändern
            if len(entries) > len(deduplicated_entries):
                flst_with_multiple += 1
            flst_data[flst_key] = deduplicated_entries
            deduplicated_count += len(deduplicated_entries)

        arcpy.AddMessage(f"  ✓ {processed_flst} Flurstücke verarbeitet, {flst_with_multiple} mit Duplikaten")
        arcpy.AddMessage(f"  ✓ {streets_removed_by_validation} Straßen durch Validierung entfernt")
        arcpy.AddMessage(f"  ✓ Finale Anzahl Lageeinträge: {deduplicated_count}")

        arcpy.AddMessage("  Schreibe deduplizierte Einträge in Ziel-Feature Class...")
        written_count = 0
        skipped_count = 0

        # Erstelle Insert Cursor mit ALLEN Feldern aus flst_lage_combined
        field_types = {}
        for field in arcpy.ListFields("flst_lage_combined"):
            if field.name in all_source_fields:
                field_types[field.name] = field.type
        insert_fields = cursor_fields

        with arcpy.da.InsertCursor("navigation_lage_deduplicated", insert_fields) as insert_cursor:
            for flst_key in flst_data:
                for entry in flst_data[flst_key]:
                    # Prüfe ob Geometrie existiert
                    geom = entry["geom"]

                    if geom is None:
                        skipped_count += 1
                        continue

                    # Baue row_values mit allen Feldern
                    row_values = [geom]

                    # Für jedes Feld versuche den Wert aus entry zu bekommen
                    for field_name in all_source_fields:
                        value = entry.get(field_name, None)

                        row_values.append(value)

                    insert_cursor.insertRow(row_values)
                    written_count += 1

        arcpy.AddMessage(f"  ✓ {written_count} Lageeinträge geschrieben ({skipped_count} übersprungen)")

        # ============================================================================
        # STEP 6: Ergebnisse in Ziel-Tabellen schreiben
        # ============================================================================
        arcpy.AddMessage("\n[STEP 6] Ergebnisse in Ziel-Datei schreiben...")

        # Nur diese Felder behalten
        keep_fields = {
            "flurstueckskennzeichen",
            "lagebezeichnung",
            "lageschluessel",
            "hausnummer",
            "abrufdatum",
            "gesamtschluessel",
            "nummer",
            "zusatz",
            "Shape_Area",
            "Shape_Length",
        }

        # Lösche alle Felder außer den gewünschten (aus navigation_lage_deduplicated)
        arcpy.env.workspace = work_gdb
        all_fields = arcpy.ListFields("navigation_lage_deduplicated")
        fields_to_delete = [
            f.name for f in all_fields if f.type not in ["OID", "Geometry"] and f.name not in keep_fields
        ]

        arcpy.DeleteField_management("navigation_lage_deduplicated", fields_to_delete)

        arcpy.env.workspace = gdb_path

        # Feature Class erstellen/updaten
        if arcpy.Exists("navigation_lage"):
            arcpy.TruncateTable_management("navigation_lage")
            arcpy.AddMessage("  ✓ navigation_lage truncated")
            arcpy.Append_management(
                os.path.join(work_gdb, "navigation_lage_deduplicated"), "navigation_lage", "NO_TEST"
            )
            arcpy.AddMessage("  ✓ Daten in navigation_lage appended")
        else:
            arcpy.FeatureClassToFeatureClass_conversion(
                os.path.join(work_gdb, "navigation_lage_deduplicated"), gdb_path, "navigation_lage"
            )
            arcpy.AddMessage("  ✓ navigation_lage erstellt")

        # ============================================================================
        # CLEANUP
        # ============================================================================
        arcpy.AddMessage("\n[CLEANUP] Temporäre Daten löschen...")
        arcpy.env.workspace = work_gdb

        temp_datasets = [
            "gebaeude_work",
            "lage_work",
            "flst_all_lage_validation",
            "flst_lage_combined",
            "flst_lage_pts_matched",
            "flst_lage_poly_matched",
            "lage_polygon_buffered",
            "lage_work_VIEW",
            "lage_outside_geb",
            "lage_mit_gebid",
            "gebaeude_point",
            "flst_lage_punkte",
            "flst_lage_polygon",
            "flst_lage_union",
            "navigation_lage_deduplicated",
        ]

        for dataset in temp_datasets:
            if arcpy.Exists(dataset):
                arcpy.Delete_management(dataset)

        arcpy.AddMessage("=" * 80)
        arcpy.AddMessage("CALCULATE_LAGE_REFACTORED - ABGESCHLOSSEN")
        arcpy.AddMessage("=" * 80)

        return True

    except Exception as e:
        arcpy.AddError(f"FEHLER bei calculate_lage_refactored: {str(e)}")
        return False

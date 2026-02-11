# -*- coding: utf-8 -*-

# Copyright (c) 2024, Jana Muetsch, Andre Voelkner, LRA Hohenlohekreis
# All rights reserved.
"""
Optimierte SFL- und EMZ-Berechnung mit Pandas-Vectorisierung und Spatial-Index Geometry-Caching.
"""

import os
import math
import time
import pandas as pd
import arcpy
from utils import add_step_message, progress_message
from sfl.init_dataframes import (
    load_nutzung_to_dataframe,
    load_flurstuecke_to_dataframe,
    load_bodenschaetzung_to_dataframe,
)
from sfl.merge_mini_geometries import merge_mini_geometries


def prepare_boden(cfg, gdb_path, workspace, xy_tolerance):
    """
    Bereitet Bodenschätzungs-Daten vor durch Intersect und Dissolve mit Flurstücken.

    Args:
        cfg: Konfigurationsdictionary mit Layer-Definitionen
        gdb_path: Pfad zur Geodatabase
        workspace: ArcGIS Workspace-Pfad
        xy_tolerance: XY-Toleranz für geometrische Operationen

    Returns:
        bool: True bei Erfolg, False bei Fehler
    """
    add_step_message("Vorbereitung der Bodenschätzungs-Daten", 1, 8)

    arcpy.env.workspace = workspace

    try:
        bodenschaetzung_layer = cfg["alkis_layers"]["bodenschaetzung"]
        bewertung_layer = cfg["alkis_layers"]["bewertung"]
        flurstueck_layer = cfg["alkis_layers"]["flurstueck"]
        bodenschaetzung = os.path.join(gdb_path, bodenschaetzung_layer)
        flurstueck = os.path.join(gdb_path, flurstueck_layer)
        bewertung = os.path.join(gdb_path, bewertung_layer)
        nutzung_dissolve = os.path.join(gdb_path, "fsk_x_nutzung")

        if not all(arcpy.Exists(fc) for fc in [bodenschaetzung, flurstueck, bewertung]):
            arcpy.AddError(
                f"Notwendige Eingabe-Layer {bodenschaetzung_layer}, {bewertung_layer} oder {flurstueck_layer} nicht vorhanden"
            )
            return False

        arcpy.AddMessage("- Überschneide Bodenschätzung und Flurstück...")
        # FSK Bodenschätzung - Intersect
        arcpy.PairwiseIntersect_analysis(
            [bodenschaetzung, flurstueck], "bodenschaetzung_intersect", "NO_FID", xy_tolerance, "INPUT"
        )

        nutz = cfg["nutzung"]
        flst = cfg["flurstueck"]
        bod = cfg["bodenschaetzung"]
        bew = cfg["bewertung"]

        dissolve_fields = [
            bod["bodenart_id"],
            bod["bodenart_name"],
            bod["nutzungsart_id"],
            bod["nutzungsart_name"],
            bod["entstehung_id"],
            bod["entstehung_name"],
            bod["klima_id"],
            bod["klima_name"],
            bod["wasser_id"],
            bod["wasser_name"],
            bod["bodenstufe_id"],
            bod["bodenstufe_name"],
            bod["zustand_id"],
            bod["zustand_name"],
            bod["sonstige_angaben_id"],
            bod["sonstige_angaben_name"],
            bod["bodenzahl"],
            bod["ackerzahl"],
            flst["flurstueckskennzeichen"],
            flst["amtliche_flaeche"],
        ]
        arcpy.AddMessage("- Dissolve Bodenschätzung...")
        # Dissolve
        arcpy.PairwiseDissolve_analysis(
            "bodenschaetzung_intersect",
            "bodenschaetzung_dissolve",
            ";".join(dissolve_fields),
        )

        arcpy.AddMessage("- Füge SFL- und EMZ-Felder hinzu...")
        # Felder hinzufügen
        for field_name, field_type in [("sfl", "LONG"), ("emz", "LONG")]:
            arcpy.AddField_management(
                "bodenschaetzung_dissolve",
                field_name,
                field_type,
                None,
                None,
                None,
                field_name.upper(),
                "NULLABLE",
                "NON_REQUIRED",
            )

        # Filterung: Nur relevante Nutzungsarten behalten -> Landwirtschaft, Heide, Sumpf, UnlandVegetationsloseFlaeche und GFLF/ Landwirtschaftliche Betriebsfläche/Forstwirtschaftliche Betriebsfläche und Garten
        arcpy.AddMessage("- Filtere nur relevante Nutzungen aus Bodenschätzung...")
        arcpy.MakeFeatureLayer_management(
            nutzung_dissolve,
            "nutzung_lyr",
            where_clause=f"NOT (({nutz['objektart']} IN (43001, 43004, 43005, 43006, 43007)) OR ({nutz['objektart']} = 41008 AND {nutz['unterart_name']} IN ('Garten')))",
        )

        arcpy.Erase_analysis("bodenschaetzung_dissolve", "nutzung_lyr", "schaetzung_relevante_nutz", xy_tolerance)

        arcpy.AddMessage("- Entferne Bewertungsflächen ohne Bodenschätzung (VWVLK Anlage 1)...")
        # Bewertungen ausschließen siehe VWVLK Anlage 1, Objektart Bewertung
        # Forstwirtschaftliche Nutzung (H), Weinbauliche Nutzung, allgemein (WG), Teichwirtschaft (TEIW), Abbauland der Land- und Forstwirtschaft (LFAB), Geringstland (GER),
        # Unland (U), Nebenfläche des Betriebs der Land- und Forstwirtschaft (NF), u.a.
        arcpy.MakeFeatureLayer_management(
            bewertung,
            "bewertung_lyr",
            f"{bew['klassifizierung_id']} IN (3100, 3105, 3200, 3411, 3480, 3481, 3482, 3490, 3510, 3520, 3530, 3600, 3611, 3610, 3612, 3613, 3614, 3615, 3616, 3710, 3999)",
        )
        arcpy.Erase_analysis("schaetzung_relevante_nutz", "bewertung_lyr", "fsk_bodenschaetzung", xy_tolerance)

        add_step_message("Hinzufügen der Bewertungsflächen", 2, 8)

        arcpy.AddMessage("- Verschneide Flurstück und Bewertung...")
        # Bewertungsflächenverschnitt
        arcpy.PairwiseIntersect_analysis(
            [flurstueck, bewertung], "fsk_bewertung_intersect", "ALL", xy_tolerance, "INPUT"
        )

        arcpy.AddMessage("- Filtere Bewertungen mit relevanten Nutzungen...")
        # Filterung: Nur relevante Nutzungsarten für Bewertungen behalten -> Landwirtschaft, Vegetation, UnlandVegetationsloseFlaeche und GFLF/ Landwirtschaftliche Betriebsfläche/Forstwirtschaftliche Betriebsfläche und Garten
        arcpy.MakeFeatureLayer_management(
            nutzung_dissolve,
            "nutzung_m_wald",
            where_clause=f"NOT (({nutz['objektart']} IN (43001, 43004, 43006, 43007, 43002, 43003, 43005)) OR ({nutz['objektart']} = 41006 AND {nutz['unterart_name']} IN ('Gebäude- und Freifläche Land- und Forstwirtschaft', 'Landwirtschaftliche Betriebsfläche', 'Forstwirtschaftliche Betriebsfläche')) OR ({nutz['objektart']} = 41008 AND {nutz['unterart_name']} IN ('Garten')))",
        )

        arcpy.Erase_analysis("fsk_bewertung_intersect", "nutzung_m_wald", "fsk_bewertung_nutz", xy_tolerance)

        # Filtere Wasserflächen- Bewertungen über Nutzung Wasser
        arcpy.AddMessage("- Prüfe Wasserflächen-Bewertungen mit Wasser-Nutzungen...")
        arcpy.MakeFeatureLayer_management(
            nutzung_dissolve,
            "gewaesser_nutzung",
            where_clause=f"NOT ({nutz['objektart']} IN (44001, 44006))",
        )

        arcpy.MakeFeatureLayer_management(
            "fsk_bewertung_intersect",
            "fsk_bewertung_was",
            where_clause=f'{bew["klassifizierung_id"]} IN (3480, 3481, 3482, 3490)',
        )

        arcpy.Erase_analysis("fsk_bewertung_was", "gewaesser_nutzung", "fsk_bewertung_gewaesser", xy_tolerance)

        arcpy.Merge_management(["fsk_bewertung_gewaesser", "fsk_bewertung_nutz"], "fsk_bewertung_merge")

        bewertung_dissolve_fields = [
            bew["klassifizierung_id"],
            bew["klassifizierung_name"],
            flst["flurstueckskennzeichen"],
            flst["amtliche_flaeche"],
        ]
        arcpy.PairwiseDissolve_analysis(
            "fsk_bewertung_merge",
            "fsk_bewertung_dissolve",
            ";".join(bewertung_dissolve_fields),
        )

        arcpy.AddMessage("- Lade Bewertung in Bodenschätzung und setze Bodenzahl, Ackerzahl und EMZ=0...")

        flstkennzeichen = flst["flurstueckskennzeichen"]
        afl = flst["amtliche_flaeche"]
        nutzungsart_id = bod["nutzungsart_id"]
        nutzungsart_name = bod["nutzungsart_name"]
        klassifizierung_id = bew["klassifizierung_id"]
        klassifizierung_name = bew["klassifizierung_name"]
        sonstige_angaben_name = bod["sonstige_angaben_name"]

        field_mapping = (
            rf'{flstkennzeichen} "flurstueckskennzeichen" true true false 254 Text 0 0,First,#,"fsk_bewertung_dissolve",{flstkennzeichen},0,254;'
            rf'{afl} "amtliche_flaeche" true true false 4 Long 0 0,First,#,"fsk_bewertung_dissolve",{afl},-1,-1;'
            rf'{nutzungsart_id} "nutzungsart_id" true true false 4 Long 0 0,First,#,"fsk_bewertung_dissolve",{klassifizierung_id},-1,-1;'
            rf'{nutzungsart_name} "nutzungsart_name" true true false 254 Text 0 0,First,#,"fsk_bewertung_dissolve",{klassifizierung_name},0,254;'
            rf'{sonstige_angaben_name} "sonstige_angaben_name" true true false 254 Text 0 0,First,#,"fsk_bewertung_dissolve",{klassifizierung_name},0,254'
        )

        arcpy.Append_management("fsk_bewertung_dissolve", "fsk_bodenschaetzung", "NO_TEST", field_mapping)

        # Bewertungsflächenanhang konstante Werte setzen
        with arcpy.da.UpdateCursor(
            "fsk_bodenschaetzung",
            [bod["bodenzahl"], bod["ackerzahl"], "emz", bod["sonstige_angaben_id"]],
            f"{bod['bodenart_name']} IS NULL",
        ) as ucursor:
            for row in ucursor:
                row[0] = 0
                row[1] = 0
                row[2] = 0
                row[3] = 9999
                ucursor.updateRow(row)

        return True

    except Exception as e:
        arcpy.AddError(f"Fehler bei prepare_boden: {str(e)}")
        return False


def vectorized_calculate_sfl_boden(
    cfg, gdb_path, workspace, max_shred_qm, merge_area, flaechenformindex, delete_unmerged_mini, delete_area
):
    """
    Führt die SFL- und EMZ-Berechnung für Bodenschätzung durch mit Pandas-Vectorisierung.

    Args:
        cfg: Konfigurationsdictionary mit Layer-Definitionen
        gdb_path: Pfad zur Geodatabase
        workspace: ArcGIS Workspace-Pfad
        max_shred_qm: Schwellenwert für Mini-Flächen-Identifikation in m²
        merge_area: Minimale Flächengröße für Erhaltung in m²
        flaechenformindex: Maximaler Flächenformindex für Erhaltung (niedrig = kompakt)
        delete_unmerged_mini: Bool, ob nicht gemergte Mini-Flächen gelöscht werden sollen
    """

    try:
        add_step_message("Erstelle pandas-Dataframes", 3, 8)
        # Laden in DataFrame
        df_flurstuecke = load_flurstuecke_to_dataframe(cfg, gdb_path)
        if df_flurstuecke is False or df_flurstuecke.empty:
            return False
        df_nutzung = load_nutzung_to_dataframe(cfg, gdb_path)
        if df_nutzung is False or df_nutzung.empty:
            return False
        df_bodenschaetzung = load_bodenschaetzung_to_dataframe(cfg, workspace)
        if df_bodenschaetzung is False or df_bodenschaetzung.empty:
            return False

        arcpy.AddMessage("- Merge Flurstücks-Verbesserungen in Bodenschätzung...")
        df = df_bodenschaetzung.merge(
            df_flurstuecke[["fsk", "verbesserung"]],
            on="fsk",
            how="left",
            suffixes=("", "_fsk"),
        )

        arcpy.AddMessage("- Berechne Schätzungs-AFL pro FSK...")
        df = df.sort_values(["fsk", "geom_area"], ignore_index=True)

        # Nur die relevanten Nutzungen filtern UND im Speicher halten
        relevant_mask = (
            (df_nutzung["objektart"].isin([43001, 43004, 43006, 43007]))
            | ((df_nutzung["objektart"] == 41006) & (df_nutzung["unterart_id"].isin([2700, 6800])))
            | ((df_nutzung["objektart"] == 41008) & (df_nutzung["unterart_id"].isin([4460])))
        )
        df_relevant_nutzung = df_nutzung[relevant_mask].copy()

        if len(df_relevant_nutzung) > 0:
            schaetz_afl_dict = df_relevant_nutzung.groupby("fsk")["sfl"].sum().to_dict()
        else:
            schaetz_afl_dict = {}
        # Ziehe Bewertungsflächen ab (sonstige_angaben_id == 9999 im df_bodenschaetzung)

        bewertung_mask = df["sonstige_angaben_id"] == 9999

        if bewertung_mask.any():
            bew_afl = (df[bewertung_mask]["geom_area"] * df[bewertung_mask]["verbesserung"] + 0.5).astype(int)
            bew_afl_dict = df[bewertung_mask][["fsk"]].assign(bew_sfl=bew_afl).groupby("fsk")["bew_sfl"].sum().to_dict()

            for fsk, bew_sum in bew_afl_dict.items():
                if fsk in schaetz_afl_dict:
                    schaetz_afl_dict[fsk] -= bew_sum

        df["schaetz_afl"] = df["fsk"].map(schaetz_afl_dict).fillna(0).astype(int)

        arcpy.AddMessage("- Berechne gerundete Feature-SFL und EMZ mit Verbesserungsfaktor...")
        # Fülle fehlende Werte und filtere nicht-finite Werte
        df["verbesserung"] = df["verbesserung"].fillna(1.0)
        df["ackerzahl"] = df["ackerzahl"].fillna(0)
        df["geom_area"] = df["geom_area"].fillna(0)

        # Ersetze inf Werte mit 0
        df["verbesserung"] = df["verbesserung"].replace([float("inf"), float("-inf")], 0)
        df["ackerzahl"] = df["ackerzahl"].replace([float("inf"), float("-inf")], 0)
        df["geom_area"] = df["geom_area"].replace([float("inf"), float("-inf")], 0)

        # Berechne SFL und EMZ
        df["sfl"] = (df["geom_area"] * df["verbesserung"] + 0.5).astype(int)
        df["emz"] = (df["sfl"] / 100 * df["ackerzahl"]).round().astype(int)

        add_step_message("Vereinige Kleinstflächen geometrisch mit Nachbarn", 4, 8)

        df_main, df_delete, df_not_merged = merge_mini_geometries(
            df, workspace, max_shred_qm, merge_area, flaechenformindex, delete_area, "bodenschaetzung"
        )
        if delete_unmerged_mini:
            df_delete = pd.concat([df_delete, df_not_merged], ignore_index=True)
            arcpy.AddMessage(
                f"- {len(df_not_merged)} Kleinstflächen, die nicht gemerged wurden, werden am Ende zusätzlich gelöscht..."
            )

        add_step_message("Nachbearbeitung der Bewertungsflächen nach Merge", 5, 8)

        bewertung_mask = df_main["sonstige_angaben_id"] == 9999
        df_bodenschaetzung = df_main[~bewertung_mask].copy()  # Nur echte Bodenschätzungen
        df_bewertung = df_main[bewertung_mask].copy()  # Bewertungsflächen separat

        if bewertung_mask.any():
            df_bewertung.loc[bewertung_mask, "emz"] = 0

        add_step_message("Verteile die Delta-Flächen", 6, 8)

        df_bodenschaetzung = _apply_delta_correction_boden(df_bodenschaetzung, max_shred_qm)

        df_main = pd.concat([df_bodenschaetzung, df_bewertung], ignore_index=True)

        add_step_message("Übertrage Dataframe-Ergebnisse in fsk_bodenschaetzung", 7, 8)

        _write_sfl_to_gdb_boden(workspace, df_main, df_delete)

        return True

    except Exception as e:
        arcpy.AddError(f"Fehler bei vectorized_calculate_sfl_boden: {str(e)}")
        return False


def _apply_delta_correction_boden(df, max_shred_qm):
    start_time = time.time()
    processed_count = 0

    grouped = df.groupby("fsk", sort=False)
    total_groups = len(grouped)
    processed_groups = 0

    for fsk, fsk_data in grouped:
        processed_groups += 1

        # Progress alle 50k Gruppen (oder am Ende)
        progress_message(50000, processed_groups, total_groups, start_time)

        schaetz_afl = fsk_data["schaetz_afl"].iloc[0]

        sfl_sum = fsk_data["sfl"].sum()

        if sfl_sum == schaetz_afl:
            processed_count += len(fsk_data)
            continue

        delta = schaetz_afl - sfl_sum
        abs_delta = abs(delta)

        if abs_delta < max_shred_qm:
            fsk_indices = fsk_data.index
            # Nutze numpy für schnelles Argsort
            sorted_idx = fsk_data["sfl"].values.argsort()[::-1]
            sorted_indices = fsk_indices[sorted_idx]

            rest_anteil = abs_delta

            for idx in sorted_indices:
                sfl = df.at[idx, "sfl"]
                ackerzahl = df.at[idx, "ackerzahl"]

                if sfl < max_shred_qm:
                    rest_anteil -= sfl
                elif rest_anteil > 0:
                    ratio = 1.0 if sfl > schaetz_afl else float(sfl) / float(schaetz_afl)
                    int_anteil = math.ceil(float(abs_delta) * float(ratio))
                    rest_anteil -= int_anteil

                    if delta < 0:
                        int_anteil *= -1

                    new_sfl = sfl + int_anteil
                    new_emz = int(round(new_sfl / 100 * ackerzahl))

                    df.at[idx, "sfl"] = new_sfl
                    df.at[idx, "emz"] = new_emz

        processed_count += len(fsk_data)

    total_time = time.time() - start_time
    arcpy.AddMessage(
        f"- Delta-Korrektur (Bodenschätzung) abgeschlossen: {processed_count} Features in {total_time:.1f}s"
    )
    return df


def _write_sfl_to_gdb_boden(workspace, df_main, df_delete):
    """
    Schreibe SFL und EMZ Werte zurück in GDB.Lösche auch Kleinstflächen-Zeilen.
    """
    try:
        # Batch Update für Main Features
        oid_to_values = dict(zip(df_main["objectid"], zip(df_main["sfl"], df_main["emz"])))
        df_with_geom = df_main[df_main["geometry"].notna()]
        if len(df_with_geom) > 0:
            oid_to_geom = dict(zip(df_with_geom["objectid"], df_with_geom["geometry"]))
        else:
            oid_to_geom = {}
        # oid_to_geom = dict(zip(df_main["objectid"], df_main["geometry"]))

        fsk_bodenschaetzung_path = os.path.join(workspace, "fsk_bodenschaetzung")

        with arcpy.da.UpdateCursor(fsk_bodenschaetzung_path, ["OBJECTID", "sfl", "emz", "SHAPE@"]) as ucursor:
            for row in ucursor:
                oid = row[0]
                update = oid in oid_to_values or oid in oid_to_geom
                if oid in oid_to_values:
                    sfl, emz = oid_to_values[oid]
                    row[1] = sfl
                    row[2] = emz
                if oid in oid_to_geom:
                    row[3] = oid_to_geom[oid]
                if update:
                    ucursor.updateRow(row)

        # Lösche Mini-Flächen
        if len(df_delete) > 0:
            mini_oids = df_delete["objectid"].tolist()
            oid_str = ",".join(map(str, mini_oids))

            with arcpy.da.UpdateCursor(fsk_bodenschaetzung_path, ["OBJECTID"], f"OBJECTID IN ({oid_str})") as ucursor:
                for row in ucursor:
                    ucursor.deleteRow()

        arcpy.AddMessage(
            f"- {len(df_main)} Features aktualisiert, davon {len(df_with_geom)} mit Geometrie, {len(df_delete)} Kleinstflächen gelöscht"
        )

    except Exception as e:
        arcpy.AddError(f"Fehler beim Schreiben (Boden): {str(e)}")
        raise


def finalize_results(gdb_path, workspace, keep_workdata):
    """Übernimmt Ergebnisse in Navigation-Tabellen mit Fieldmapping und Tabellen-Erstellung."""
    try:
        add_step_message("Schreibe Ergebnisse in Ziel-GDB", 8, 8)

        nav_bodensch = os.path.join(gdb_path, "fsk_x_bodenschaetzung")
        fsk_bodenschaetzung = os.path.join(workspace, "fsk_bodenschaetzung")

        if not arcpy.Exists(nav_bodensch):
            # Tabelle existiert nicht -> kopiere zum Erstellen
            arcpy.CopyFeatures_management(fsk_bodenschaetzung, nav_bodensch)
            arcpy.AddMessage("- fsk_x_bodenschaetzung erstellt")
        else:
            # Tabelle existiert -> truncate und append mit Fieldmapping
            arcpy.TruncateTable_management(nav_bodensch)
            arcpy.Append_management(fsk_bodenschaetzung, nav_bodensch, "TEST")
            arcpy.AddMessage("- fsk_x_bodenschaetzung aktualisiert")

        if not keep_workdata:
            add_step_message("CLEANUP -- Lösche Zwischenergebnisse")

            workdata = [
                "fsk_bodenschaetzung",
                "bodenschaetzung_dissolve",
                "bodenschaetzung_intersect",
                "schaetzung_relevante_nutz",
                "schaetzung_o_bewertung",
                "fsk_bewertung",
                "fsk_bewertung_nutz",
                "fsk_bewertung_merge",
                "fsk_bewertung_gewaesser",
                "fsk_bewertung_intersect",
                "fsk_bewertung_dissolve",
                "fsk_bewertung_relevant",
            ]
            for wd in workdata:
                arcpy.Delete_management(os.path.join(workspace, wd))

        return True

    except Exception as e:
        arcpy.AddError(f"Fehler bei finalize_results: {str(e)}")
        return False


def calculate_sfl_bodenschaetzung(
    cfg,
    gdb_path,
    workspace,
    keep_workdata,
    flaechenformindex,
    max_shred_area,
    merge_area,
    delete_unmerged_mini,
    delete_area,
    xy_tolerance,
):
    """
    Hauptfunktion: Berechnet Schnittflächen (SFL) und Ertragsmesszahlen (EMZ) für Bodenschätzung.

    Orchestriert alle Schritte: Vorbereitung, Berechnung, Mini-Flächen-Merge und Finalisierung.

    Args:
        cfg: Konfigurationsdictionary
        gdb_path: Pfad zur Geodatabase
        workspace: ArcGIS Workspace-Pfad
        keep_workdata: Bool, ob Zwischenergebnisse behalten werden sollen
        flaechenformindex: Flächenformindex-Schwellenwert
        max_shred_qm: Schwellenwert für Mini-Flächen in m²
        merge_area: Minimale Fläche für Erhaltung in m²
        delete_unmerged_mini: Bool, ob nicht gemergte Mini-Flächen gelöscht werden sollen
        xy_tolerance: XY-Toleranz für geometrische Operationen



    Returns:
        bool: True bei Erfolg, False bei Fehler
    """

    arcpy.env.workspace = workspace
    arcpy.env.overwriteOutput = True

    if not prepare_boden(cfg, gdb_path, workspace, xy_tolerance):
        return False

    if not vectorized_calculate_sfl_boden(
        cfg,
        gdb_path,
        workspace,
        max_shred_area,
        merge_area,
        flaechenformindex,
        delete_unmerged_mini,
        delete_area,
    ):
        return False

    if not finalize_results(gdb_path, workspace, keep_workdata):
        return False

    return True

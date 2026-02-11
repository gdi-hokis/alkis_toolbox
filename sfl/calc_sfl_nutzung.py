# -*- coding: utf-8 -*-

# Copyright (c) 2024, Jana Muetsch, Andre Voelkner, LRA Hohenlohekreis
# All rights reserved.

"""
Optimierte SFL- und EMZ-Berechnung mit Pandas-Vectorisierung und Spatial-Index Geometry-Caching.
"""
import os
import time
import arcpy
import pandas as pd
from utils import add_step_message, progress_message
from sfl.init_dataframes import (
    load_nutzung_to_dataframe,
    load_flurstuecke_to_dataframe,
)
from sfl.merge_mini_geometries import merge_mini_geometries


def prepare_nutzung(cfg, gdb_path, workspace, xy_tolerance):
    """
    Vorbereitung der Nutzungs-Daten: Überschneidung mit Flurstück und Dissolve.
    """

    arcpy.env.workspace = None
    arcpy.env.overwriteOutput = True

    add_step_message("Vorbereitung der Nutzungs-Daten", step=1, total_steps=6)

    try:
        nutzung_layer = cfg["alkis_layers"]["nutzung"]
        flurstueck_layer = cfg["alkis_layers"]["flurstueck"]
        nutzung = os.path.join(gdb_path, nutzung_layer)
        flurstueck = os.path.join(gdb_path, flurstueck_layer)
        nutzung_dissolve = os.path.join(workspace, "nutzung_dissolve")
        nutzung_intersect = os.path.join(workspace, "nutzung_intersect")

        if not arcpy.Exists(nutzung) or not arcpy.Exists(flurstueck):
            arcpy.AddError(f"{nutzung_layer} oder {flurstueck_layer} nicht vorhanden")
            return False

        # Verschneiden
        arcpy.AddMessage("-  Überschneide Nutzung und Flurstück...")
        arcpy.PairwiseIntersect_analysis([nutzung, flurstueck], nutzung_intersect, "NO_FID", xy_tolerance, "INPUT")

        # Dissolve mit Klassifizierungsfeldern
        arcpy.AddMessage("-  Dissolve...")
        nutz = cfg["nutzung"]
        flst = cfg["flurstueck"]
        dissolve_fields = [
            nutz["objektart"],
            nutz["objektname"],
            nutz["unterart_typ"],
            nutz["unterart_id"],
            nutz["unterart_kuerzel"],
            nutz["unterart_name"],
            nutz["eigenname"],
            nutz["weitere_nutzung_id"],
            nutz["weitere_nutzung_name"],
            nutz["klasse"],
            flst["flurstueckskennzeichen"],
            flst["amtliche_flaeche"],
        ]
        arcpy.PairwiseDissolve_analysis(
            nutzung_intersect,
            nutzung_dissolve,
            ";".join(dissolve_fields),
        )

        arcpy.AddMessage("-  Füge SFL-Feld hinzu...")
        # SFL-Feld hinzufügen
        arcpy.AddField_management(
            nutzung_dissolve,
            "sfl",
            "LONG",
            None,
            None,
            None,
            "Schnittfläche",
            "NULLABLE",
            "NON_REQUIRED",
        )

        return True

    except Exception as e:
        arcpy.AddError(f"Fehler bei Vorbereitung der Nutzung: {str(e)}")
        return False


def vectorized_calculate_sfl_nutzung(
    cfg, gdb_path, workspace, max_shred_qm, merge_area, flaechenformindex, delete_unmerged_mini, delete_area
):
    """
    Vectorisierte Berechnung der SFL für alle Nutzungsflächen.
    """

    try:
        add_step_message("Schritt 2 von 6 -- Erstelle pandas-Dataframes", step=2, total_steps=6)
        # Laden in DataFrame
        df_flurstuecke = load_flurstuecke_to_dataframe(cfg, gdb_path)
        if df_flurstuecke is False or df_flurstuecke.empty:
            return False

        df_nutzung = load_nutzung_to_dataframe(cfg, workspace, "nutzung_dissolve")
        if df_nutzung is False or df_nutzung.empty:
            return False

        # Merge DataFrames auf FSK um Verbesserungsfaktor zu bekommen
        df = df_nutzung.merge(df_flurstuecke[["fsk", "verbesserung"]], on="fsk", how="left")

        # Sortiere nach FSK und Fläche
        df = df.sort_values(["fsk", "geom_area"])

        # Vectorisierte Basis-SFL Berechnung
        arcpy.AddMessage("- Berechne gerundete SFL mit Verbesserungsfaktor...")
        df["raw_sfl"] = df["geom_area"] * df["verbesserung"]
        df["sfl"] = (df["raw_sfl"] + 0.5).astype(int)  # round-half-up

        add_step_message(
            "Schritt 3 von 6 -- Vereinige Kleinstflächen geometrisch mit Nachbarn (im Dataframe)", step=3, total_steps=6
        )

        df_main, df_delete, df_not_merged = merge_mini_geometries(
            df, workspace, max_shred_qm, merge_area, flaechenformindex, delete_area
        )
        if delete_unmerged_mini:
            df_delete = pd.concat([df_delete, df_not_merged], ignore_index=True)
            arcpy.AddMessage(
                f"- {len(df_not_merged)} Kleinstflächen, die nicht gemerged wurden, werden am Ende zusätzlich gelöscht..."
            )
        add_step_message("Schritt 4 von 6 -- Verteile die Delta-Flächen", step=4, total_steps=6)
        # Overlap-Handling: weitere_nutzung_id == 1000
        overlap_mask = df_main["weitere_nutzung_id"] == 1000
        df_main.loc[overlap_mask, "sfl"] = (df_main.loc[overlap_mask, "geom_area"]).astype(int)
        df_main["is_overlap"] = df_main["weitere_nutzung_id"] == 1000

        # Delta-Korrektur pro FSK
        df_main = _apply_delta_correction_nutzung(df_main, max_shred_qm)

        # Zurückschreiben in GDB
        add_step_message("Schritt 5 von 6 -- Übertrage Dataframe-Ergebnisse in nutzung_dissolve", step=5, total_steps=6)
        _write_sfl_to_gdb_nutzung(workspace, df_main, df_delete)
        return True

    except Exception as e:
        arcpy.AddError(f"Fehler bei vectorized_calculate_sfl_nutzung: {str(e)}")
        return False


def _apply_delta_correction_nutzung(df, max_shred_qm):
    """Delta-Korrektur je FSK: kleine Deltas proportional auf große Features verteilen."""
    try:

        start_time = time.time()
        processed_count = 0

        grouped = df.groupby("fsk", sort=False)
        total_groups = len(grouped)
        processed_groups = 0

        for fsk, fsk_data in grouped:
            processed_groups += 1

            # Progress alle 50k Gruppen (oder am Ende)
            progress_message(50000, processed_groups, total_groups, start_time)

            afl = fsk_data["amtliche_flaeche"].iloc[0]

            non_overlap_mask = fsk_data["is_overlap"] == False
            fsk_data_main = fsk_data[non_overlap_mask]
            sfl_sum = fsk_data_main["sfl"].sum()

            if sfl_sum == afl:
                processed_count += len(fsk_data)
                continue

            delta = afl - sfl_sum
            abs_delta = abs(delta)

            # Nur kleine Deltas korrigieren
            if abs_delta >= max_shred_qm:
                processed_count += len(fsk_data)
                continue

            # Sortiere Features nach SFL absteigend
            fsk_indices = fsk_data.index
            sorted_idx = fsk_data["sfl"].values.argsort()[::-1]
            sorted_indices = fsk_indices[sorted_idx]

            # Nur Features >= max_shred_qm berücksichtigen
            eligible_indices = [
                idx for idx in sorted_indices if idx in fsk_data_main.index and fsk_data.at[idx, "sfl"] >= max_shred_qm
            ]

            if not eligible_indices:
                # Nichts zu korrigieren, weil keine geeigneten Features vorhanden
                processed_count += len(fsk_data)
                continue

            total_sfl_eligible = float(sum(df.at[idx, "sfl"] for idx in eligible_indices))
            if total_sfl_eligible <= 0:
                processed_count += len(fsk_data)
                continue

            # Verteile abs_delta: alle außer dem größten bekommen Anteile, der größte bekommt den Rest
            first_idx = eligible_indices[0]  # größtes Feature
            shares = {}

            sum_other = 0
            for idx in eligible_indices[1:]:
                sfl = float(df.at[idx, "sfl"])
                ratio = sfl / total_sfl_eligible
                share = int(abs_delta * ratio)
                shares[idx] = share
                sum_other += share

            # Rest geht an größtes Feature, damit Summe exakt abs_delta wird
            remainder = abs_delta - sum_other
            shares[first_idx] = remainder

            # Anwenden (Vorzeichen beachten)
            sign = 1 if delta >= 0 else -1
            for idx, share in shares.items():
                if not share:
                    continue
                old_sfl = df.at[idx, "sfl"]
                new_sfl = old_sfl + (sign * share)
                df.at[idx, "sfl"] = new_sfl

            processed_count += len(fsk_data)

        total_time = time.time() - start_time
        arcpy.AddMessage(f"- Delta-Korrektur abgeschlossen: {processed_count} Features in {total_time:.1f}s")
        return df
    except Exception as e:
        arcpy.AddError(f"Fehler bei apply_delta_correction: {str(e)}")
        return False


def _write_sfl_to_gdb_nutzung(workspace, df_main, df_delete):
    """
    Schreibe SFL-Werte in GDB zurück mit Batch UpdateCursor.
    Lösche auch Kleinstflächen-Zeilen.
    """

    try:
        # Batch Update für Main Features
        oid_to_sfl = dict(zip(df_main["objectid"], df_main["sfl"]))
        df_with_geom = df_main[df_main["geometry"].notna()]
        if len(df_with_geom) > 0:
            oid_to_geom = dict(zip(df_with_geom["objectid"], df_with_geom["geometry"]))
        else:
            oid_to_geom = {}

        nutzung_dissolve_path = os.path.join(workspace, "nutzung_dissolve")

        with arcpy.da.UpdateCursor(nutzung_dissolve_path, ["OBJECTID", "sfl", "SHAPE@"]) as ucursor:
            for row in ucursor:
                oid = row[0]
                update = oid in oid_to_sfl or oid in oid_to_geom
                if oid in oid_to_sfl:
                    row[1] = oid_to_sfl[oid]
                if oid in oid_to_geom:
                    row[2] = oid_to_geom[oid]
                if update:
                    ucursor.updateRow(row)

        # Lösche Mini-Flächen
        if len(df_delete) > 0:
            mini_oids = df_delete["objectid"].tolist()
            oid_str = ",".join(map(str, mini_oids))

            with arcpy.da.UpdateCursor(nutzung_dissolve_path, ["OBJECTID"], f"OBJECTID IN ({oid_str})") as ucursor:
                for row in ucursor:
                    ucursor.deleteRow()

        arcpy.AddMessage(
            f"- {len(df_main)} Features aktualisiert, davon {len(df_with_geom)} mit Geometrie, {len(df_delete)} Kleinstflächen gelöscht"
        )

    except Exception as e:
        arcpy.AddError(f"Fehler beim Schreiben: {str(e)}")
        raise


def finalize_results(cfg, gdb_path, workspace, keep_workdata):
    """Übernimmt Ergebnisse in Navigation-Tabellen mit Fieldmapping und Tabellen-Erstellung."""
    # Zurückschreiben in GDB
    add_step_message("Schreibe Ergebnisse in Ziel-GDB", step=6, total_steps=6)

    try:
        nav_nutzung = os.path.join(gdb_path, "fsk_x_nutzung")
        nutzung_dissolve = os.path.join(workspace, "nutzung_dissolve")
        nutz = cfg["nutzung"]
        flst = cfg["flurstueck"]

        objektart = (nutz["objektart"],)
        objektname = (nutz["objektname"],)
        unterart_typ = (nutz["unterart_typ"],)
        unterart_id = (nutz["unterart_id"],)
        unterart_kuerzel = (nutz["unterart_kuerzel"],)
        unterart_name = (nutz["unterart_name"],)
        eigenname = (nutz["eigenname"],)
        weitere_nutzung_id = (nutz["weitere_nutzung_id"],)
        weitere_nutzung_name = (nutz["weitere_nutzung_name"],)
        klasse = (nutz["klasse"],)
        flstkennzeichen = (flst["flurstueckskennzeichen"],)
        afl = (flst["amtliche_flaeche"],)

        nutzung_field_mapping = (
            rf'{objektart} "Objektart" true true false 8 Double 8 38,First,#,{nutzung_dissolve},{objektart},-1,-1;'
            rf'{objektname} "Nutzung" true true false 255 Text 0 0,First,#,{nutzung_dissolve},{objektname},0,253;'
            rf'{unterart_typ} "Unterart Typ" true true false 255 Text 0 0,First,#,f{nutzung_dissolve},{unterart_typ},0,253;'
            rf'{unterart_id} "Unterart Schlüssel" true true false 8 Double 8 38,First,#,{nutzung_dissolve},{unterart_id},-1,-1;'
            rf'{unterart_kuerzel} "Abkürzung" true true false 10 Text 0 0,First,#,{nutzung_dissolve},{unterart_kuerzel},0,49;'
            rf'{unterart_name} "Unterart" true true false 255 Text 0 0,First,#,{nutzung_dissolve},{unterart_name},0,253;'
            rf'{eigenname} "Eigenname" true true false 50 Text 0 0,First,#,{nutzung_dissolve},{eigenname},0,253;'
            rf'{weitere_nutzung_id} "weitere Nutzung Schlüssel" true true false 8 Double 8 38,First,#,{nutzung_dissolve},{weitere_nutzung_id},0,254;'
            rf'{weitere_nutzung_name} "weitere Nutzung" true true false 255 Text 0 0,First,#,{nutzung_dissolve},{weitere_nutzung_name},0,253;'
            rf'{klasse} "Klasse" true true false 8 Double 8 38,First,#,{nutzung_dissolve},{klasse},-1,-1;'
            rf'{flstkennzeichen} "Flurstückskennzeichen" true true false 255 Text 0 0,First,#,{nutzung_dissolve},{flstkennzeichen},0,253;'
            rf'{afl} "Amtliche Fläche [m²]" true true false 4 Long 0 10,First,#,{nutzung_dissolve},{afl},-1,-1;'
            rf'sfl "Fläche [m²]" true true false 4 Long 0 10,First,#,{nutzung_dissolve},sfl,-1,-1'
        )

        if not arcpy.Exists(nav_nutzung):
            # Tabelle existiert nicht -> kopiere mit Fieldmapping zum Erstellen
            arcpy.CopyFeatures_management(nutzung_dissolve, nav_nutzung)
            arcpy.AddMessage("- fsk_x_nutzung erstellt")
        else:
            # Tabelle existiert -> truncate und append mit Fieldmapping
            arcpy.TruncateTable_management(nav_nutzung)
            arcpy.Append_management(nutzung_dissolve, nav_nutzung, "NO_TEST", nutzung_field_mapping)
            arcpy.AddMessage("- fsk_x_nutzung aktualisiert")

        if not keep_workdata:
            add_step_message("CLEANUP -- Lösche Zwischenergebnisse")
            arcpy.Delete_management(os.path.join(workspace, "nutzung_intersect"))
            arcpy.Delete_management(nutzung_dissolve)

        return True

    except Exception as e:
        arcpy.AddError(f"Fehler bei finalize_results: {str(e)}")
        return False


def calculate_sfl_nutzung(
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
    :return: True bei Erfolg, False bei Fehler
    """
    try:

        arcpy.env.workspace = workspace
        arcpy.env.overwriteOutput = True

        if not prepare_nutzung(cfg, gdb_path, workspace, xy_tolerance):
            return False

        if not vectorized_calculate_sfl_nutzung(
            cfg, gdb_path, workspace, max_shred_area, merge_area, flaechenformindex, delete_unmerged_mini, delete_area
        ):
            return False

        if not finalize_results(cfg, gdb_path, workspace, keep_workdata):
            return False

        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei calculate_sfl_nutzung: {str(e)}")
        return False

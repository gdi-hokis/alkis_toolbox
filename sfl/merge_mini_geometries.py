# -*- coding: utf-8 -*-

# Copyright (c) 2024, Jana Muetsch, Andre Voelkner, LRA Hohenlohekreis
# All rights reserved.

"""
Generalisierte Mini-Flächen-Merge-Utilities für SFL-Berechnungen (Nutzung und Bodenschätzung).
Unterstützt unterschiedliche Recalculation-Logiken via Typ-Parameter.
"""

import arcpy
import time
import pandas as pd
import numpy as np

try:
    from shapely.geometry import shape

    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    arcpy.AddError("Shapely nicht verfügbar - Mini-Flächen-Merge wird übersprungen")


def merge_mini_geometries(df, max_shred_qm, merge_area, flaechenformindex, calc_type="nutzung"):
    # Kleinstflächen-Filterung pro FSK
    mask_mini = (df["sfl"] <= max_shred_qm) & (df["amtliche_flaeche"] > max_shred_qm)

    df.loc[mask_mini, "is_mini"] = True
    df.loc[~mask_mini, "is_mini"] = False

    # Separate mini und non-mini Features
    df_mini = df[df["is_mini"] == True].copy()
    df_main = df[df["is_mini"] == False].copy()

    arcpy.AddMessage(f"- Identifiziert {len(df_mini)} Kleinstflächen zur Verarbeitung")

    df_mini_not_merged = pd.DataFrame()

    # Mini-Flächen-Filterung: Nur die mergen, die WENIGER als 1 m² bei Verteilung ergeben
    if len(df_mini) > 0:
        # Trennung: erhaltungswürdig (>= 1) vs. zu mergen (< 1)
        mask_keep = df_mini["sfl"] >= merge_area
        df_mini["perimeter"] = df_mini["geometry"].apply(lambda geom: geom.length)
        df_mini["form_index"] = df_mini["perimeter"] / np.sqrt(df_mini["geom_area"])

        # Schmale, lange Schnipsel filtern (form_index < flaechenformindex_input = sehr dünn)
        mask_real_feature = df_mini["form_index"] < flaechenformindex
        df_mini_keep = df_mini[(mask_keep) & (mask_real_feature)].copy()
        df_mini_merge = df_mini[(~mask_keep) | (~mask_real_feature)].copy()

        arcpy.AddMessage(
            f"- {len(df_mini_keep)} Mini-Flächen erhalten (>= {merge_area} m² und Flächenformindex <{flaechenformindex}), "
            f"- {len(df_mini_merge)} Mini-Flächen werden gemergt (< {merge_area} m²) oder Flächenformindex >={flaechenformindex})"
        )

        # Erhaltungswürdige Mini-Flächen zu Main hinzufügen
        df_main = pd.concat([df_main, df_mini_keep], ignore_index=True)

        # Merge zu verlustende Mini-Flächen mit angrenzenden Hauptflächen
        # Nach dem Merge: ungemergte werden zu Main hinzugefügt, gemergte werden aus df_mini entfernt
        if len(df_mini_merge) > 0 and SHAPELY_AVAILABLE:
            df_main_after_merge, df_mini_to_delete, df_mini_not_merged = merge(
                df_main, df_mini_merge, calc_type=calc_type
            )
            df_main = df_main_after_merge
            df_mini = df_mini_to_delete  # Nur die tatsächlich gemergt wurden
        else:
            df_mini = pd.DataFrame()

        # Nichts zu mergen
    return df_main, df_mini, df_mini_not_merged


def merge(df_main, df_mini, calc_type):

    start_time = time.time()
    merged_oids = set()
    tolerance = 0.1  # 10cm Buffer für Toleranz
    total_mini = len(df_mini)
    processed_mini = 0

    # Loop durch Mini-Flächen (äußerer Loop = klein!)
    for _, mini_row in df_mini.iterrows():
        processed_mini += 1
        mini_oid = mini_row["objectid"]
        mini_geom = mini_row["geometry"]
        mini_fsk = mini_row["fsk"]

        # Progress alle 1000 Features oder am Ende
        if processed_mini % 1000 == 0 or processed_mini == total_mini:
            elapsed = time.time() - start_time
            arcpy.AddMessage(
                f"    Fortschritt: {processed_mini}/{total_mini} Mini-Flächen verarbeitet "
                f"({len(merged_oids)} erfolgreich gemergt, {elapsed:.1f}s)"
            )

        # Hole nur Main-Features dieser FSK
        fsk_main_mask = df_main["fsk"] == mini_fsk
        if not fsk_main_mask.any():
            continue

        fsk_main_idx = df_main[fsk_main_mask].index
        best_match_idx = None

        # === Strategie 1: Direct touches/intersects ===
        for main_idx in fsk_main_idx:
            main_geom = df_main.at[main_idx, "geometry"]
            try:
                if main_geom.touches(mini_geom) or main_geom.intersects(mini_geom):
                    best_match_idx = main_idx
                    break
            except:
                pass

        # === Strategie 2: Distance check mit Toleranz ===
        if best_match_idx is None:
            min_distance = float("inf")
            for main_idx in fsk_main_idx:
                main_geom = df_main.at[main_idx, "geometry"]
                try:
                    distance = main_geom.distance(mini_geom)
                    if distance < tolerance and distance < min_distance:
                        min_distance = distance
                        best_match_idx = main_idx
                except:
                    pass

        # === Strategie 3: Buffer - größte angrenzende Fläche ===
        if best_match_idx is None:
            try:
                mini_buffer = mini_geom.buffer(0.5)
                max_area = 0
                for main_idx in fsk_main_idx:
                    main_geom = df_main.at[main_idx, "geometry"]
                    try:
                        if mini_buffer.intersects(main_geom):
                            if main_geom.area > max_area:
                                max_area = main_geom.area
                                best_match_idx = main_idx
                    except:
                        pass
            except:
                pass

        # === Merge durchführen ===
        if best_match_idx is not None:
            try:
                main_geom = df_main.at[best_match_idx, "geometry"]
                union_geom = main_geom.union(mini_geom)
                union_area = union_geom.area

                df_main.at[best_match_idx, "geometry"] = union_geom
                df_main.at[best_match_idx, "geom_area"] = union_area

                # SFL mit neuer Fläche berechnen
                verbesserung = df_main.at[best_match_idx, "verbesserung"]
                new_sfl = int(union_area * verbesserung + 0.5)
                df_main.at[best_match_idx, "sfl"] = new_sfl

                # Typ-spezifische Recalculation
                if calc_type == "bodenschaetzung":
                    # EMZ auch neu berechnen
                    ackerzahl = df_main.at[best_match_idx, "ackerzahl"]
                    new_emz = int(round(new_sfl / 100 * ackerzahl))
                    df_main.at[best_match_idx, "emz"] = new_emz

                merged_oids.add(mini_oid)
            except Exception as e:
                arcpy.AddWarning(f"    Merge für Mini {mini_oid} fehlgeschlagen: {e}")

    df_mini_deleted = df_mini[df_mini["objectid"].isin(merged_oids)].copy()
    df_mini_not_merged = df_mini[~df_mini["objectid"].isin(merged_oids)].copy()
    elapsed = time.time() - start_time

    # Warnung für nicht-gemergte Flächen
    if len(df_mini_not_merged) > 0:
        arcpy.AddWarning(
            f"    WARNUNG: {len(df_mini_not_merged)} Mini-Flächen konnten nicht an angrenzendes Flurstück angeschmiegt werden."
        )

    arcpy.AddMessage(f"    {len(merged_oids)}/{len(df_mini)} Mini-Flächen gemergt ({elapsed:.2f}s)")

    # Alle Mini-Flächen zurückgeben (gemergt + nicht-gemergt) zum Löschen
    return df_main, df_mini_deleted, df_mini_not_merged

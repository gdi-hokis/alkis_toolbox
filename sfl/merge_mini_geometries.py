# -*- coding: utf-8 -*-

# Copyright (c) 2024, Jana Muetsch, Andre Voelkner, LRA Hohenlohekreis
# All rights reserved.

"""
Generalisierte Mini-Flächen-Merge-Utilities für SFL-Berechnungen (Nutzung und Bodenschätzung).
Unterstützt unterschiedliche Recalculation-Logiken via Typ-Parameter.
"""
import time
import arcpy
import pandas as pd
import numpy as np


def merge_mini_geometries(df, max_shred_qm, merge_area, flaechenformindex, calc_type="nutzung"):
    """
    Identifiziert und merged Kleinstflächen mit angrenzenden Hauptflächen.

    Filtert Mini-Flächen basierend auf Flächengröße und Flächenformindex.
    Behält erhaltungswürdige Mini-Flächen, merged übrige mit angrenzenden Features.

    Args:
        df: DataFrame mit allen Features (Spalten: sfl, amtliche_flaeche, geometry,
            geom_area, fsk, objectid, verbesserung, ackerzahl für bodenschaetzung)
        max_shred_qm: Schwellenwert für Mini-Flächen-Identifikation in m²
        merge_area: Minimale Flächengröße für Erhaltung in m²
        flaechenformindex: Maximaler Flächenformindex für Erhaltung (niedrig = kompakt)
        calc_type: Berechnungstyp 'nutzung' oder 'bodenschaetzung' (berechnet EMZ bei Bodenschätzung)

    Returns:
        tuple: (df_main, df_mini, df_mini_not_merged)
            - df_main: Alle Flächen nach Merge (Haupt- + erhaltungswürdige Mini)
            - df_mini: Erfolgreich gemergte Mini-Flächen
            - df_mini_not_merged: Mini-Flächen, die nicht an Features angrenzen
    """
    try:
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
                f"- {len(df_mini_keep)} Mini-Flächen erhalten (>= {merge_area} m² und Flächenformindex <{flaechenformindex})"
            )
            arcpy.AddMessage(
                f"- {len(df_mini_merge)} Mini-Flächen werden gemergt (< {merge_area} m²) oder Flächenformindex >={flaechenformindex})"
            )

            # Erhaltungswürdige Mini-Flächen zu Main hinzufügen
            df_main = pd.concat([df_main, df_mini_keep], ignore_index=True)

            # Merge zu verlustende Mini-Flächen mit angrenzenden Hauptflächen
            # Nach dem Merge: ungemergte werden zu Main hinzugefügt, gemergte werden aus df_mini entfernt
            if len(df_mini_merge) > 0:
                df_main_after_merge, df_mini_to_delete, df_mini_not_merged = process_merging(
                    df_main, df_mini_merge, calc_type=calc_type
                )
                df_main = df_main_after_merge
                df_mini = df_mini_to_delete  # Nur die tatsächlich gemergt wurden
            else:
                df_mini = pd.DataFrame()

            # Nichts zu mergen
        return df_main, df_mini, df_mini_not_merged
    except Exception as e:
        arcpy.AddError(f"Fehler beim Merge von Mini-Flächen: {str(e)}")
        return False


def process_merging(df_main, df_mini, calc_type):
    """
    Merged Mini-Flächen mit angrenzenden Hauptflächen basierend auf Geometrie-Kontakt.

    Args:
        df_main: DataFrame mit Hauptflächen
        df_mini: DataFrame mit Mini-Flächen zum Mergen
        calc_type: Berechnungstyp ('nutzung' oder 'bodenschaetzung') - bei Bodenschätzung wird EMZ kalkuliert

    Returns:
        tuple: (df_main_after_merge, df_mini_deleted, df_mini_not_merged)
            - df_main_after_merge: Hauptflächen nach Merge-Operation
            - df_mini_deleted: Erfolgreich gemergte Mini-Flächen
            - df_mini_not_merged: Mini-Flächen, die nicht gemergt werden konnten
    """

    start_time = time.time()
    merged_oids = set()
    total_mini = len(df_mini)
    processed_mini = 0

    # Loop durch Mini-Flächen (äußerer Loop = klein!)
    for _, mini_row in df_mini.iterrows():
        processed_mini += 1
        mini_oid = mini_row["objectid"]
        mini_geom = mini_row["geometry"]
        mini_fsk = mini_row["fsk"]

        # Progress alle 1000 Features oder am Ende
        if not processed_mini % 2000 or processed_mini == total_mini:
            elapsed = time.time() - start_time
            arcpy.AddMessage(
                f"- Fortschritt: {processed_mini}/{total_mini} Mini-Flächen verarbeitet "
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
            except Exception:
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
                arcpy.AddWarning(f"- Merge für Mini {mini_oid} fehlgeschlagen: {e}")

    df_mini_deleted = df_mini[df_mini["objectid"].isin(merged_oids)].copy()
    df_mini_not_merged = df_mini[~df_mini["objectid"].isin(merged_oids)].copy()
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = elapsed % 60

    arcpy.AddMessage(f"- {len(merged_oids)}/{len(df_mini)} Mini-Flächen gemergt ({minutes}min {seconds:.2f}s)")

    # Warnung für nicht-gemergte Flächen
    if len(df_mini_not_merged) > 0:
        arcpy.AddWarning(
            f"{len(df_mini_not_merged)} Mini-Flächen konnten nicht an angrenzendes Flurstück angeschmiegt werden."
        )

    # Alle Mini-Flächen zurückgeben (gemergt + nicht-gemergt) zum Löschen
    return df_main, df_mini_deleted, df_mini_not_merged

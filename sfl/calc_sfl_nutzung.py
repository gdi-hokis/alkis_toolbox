# -*- coding: utf-8 -*-

# Copyright (c) 2024, Jana Muetsch, Andre Voelkner, LRA Hohenlohekreis
# All rights reserved.

"""
Optimierte SFL- und EMZ-Berechnung mit Pandas-Vectorisierung und Spatial-Index Geometry-Caching.
"""

import arcpy
import os
import time
import pandas as pd
import numpy as np
from sfl.init_dataframes import DataFrameLoader
from config.config_loader import FieldConfigLoader

try:
    from shapely.geometry import shape

    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    arcpy.AddWarning("Shapely nicht verfügbar - Mini-Flächen-Merge wird übersprungen")


class SFLCalculatorNutzung(DataFrameLoader):
    """
    Optimierte Klasse für SFL- und EMZ-Berechnungen mit Pandas/NumPy Vectorisierung.
    """

    def __init__(self, gdb_path, workspace, keep_workdata, flaechenformindex, max_shred_area, merge_area):
        """
        Initialisiert den optimierten SFL Calculator.

        :param gdb_path: Pfad zur Geodatabase
        :param workspace: Arbeitsverzeichnis für temporäre Daten
        """
        self.gdb_path = gdb_path
        self.workspace = workspace
        self.max_shred_qm = (
            max_shred_area  # Schwellenwert für Kleinstflächen - alles wo fläche kleiner aber afl größer ist
        )

        self.merge_area = merge_area  # Splitterflächengröße für Kleinstflächen, die ohne Merge in angrenzende Geometrie erhalten bleiben

        self.flaechenformindex = flaechenformindex

        arcpy.env.workspace = self.workspace
        arcpy.env.overwriteOutput = True

        # DataFrames für Zwischenspeicherung (werden beim Load gefüllt)
        self.df_flurstuecke = None  # FSK, geometry_area, amtliche_flaeche, verbesserung
        self.df_nutzung = None  # Alle Nutzung Features mit Geometrien

        self.geom_cache_nutzung = {}  # Geometry Cache für Nutzung Features

        self.keep_workdata = keep_workdata
        self.cfg = FieldConfigLoader.load_config()
        self.nutz = self.cfg["nutzung"]
        self.flst = self.cfg["flurstueck"]

    def prepare_nutzung(self):
        arcpy.AddMessage("Vorbereitung der Nutzung-Daten...")

        try:
            nutzung_layer = FieldConfigLoader.get("alkis_layers", "nutzung")
            flurstueck_layer = FieldConfigLoader.get("alkis_layers", "flurstueck")
            nutzung = os.path.join(self.gdb_path, nutzung_layer)
            flurstueck = os.path.join(self.gdb_path, flurstueck_layer)

            if not arcpy.Exists(nutzung) or not arcpy.Exists(flurstueck):
                arcpy.AddError(f"{nutzung_layer} oder {flurstueck_layer} nicht vorhanden")
                return False

            # Verschneiden
            arcpy.PairwiseIntersect_analysis(
                [nutzung, flurstueck], "nutzung_intersect", "NO_FID", "0.001 Meters", "INPUT"
            )
            arcpy.AddMessage("Nutzung-Intersect durchgeführt")

            # Dissolve mit Klassifizierungsfeldern
            nutz = self.nutz
            flst = self.flst
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
                "nutzung_intersect",
                "nutzung_dissolve",
                ";".join(dissolve_fields),
            )
            arcpy.AddMessage("Nutzung-Dissolve durchgeführt")

            # SFL-Feld hinzufügen
            arcpy.AddField_management(
                "nutzung_dissolve", "sfl", "LONG", None, None, None, "Schnittfläche", "NULLABLE", "NON_REQUIRED"
            )

            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei prepare_nutzung: {str(e)}")
            return False

    def vectorized_calculate_sfl_nutzung(self):
        """
        Vectorisierte Berechnung der SFL für alle Nutzungsflächen.
        """
        arcpy.AddMessage("Starte vectorisierte SFL-Berechnung (Nutzung)")

        try:
            # Laden in DataFrame
            if not self.load_flurstuecke_to_dataframe():
                return False
            if not self.load_nutzung_to_dataframe():
                return False

            # Merge DataFrames auf FSK um Verbesserungsfaktor zu bekommen
            df = self.df_nutzung.merge(
                self.df_flurstuecke[["fsk", "verbesserung", "amtliche_flaeche"]], on="fsk", how="left"
            )

            # Sortiere nach FSK und Fläche
            df = df.sort_values(["fsk", "geom_area"])

            # Vectorisierte Basis-SFL Berechnung
            df["raw_sfl"] = df["geom_area"] * df["verbesserung"]
            df["sfl"] = (df["raw_sfl"] + 0.5).astype(int)  # round-half-up

            # Kleinstflächen-Filterung pro FSK
            mask_mini = (df["sfl"] <= self.max_shred_qm) & (df["amtliche_flaeche"] > self.max_shred_qm)

            df.loc[mask_mini, "is_mini"] = True
            df.loc[~mask_mini, "is_mini"] = False

            # Separate mini und non-mini Features
            df_mini = df[df["is_mini"] == True].copy()
            df_main = df[df["is_mini"] == False].copy()

            arcpy.AddMessage(f"  Identifiziert {len(df_mini)} Kleinstflächen zur Verarbeitung")

            # Mini-Flächen-Filterung: Nur die mergen, die WENIGER als 1 m² bei Verteilung ergeben
            if len(df_mini) > 0:
                # Trennung: erhaltungswürdig (>= 1) vs. zu mergen (< 1)
                mask_keep = df_mini["sfl"] >= self.merge_area
                df_mini["perimeter"] = df_mini["geometry"].apply(lambda geom: geom.length)
                df_mini["form_index"] = df_mini["perimeter"] / np.sqrt(df_mini["geom_area"])

                # Schmale, lange Schnipsel filtern (form_index < flaechenformindex_input = sehr dünn)
                mask_real_feature = df_mini["form_index"] < self.flaechenformindex
                df_mini_keep = df_mini[(mask_keep) & (mask_real_feature)].copy()
                df_mini_merge = df_mini[(~mask_keep) | (~mask_real_feature)].copy()

                arcpy.AddMessage(
                    f"    {len(df_mini_keep)} Mini-Flächen erhalten (>= {self.merge_area} m² und Flächenformindex <{self.flaechenformindex}), "
                    f"{len(df_mini_merge)} Mini-Flächen werden gemergt (< {self.merge_area} m²) oder Flächenformindex >={self.flaechenformindex})"
                )

                # Erhaltungswürdige Mini-Flächen zu Main hinzufügen
                df_main = pd.concat([df_main, df_mini_keep], ignore_index=True)

                # Merge zu verlustende Mini-Flächen mit angrenzenden Hauptflächen
                # Nach dem Merge: ungemergte werden zu Main hinzugefügt, gemergte werden aus df_mini entfernt
                if len(df_mini_merge) > 0 and SHAPELY_AVAILABLE:
                    df_main_after_merge, df_mini_to_delete = self._merge_mini_into_main_nutzung(df_main, df_mini_merge)
                    df_main = df_main_after_merge
                    df_mini = df_mini_to_delete  # Nur die tatsächlich gemergt wurden
                else:
                    df_mini = pd.DataFrame()  # Nichts zu mergen

            # Overlap-Handling: weitere_nutzung_id == 1000
            overlap_mask = df_main["weitere_nutzung_id"] == 1000
            df_main.loc[overlap_mask, "sfl"] = (df_main.loc[overlap_mask, "geom_area"]).astype(int)
            df_main["is_overlap"] = df_main["weitere_nutzung_id"] == 1000

            # Delta-Korrektur pro FSK
            df_main = self._apply_delta_correction_nutzung(df_main)

            # Zurückschreiben in GDB
            self._write_sfl_to_gdb_nutzung(df_main, df_mini)

            arcpy.AddMessage("--------Vectorisierte SFL-Berechnung (Nutzung) abgeschlossen--------")
            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei vectorized_calculate_sfl_nutzung: {str(e)}")
            return False

    def _merge_mini_into_main_nutzung(self, df_main, df_mini):
        """
        Merge Mini-Flächen mit angrenzenden Hauptflächen
        - Fallback-Strategien: touches → intersects → buffer-distance
        """
        arcpy.AddMessage("  Merge Kleinstflächen mit Hauptflächen...")

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

            # Progress alle 100 Features oder am Ende
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

                    merged_oids.add(mini_oid)
                except Exception as e:
                    arcpy.AddWarning(f"    Merge für Mini {mini_oid} fehlgeschlagen: {e}")

        df_mini_deleted = df_mini[df_mini["objectid"].isin(merged_oids)].copy()
        df_mini_not_merged = df_mini[~df_mini["objectid"].isin(merged_oids)].copy()
        elapsed = time.time() - start_time

        # Warnung für nicht-gemergte Flächen
        if len(df_mini_not_merged) > 0:
            arcpy.AddWarning(
                f"    WARNUNG: {len(df_mini_not_merged)} Mini-Flächen konnten nicht an angrenzendes Flurstück angeschmiegt werden und werden gelöscht"
            )
            for _, row in df_mini_not_merged.iterrows():
                fsk = row["fsk"]
                oid = row["objectid"]
                sfl = row["sfl"]
                arcpy.AddWarning(f"      FSK {fsk}, OID {oid}, SFL {sfl} m² - GELÖSCHT")

        arcpy.AddMessage(f"    {len(merged_oids)}/{len(df_mini)} Mini-Flächen gemergt ({elapsed:.2f}s)")

        # Alle Mini-Flächen zurückgeben (gemergt + nicht-gemergt) zum Löschen
        all_mini_to_delete = pd.concat([df_mini_deleted, df_mini_not_merged], ignore_index=True)
        return df_main, all_mini_to_delete

    def _apply_delta_correction_nutzung(self, df):
        """Delta-Korrektur je FSK: kleine Deltas (<5 qm) proportional auf große Features verteilen."""
        arcpy.AddMessage("  Wende Delta-Korrektur an...")

        start_time = time.time()
        processed_count = 0

        grouped = df.groupby("fsk", sort=False)
        total_groups = len(grouped)
        processed_groups = 0

        for fsk, fsk_data in grouped:
            processed_groups += 1

            # Progress alle 50k Gruppen (oder am Ende)
            if processed_groups % 50000 == 0 or processed_groups == total_groups:
                elapsed = time.time() - start_time
                arcpy.AddMessage(
                    f"    Fortschritt: {processed_groups}/{total_groups} FSK "
                    f"({processed_count} Features bearbeitet, {elapsed:.1f}s)"
                )

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
            if abs_delta >= self.max_shred_qm:
                processed_count += len(fsk_data)
                continue

            # Sortiere Features nach SFL absteigend
            fsk_indices = fsk_data.index
            sorted_idx = fsk_data["sfl"].values.argsort()[::-1]
            sorted_indices = fsk_indices[sorted_idx]

            # Nur Features >= max_shred_qm berücksichtigen
            eligible_indices = [
                idx
                for idx in sorted_indices
                if idx in fsk_data_main.index and fsk_data.at[idx, "sfl"] >= self.max_shred_qm
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
                if share == 0:
                    continue
                old_sfl = df.at[idx, "sfl"]
                new_sfl = old_sfl + (sign * share)
                df.at[idx, "sfl"] = new_sfl

            processed_count += len(fsk_data)

        total_time = time.time() - start_time
        arcpy.AddMessage(f"  Delta-Korrektur abgeschlossen: {processed_count} Features in {total_time:.1f}s")
        return df

    def _write_sfl_to_gdb_nutzung(self, df_main, df_mini):
        """
        Schreibe SFL-Werte in GDB zurück mit Batch UpdateCursor.
        Lösche auch Kleinstflächen-Zeilen.
        """
        arcpy.AddMessage("  Schreibe SFL-Werte zurück in GDB...")

        try:
            # Batch Update für Main Features
            oid_to_sfl = dict(zip(df_main["objectid"], df_main["sfl"]))
            oid_to_geom = dict(zip(df_main["objectid"], df_main["geometry"]))

            with arcpy.da.UpdateCursor("nutzung_dissolve", ["OBJECTID", "sfl", "SHAPE@"]) as ucursor:
                for row in ucursor:
                    oid = row[0]
                    if oid in oid_to_sfl:
                        row[1] = oid_to_sfl[oid]
                        row[2] = oid_to_geom[oid]
                        ucursor.updateRow(row)

            # Lösche Mini-Flächen
            if len(df_mini) > 0:
                mini_oids = df_mini["objectid"].tolist()
                oid_str = ",".join(map(str, mini_oids))

                with arcpy.da.UpdateCursor("nutzung_dissolve", ["OBJECTID"], f"OBJECTID IN ({oid_str})") as ucursor:
                    for row in ucursor:
                        ucursor.deleteRow()

            arcpy.AddMessage(f"  {len(df_main)} Features aktualisiert, {len(df_mini)} Kleinstflächen gelöscht")

        except Exception as e:
            arcpy.AddError(f"Fehler beim Schreiben: {str(e)}")
            raise

    def finalize_results(self):
        """Übernimmt Ergebnisse in Navigation-Tabellen mit Fieldmapping und Tabellen-Erstellung."""
        try:
            nav_nutzung = os.path.join(self.gdb_path, "fsk_x_nutzung")
            nutz = self.nutz
            flst = self.flst

            nutzung_field_mapping = (
                r'{1} "Objektart" true true false 8 Double 8 38,First,#,{0},{1},-1,-1;'
                r'{2} "Nutzung" true true false 255 Text 0 0,First,#,{0},{2},0,253;'
                r'{3} "Unterart Typ" true true false 255 Text 0 0,First,#,{0},{3},0,253;'
                r'{4} "Unterart Schlüssel" true true false 8 Double 8 38,First,#,{0},{4},-1,-1;'
                r'{5} "Abkürzung" true true false 10 Text 0 0,First,#,{0},{5},0,49;'
                r'{6} "Unterart" true true false 255 Text 0 0,First,#,{0},{6},0,253;'
                r'{7} "Eigenname" true true false 50 Text 0 0,First,#,{0},{7},0,253;'
                r'{8} "weitere Nutzung Schlüssel" true true false 8 Double 8 38,First,#,{0},{8},0,254;'
                r'{9} "weitere Nutzung" true true false 255 Text 0 0,First,#,{0},{9},0,253;'
                r'{10} "Klasse" true true false 8 Double 8 38,First,#,{0},{10},-1,-1;'
                r'{11} "Flurstückskennzeichen" true true false 255 Text 0 0,First,#,{0},{11},0,253;'
                r'{12} "Amtliche Fläche [m²]" true true false 4 Long 0 10,First,#,{0},{12},-1,-1;'
                r'sfl "Fläche [m²]" true true false 4 Long 0 10,First,#,{0},sfl,-1,-1'
            ).format(
                "nutzung_dissolve",
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
            )

            if not arcpy.Exists(nav_nutzung):
                # Tabelle existiert nicht -> kopiere mit Fieldmapping zum Erstellen
                arcpy.CopyFeatures_management("nutzung_dissolve", nav_nutzung)
                arcpy.AddMessage("fsk_x_nutzung erstellt")
            else:
                # Tabelle existiert -> truncate und append mit Fieldmapping
                arcpy.TruncateTable_management(nav_nutzung)
                arcpy.Append_management("nutzung_dissolve", nav_nutzung, "NO_TEST", nutzung_field_mapping)
                arcpy.AddMessage("fsk_x_nutzung aktualisiert")

            if not self.keep_workdata:
                arcpy.Delete_management("nutzung_intersect")
                arcpy.Delete_management("nutzung_dissolve")
                arcpy.AddMessage("Temporäre Arbeitstabellen gelöscht")

            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei finalize_results: {str(e)}")
            return False


def calculate_sfl_nutzung(gdb_path, workspace, keep_workdata, flaechenformindex, max_shred_area, merge_area):
    """
    :return: True bei Erfolg, False bei Fehler
    """
    calculator = SFLCalculatorNutzung(gdb_path, workspace, keep_workdata, flaechenformindex, max_shred_area, merge_area)

    # if not calculator.prepare_nutzung():
    #     return False

    if not calculator.vectorized_calculate_sfl_nutzung():
        return False

    if not calculator.finalize_results():
        return False

    return True

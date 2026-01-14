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
from sfl.init_dataframes import DataFrameLoader
from config.config_loader import FieldConfigLoader
from sfl.merge_mini_geometries import merge_mini_geometries


class SFLCalculatorNutzung(DataFrameLoader):
    """
    Optimierte Klasse für SFL- und EMZ-Berechnungen mit Pandas/NumPy Vectorisierung.
    """

    def __init__(
        self, gdb_path, workspace, keep_workdata, flaechenformindex, max_shred_area, merge_area, delete_unmerged_mini
    ):
        self.gdb_path = gdb_path
        self.workspace = workspace
        self.max_shred_qm = (
            max_shred_area  # Schwellenwert für Kleinstflächen - alles wo Fläche kleiner aber afl größer ist
        )

        self.merge_area = merge_area  # Splitterflächengröße für Kleinstflächen, die ohne Merge in angrenzende Geometrie erhalten bleiben
        self.delete_unmerged_mini = delete_unmerged_mini

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
        arcpy.AddMessage("-" * 40)
        arcpy.AddMessage("Schritt 1 von 6 -- Vorbereitung der Nutzung-Daten...")
        arcpy.AddMessage("-" * 40)

        try:
            nutzung_layer = FieldConfigLoader.get("alkis_layers", "nutzung")
            flurstueck_layer = FieldConfigLoader.get("alkis_layers", "flurstueck")
            nutzung = os.path.join(self.gdb_path, nutzung_layer)
            flurstueck = os.path.join(self.gdb_path, flurstueck_layer)

            if not arcpy.Exists(nutzung) or not arcpy.Exists(flurstueck):
                arcpy.AddError(f"{nutzung_layer} oder {flurstueck_layer} nicht vorhanden")
                return False

            # Verschneiden
            arcpy.AddMessage("-  Überschneide Nutzung und Flurstück...")
            arcpy.PairwiseIntersect_analysis(
                [nutzung, flurstueck], "nutzung_intersect", "NO_FID", "0.001 Meters", "INPUT"
            )

            # Dissolve mit Klassifizierungsfeldern
            arcpy.AddMessage("-  Dissolve...")
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

            # SFL-Feld hinzufügen
            arcpy.AddField_management(
                "nutzung_dissolve", "sfl", "LONG", None, None, None, "Schnittfläche", "NULLABLE", "NON_REQUIRED"
            )

            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei Vorbereitung der Nutzung: {str(e)}")
            return False

    def vectorized_calculate_sfl_nutzung(self):
        """
        Vectorisierte Berechnung der SFL für alle Nutzungsflächen.
        """

        try:
            arcpy.AddMessage("-" * 40)
            arcpy.AddMessage("Schritt 2 von 6 -- Erstelle pandas-Dataframes...")
            arcpy.AddMessage("-" * 40)
            # Laden in DataFrame
            if not self.load_flurstuecke_to_dataframe():
                return False
            if not self.load_nutzung_to_dataframe("nutzung_dissolve"):
                return False

            # Merge DataFrames auf FSK um Verbesserungsfaktor zu bekommen
            df = self.df_nutzung.merge(
                self.df_flurstuecke[["fsk", "verbesserung", "amtliche_flaeche"]], on="fsk", how="left"
            )

            # Sortiere nach FSK und Fläche
            df = df.sort_values(["fsk", "geom_area"])

            # Vectorisierte Basis-SFL Berechnung
            arcpy.AddMessage("- Berechne gerundete SFL mit Verbesserungsfaktor...")
            df["raw_sfl"] = df["geom_area"] * df["verbesserung"]
            df["sfl"] = (df["raw_sfl"] + 0.5).astype(int)  # round-half-up

            arcpy.AddMessage("-" * 40)
            arcpy.AddMessage("Schritt 3 von 6 -- Vereinige Kleinstflächen geometrisch mit Nachbarn (im Dataframe)...")
            arcpy.AddMessage("-" * 40)
            df_main, df_mini, df_not_merged = merge_mini_geometries(
                df, self.max_shred_qm, self.merge_area, self.flaechenformindex
            )
            if self.delete_unmerged_mini:
                df_mini = pd.concat([df_mini, df_not_merged], ignore_index=True)
            else:
                df_main = pd.concat([df_main, df_not_merged], ignore_index=True)

            arcpy.AddMessage("-" * 40)
            arcpy.AddMessage("Schritt 4 von 6 -- Verteile die Delta-Flächen...")
            arcpy.AddMessage("-" * 40)
            # Overlap-Handling: weitere_nutzung_id == 1000
            overlap_mask = df_main["weitere_nutzung_id"] == 1000
            df_main.loc[overlap_mask, "sfl"] = (df_main.loc[overlap_mask, "geom_area"]).astype(int)
            df_main["is_overlap"] = df_main["weitere_nutzung_id"] == 1000

            # Delta-Korrektur pro FSK
            df_main = self._apply_delta_correction_nutzung(df_main)

            # Zurückschreiben in GDB
            arcpy.AddMessage("-" * 40)
            arcpy.AddMessage("Schritt 5 von 6 -- Übertrage Dataframe-Ergebnisse in nutzung_dissolve...")
            arcpy.AddMessage("-" * 40)
            self._write_sfl_to_gdb_nutzung(df_main, df_mini)

            arcpy.AddMessage("--------Vectorisierte SFL-Berechnung (Nutzung) abgeschlossen--------")
            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei vectorized_calculate_sfl_nutzung: {str(e)}")
            return False

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
        # Zurückschreiben in GDB
        arcpy.AddMessage("-" * 40)
        arcpy.AddMessage("Schritt 6 von 6 -- Schreibe Ergebnisse in Ziel-GDB...")
        arcpy.AddMessage("-" * 40)
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
                arcpy.AddMessage("-" * 40)
                arcpy.AddMessage("CLEANUP -- Lösche Zwischenergebnisse...")
                arcpy.AddMessage("-" * 40)
                arcpy.Delete_management("nutzung_intersect")
                arcpy.Delete_management("nutzung_dissolve")
                arcpy.AddMessage("Temporäre Arbeitstabellen gelöscht")

            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei finalize_results: {str(e)}")
            return False


def calculate_sfl_nutzung(
    gdb_path, workspace, keep_workdata, flaechenformindex, max_shred_area, merge_area, delete_unmerged_mini
):
    """
    :return: True bei Erfolg, False bei Fehler
    """
    try:
        calculator = SFLCalculatorNutzung(
            gdb_path, workspace, keep_workdata, flaechenformindex, max_shred_area, merge_area, delete_unmerged_mini
        )

        if not calculator.prepare_nutzung():
            return False

        if not calculator.vectorized_calculate_sfl_nutzung():
            return False

        if not calculator.finalize_results():
            return False

        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei calculate_sfl_nutzung: {str(e)}")
        return False

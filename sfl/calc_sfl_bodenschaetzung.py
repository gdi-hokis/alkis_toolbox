# -*- coding: utf-8 -*-

# Copyright (c) 2024, Jana Muetsch, Andre Voelkner, LRA Hohenlohekreis
# All rights reserved.

"""
Optimierte SFL- und EMZ-Berechnung mit Pandas-Vectorisierung und Spatial-Index Geometry-Caching.
Ziel: 5-10x schneller als UpdateCursor-basierter Ansatz, gleiche Ergebnisse.
"""

import arcpy
import os
import math
import time
import pandas as pd
from sfl.init_dataframes import DataFrameLoader
from config.config_loader import FieldConfigLoader
from sfl.merge_mini_geometries import merge_mini_geometries


class SFLCalculatorBodenschaetzung(DataFrameLoader):
    """
    Optimierte Klasse für SFL- und EMZ-Berechnungen mit Pandas/NumPy Vectorisierung.
    """

    def __init__(
        self, gdb_path, workspace, keep_workdata, flaechenformindex, max_shred_area, merge_area, delete_unmerged_mini
    ):
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
        self.keep_workdata = keep_workdata
        self.delete_unmerged_mini = delete_unmerged_mini

        arcpy.env.workspace = self.workspace
        arcpy.env.overwriteOutput = True

        # DataFrames für Zwischenspeicherung (werden beim Load gefüllt)
        self.df_flurstuecke = None  # FSK, geometry_area, amtliche_flaeche, verbesserung
        self.df_nutzung = None  # Alle Nutzung Features mit Geometrien
        self.df_bodenschaetzung = None  # Alle Bodenschätzung Features mit Geometrien

        if arcpy.Exists("nutzung_dissolve"):
            self.nutzung_dissolve = "nutzung_dissolve"
            arcpy.AddMessage("  Verwende nutzung_dissolve")
        elif arcpy.Exists(os.path.join(self.gdb_path, "fsk_x_nutzung")):
            self.nutzung_dissolve = os.path.join(self.gdb_path, "fsk_x_nutzung")
            arcpy.AddMessage("  nutzung_dissolve nicht gefunden, verwende fsk_x_nutzung als Fallback")
        else:
            arcpy.AddError("Fehler: Weder nutzung_dissolve noch fsk_x_nutzung gefunden")
            return False

        self.geom_cache_nutzung = {}  # ObjectID -> geometry Mapping
        self.cfg = FieldConfigLoader.load_config()

    def prepare_boden(self):
        """Vorbereitung der Bodenschätzungsdaten: Intersect, Dissolve und Filterung."""
        arcpy.AddMessage("-----------prepare Bodenschaetzung----------")

        try:
            bodenschaetzung_layer = FieldConfigLoader.get("alkis_layers", "bodenschaetzung")
            bewertung_layer = FieldConfigLoader.get("alkis_layers", "bewertung")
            flurstueck_layer = FieldConfigLoader.get("alkis_layers", "flurstueck")
            bodenschaetzung = os.path.join(self.gdb_path, bodenschaetzung_layer)
            flurstueck = os.path.join(self.gdb_path, flurstueck_layer)
            bewertung = os.path.join(self.gdb_path, bewertung_layer)

            if not all(arcpy.Exists(fc) for fc in [bodenschaetzung, flurstueck, bewertung]):
                arcpy.AddError(
                    f"Notwendige Eingabe-Layer {bodenschaetzung_layer}, {bewertung_layer} oder {flurstueck_layer} nicht vorhanden"
                )
                return False

            # FSK Bodenschätzung - Intersect
            arcpy.PairwiseIntersect_analysis(
                [bodenschaetzung, flurstueck], "bodenschaetzung_intersect", "NO_FID", "0.005 Meters", "INPUT"
            )
            arcpy.AddMessage("Bodenschätzung-Intersect durchgeführt")

            nutz = self.cfg["nutzung"]
            flst = self.cfg["flurstueck"]
            bod = self.cfg["bodenschaetzung"]
            bew = self.cfg["bewertung"]

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

            # Dissolve
            arcpy.PairwiseDissolve_analysis(
                "bodenschaetzung_intersect",
                "bodenschaetzung_dissolve",
                ";".join(dissolve_fields),
            )
            arcpy.AddMessage("Bodenschätzung-Dissolve durchgeführt")

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
            arcpy.AddMessage("SFL- und EMZ-Felder hinzugefügt")

            # Filterung: Nur relevante Nutzungsarten behalten -> Landwirtschaft, Heide, Sumpf, UnlandVegetationsloseFlaeche und GFLF/ Landwirtschaftliche Betriebsfläche/Forstwirtschaftliche Betriebsfläche und Garten
            arcpy.MakeFeatureLayer_management(
                self.nutzung_dissolve,
                "nutzung_lyr",
                where_clause=f"NOT (({nutz['objektart']} IN (43001, 43004, 43006, 43007)) OR ({nutz['objektart']} = 41006 AND {nutz['unterart_name']} IN ('Gebäude- und Freifläche Land- und Forstwirtschaft', 'Landwirtschaftliche Betriebsfläche', 'Forstwirtschaftliche Betriebsfläche')) OR ({nutz['objektart']} = 41008 AND {nutz['unterart_name']} IN ('Garten')))",
            )

            arcpy.Erase_analysis("bodenschaetzung_dissolve", "nutzung_lyr", "schaetzung_relevante_nutz", "0,02 Meters")
            arcpy.AddMessage("Relevante Nutzungen aus Bodenschätzung gefiltert")

            # Bewertungen ausschließen siehe VWVLK Anlage 1, Objektart Bewertung
            # Forstwirtschaftliche Nutzung (H), Weinbauliche Nutzung, allgemein (WG), Teichwirtschaft (TEIW), Abbauland der Land- und Forstwirtschaft (LFAB), Geringstland (GER),
            # Unland (U), Nebenfläche des Betriebs der Land- und Forstwirtschaft (NF), u.a.
            arcpy.MakeFeatureLayer_management(
                bewertung,
                "bewertung_lyr",
                f"{bew['klassifizierung_id']} IN (3100, 3105, 3200, 3411, 3480, 3481, 3482, 3490, 3510, 3520, 3530, 3600, 3611, 3610, 3612, 3613, 3614, 3615, 3616, 3710, 3999)",
            )
            arcpy.Erase_analysis("schaetzung_relevante_nutz", "bewertung_lyr", "fsk_bodenschaetzung", "0.005 Meters")
            arcpy.AddMessage("Bewertungsflächen ausgeschlossen")

            # Bewertungsflächenverschnitt
            arcpy.PairwiseIntersect_analysis([flurstueck, bewertung], "fsk_bewertung", "ALL", "0.005 Meters", "INPUT")
            arcpy.MakeFeatureLayer_management(
                "fsk_bewertung",
                "fsk_bewertung_lyr",
                f"shape_Area < 0.5 OR {bew['klassifizierung_id']} NOT IN (3100, 3105, 3200, 3411, 3480, 3481, 3482, 3490, 3510, 3520, 3530, 3600, 3611, 3610, 3612, 3613, 3614, 3615, 3616, 3710, 3999)",
            )
            arcpy.DeleteFeatures_management("fsk_bewertung_lyr")
            arcpy.AddMessage("Bewertungslayer mit relevanten Bewertungen und ohne Kleinstflächen erstellt")

            # Filterung: Nur relevante Nutzungsarten für Bewertungen behalten -> Landwirtschaft, Vegetation, UnlandVegetationsloseFlaeche und GFLF/ Landwirtschaftliche Betriebsfläche/Forstwirtschaftliche Betriebsfläche und Garten
            arcpy.MakeFeatureLayer_management(
                self.nutzung_dissolve,
                "nutzung_m_wald",
                where_clause=f"NOT (({nutz['objektart']} IN (43001, 43004, 43006, 43007, 43002, 43003, 43005)) OR ({nutz['objektart']} = 41006 AND {nutz['unterart_name']} IN ('Gebäude- und Freifläche Land- und Forstwirtschaft', 'Landwirtschaftliche Betriebsfläche', 'Forstwirtschaftliche Betriebsfläche')) OR ({nutz['objektart']} = 41008 AND {nutz['unterart_name']} IN ('Garten')))",
            )

            arcpy.Erase_analysis("fsk_bewertung", "nutzung_m_wald", "fsk_bewertung_relevant", "0.005 Meters")

            field_mapping = (
                r'{1} "flurstueckskennzeichen" true true false 254 Text 0 0,First,#,{0},{1},0,254;'
                r'{2} "amtliche_flaeche" true true false 4 Long 0 0,First,#,{0},{2},-1,-1;'
                r'{3} "nutzungsart_id" true true false 4 Long 0 0,First,#,{0},{4},-1,-1;'
                r'{5} "nutzungsart_name" true true false 254 Text 0 0,First,#,{0},{6},0,254;'
                r'{7} "sonstige_angaben_name" true true false 254 Text 0 0,First,#,{0},{6},0,254'
            ).format(
                "fsk_bewertung",
                flst["flurstueckskennzeichen"],
                flst["amtliche_flaeche"],
                bod["nutzungsart_id"],
                bew["klassifizierung_id"],
                bod["nutzungsart_name"],
                bew["klassifizierung_name"],
                bod["sonstige_angaben_name"],
            )

            arcpy.Append_management("fsk_bewertung_relevant", "fsk_bodenschaetzung", "NO_TEST", field_mapping)

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

            arcpy.AddMessage("Bewertungsflächenverschnitt durchgeführt")

            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei prepare_boden: {str(e)}")
            return False

    def vectorized_calculate_sfl_boden(self):
        """
        Vectorisierte Berechnung der SFL und EMZ für Bodenschätzung.
        """

        arcpy.AddMessage("--------Starte vectorisierte SFL/EMZ-Berechnung (Bodenschätzung)--------")

        try:
            # Laden in DataFrame
            if not self.load_flurstuecke_to_dataframe():
                return False
            if not self.load_nutzung_to_dataframe(self.nutzung_dissolve):
                return False
            if not self.load_bodenschaetzung_to_dataframe():
                return False

            # ========== SCHRITT 1: MERGE ==========
            step_start = time.time()
            arcpy.AddMessage("  1. Merge mit Flurstück-Daten...")
            df = self.df_bodenschaetzung.merge(
                self.df_flurstuecke[["fsk", "verbesserung"]],
                on="fsk",
                how="left",
                suffixes=("", "_fsk"),
            )
            arcpy.AddMessage(f"      Merge abgeschlossen: {time.time() - step_start:.2f}s ({len(df)} Zeilen)")

            # ========== SCHRITT 2: SORTIERUNG ==========
            step_start = time.time()
            arcpy.AddMessage("  2. Sortiere nach FSK und Fläche...")
            df = df.sort_values(["fsk", "geom_area"], ignore_index=True)
            arcpy.AddMessage(f"      Sortierung abgeschlossen: {time.time() - step_start:.2f}s")

            # ========== SCHRITT 3: SCHAETZUNGS-AFL BERECHNUNG - OPTIMIERT ==========
            step_start = time.time()
            arcpy.AddMessage("  3. Berechne Schätzungs-AFL pro FSK (optimiert)...")

            # Statt lambda in groupby: Direkt vectorisiert berechnen
            # Nur die relevanten Nutzungen filtern UND im Speicher halten
            relevant_mask = (
                (self.df_nutzung["objektart"].isin([43001, 43004, 43006, 43007]))
                | ((self.df_nutzung["objektart"] == 41006) & (self.df_nutzung["unterart_id"].isin([2700, 6800])))
                | ((self.df_nutzung["objektart"] == 41008) & (self.df_nutzung["unterart_id"].isin([4460])))
            )
            df_relevant_nutzung = self.df_nutzung[relevant_mask].copy()

            if len(df_relevant_nutzung) > 0:
                schaetz_afl_dict = df_relevant_nutzung.groupby("fsk")["sfl"].sum().to_dict()
            else:
                schaetz_afl_dict = {}
            # Ziehe Bewertungsflächen ab (sonstige_angaben_id == 9999 im df_bodenschaetzung)

            bewertung_mask = df["sonstige_angaben_id"] == 9999

            if bewertung_mask.any():
                bew_afl = (df[bewertung_mask]["geom_area"] * df[bewertung_mask]["verbesserung"] + 0.5).astype(int)
                bew_afl_dict = (
                    df[bewertung_mask][["fsk"]].assign(bew_sfl=bew_afl).groupby("fsk")["bew_sfl"].sum().to_dict()
                )

                for fsk, bew_sum in bew_afl_dict.items():
                    if fsk in schaetz_afl_dict:
                        schaetz_afl_dict[fsk] -= bew_sum

            df["schaetz_afl"] = df["fsk"].map(schaetz_afl_dict).fillna(0).astype(int)
            calc_time = time.time() - step_start
            arcpy.AddMessage(f"      Schätzungs-AFL berechnet: {calc_time:.2f}s ({len(schaetz_afl_dict)} FSKs)")

            # ========== SCHRITT 4: BASIS-SFL BERECHNUNG ==========
            step_start = time.time()
            arcpy.AddMessage("  4. Berechne SFL und EMZ...")
            df["sfl"] = (df["geom_area"] * df["verbesserung"] + 0.5).astype(int)
            df["emz"] = (df["sfl"] / 100 * df["ackerzahl"]).round().astype(int)
            arcpy.AddMessage(f"      SFL/EMZ berechnet: {time.time() - step_start:.2f}s")

            # ========== SCHRITT 5: KLEINSTFLÄCHEN-FILTERUNG ==========
            df_main, df_mini, df_not_merged = merge_mini_geometries(
                df, self.max_shred_qm, self.merge_area, self.flaechenformindex, "bodenschaetzung"
            )

            if self.delete_unmerged_mini:
                df_mini = pd.concat([df_mini, df_not_merged], ignore_index=True)
            else:
                df_main = pd.concat([df_main, df_not_merged], ignore_index=True)

            # ========== SCHRITT 7: BEWERTUNGSFLÄCHEN-HANDLING ==========
            step_start = time.time()
            arcpy.AddMessage("  6. Bearbeite Bewertungsflächen...")

            bewertung_mask = df_main["sonstige_angaben_id"] == 9999
            df_bodenschaetzung = df_main[~bewertung_mask].copy()  # Nur echte Bodenschätzungen
            df_bewertung = df_main[bewertung_mask].copy()  # Bewertungsflächen separat

            if bewertung_mask.any():
                df_bewertung.loc[bewertung_mask, "emz"] = 0
                arcpy.AddMessage(
                    f"      {bewertung_mask.sum()} Bewertungsflächen bearbeitet: {time.time() - step_start:.2f}s"
                )
            else:
                arcpy.AddMessage(f"      Keine Bewertungsflächen gefunden: {time.time() - step_start:.2f}s")

            # ========== SCHRITT 8: DELTA-KORREKTUR ==========
            df_bodenschaetzung = self._apply_delta_correction_boden(df_bodenschaetzung)

            # ========== SCHRITT 9: WIEDER ZUSAMMENFÜGEN ==========
            df_main = pd.concat([df_bodenschaetzung, df_bewertung], ignore_index=True)

            # ========== SCHRITT 9: ZURÜCKSCHREIBEN ==========
            self._write_sfl_to_gdb_boden(df_main, df_mini)

            arcpy.AddMessage("--------Vectorisierte SFL/EMZ-Berechnung (Bodenschätzung) abgeschlossen--------")
            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei vectorized_calculate_sfl_boden: {str(e)}")
            return False

    def _apply_delta_correction_boden(self, df):
        """Vectorisierte Delta-Korrektur für Bodenschätzung pro FSK - optimiert mit Progress-Tracking."""
        arcpy.AddMessage("  Wende Delta-Korrektur an (Bodenschätzung)...")

        start_time = time.time()
        processed_count = 0

        grouped = df.groupby("fsk", sort=False)
        total_groups = len(grouped)
        processed_groups = 0

        for fsk, fsk_data in grouped:
            processed_groups += 1

            # Progress alle 5000 Gruppen
            if processed_groups % 5000 == 0 or processed_groups == total_groups:
                elapsed = time.time() - start_time
                arcpy.AddMessage(
                    f"    Fortschritt: {processed_groups}/{total_groups} FSK ({processed_count} Features bearbeitet, {elapsed:.1f}s)"
                )

            schaetz_afl = fsk_data["schaetz_afl"].iloc[0]

            sfl_sum = fsk_data["sfl"].sum()

            if sfl_sum == schaetz_afl:
                processed_count += len(fsk_data)
                continue

            delta = schaetz_afl - sfl_sum
            abs_delta = abs(delta)

            if abs_delta < self.max_shred_qm:  # 5 qm threshold
                fsk_indices = fsk_data.index
                # Nutze numpy für schnelles Argsort
                sorted_idx = fsk_data["sfl"].values.argsort()[::-1]
                sorted_indices = fsk_indices[sorted_idx]

                rest_anteil = abs_delta

                for idx in sorted_indices:
                    sfl = df.at[idx, "sfl"]
                    ackerzahl = df.at[idx, "ackerzahl"]

                    if sfl < self.max_shred_qm:
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
            f"  Delta-Korrektur (Bodenschätzung) abgeschlossen: {processed_count} Features in {total_time:.1f}s"
        )
        return df

    def _write_sfl_to_gdb_boden(self, df_main, df_mini):
        """
        Schreibe SFL und EMZ Werte zurück in GDB.
        """
        arcpy.AddMessage("  Schreibe SFL/EMZ-Werte zurück in GDB...")

        try:
            # Batch Update für Main Features
            oid_to_values = dict(zip(df_main["objectid"], zip(df_main["sfl"], df_main["emz"])))
            oid_to_geom = dict(zip(df_main["objectid"], df_main["geometry"]))

            with arcpy.da.UpdateCursor("fsk_bodenschaetzung", ["OBJECTID", "sfl", "emz", "SHAPE@"]) as ucursor:
                for row in ucursor:
                    oid = row[0]
                    if oid in oid_to_values:
                        sfl, emz = oid_to_values[oid]
                        row[1] = sfl
                        row[2] = emz
                        row[3] = oid_to_geom[oid]
                        ucursor.updateRow(row)

            # Lösche Mini-Flächen
            if len(df_mini) > 0:
                mini_oids = df_mini["objectid"].tolist()
                oid_str = ",".join(map(str, mini_oids))

                with arcpy.da.UpdateCursor("fsk_bodenschaetzung", ["OBJECTID"], f"OBJECTID IN ({oid_str})") as ucursor:
                    for row in ucursor:
                        ucursor.deleteRow()

            arcpy.AddMessage(f"  {len(df_main)} Features aktualisiert, {len(df_mini)} Kleinstflächen gelöscht")

        except Exception as e:
            arcpy.AddError(f"Fehler beim Schreiben (Boden): {str(e)}")
            raise

    def finalize_results(self):
        """Übernimmt Ergebnisse in Navigation-Tabellen mit Fieldmapping und Tabellen-Erstellung."""
        try:

            nav_bodensch = os.path.join(self.gdb_path, "fsk_x_bodenschaetzung")
            flst = self.cfg["flurstueck"]
            bodsch = self.cfg["bodenschaetzung"]

            bodensch_field_mapping = (
                r'{1} "Flurstückskennzeichen" true true false 255 Text 0 0,First,#,{0},{1},0,253;'
                r'{2} "Bodenart" true true false 255 Text 0 0,First,#,{0},{2},0,253;'
                r'{3} "Nutzungsart" true true false 255 Text 0 0,First,#,{0},{3},0,253;'
                r'{4}"Bodenzahl" true true false 4 Long 0 10,First,#,{0},{4},-1,-1;'
                r'{5} "Ackerzahl" true true false 4 Long 0 10,First,#,{0},{5},-1,-1;'
                r'sfl "SFL [m²]" true true false 4 Long 0 10,First,#,{0},sfl,-1,-1;'
                r'emz "EMZ [m²]" true true false 4 Long 0 10,First,#,{0},emz,-1,-1'
            ).format(
                "fsk_bodenschaetzung",
                flst["flurstueckskennzeichen"],
                bodsch["bodenart_name"],
                bodsch["nutzungsart_name"],
                bodsch["bodenzahl"],
                bodsch["ackerzahl"],
            )

            if not arcpy.Exists(nav_bodensch):
                # Tabelle existiert nicht -> kopiere zum Erstellen
                arcpy.CopyFeatures_management("fsk_bodenschaetzung", nav_bodensch)
                arcpy.AddMessage("Navigation_bodenschaetzung erstellt")
            else:
                # Tabelle existiert -> truncate und append mit Fieldmapping
                arcpy.TruncateTable_management(nav_bodensch)
                arcpy.Append_management("fsk_bodenschaetzung", nav_bodensch, "NO_TEST", bodensch_field_mapping)
                arcpy.AddMessage("Navigation_bodenschaetzung aktualisiert")

            if not self.keep_workdata:
                workdata = [
                    "fsk_bodenschaetzung",
                    "bodenschaetzung_dissolve",
                    "bodenschaetzung_intersect",
                    "schaetzung_relevante_nutz",
                    "fsk_bewertung",
                    "fsk_bewertung_relevant",
                ]
                for wd in workdata:
                    arcpy.Delete_management(wd)
                arcpy.AddMessage("Temporäre Arbeitstabellen gelöscht")

            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei finalize_results: {str(e)}")
            return False


def calculate_sfl_bodenschaetzung(
    gdb_path, workspace, keep_workdata, flaechenformindex, max_shred_area, merge_area, delete_unmerged_mini
):

    calculator = SFLCalculatorBodenschaetzung(
        gdb_path, workspace, keep_workdata, flaechenformindex, max_shred_area, merge_area, delete_unmerged_mini
    )

    if not calculator.prepare_boden():
        return False

    if not calculator.vectorized_calculate_sfl_boden():
        return False

    if not calculator.finalize_results():
        return False

    return True

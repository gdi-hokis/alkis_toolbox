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
import numpy as np

try:
    from shapely.geometry import shape

    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False
    arcpy.AddWarning("Shapely nicht verfügbar - Mini-Flächen-Merge wird übersprungen")


class SFLCalculatorOptimized:
    """
    Optimierte Klasse für SFL- und EMZ-Berechnungen mit Pandas/NumPy Vectorisierung.
    """

    def __init__(self, gdb_path, workspace):
        """
        Initialisiert den optimierten SFL Calculator.

        :param gdb_path: Pfad zur Geodatabase
        :param workspace: Arbeitsverzeichnis für temporäre Daten
        """
        self.gdb_path = gdb_path
        self.workspace = workspace
        self.max_shred_qm = 5  # Schwellenwert für Kleinstflächen

        # DEBUG: Logging nur für FSK 080258
        self.debug_fsk = "080280"
        self.debug_log = []

        arcpy.env.workspace = self.workspace
        arcpy.env.overwriteOutput = True

        # DataFrames für Zwischenspeicherung (werden beim Load gefüllt)
        self.df_flurstuecke = None  # FSK, geometry_area, amtliche_flaeche, verbesserung
        self.df_nutzung = None  # Alle Nutzung Features mit Geometrien
        self.df_bodenschaetzung = None  # Alle Bodenschätzung Features mit Geometrien

        # Geometry Caches
        self.geom_index_nutzung = None  # STRtree index für Nutzung Geometrien
        self.geom_cache_nutzung = {}  # ObjectID -> geometry Mapping
        self.mini_sfl_dict = {}  # FSK -> list of mini_sfl geometries and areas

    def load_flurstuecke_to_dataframe(self):
        """
        Lädt alle Flurstücke in einen Pandas DataFrame mit Geometrien.
        Berechnet auch den Verbesserungsfaktor.
        """
        arcpy.AddMessage("Lade Flurstücke in DataFrame...")
        try:
            flurstueck = os.path.join(self.gdb_path, "nora_v_al_flurstueck")

            # Daten mit Spatialindex auslesen
            fields = ["flurstueckskennzeichen", "SHAPE@", "SHAPE@AREA", "amtliche_flaeche"]
            data = []

            with arcpy.da.SearchCursor(flurstueck, fields) as scursor:
                for row in scursor:
                    fsk, geom, geom_area, afl = row
                    if geom_area > 0:
                        verbesserung = float(afl) / geom_area
                        data.append(
                            {
                                "fsk": fsk,
                                "geometry": geom,
                                "geom_area": geom_area,
                                "amtliche_flaeche": afl,
                                "verbesserung": verbesserung,
                            }
                        )

            self.df_flurstuecke = pd.DataFrame(data)
            arcpy.AddMessage(f"  Geladen: {len(self.df_flurstuecke)} Flurstücke")
            return True

        except Exception as e:
            arcpy.AddError(f"Fehler beim Load von Flurstücken: {str(e)}")
            return False

    def load_nutzung_to_dataframe(self):
        """
        Lädt alle Nutzung Features in DataFrame nach Prepare-Phase.
        """
        arcpy.AddMessage("Lade Nutzung Dissolve in DataFrame...")
        try:
            # Nutzt bereits vorbereitete nutzung_dissolve aus Prepare-Phase
            fields = [
                "OBJECTID",
                "flurstueckskennzeichen",
                "amtliche_flaeche",
                "SHAPE@",
                "SHAPE@AREA",
                "objektart",
                "objektname",
                "unterart_typ",
                "unterart_id",
                "unterart_kuerzel",
                "unterart_name",
                "eigenname",
                "weitere_nutzung_id",
                "weitere_nutzung_name",
                "klasse",
                "sfl",
            ]
            data = []

            with arcpy.da.SearchCursor("nutzung_dissolve", fields) as scursor:
                for row in scursor:
                    (
                        oid,
                        fsk,
                        afl,
                        geom,
                        geom_area,
                        obj_art,
                        obj_name,
                        u_typ,
                        u_id,
                        u_kurz,
                        u_name,
                        eigen,
                        weit_id,
                        weit_name,
                        klasse,
                        sfl,
                    ) = row

                    data.append(
                        {
                            "objectid": oid,
                            "fsk": fsk,
                            "afl": afl,
                            "geometry": geom,
                            "geom_area": geom_area,
                            "objektart": obj_art,
                            "objektname": obj_name,
                            "unterart_typ": u_typ,
                            "unterart_id": u_id,
                            "unterart_kuerzel": u_kurz,
                            "unterart_name": u_name,
                            "eigenname": eigen,
                            "weitere_nutzung_id": weit_id,
                            "weitere_nutzung_name": weit_name,
                            "klasse": klasse,
                            "sfl": sfl if sfl else 0,
                        }
                    )

                    self.geom_cache_nutzung[oid] = geom

            self.df_nutzung = pd.DataFrame(data)
            arcpy.AddMessage(f"  Geladen: {len(self.df_nutzung)} Nutzung Features")
            return True

        except Exception as e:
            arcpy.AddError(f"Fehler beim Load von Nutzung: {str(e)}")
            return False

    def load_bodenschaetzung_to_dataframe(self):
        """
        Lädt alle Bodenschätzung Features in DataFrame nach Prepare-Phase.
        """
        arcpy.AddMessage("Lade Bodenschätzung in DataFrame...")
        try:
            fields = [
                "OBJECTID",
                "flurstueckskennzeichen",
                "SHAPE@",
                "SHAPE@AREA",
                "bodenart_id",
                "bodenart_name",
                "nutzungsart_id",
                "nutzungsart_name",
                "entstehung_id",
                "entstehung_name",
                "klima_id",
                "klima_name",
                "wasser_id",
                "wasser_name",
                "bodenstufe_id",
                "bodenstufe_name",
                "zustand_id",
                "zustand_name",
                "sonstige_angaben_id",
                "sonstige_angaben_name",
                "bodenzahl",
                "ackerzahl",
                "amtliche_flaeche",
                "sfl",
                "emz",
            ]
            data = []

            with arcpy.da.SearchCursor("fsk_bodenschaetzung", fields) as scursor:
                for row in scursor:
                    (
                        oid,
                        fsk,
                        geom,
                        geom_area,
                        boda_id,
                        boda_name,
                        nut_id,
                        nut_name,
                        erst_id,
                        erst_name,
                        klim_id,
                        klim_name,
                        wass_id,
                        wass_name,
                        bods_id,
                        bods_name,
                        zust_id,
                        zust_name,
                        sont_id,
                        sont_name,
                        bodenzahl,
                        ackerzahl,
                        afl,
                        sfl,
                        emz,
                    ) = row

                    data.append(
                        {
                            "objectid": oid,
                            "fsk": fsk,
                            "geometry": geom,
                            "geom_area": geom_area,
                            "bodenart_id": boda_id,
                            "bodenart_name": boda_name,
                            "nutzungsart_id": nut_id,
                            "nutzungsart_name": nut_name,
                            "entstehung_id": erst_id,
                            "entstehung_name": erst_name,
                            "klima_id": klim_id,
                            "klima_name": klim_name,
                            "wasser_id": wass_id,
                            "wasser_name": wass_name,
                            "bodenstufe_id": bods_id,
                            "bodenstufe_name": bods_name,
                            "zustand_id": zust_id,
                            "zustand_name": zust_name,
                            "sonstige_angaben_id": sont_id,
                            "sonstige_angaben_name": sont_name,
                            "bodenzahl": bodenzahl if bodenzahl else 0,
                            "ackerzahl": ackerzahl if ackerzahl else 0,
                            "amtliche_flaeche": afl,
                            "sfl": sfl if sfl else 0,
                            "emz": emz if emz else 0,
                        }
                    )

            self.df_bodenschaetzung = pd.DataFrame(data)
            arcpy.AddMessage(f"  Geladen: {len(self.df_bodenschaetzung)} Bodenschätzung Features")
            return True

        except Exception as e:
            arcpy.AddError(f"Fehler beim Load von Bodenschätzung: {str(e)}")
            return False

    def prepare_nutzung(self):
        """Vorbereitung der Nutzungsdaten: Intersect und Dissolve."""
        arcpy.AddMessage("--------prepare Nutzung---------")

        try:
            nutzung = os.path.join(self.gdb_path, "nora_v_al_tatsaechliche_nutzung")
            flurstueck = os.path.join(self.gdb_path, "nora_v_al_flurstueck")

            if not arcpy.Exists(nutzung) or not arcpy.Exists(flurstueck):
                arcpy.AddError("nora_v_al_tatsaechliche_nutzung oder nora_v_al_flurstueck nicht vorhanden")
                return False

            # Verschneiden
            arcpy.PairwiseIntersect_analysis([nutzung, flurstueck], "nutzung_intersect", "NO_FID", None, "INPUT")
            arcpy.AddMessage("Nutzung-Intersect durchgeführt")

            # Dissolve mit Klassifizierungsfeldern
            arcpy.PairwiseDissolve_analysis(
                "nutzung_intersect",
                "nutzung_dissolve",
                "objektart;objektname;unterart_typ;unterart_id;unterart_kuerzel;unterart_name;eigenname;weitere_nutzung_id;weitere_nutzung_name;klasse;flurstueckskennzeichen;amtliche_flaeche",
            )
            arcpy.AddMessage("Nutzung-Dissolve durchgeführt")

            # SFL-Feld hinzufügen
            if not any(f.name == "sfl" for f in arcpy.ListFields("nutzung_dissolve")):
                arcpy.AddField_management(
                    "nutzung_dissolve", "sfl", "LONG", None, None, None, "Schnittfläche", "NULLABLE", "NON_REQUIRED"
                )

            # Navigation_nutzung Tabelle initialisieren/leeren
            nav_nutzung = os.path.join(self.gdb_path, "navigation_nutzung")
            if arcpy.Exists(nav_nutzung):
                arcpy.TruncateTable_management(nav_nutzung)

            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei prepare_nutzung: {str(e)}")
            return False

    def prepare_boden(self):
        """Vorbereitung der Bodenschätzungsdaten: Intersect, Dissolve und Filterung."""
        arcpy.AddMessage("-----------prepare Bodenschaetzung----------")

        try:
            bodenschaetzung = os.path.join(self.gdb_path, "nora_v_al_bodenschaetzung_f")
            flurstueck = os.path.join(self.gdb_path, "nora_v_al_flurstueck")
            nutzung_dissolve = os.path.join(self.workspace, "nutzung_dissolve")
            bewertung = os.path.join(self.gdb_path, "nora_v_al_bodenbewertung")

            if not all(arcpy.Exists(fc) for fc in [bodenschaetzung, flurstueck, nutzung_dissolve]):
                arcpy.AddError("Notwendige Bodenschätzungs-Layer nicht vorhanden")
                return False

            # FSK Bodenschätzung - Intersect
            arcpy.PairwiseIntersect_analysis(
                [bodenschaetzung, flurstueck], "bodenschaetzung_intersect", "NO_FID", None, "INPUT"
            )
            arcpy.AddMessage("Bodenschätzung-Intersect durchgeführt")

            # Dissolve
            arcpy.PairwiseDissolve_analysis(
                "bodenschaetzung_intersect",
                "fsk_bodenschaetzung",
                "bodenart_id;bodenart_name;nutzungsart_id;nutzungsart_name;entstehung_id;entstehung_name;klima_id;klima_name;wasser_id;wasser_name;bodenstufe_id;bodenstufe_name;zustand_id;zustand_name;sonstige_angaben_id;sonstige_angaben_name;bodenzahl;ackerzahl;flurstueckskennzeichen;amtliche_flaeche",
            )
            arcpy.AddMessage("Bodenschätzung-Dissolve durchgeführt")

            # Felder hinzufügen
            for field_name, field_type in [("sfl", "LONG"), ("emz", "LONG")]:
                if not any(f.name == field_name for f in arcpy.ListFields("fsk_bodenschaetzung")):
                    arcpy.AddField_management(
                        "fsk_bodenschaetzung",
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
                nutzung_dissolve,
                "nutzung_lyr",
                where_clause="objektart NOT IN (43001, 43004, 43006, 43007) Or (objektart = 41006 And unterart_id IN (2700,7600,6800)) Or (objektart = 41008 And unterart_id IN (4460))",
            )
            arcpy.Erase_analysis("fsk_bodenschaetzung", "nutzung_lyr", "schaetzung_relevante_nutz", "0.02 Meters")
            arcpy.AddMessage("Relevante Nutzungen aus Bodenschätzung gefiltert")

            # Bewertungen ausschließen siehe VWVLK Anlage 1, Objektart Bewertung
            # Forstwirtschaftliche Nutzung (H), Weinbauliche Nutzung, allgemein (WG), Teichwirtschaft (TEIW), Abbauland der Land- und Forstwirtschaft (LFAB), Geringstland (GER),
            # Unland (U), Nebenfläche des Betriebs der Land- und Forstwirtschaft (NF), u.a.
            if arcpy.Exists(bewertung):
                arcpy.MakeFeatureLayer_management(
                    bewertung,
                    "bewertung_lyr",
                    "klassifizierung_id IN (3100, 3105, 3200, 3411, 3480, 3481, 3482, 3490, 3510, 3520, 3530, 3600, 3611, 3610, 3612, 3613, 3614, 3615, 3616, 3710, 3999)",
                )
                arcpy.Erase_analysis(
                    "schaetzung_relevante_nutz", "bewertung_lyr", "schaetzung_o_bewertung", "0.02 Meters"
                )
                arcpy.AddMessage("Bewertungsflächen ausgeschlossen")
            else:
                arcpy.AddError(
                    "nora_v_al_bodenbewertung nicht vorhanden, Bewertungsflächen können nicht ausgeschlossen werden"
                )

            # Kleinstflächen löschen
            arcpy.MakeFeatureLayer_management(
                "schaetzung_o_bewertung", "schaetzung_o_bewertung_lyr", "shape_Area < 0.5"
            )
            arcpy.DeleteFeatures_management("schaetzung_o_bewertung_lyr")
            arcpy.AddMessage("Kleinstflächen gelöscht")

            # In fsk_bodenschaetzung übernehmen
            arcpy.TruncateTable_management("fsk_bodenschaetzung")
            arcpy.Append_management("schaetzung_o_bewertung", "fsk_bodenschaetzung", "NO_TEST")

            # Bewertungsflächenverschnitt
            if arcpy.Exists(bewertung):
                arcpy.PairwiseIntersect_analysis([flurstueck, bewertung], "fsk_bewertung", "ALL", None, "INPUT")
                arcpy.MakeFeatureLayer_management(
                    "fsk_bewertung",
                    "fsk_bewertung_lyr",
                    "shape_Area < 0.5 OR klassifizierung_id NOT IN (3100, 3105, 3200, 3411, 3480, 3481, 3482, 3490, 3510, 3520, 3530, 3600, 3611, 3610, 3612, 3613, 3614, 3615, 3616, 3710, 3999)",
                )
                arcpy.DeleteFeatures_management("fsk_bewertung_lyr")

                arcpy.Erase_analysis("fsk_bewertung", "nutzung_lyr", "fsk_bewertung_relevant", "0.02 Meters")

                field_mapping = (
                    r'flurstueckskennzeichen "flurstueckskennzeichen" true true false 254 Text 0 0,First,#,{0},flurstueckskennzeichen,0,254;'
                    r'amtliche_flaeche "amtliche_flaeche" true true false 4 Long 0 0,First,#,{0},amtliche_flaeche,-1,-1;'
                    r'nutzungsart_id "nutzungsart_id" true true false 4 Long 0 0,First,#,{0},klassifizierung_id,-1,-1;'
                    r'nutzungsart_name "nutzungsart_name" true true false 254 Text 0 0,First,#,{0},klassifizierung_name,0,254;'
                    r'sonstige_angaben_name "sonstige_angaben_name" true true false 254 Text 0 0,First,#,{0},klassifizierung_name,0,254'
                ).format("fsk_bewertung")

                arcpy.Append_management("fsk_bewertung", "fsk_bodenschaetzung", "NO_TEST", field_mapping)

                # Bewertungsflächenanhang konstante Werte setzen
                with arcpy.da.UpdateCursor(
                    "fsk_bodenschaetzung",
                    ["bodenzahl", "ackerzahl", "emz", "sonstige_angaben_id"],
                    "bodenart_id IS NULL",
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

    def vectorized_calculate_sfl_nutzung(self):
        """
        Vectorisierte Berechnung der SFL für alle Nutzungsflächen.
        Ersetzt die ursprüngliche Cursor-Loop mit Pandas-Operationen.
        """
        arcpy.AddMessage("--------Starte vectorisierte SFL-Berechnung (Nutzung)--------")

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
            df["sfl"] = (df["geom_area"] * df["verbesserung"] + 0.5).astype(int)

            # Kleinstflächen-Filterung pro FSK
            mask_mini = (df["geom_area"] < 2) & (df["amtliche_flaeche"] > 5)
            df.loc[mask_mini, "is_mini"] = True
            df.loc[~mask_mini, "is_mini"] = False

            # Separate mini und non-mini Features
            df_mini = df[df["is_mini"] == True].copy()
            df_main = df[df["is_mini"] == False].copy()

            arcpy.AddMessage(f"  Identifiziert {len(df_mini)} Kleinstflächen zur Verarbeitung")

            # Mini-Flächen-Filterung: Nur die merge'en, die WENIGER als 1 m² bei Verteilung ergeben
            # Prüfe ohne +0.5: geom_area * verbesserung < 1
            if len(df_mini) > 0:
                # df[]=np.round(df["geom_area"] * df["verbesserung"]).astype(int)
                # Trennung: erhaltungswürdig (>= 1) vs. zu mergen (< 1)
                mask_keep = df_mini["sfl"] >= 1
                df_mini["perimeter"] = df_mini["geometry"].apply(lambda geom: geom.length)
                df_mini["form_index"] = df_mini["perimeter"] / np.sqrt(df_mini["geom_area"])

                # Schmale, lange Schnipsel filtern (form_index > 8 = sehr dünn)
                mask_real_feature = df_mini["form_index"] < 8  # Nur normale Formen behalten
                df_mini_keep = df_mini[(mask_keep) & (mask_real_feature)].copy()
                df_mini_merge = df_mini[(~mask_keep) | (~mask_real_feature)].copy()

                arcpy.AddMessage(
                    f"    {len(df_mini_keep)} Mini-Flächen erhalten (>= 1 m²), "
                    f"{len(df_mini_merge)} Mini-Flächen werden gemergt (< 1 m²)"
                )

                # Erhaltungswürdige Mini-Flächen zu Main hinzufügen
                df_main = pd.concat([df_main, df_mini_keep], ignore_index=True)

                # Merge zu verlustende Mini-Flächen mit angrenzenden Hauptflächen
                if len(df_mini_merge) > 0 and SHAPELY_AVAILABLE:
                    df_main = self._merge_mini_into_main_nutzung(df_main, df_mini_merge)

                df_mini = df_mini_merge

            else:
                df_mini = pd.DataFrame()

            # Overlap-Handling: weitere_nutzung_id == 1000
            overlap_mask = df_main["weitere_nutzung_id"] == 1000
            df_main.loc[overlap_mask, "sfl"] = (df_main.loc[overlap_mask, "geom_area"]).astype(int)

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
        Merge Mini-Flächen mit angrenzenden Hauptflächen.
        Nutzt Geometrie-Union und touches() Logic.
        """
        arcpy.AddMessage("  Merge Kleinstflächen mit Hauptflächen...")

        for fsk in df_main["fsk"].unique():
            fsk_mini = df_mini[df_mini["fsk"] == fsk]
            fsk_main_idx = df_main[df_main["fsk"] == fsk].index

            if len(fsk_mini) == 0:
                continue

            # Für jede Mini-Fläche: find angrenzende Hauptfläche
            for _, mini_row in fsk_mini.iterrows():
                mini_geom = mini_row["geometry"]
                touched = False

                for main_idx in fsk_main_idx:
                    main_row = df_main.loc[main_idx]
                    main_geom = main_row["geometry"]

                    try:
                        if main_geom.touches(mini_geom):
                            # Union und neu berechnen
                            union_geom = main_geom.union(mini_geom)
                            union_area = union_geom.area

                            verbesserung = main_row["verbesserung"]
                            new_sfl = int(union_area * verbesserung + 0.5)

                            df_main.at[main_idx, "geometry"] = union_geom
                            df_main.at[main_idx, "geom_area"] = union_area
                            df_main.at[main_idx, "sfl"] = new_sfl

                            touched = True
                            break
                    except Exception as e:
                        arcpy.AddWarning(f"    Geometrie-Union fehlgeschlagen: {str(e)}")

                if not touched:
                    arcpy.AddMessage(
                        f"    Mini-Fläche {mini_row['objectid']} in {fsk} hat keine angrenzende Hauptfläche"
                    )

        return df_main

    def _apply_delta_correction_nutzung(self, df):
        """Vectorisierte Delta-Korrektur mit korrekt gestaffelter Verteilung."""
        arcpy.AddMessage("  Wende Delta-Korrektur an...")

        start_time = time.time()
        processed_count = 0

        grouped = df.groupby("fsk", sort=False)
        total_groups = len(grouped)
        processed_groups = 0

        for fsk, fsk_data in grouped:
            processed_groups += 1
            is_debug = str(fsk).startswith(self.debug_fsk)

            # if is_debug:
            #     arcpy.AddMessage(f"[DEBUG {fsk}] Starte Delta-Korrektur")
            #     arcpy.AddMessage(f"[DEBUG {fsk}] Features in dieser FSK: {len(fsk_data)}")

            # Progress alle 5000 Gruppen
            if processed_groups % 50000 == 0 or processed_groups == total_groups:
                elapsed = time.time() - start_time
                arcpy.AddMessage(
                    f"    Fortschritt: {processed_groups}/{total_groups} FSK ({processed_count} Features bearbeitet, {elapsed:.1f}s)"
                )

            afl = fsk_data["amtliche_flaeche"].iloc[0]
            sfl_sum = fsk_data["sfl"].sum()

            # if is_debug:
            #     arcpy.AddMessage(f"[DEBUG {fsk}] AFL: {afl}, SFL_sum: {sfl_sum}")

            if sfl_sum == afl:
                processed_count += len(fsk_data)
                # if is_debug:
                #     arcpy.AddMessage(f"[DEBUG {fsk}] SFL_sum == AFL, keine Korrektur nötig")
                continue

            delta = afl - sfl_sum
            abs_delta = abs(delta)

            if is_debug:
                arcpy.AddMessage(f"[DEBUG {fsk}] Delta: {delta}, Abs_delta: {abs_delta}")

            if abs_delta < 5:  # Nur kleine Deltas korrigieren
                fsk_indices = fsk_data.index
                sorted_idx = fsk_data["sfl"].values.argsort()[::-1]
                sorted_indices = fsk_indices[sorted_idx]

                if is_debug:
                    arcpy.AddMessage(
                        f"[DEBUG {fsk}] Sortierte Indices nach SFL (absteigend): {sorted_indices.tolist()}"
                    )

                adjustments = {}  # idx -> adjustment_value

                # Nur Features > max_shred_qm berücksichtigen
                eligible_indices = [idx for idx in sorted_indices if df.at[idx, "sfl"] >= self.max_shred_qm]

                if is_debug:
                    arcpy.AddMessage(f"[DEBUG {fsk}] Eligible indices (SFL >= {self.max_shred_qm}): {eligible_indices}")
                    for idx in eligible_indices:
                        arcpy.AddMessage(f"[DEBUG {fsk}]   OID {df.at[idx, 'objectid']}: SFL={df.at[idx, 'sfl']}")

                if len(eligible_indices) > 0:
                    total_sfl_eligible = sum(df.at[idx, "sfl"] for idx in eligible_indices)

                    if is_debug:
                        arcpy.AddMessage(f"[DEBUG {fsk}] Total SFL eligible: {total_sfl_eligible}")

                    remaining_delta = abs_delta

                    # Berechne Anteile proportional (NEUE LOGIK: proportionale Verteilung für ALLE)
                    for idx in eligible_indices:
                        sfl = df.at[idx, "sfl"]
                        ratio = float(sfl) / float(total_sfl_eligible) if total_sfl_eligible > 0 else 0
                        oid = df.at[idx, "objectid"]

                        # Alle Features bekommen ihren proportionalen Anteil
                        int_anteil = int(abs_delta * ratio)
                        if is_debug:
                            arcpy.AddMessage(
                                f"[DEBUG {fsk}]   OID {oid}: SFL={sfl}, Ratio={ratio:.4f}, int_anteil={int_anteil}"
                            )

                        remaining_delta -= int_anteil
                        adjustments[idx] = int_anteil

                    # Der ERSTE (größte) nimmt den Rundungsrest
                    if len(adjustments) > 0:
                        first_idx = eligible_indices[0]
                        old_adjustment = adjustments[first_idx]
                        adjustments[first_idx] = old_adjustment + remaining_delta

                        if is_debug and remaining_delta != 0:
                            oid = df.at[first_idx, "objectid"]
                            arcpy.AddMessage(
                                f"[DEBUG {fsk}]   Rundungsausgleich für größtes Feature OID {oid}: +{remaining_delta} qm"
                            )

                        remaining_delta = 0

                    # # ALT: ERSTER (größter) nimmt exakt den Rest
                    # for i, idx in enumerate(eligible_indices):
                    #     sfl = df.at[idx, "sfl"]
                    #     ratio = float(sfl) / float(total_sfl_eligible) if total_sfl_eligible > 0 else 0
                    #     oid = df.at[idx, "objectid"]
                    #
                    #     if i == 0:
                    #         # ERSTER (größter): nimm exakt den Rest
                    #         int_anteil = remaining_delta
                    #         if is_debug:
                    #             arcpy.AddMessage(
                    #                 f"[DEBUG {fsk}]   OID {oid}: ERSTER Feature (größter), int_anteil={int_anteil} (Rest)"
                    #             )
                    #     else:
                    #         int_anteil = int(abs_delta * ratio)
                    #         if is_debug:
                    #             arcpy.AddMessage(
                    #                 f"[DEBUG {fsk}]   OID {oid}: SFL={sfl}, Ratio={ratio:.4f}, int_anteil={int_anteil}"
                    #             )
                    #
                    #     remaining_delta -= int_anteil
                    #     adjustments[idx] = int_anteil

                    # Wende Anpassungen an
                    for idx, adjustment in adjustments.items():
                        old_sfl = df.at[idx, "sfl"]
                        new_sfl = old_sfl + (adjustment if delta >= 0 else -adjustment)
                        df.at[idx, "sfl"] = new_sfl

                        if is_debug:
                            oid = df.at[idx, "objectid"]
                            arcpy.AddMessage(f"[DEBUG {fsk}]   ANPASSUNG OID {oid}: {old_sfl} -> {new_sfl}")

                    if remaining_delta != 0 and is_debug:
                        arcpy.AddMessage(f"[DEBUG {fsk}] Restanteil {remaining_delta} qm (unverteilt)")
            elif is_debug:
                arcpy.AddMessage(f"[DEBUG {fsk}] abs_delta={abs_delta} >= 5, keine Korrektur (zu großer Delta)")

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

            with arcpy.da.UpdateCursor("nutzung_dissolve", ["OBJECTID", "sfl"]) as ucursor:
                for row in ucursor:
                    oid = row[0]
                    if oid in oid_to_sfl:
                        row[1] = oid_to_sfl[oid]
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

    def vectorized_calculate_sfl_boden(self):
        """
        Vectorisierte Berechnung der SFL und EMZ für Bodenschätzung.
        """

        arcpy.AddMessage("--------Starte vectorisierte SFL/EMZ-Berechnung (Bodenschätzung)--------")

        try:
            if not self.load_bodenschaetzung_to_dataframe():
                return False

            # ========== SCHRITT 1: MERGE ==========
            step_start = time.time()
            arcpy.AddMessage("  1. Merge mit Flurstück-Daten...")
            df = self.df_bodenschaetzung.merge(
                self.df_flurstuecke[["fsk", "verbesserung", "amtliche_flaeche"]],
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
            if self.df_nutzung is not None and len(self.df_nutzung) > 0:
                # Vorfiltert: nur relevante Nutzungen
                relevant_mask = (
                    (self.df_nutzung["objektart"].isin([43001, 43004, 43006, 43007]))
                    | (
                        (self.df_nutzung["objektart"] == 41006)
                        & (self.df_nutzung["unterart_id"].isin(["2700", "6800"]))
                    )
                    | ((self.df_nutzung["objektart"] == 41008) & (self.df_nutzung["unterart_id"].isin(["4460"])))
                )
                df_relevant_nutzung = self.df_nutzung[relevant_mask].copy()

                if len(df_relevant_nutzung) > 0:
                    # Merge der relevanten Nutzungen mit ihren Verbesserungsfaktoren
                    df_nutzung_merged = df_relevant_nutzung.merge(
                        self.df_flurstuecke[["fsk", "verbesserung"]], on="fsk", how="left"
                    )
                    df_nutzung_merged["sfl"] = (
                        df_nutzung_merged["geom_area"] * df_nutzung_merged["verbesserung"] + 0.5
                    ).astype(int)

                    # Gruppiere und summiere
                    schaetz_afl_dict = df_nutzung_merged.groupby("fsk")["sfl"].sum().to_dict()
                else:
                    schaetz_afl_dict = {}
            else:
                schaetz_afl_dict = {}

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
            step_start = time.time()
            arcpy.AddMessage("  5. Filtere Kleinstflächen...")
            mask_mini = (df["geom_area"] < self.max_shred_qm) & (df["amtliche_flaeche_fsk"] > self.max_shred_qm * 2)
            df_mini = df[mask_mini].copy()
            df_main = df[~mask_mini].copy()
            arcpy.AddMessage(
                f"      Filtert: {time.time() - step_start:.2f}s ({len(df_mini)} Mini, {len(df_main)} Main)"
            )

            # ========== SCHRITT 6: MERGE MINI MIT MAIN ==========
            if len(df_mini) > 0 and SHAPELY_AVAILABLE:
                step_start = time.time()
                df_main = self._merge_mini_into_main_boden(df_main, df_mini)
                arcpy.AddMessage(f"      Mini-Merge: {time.time() - step_start:.2f}s")

            # ========== SCHRITT 7: BEWERTUNGSFLÄCHEN-HANDLING ==========
            step_start = time.time()
            arcpy.AddMessage("  6. Bearbeite Bewertungsflächen...")
            bewertung_mask = df_main["sonstige_angaben_id"] == "9999"
            if bewertung_mask.any():
                df_main.loc[bewertung_mask, "sfl"] = (
                    df_main.loc[bewertung_mask, "geom_area"] * df_main.loc[bewertung_mask, "verbesserung"] + 0.5
                ).astype(int)
                df_main.loc[bewertung_mask, "emz"] = 0
                arcpy.AddMessage(
                    f"      {bewertung_mask.sum()} Bewertungsflächen bearbeitet: {time.time() - step_start:.2f}s"
                )
            else:
                arcpy.AddMessage(f"      Keine Bewertungsflächen gefunden: {time.time() - step_start:.2f}s")

            # ========== SCHRITT 8: DELTA-KORREKTUR ==========
            df_main = self._apply_delta_correction_boden(df_main)

            # ========== SCHRITT 9: ZURÜCKSCHREIBEN ==========
            self._write_sfl_to_gdb_boden(df_main, df_mini)

            arcpy.AddMessage("--------Vectorisierte SFL/EMZ-Berechnung (Bodenschätzung) abgeschlossen--------")
            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei vectorized_calculate_sfl_boden: {str(e)}")
            return False

    def _calculate_schaetz_afl(self, group):
        """
        Berechne Schätzungs-AFL als Summe der Nutzungsflächen für diese FSK.
        """
        fsk = group["fsk"].iloc[0]

        # Lade Nutzung Features für diese FSK
        relevant_nutzung_fsk = self.df_nutzung[
            (self.df_nutzung["fsk"] == fsk)
            & (
                (self.df_nutzung["objektart"].isin([43001, 43004, 43006, 43007]))
                | ((self.df_nutzung["objektart"] == 41006) & (self.df_nutzung["unterart_id"].isin(["2700", "6800"])))
                | ((self.df_nutzung["objektart"] == 41008) & (self.df_nutzung["unterart_id"].isin(["4460"])))
            )
        ]

        if len(relevant_nutzung_fsk) == 0:
            return 0

        # Summe der SFL
        # Verwende mergemerged verbesserung
        fsk_verbesserung = group["verbesserung"].iloc[0]
        schaetz_sum = (relevant_nutzung_fsk["geom_area"] * fsk_verbesserung + 0.5).sum()

        return int(schaetz_sum)

    def _merge_mini_into_main_boden(self, df_main, df_mini):
        """
        Merge Mini-Flächen in Bodenschätzung mit angrenzenden Hauptflächen.
        """
        arcpy.AddMessage("  Merge Kleinstflächen (Bodenschätzung) mit Hauptflächen...")

        for fsk in df_main["fsk"].unique():
            fsk_mini = df_mini[df_mini["fsk"] == fsk]
            fsk_main_idx = df_main[df_main["fsk"] == fsk].index

            if len(fsk_mini) == 0:
                continue

            for _, mini_row in fsk_mini.iterrows():
                mini_geom = mini_row["geometry"]

                for main_idx in fsk_main_idx:
                    main_row = df_main.loc[main_idx]
                    main_geom = main_row["geometry"]

                    try:
                        if main_geom.touches(mini_geom):
                            union_geom = main_geom.union(mini_geom)
                            union_area = union_geom.area

                            verbesserung = main_row["verbesserung"]
                            new_sfl = int(union_area * verbesserung + 0.5)
                            ackerzahl = main_row["ackerzahl"]
                            new_emz = int(round(new_sfl / 100 * ackerzahl))

                            df_main.at[main_idx, "geometry"] = union_geom
                            df_main.at[main_idx, "geom_area"] = union_area
                            df_main.at[main_idx, "sfl"] = new_sfl
                            df_main.at[main_idx, "emz"] = new_emz

                            break
                    except Exception as e:
                        arcpy.AddWarning(f"    Geometrie-Union (Boden) fehlgeschlagen: {str(e)}")

        return df_main

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

            if schaetz_afl == 0:
                processed_count += len(fsk_data)
                continue

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

            with arcpy.da.UpdateCursor("fsk_bodenschaetzung", ["OBJECTID", "sfl", "emz"]) as ucursor:
                for row in ucursor:
                    oid = row[0]
                    if oid in oid_to_values:
                        sfl, emz = oid_to_values[oid]
                        row[1] = sfl
                        row[2] = emz
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
        """Übernimmt Ergebnisse in Navigation-Tabellen."""
        try:
            nav_nutzung = os.path.join(self.gdb_path, "navigation_nutzung")
            nav_bodensch = os.path.join(self.gdb_path, "navigation_bodenschaetzung")

            # Nutzung übernehmen
            if arcpy.Exists(nav_nutzung):
                field_mapping = (
                    r'objektart "Objektart" true true false 8 Double 8 38,First,#,{0},objektart,-1,-1;'
                    r'objektname "Nutzung" true true false 255 Text 0 0,First,#,{0},objektname,0,253;'
                    r'unterart_typ "Unterart Typ" true true false 255 Text 0 0,First,#,{0},unterart_typ,0,253;'
                    r'unterart_id "Unterart Schlüssel" true true false 8 Double 8 38,First,#,{0},unterart_id,-1,-1;'
                    r'unterart_kuerzel "Abkürzung" true true false 10 Text 0 0,First,#,{0},unterart_kuerzel,0,49;'
                    r'unterart_name "Unterart" true true false 255 Text 0 0,First,#,{0},unterart_name,0,253;'
                    r'eigenname "Eigenname" true true false 50 Text 0 0,First,#,{0},eigenname,0,253;'
                    r'weitere_nutzung_id "weitere Nutzung Schlüssel" true true false 8 Double 8 38,First,#,{0},weitere_nutzung_id,0,254;'
                    r'weitere_nutzung_name "weitere Nutzung" true true false 255 Text 0 0,First,#,{0},weitere_nutzung_name,0,253;'
                    r'klasse "Klasse" true true false 8 Double 8 38,First,#,{0},klasse,-1,-1;'
                    r'flurstueckskennzeichen "Flurstückskennzeichen" true true false 255 Text 0 0,First,#,{0},flurstueckskennzeichen,0,253;'
                    r'sfl "Fläche [m²]" true true false 4 Long 0 10,First,#,{0},sfl,-1,-1'
                ).format("nutzung_dissolve")

                arcpy.TruncateTable_management(nav_nutzung)
                arcpy.Append_management("nutzung_dissolve", nav_nutzung, "NO_TEST", field_mapping)
                arcpy.AddMessage("Navigation_nutzung übernommen")

            # Bodenschätzung übernehmen
            if arcpy.Exists(nav_bodensch):
                arcpy.TruncateTable_management(nav_bodensch)
                arcpy.Append_management("fsk_bodenschaetzung", nav_bodensch, "NO_TEST")
                arcpy.AddMessage("Navigation_bodenschaetzung übernommen")

            return True

        except Exception as e:
            arcpy.AddError(f"Fehler bei finalize_results: {str(e)}")
            return False


def calculate_sfl_optimized(gdb_path, workspace):
    """
    Hauptfunktion für optimierte SFL- und EMZ-Berechnung.

    :param gdb_path: Pfad zur Geodatabase
    :param workspace: Arbeitsverzeichnis für temporäre Daten
    :param use_individual_verbesserung: True = individueller Verbesserungsfaktor pro Feature (NEU)
                                         False = globaler Verbesserungsfaktor pro Flurstück (ALT)
    :return: True bei Erfolg, False bei Fehler
    """
    calculator = SFLCalculatorOptimized(gdb_path, workspace)

    # Schritt 1: Nutzung vorbereiten
    if not calculator.prepare_nutzung():
        return False

    # Schritt 2: Bodenschätzung vorbereiten
    if not calculator.prepare_boden():
        return False

    arcpy.AddMessage("========================================")
    arcpy.AddMessage("Nutze: GLOBALER Verbesserungsfaktor pro Flurstück")
    arcpy.AddMessage("========================================")
    if not calculator.vectorized_calculate_sfl_nutzung():
        return False
    if not calculator.vectorized_calculate_sfl_boden():
        return False

    # Schritt 4: Ergebnisse in Navigation-Tabellen
    if not calculator.finalize_results():
        return False

    return True

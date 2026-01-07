# -*- coding: utf-8 -*-

# Copyright (c) 2024, Jana Muetsch, Andre Voelkner, LRA Hohenlohekreis
# All rights reserved.

"""
DataFrames Loader Mixin - Lädt Flurstücke, Nutzung und Bodenschätzung in Pandas DataFrames.
"""

import arcpy
import os
import pandas as pd
from config.config_loader import FieldConfigLoader


class DataFrameLoader:
    """
    Mixin-Klasse zum Laden von Geodaten in Pandas DataFrames.
    Erfordert folgende Instance-Variablen in der Hauptklasse:
    - self.gdb_path
    - self.df_flurstuecke
    - self.df_nutzung
    - self.df_bodenschaetzung
    - self.geom_cache_nutzung
    """

    def __init__(self, config_path=None):
        """Initialisiert den Config Loader."""
        self.config = FieldConfigLoader.load_config(config_path)

    def load_flurstuecke_to_dataframe(self):
        """
        Lädt alle Flurstücke in einen Pandas DataFrame mit Geometrien.
        Berechnet auch den Verbesserungsfaktor.
        """
        if self.df_flurstuecke is not None:
            arcpy.AddMessage("  Flurstücke bereits geladen, überspringe Load")
            return True
        arcpy.AddMessage("Lade Flurstücke in DataFrame...")
        try:
            flst = FieldConfigLoader.get("flurstueck")
            fsk_field = flst["flurstueckskennzeichen"]
            shape_field = flst["shape"]
            shape_area_field = flst["shape_area"]
            afl_field = flst["amtliche_flaeche"]

            flurstueck_layer = FieldConfigLoader.get("alkis_layers", "flurstueck")
            flurstueck = os.path.join(self.gdb_path, flurstueck_layer)

            # Daten mit Spatialindex auslesen
            fields = [fsk_field, shape_field, shape_area_field, afl_field]
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
        if self.df_nutzung is not None:
            arcpy.AddMessage("  Nutzung bereits geladen, überspringe Load")
            return True
        arcpy.AddMessage("Lade Nutzung Dissolve in DataFrame...")
        try:
            # Bestimme welche Tabelle verwendet werden soll
            nutzung_table = None

            # Strategie 1: Versuche nutzung_dissolve zu finden
            if arcpy.Exists("nutzung_dissolve"):
                nutzung_table = "nutzung_dissolve"
                arcpy.AddMessage("  Verwende nutzung_dissolve")
            # Strategie 2: Fallback auf fsk_x_nutzung
            elif arcpy.Exists(os.path.join(self.gdb_path, "fsk_x_nutzung")):
                nutzung_table = os.path.join(self.gdb_path, "fsk_x_nutzung")
                arcpy.AddMessage("  nutzung_dissolve nicht gefunden, verwende fsk_x_nutzung als Fallback")
            # Strategie 3: Fehler
            else:
                arcpy.AddError("Fehler: Weder nutzung_dissolve noch fsk_x_nutzung gefunden")
                return False

            # Lade Daten
            flst = FieldConfigLoader.get("flurstueck")
            nutz = FieldConfigLoader.get("nutzung")
            fields = [
                "OBJECTID",
                flst["flurstueckskennzeichen"],
                flst["amtliche_flaeche"],
                flst["shape"],
                flst["shape_area"],
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
                "sfl",
            ]
            data = []

            with arcpy.da.SearchCursor(nutzung_table, fields) as scursor:
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
        if self.df_bodenschaetzung is not None:
            arcpy.AddMessage("  Bodenschätzung bereits geladen, überspringe Load")
            return True
        arcpy.AddMessage("Lade Bodenschätzung in DataFrame...")
        try:
            flst = FieldConfigLoader.get("flurstueck")
            bods = FieldConfigLoader.get("bodenschaetzung")
            fields = [
                "OBJECTID",
                flst["flurstueckskennzeichen"],
                flst["shape"],
                flst["shape_area"],
                bods["bodenart_id"],
                bods["bodenart_name"],
                bods["nutzungsart_id"],
                bods["nutzungsart_name"],
                bods["entstehung_id"],
                bods["entstehung_name"],
                bods["klima_id"],
                bods["klima_name"],
                bods["wasser_id"],
                bods["wasser_name"],
                bods["bodenstufe_id"],
                bods["bodenstufe_name"],
                bods["zustand_id"],
                bods["zustand_name"],
                bods["sonstige_angaben_id"],
                bods["sonstige_angaben_name"],
                bods["bodenzahl"],
                bods["ackerzahl"],
                flst["amtliche_flaeche"],
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

# -*- coding: utf-8 -*-
"""
DataFrames Loader Mixin - Lädt Flurstücke, Nutzung und Bodenschätzung in Pandas DataFrames.
"""
import os
import arcpy
import pandas as pd


def load_flurstuecke_to_dataframe(cfg, gdb_path):
    """
    Lädt alle Flurstücke in einen Pandas DataFrame mit Geometrien.
    Berechnet auch den Verbesserungsfaktor.
    """
    arcpy.AddMessage("- Lade Flurstücke in DataFrame...")
    try:
        flst = cfg["flurstueck"]
        fsk_field = flst["flurstueckskennzeichen"]
        shape_area_field = flst["shape_area"]
        afl_field = flst["amtliche_flaeche"]

        flurstueck_layer = cfg["alkis_layers"]["flurstueck"]
        flurstueck = os.path.join(gdb_path, flurstueck_layer)

        # Daten mit Spatialindex auslesen
        fields = [fsk_field, shape_area_field, afl_field]
        data = []

        with arcpy.da.SearchCursor(flurstueck, fields) as scursor:
            for row in scursor:
                fsk, geom_area, afl = row
                if geom_area > 0:
                    verbesserung = float(afl) / geom_area
                    data.append(
                        {
                            "fsk": fsk,
                            "geom_area": geom_area,
                            "amtliche_flaeche": afl,
                            "verbesserung": verbesserung,
                        }
                    )

        df_flurstuecke = pd.DataFrame(data)
        arcpy.AddMessage(f"- Geladen: {len(df_flurstuecke)} Flurstücke")
        return df_flurstuecke

    except Exception as e:
        arcpy.AddError(f"Fehler beim Dataframe-Load von Flurstücken: {str(e)}")
        return False


def load_nutzung_to_dataframe(cfg, gdb_path, feature_class_name="fsk_x_nutzung"):
    """
    Lädt alle Nutzung Features in DataFrame nach Prepare-Phase.
    """
    arcpy.AddMessage("- Lade Nutzung Dissolve in DataFrame...")
    try:

        # Lade Daten
        flst = cfg["flurstueck"]
        nutz = cfg["nutzung"]
        fields = [
            "OBJECTID",
            flst["flurstueckskennzeichen"],
            flst["amtliche_flaeche"],
            flst["shape_length"],
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

        with arcpy.da.SearchCursor(os.path.join(gdb_path, feature_class_name), fields) as scursor:
            for row in scursor:
                (
                    oid,
                    fsk,
                    amtliche_flaeche,
                    geom_length,
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
                        "amtliche_flaeche": amtliche_flaeche,
                        "geom_length": geom_length,
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

        df_nutzung = pd.DataFrame(data)
        arcpy.AddMessage(f"- Geladen: {len(df_nutzung)} Nutzung Features")
        return df_nutzung

    except Exception as e:
        arcpy.AddError(f"Fehler beim Dataframe-Load von Nutzung: {str(e)}")
        return False


def load_bodenschaetzung_to_dataframe(cfg, workspace):
    """
    Lädt alle Bodenschätzung Features in DataFrame nach Prepare-Phase.
    """
    arcpy.AddMessage("- Lade Bodenschätzung in DataFrame...")
    try:
        flst = cfg["flurstueck"]
        bods = cfg["bodenschaetzung"]
        fields = [
            "OBJECTID",
            flst["flurstueckskennzeichen"],
            flst["shape_length"],
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

        with arcpy.da.SearchCursor(os.path.join(workspace, "fsk_bodenschaetzung"), fields) as scursor:
            for row in scursor:
                (
                    oid,
                    fsk,
                    geom_length,
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
                    amtliche_flaeche,
                    sfl,
                    emz,
                ) = row

                data.append(
                    {
                        "objectid": oid,
                        "fsk": fsk,
                        "geom_length": geom_length,
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
                        "amtliche_flaeche": amtliche_flaeche,
                        "sfl": sfl if sfl else 0,
                        "emz": emz if emz else 0,
                    }
                )

        df_bodenschaetzung = pd.DataFrame(data)
        arcpy.AddMessage(f"- Geladen: {len(df_bodenschaetzung)} Bodenschätzung Features")
        return df_bodenschaetzung

    except Exception as e:
        arcpy.AddError(f"Fehler beim Dataframe-Load von Bodenschätzung: {str(e)}")
        return False


def add_geometries_from_fc(dataframes, feature_class):
    """
    Fügt Geometrien aus Feature Class zu mehreren DataFrames basierend auf OBJECTID hinzu.

    Args:
        dataframes: Dict mit {df_name: dataframe} oder Liste von DataFrames
        feature_class: Pfad zur Feature Class

    Returns:
        Dict mit aktualisierten DataFrames oder Liste (je nach Input)
    """
    arcpy.AddMessage(f"- Füge Geometrien zu {len(dataframes)} DataFrames hinzu...")

    # Alle benötigten OIDs sammeln
    all_oids_needed = set()
    if isinstance(dataframes, dict):
        for df in dataframes.values():
            all_oids_needed.update(df["objectid"].unique())
    else:
        for df in dataframes:
            all_oids_needed.update(df["objectid"].unique())

    # Einmal durchlesen und Geometrien cachen
    geom_data = {}
    with arcpy.da.SearchCursor(feature_class, ["OBJECTID", "SHAPE@"]) as cursor:
        for oid, geom in cursor:
            if oid in all_oids_needed:
                geom_data[oid] = geom

    arcpy.AddMessage(f"- Geladen: {len(geom_data)} Geometrien")

    # Auf alle DataFrames anwenden
    if isinstance(dataframes, dict):
        for df_name, df in dataframes.items():
            df["geometry"] = df["objectid"].map(geom_data)
        return dataframes
    else:
        for df in dataframes:
            df["geometry"] = df["objectid"].map(geom_data)
        return dataframes

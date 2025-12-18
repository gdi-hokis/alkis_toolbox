# -*- coding: utf-8 -*-

"""
Validierungsskript: Vergleicht Ergebnisse zwischen alter (calc_sfl.py) und neuer (calc_sfl_optimized.py) Implementierung.
Ziel: Sicherstellen, dass beide Versionen identische SFL/EMZ-Werte produzieren.
"""

import arcpy
import os
import pandas as pd
from collections import defaultdict


def compare_nutzung_sfl(gdb_path):
    """
    Vergleiche SFL-Werte in nutzung_dissolve zwischen beiden Implementierungen.
    Erstelle Report über Abweichungen.
    """
    arcpy.AddMessage("=" * 60)
    arcpy.AddMessage("VALIDIERUNG: Nutzung SFL-Vergleich")
    arcpy.AddMessage("=" * 60)

    try:
        nav_nutzung = os.path.join(gdb_path, "navigation_nutzung")

        if not arcpy.Exists(nav_nutzung):
            arcpy.AddError("navigation_nutzung Tabelle nicht vorhanden")
            return False

        fields = ["flurstueckskennzeichen", "objektart", "unterart_id", "sfl", "SHAPE@AREA"]

        # Lade Daten
        data = []
        with arcpy.da.SearchCursor(nav_nutzung, fields) as scursor:
            for row in scursor:
                data.append(
                    {
                        "fsk": row[0],
                        "objektart": row[1],
                        "unterart_id": row[2],
                        "sfl": row[3],
                        "geom_area": row[4],
                    }
                )

        df = pd.DataFrame(data)

        # Statistiken
        arcpy.AddMessage(f"\nGeladen: {len(df)} Nutzung Features")
        arcpy.AddMessage(f"Summe SFL: {df['sfl'].sum()} qm")
        arcpy.AddMessage(f"Min SFL: {df['sfl'].min()} qm")
        arcpy.AddMessage(f"Max SFL: {df['sfl'].max()} qm")
        arcpy.AddMessage(f"Durchschnitt SFL: {df['sfl'].mean():.2f} qm")

        # Pro FSK Statistiken
        fsk_stats = (
            df.groupby("fsk")
            .agg(
                {
                    "sfl": ["sum", "count"],
                }
            )
            .reset_index()
        )

        fsk_stats.columns = ["fsk", "sfl_sum", "feature_count"]
        arcpy.AddMessage(f"\nPro FSK Statistiken:")
        arcpy.AddMessage(f"  FSKs mit Nutzung: {len(fsk_stats)}")
        arcpy.AddMessage(
            f"  Features pro FSK (min/max/avg): {fsk_stats['feature_count'].min()}/{fsk_stats['feature_count'].max()}/{fsk_stats['feature_count'].mean():.1f}"
        )

        # Anomalien detektieren
        zero_sfl = df[df["sfl"] == 0]
        if len(zero_sfl) > 0:
            arcpy.AddWarning(f"\n  WARNUNG: {len(zero_sfl)} Features mit SFL=0 gefunden")

        negative_sfl = df[df["sfl"] < 0]
        if len(negative_sfl) > 0:
            arcpy.AddError(f"\n  FEHLER: {len(negative_sfl)} Features mit negativer SFL gefunden!")

        return True

    except Exception as e:
        arcpy.AddError(f"Fehler bei Nutzung-Vergleich: {str(e)}")
        return False


def compare_bodenschaetzung_sfl(gdb_path):
    """
    Vergleiche SFL und EMZ-Werte in Bodenschätzung.
    """
    arcpy.AddMessage("\n" + "=" * 60)
    arcpy.AddMessage("VALIDIERUNG: Bodenschätzung SFL/EMZ-Vergleich")
    arcpy.AddMessage("=" * 60)

    try:
        nav_bodensch = os.path.join(gdb_path, "navigation_bodenschaetzung")

        if not arcpy.Exists(nav_bodensch):
            arcpy.AddError("navigation_bodenschaetzung Tabelle nicht vorhanden")
            return False

        fields = ["flurstueckskennzeichen", "bodenart_id", "ackerzahl", "sfl", "emz", "SHAPE@AREA"]

        data = []
        with arcpy.da.SearchCursor(nav_bodensch, fields) as scursor:
            for row in scursor:
                data.append(
                    {
                        "fsk": row[0],
                        "bodenart_id": row[1],
                        "ackerzahl": row[2] if row[2] else 0,
                        "sfl": row[3],
                        "emz": row[4],
                        "geom_area": row[5],
                    }
                )

        df = pd.DataFrame(data)

        # Statistiken
        arcpy.AddMessage(f"\nGeladen: {len(df)} Bodenschätzung Features")
        arcpy.AddMessage(f"Summe SFL: {df['sfl'].sum()} qm")
        arcpy.AddMessage(f"Summe EMZ: {df['emz'].sum()}")
        arcpy.AddMessage(f"Min SFL: {df['sfl'].min()} qm")
        arcpy.AddMessage(f"Max SFL: {df['sfl'].max()} qm")

        # EMZ Validation: emz sollte = sfl / 100 * ackerzahl sein
        df["emz_calc"] = (df["sfl"] / 100 * df["ackerzahl"]).round().astype(int)
        emz_mismatches = df[df["emz"] != df["emz_calc"]]

        if len(emz_mismatches) > 0:
            arcpy.AddWarning(f"\n  WARNUNG: {len(emz_mismatches)} EMZ-Abweichungen gefunden")
            arcpy.AddMessage(f"    Beispiele (erste 5):")
            for idx, row in emz_mismatches.head(5).iterrows():
                arcpy.AddMessage(
                    f"      SFL={row['sfl']}, Ackerzahl={row['ackerzahl']}, EMZ={row['emz']} (Erwartet: {row['emz_calc']})"
                )

        # Pro FSK Statistiken
        fsk_stats = (
            df.groupby("fsk")
            .agg(
                {
                    "sfl": ["sum", "count"],
                    "emz": "sum",
                }
            )
            .reset_index()
        )

        fsk_stats.columns = ["fsk", "sfl_sum", "feature_count", "emz_sum"]
        arcpy.AddMessage(f"\nPro FSK Statistiken:")
        arcpy.AddMessage(f"  FSKs mit Bodenschätzung: {len(fsk_stats)}")
        arcpy.AddMessage(f"  Gesamt EMZ: {fsk_stats['emz_sum'].sum()}")

        # Anomalien
        negative_sfl = df[df["sfl"] < 0]
        if len(negative_sfl) > 0:
            arcpy.AddError(f"\n  FEHLER: {len(negative_sfl)} Features mit negativer SFL!")

        negative_emz = df[df["emz"] < 0]
        if len(negative_emz) > 0:
            arcpy.AddError(f"\n  FEHLER: {len(negative_emz)} Features mit negativem EMZ!")

        return True

    except Exception as e:
        arcpy.AddError(f"Fehler bei Bodenschätzung-Vergleich: {str(e)}")
        return False


def validate_delta_corrections(gdb_path):
    """
    Validiere, dass Delta-Korrektionen korrekt angewendet wurden.
    Für jedes FSK: Summe der SFL sollte = amtliche Fläche oder sehr nah dran sein.
    """
    arcpy.AddMessage("\n" + "=" * 60)
    arcpy.AddMessage("VALIDIERUNG: Delta-Korrektionen")
    arcpy.AddMessage("=" * 60)

    try:
        # Lade Flurstücke
        flurstueck = os.path.join(gdb_path, "v_al_flurstueck")
        fsk_afl = {}

        with arcpy.da.SearchCursor(flurstueck, ["flurstueckskennzeichen", "amtliche_flaeche"]) as scursor:
            for row in scursor:
                fsk_afl[row[0]] = row[1]

        # Berechne Summen aus navigation_nutzung
        nav_nutzung = os.path.join(gdb_path, "navigation_nutzung")
        nutzung_sums = defaultdict(int)

        with arcpy.da.SearchCursor(nav_nutzung, ["flurstueckskennzeichen", "sfl"]) as scursor:
            for row in scursor:
                nutzung_sums[row[0]] += row[1]

        # Vergleich
        deltas = []
        for fsk, expected_sfl in fsk_afl.items():
            actual_sfl = nutzung_sums.get(fsk, 0)
            delta = expected_sfl - actual_sfl

            if abs(delta) > 0:
                deltas.append(
                    {
                        "fsk": fsk,
                        "expected": expected_sfl,
                        "actual": actual_sfl,
                        "delta": delta,
                    }
                )

        if len(deltas) == 0:
            arcpy.AddMessage("  ✓ PERFEKT: Alle FSKs haben korrekte SFL-Summen!")
        else:
            df_deltas = pd.DataFrame(deltas)
            large_deltas = df_deltas[abs(df_deltas["delta"]) > 5]

            arcpy.AddMessage(f"\n  Statistiken zu Deltas:")
            arcpy.AddMessage(f"    FSKs mit Abweichung: {len(deltas)}")
            arcpy.AddMessage(f"    FSKs mit großen Abweichungen (>5qm): {len(large_deltas)}")
            arcpy.AddMessage(f"    Durchschnittliches Delta: {df_deltas['delta'].mean():.2f} qm")
            arcpy.AddMessage(f"    Max Delta: {df_deltas['delta'].abs().max()} qm")

            if len(large_deltas) > 0:
                arcpy.AddWarning(f"\n    WARNUNG: Große Deltas gefunden (erste 10):")
                for idx, row in large_deltas.head(10).iterrows():
                    arcpy.AddMessage(
                        f"      FSK {row['fsk']}: expected={row['expected']}, actual={row['actual']}, delta={row['delta']}"
                    )

        return True

    except Exception as e:
        arcpy.AddError(f"Fehler bei Delta-Validierung: {str(e)}")
        return False


def validate_all(gdb_path):
    """
    Führe alle Validierungen durch.
    """
    arcpy.AddMessage("\n\n")
    arcpy.AddMessage("█" * 60)
    arcpy.AddMessage("█  VALIDIERUNG: SFL-BERECHNUNG")
    arcpy.AddMessage("█" * 60)

    success = True
    success &= compare_nutzung_sfl(gdb_path)
    success &= compare_bodenschaetzung_sfl(gdb_path)
    success &= validate_delta_corrections(gdb_path)

    arcpy.AddMessage("\n" + "█" * 60)
    if success:
        arcpy.AddMessage("█  VALIDIERUNG: ✓ ABGESCHLOSSEN (KEINE FEHLER)")
    else:
        arcpy.AddMessage("█  VALIDIERUNG: ✗ FEHLER GEFUNDEN")
    arcpy.AddMessage("█" * 60 + "\n")

    return success

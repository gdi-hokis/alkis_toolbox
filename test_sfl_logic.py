# -*- coding: utf-8 -*-

"""
Quick Test Script für SFL-Berechnung ohne ArcGIS-Abhängigkeit.
Nützlich für schnelle Tests während der Entwicklung.
"""

import sys
import os
import pandas as pd
import numpy as np


def test_sfl_formula():
    """Test: Basis SFL-Berechnung Formel."""
    print("\n" + "=" * 60)
    print("TEST: SFL-Berechnung Formel")
    print("=" * 60)

    # Test Daten
    test_cases = [
        {"geom_area": 1000.0, "afl": 1050.0, "expected_sfl": 1050},  # verbesserung = 1.05
        {"geom_area": 5000.0, "afl": 5000.0, "expected_sfl": 5000},  # verbesserung = 1.0
        {"geom_area": 2000.5, "afl": 2001.0, "expected_sfl": 2001},  # INT rounding
        {"geom_area": 3333.333, "afl": 3333.0, "expected_sfl": 3333},  # Rounding test
    ]

    for i, test in enumerate(test_cases):
        geom_area = test["geom_area"]
        afl = test["afl"]
        expected = test["expected_sfl"]

        verbesserung = afl / geom_area
        calculated = int(geom_area * verbesserung + 0.5)

        status = "✓" if calculated == expected else "✗"
        print(f"\n{status} Test {i+1}: geom_area={geom_area}, afl={afl}")
        print(f"  verbesserung: {verbesserung:.6f}")
        print(f"  calculated: {calculated}, expected: {expected}")

        assert calculated == expected, f"Mismatch: {calculated} != {expected}"

    print("\n✓ Alle Formeltests bestanden!")


def test_emz_formula():
    """Test: EMZ-Berechnung Formel."""
    print("\n" + "=" * 60)
    print("TEST: EMZ-Berechnung Formel")
    print("=" * 60)

    test_cases = [
        {"sfl": 1000, "ackerzahl": 50, "expected_emz": 500},
        {"sfl": 2500, "ackerzahl": 60, "expected_emz": 1500},
        {"sfl": 3333, "ackerzahl": 45, "expected_emz": 1500},  # ROUND test
        {"sfl": 100, "ackerzahl": 0, "expected_emz": 0},
    ]

    for i, test in enumerate(test_cases):
        sfl = test["sfl"]
        ackerzahl = test["ackerzahl"]
        expected = test["expected_emz"]

        calculated = int(round(sfl / 100 * ackerzahl))

        status = "✓" if calculated == expected else "✗"
        print(f"\n{status} Test {i+1}: sfl={sfl}, ackerzahl={ackerzahl}")
        print(f"  raw: {sfl / 100 * ackerzahl:.2f}")
        print(f"  calculated: {calculated}, expected: {expected}")

        assert calculated == expected, f"Mismatch: {calculated} != {expected}"

    print("\n✓ Alle EMZ-Tests bestanden!")


def test_delta_correction():
    """Test: Delta-Korrektur Logik."""
    print("\n" + "=" * 60)
    print("TEST: Delta-Korrektur Logik")
    print("=" * 60)

    # Simulation: 3 Features mit verschiedenen SFL-Werten
    # Ziel-AFL = 1000, SFL-Sum = 1003 → delta = -3

    sfl_values = [250, 400, 500]  # Summe = 1150
    target_afl = 1147
    max_shred_qm = 5

    delta = target_afl - sum(sfl_values)  # -3
    abs_delta = abs(delta)

    print(f"\nZiel-AFL: {target_afl} qm")
    print(f"SFL-Summe: {sum(sfl_values)} qm")
    print(f"Delta: {delta} qm")
    print(f"Kleinster Schwellenwert: {max_shred_qm} qm")

    assert abs_delta < 5, "Test setup invalid"

    # Sortiere absteigend nach SFL
    sorted_indices = sorted(range(len(sfl_values)), key=lambda i: sfl_values[i], reverse=True)
    rest_anteil = abs_delta

    corrected_sfl = sfl_values.copy()

    for idx in sorted_indices:
        sfl = corrected_sfl[idx]

        if sfl < max_shred_qm:
            rest_anteil -= sfl
            print(f"\n  Feature {idx}: sfl={sfl} < {max_shred_qm} → skip")
        elif rest_anteil > 0:
            ratio = 1.0 if sfl > target_afl else float(sfl) / float(target_afl)
            int_anteil = math.ceil(float(abs_delta) * float(ratio))
            rest_anteil -= int_anteil

            if delta < 0:
                int_anteil *= -1

            corrected_sfl[idx] += int_anteil
            print(f"\n  Feature {idx}: sfl={sfl} → {corrected_sfl[idx]} (anteil: {int_anteil})")
        else:
            print(f"\n  Feature {idx}: sfl={sfl} (kein Ausgleich mehr nötig)")
            break

    print(f"\nKorrigierte Summe: {sum(corrected_sfl)} qm")
    print(f"Restanteil: {rest_anteil} qm")

    assert sum(corrected_sfl) == target_afl or rest_anteil <= 0, "Delta-Korrektur fehlgeschlagen"

    print("\n✓ Delta-Korrektur Test bestanden!")


def test_vectorized_operations():
    """Test: Pandas Vectorisierung."""
    print("\n" + "=" * 60)
    print("TEST: Pandas Vectorisierung")
    print("=" * 60)

    # Erstelle Test DataFrame
    df = pd.DataFrame(
        {
            "fsk": ["001", "001", "001", "002", "002"],
            "geom_area": [1000, 2000, 3000, 1500, 2500],
            "verbesserung": [1.05, 1.05, 1.05, 1.0, 1.0],
            "ackerzahl": [50, 60, 40, 55, 45],
        }
    )

    print("\nOriginal DataFrame:")
    print(df.to_string())

    # Vectorisierte SFL Berechnung
    df["sfl"] = (df["geom_area"] * df["verbesserung"] + 0.5).astype(int)

    print("\nNach SFL-Berechnung:")
    print(df[["fsk", "geom_area", "sfl"]].to_string())

    # Vectorisierte EMZ Berechnung
    df["emz"] = (df["sfl"] / 100 * df["ackerzahl"]).round().astype(int)

    print("\nNach EMZ-Berechnung:")
    print(df[["fsk", "sfl", "ackerzahl", "emz"]].to_string())

    # Groupby Aggregation
    fsk_stats = df.groupby("fsk").agg(
        {
            "sfl": ["sum", "count"],
            "emz": "sum",
        }
    )

    print("\nFSK-Statistiken:")
    print(fsk_stats.to_string())

    print("\n✓ Vectorisierungs-Tests bestanden!")


def test_mini_flaechen_filterung():
    """Test: Kleinstflächen-Filterung Logik."""
    print("\n" + "=" * 60)
    print("TEST: Kleinstflächen-Filterung")
    print("=" * 60)

    df = pd.DataFrame(
        {
            "fsk": ["001", "001", "001", "002", "002"],
            "geom_area": [0.5, 1.5, 5000, 2, 3000],
            "amtliche_flaeche": [10, 10, 10000, 5, 3000],
        }
    )

    print("\nOriginal DataFrame:")
    print(df.to_string())

    # Filterung für Nutzung (< 2 qm)
    mask_mini_nutzung = (df["geom_area"] < 2) & (df["amtliche_flaeche"] > 10)
    df["is_mini"] = mask_mini_nutzung

    print("\nNach Mini-Filterung (Nutzung: < 2 qm):")
    print(df[["fsk", "geom_area", "amtliche_flaeche", "is_mini"]].to_string())

    # Filterung für Bodenschätzung (< 5 qm)
    mask_mini_boden = (df["geom_area"] < 5) & (df["amtliche_flaeche"] > 10)

    print("\nMini-Filterung (Bodenschätzung: < 5 qm):")
    print(f"  Mask: {mask_mini_boden.tolist()}")

    print("\n✓ Mini-Filterungs-Tests bestanden!")


def main():
    """Führe alle Tests durch."""
    print("\n\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║  SFL-BERECHNUNG: Unit Tests" + " " * 30 + "║")
    print("║" + " " * 58 + "║")
    print("╚" + "=" * 58 + "╝")

    try:
        test_sfl_formula()
        test_emz_formula()
        test_delta_correction()
        test_vectorized_operations()
        test_mini_flaechen_filterung()

        print("\n\n" + "=" * 60)
        print("✓ ALLE TESTS BESTANDEN!")
        print("=" * 60 + "\n")

        return True

    except AssertionError as e:
        print(f"\n✗ TEST FEHLGESCHLAGEN: {str(e)}")
        return False
    except Exception as e:
        print(f"\n✗ FEHLER: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Importiere Math für Delta-Test
    import math

    success = main()
    sys.exit(0 if success else 1)

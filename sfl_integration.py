# -*- coding: utf-8 -*-

"""
Integrationsskript: Wrapper für einfache Ausführung und Vergleich beider SFL-Implementierungen.
Bietet auch Performance-Metriken und automatische Validierung.
"""

import arcpy
import importlib
import time
import calc_sfl_optimized
import validate_sfl_results

importlib.reload(calc_sfl_optimized)
importlib.reload(validate_sfl_results)


def run_optimized_implementation(gdb_path, workspace):
    """Führe die optimierte Pandas-basierte Implementierung aus."""
    start_time = time.time()

    try:
        success = calc_sfl_optimized.calculate_sfl_optimized(gdb_path, workspace)
        elapsed = time.time() - start_time

        if success:
            arcpy.AddMessage(f"✓ Optimierte Implementierung abgeschlossen in {elapsed:.2f} Sekunden")
        else:
            arcpy.AddError("✗ Optimierte Implementierung fehlgeschlagen")

        return success, elapsed

    except Exception as e:
        elapsed = time.time() - start_time
        arcpy.AddError(f"✗ Optimierte Implementierung Fehler nach {elapsed:.2f}s: {str(e)}")
        return False, elapsed

# -*- coding: utf-8 -*-

# Copyright (c) 2025, Jana Mütsch LRA Hohenlohekreis
# All rights reserved.

# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.

# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS
# BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
# GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
# DAMAGE.

"""
Modul für Feldberechnungen auf WFS-Download Daten.
Enthält Funktionen für Berechnungen auf v_al_flurstueck, v_al_bodenschaetzung_f und v_al_gebaeude.
"""

import os
import arcpy

def alkis_calc(input_layer, gdb):
    """
    Führt spezifische Feldberechnungen für die heruntergeladenen Layer durch.
    Behandelt:
    - v_al_flurstueck: Flurnummer-ID, FSK, FLSTKEY, locator_place
    - v_al_bodenschaetzung_f: Label-Beschriftung
    - v_al_gebaeude: object_id UUID

    :param input_layer: Input Layer/Feature Class/Shapefile (arcpy Layer-Objekt)
    :param gdb: Geodatabase-Pfad
    """
    try:
        # Extrahiere den Feature Class Namen aus dem Layer-Objekt
        desc = arcpy.Describe(input_layer)
        output_fc = desc.baseName  # Liefert nur den Namen ohne Pfad und Erweiterung
        
        # Ziel-Feature-Class Pfad
        output_fc_path = os.path.join(gdb, output_fc)
        
        # Prüfen ob Feature Class bereits in der Ziel-GDB existiert
        if arcpy.Exists(output_fc_path):
            arcpy.AddMessage(f"- Feature Class '{output_fc}' existiert bereits in der Geodatabase")
        else:
            arcpy.AddMessage(f"- Kopiere '{output_fc}' in die Geodatabase...")
            arcpy.management.CopyFeatures(input_layer, output_fc_path)

        # Flurstücke - Feldberechnungen
        if output_fc == "nora_v_al_flurstueck":
            arcpy.AddMessage("- Starte Feldberechnungen für Flurstücke...")

            # Flurnummer-Berechnung benötigt auch v_al_flur
            if arcpy.Exists(os.path.join(gdb, "nora_v_al_flur")):
                flur_fc_path = os.path.join(gdb, "nora_v_al_flur")
                calculate_flurnummer_l(flur_fc_path, output_fc_path)
                join_flurnamen(output_fc_path, flur_fc_path)
                calculate_locator_place(output_fc_path)
                clean_up_flur_fields(flur_fc_path)

            # FSK and FLSTKEY
            calculate_fsk(output_fc_path)
            calculate_flstkey(output_fc_path)

        # Bodenschätzung - Label-Berechnung
        elif output_fc == "nora_v_al_bodenschaetzung_f":
            arcpy.AddMessage("- Starte Feldberechnungen für Bodenschätzung...")
            calculate_label_bodensch(output_fc_path)

        # Gebäude - object_id Generierung
        elif output_fc == "nora_v_al_gebaeude":
            arcpy.AddMessage("- Starte Feldberechnungen für Gebäude...")
            calculate_gebaeude_object_id(output_fc_path)
        else:
            arcpy.AddMessage(f"- Keine spezifischen Feldberechnungen für {output_fc} definiert.")

    except Exception as e:
        arcpy.AddWarning(f"Feldberechnungen für {output_fc} konnten nicht durchgeführt werden: {str(e)}")


def calculate_flurnummer_l(flur_fc, flurstueck_fc):
    """
    Berechnet die Flurnummer-ID (flurnummer_l) aus Gemarkung und Flurnummer.
    Format: "080" + gemarkung_id + "00" + flurnummer

    :param flur_fc: Feature Class der Fluren (v_al_flur)
    :param flurstueck_fc: Feature Class der Flurstücke (v_al_flurstueck)
    """
    try:
        arcpy.AddMessage("- Flurnummer-ID für Fluren berechnen...")
        arcpy.CalculateField_management(
            flur_fc, "flurnummer_l", '"080"+$feature.gemarkung_id+"00"+$feature.flurnummer', "ARCADE"
        )

        arcpy.AddMessage("- Flurnummer-ID für Flurstücke berechnen...")
        arcpy.CalculateField_management(
            flurstueck_fc, "flurnummer_l", '"080"+$feature.gemarkung_id+"00"+$feature.flurnummer', "ARCADE"
        )

        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Berechnung Flurnummer-ID: {str(e)}")
        return False


def join_flurnamen(flurstueck_fc, flur_fc):
    """
    Verknüpft Flurnamen aus Flur-FC mit Flurstück-FC über flurnummer_l.

    :param flurstueck_fc: Feature Class der Flurstücke (v_al_flurstueck)
    :param flur_fc: Feature Class der Fluren (v_al_flur)
    """
    try:
        arcpy.AddMessage("- Flurnamen mit Flurstücken verknüpfen...")
        arcpy.JoinField_management(flurstueck_fc, "flurnummer_l", flur_fc, "flurnummer_l", "flurname")
        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Join Flurnamen: {str(e)}")
        return False


def calculate_locator_place(flurstueck_fc):
    """
    Berechnet Locator-Place-Feld für Flurstücke.
    Priorität: Flurname > Gemarkungsname

    :param flurstueck_fc: Feature Class der Flurstücke (v_al_flurstueck)
    """
    try:
        arcpy.AddMessage("- Feld Locator-Place für Flurstücke berechnen...")
        arcpy.CalculateField_management(
            flurstueck_fc,
            "locator_place",
            "calcPlace(!gemarkung_name!,!flurname!)",
            "PYTHON3",
            """def calcPlace(gemarkung, flurname):
    if flurname:
        return flurname
    else:
        return gemarkung""",
        )
        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Berechnung Locator-Place: {str(e)}")
        return False


def calculate_fsk(flurstueck_fc):
    """
    Berechnet Flurstückskennzeichen-Kurzform (FSK).
    Ersetzt führende Nullen in bestimmten Positionen durch Unterstriche.

    :param flurstueck_fc: Feature Class der Flurstücke (v_al_flurstueck)
    """
    try:
        arcpy.AddMessage("- Feld FSK-Kurzform berechnen...")
        arcpy.CalculateField_management(
            flurstueck_fc,
            "fsk",
            "replaceZerosInFSK(!flurstueckskennzeichen!)",
            "PYTHON3",
            """def replaceZerosInFSK(flstId):
      fsk = flstId
      if fsk[6:9] == "000":
          fsk = fsk[:6] + "___" + fsk[9:]
      if fsk[14:18] == "0000":
          fsk = fsk[:14] + "____" + fsk[18:]
      if fsk[-2:] == "00":
          fsk = fsk[:-2]
      return fsk""",
            "TEXT",
        )
        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Berechnung FSK: {str(e)}")
        return False


def calculate_flstkey(flurstueck_fc):
    """
    Berechnet FLSTKEY aus Gemarkung, Flurnummer und Flurstückstext.
    Format: gemarkung_id + "-" + flurnummer + "-" + flurstueckstext

    :param flurstueck_fc: Feature Class der Flurstücke (v_al_flurstueck)
    """
    try:
        arcpy.AddMessage("- Feld FLSTKEY berechnen...")
        arcpy.CalculateField_management(
            flurstueck_fc,
            "FLSTKEY",
            'str(int(!gemarkung_id!)) + "-" + str(int(!flurnummer!)) + "-" + !flurstueckstext!',
            "PYTHON3",
        )
        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Berechnung FLSTKEY: {str(e)}")
        return False


def calculate_label_bodensch(bodenschaetzung_fc):
    """
    Berechnet Beschriftungsfeld (label) für Bodenschätzung.
    Zeigt Bodenart, Klassifizierungen und Wertezahlen an.

    :param bodenschaetzung_fc: Feature Class der Bodenschätzung (v_al_bodenschaetzung_f)
    """
    try:
        code_block = """import re

def extractText(text):
    # Regulärer Ausdruck, um den Text zwischen den Klammern zu finden
    pattern = r'\((.*?)\)'
    if text:
        matches = re.findall(pattern, text)
        if matches:
            return matches[0]
        else:
            return ''
    else:
        return ''

def formatWertzahl(wertzahl):
    if wertzahl is None:
        return "-"
    else:
        return str(int(wertzahl))

def calcBeschriftung(bodenart, nutzungsart, entstehung, klimastufe, wasserstufe, bodenstufe, zustandsstufe, sonstiges, bodenzahl, ackerzahl):
    boden = formatWertzahl(bodenzahl)
    acker = formatWertzahl(ackerzahl)
    
    if "(A)" in nutzungsart or "(AGr)" in nutzungsart:
        KN1 = extractText(bodenart)
        KN2 = extractText(zustandsstufe)
        KN3 = extractText(entstehung)
        SO = extractText(sonstiges)
        if "(A)" in nutzungsart:
            label = KN1 + KN2 + KN3 + "\\n" + boden + "/" + acker
        elif "(AGr)" in nutzungsart:
            label = "(" + KN1 + KN2 + KN3 + ")" + "\\n" + boden + "/" + acker
        if SO:
            label = label + "\\n" + SO
        return label
            
    elif "(Gr)" in nutzungsart or "(GrA)" in nutzungsart:
        KN1 = extractText(bodenart)
        KN2 = extractText(bodenstufe)
        KN3_1 = extractText(klimastufe)
        KN3_2 = extractText(wasserstufe)
        SO = extractText(sonstiges)
        if "(Gr)" in nutzungsart:
            label = KN1 + KN2 + KN3_1 + KN3_2 + "\\n" + boden + "/" + acker
        elif "(GrA)" in nutzungsart:
            label = "(" + KN1 + KN2 + KN3_1 + KN3_2 + ")" + "\\n" + boden + "/" + acker
        if SO:
            label = label + "\\n" + SO
        return label
    
    return ""
"""

        arcpy.AddMessage("- Feld Label für Bodenschätzung berechnen...")
        arcpy.CalculateField_management(
            bodenschaetzung_fc,
            "label",
            "calcBeschriftung(!bodenart_name!, !nutzungsart_name!, !entstehung_name!, !klima_name!, !wasser_name!, !bodenstufe_name!, !zustand_name!, !sonstige_angaben_name!, !bodenzahl!, !ackerzahl!)",
            "PYTHON3",
            code_block,
        )
        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Berechnung Label Bodenschätzung: {str(e)}")
        return False


def calculate_gebaeude_object_id(gebaeude_fc):
    """
    Generiert eindeutige UUID für jedes Gebäude.

    :param gebaeude_fc: Feature Class der Gebäude (v_al_gebaeude)
    """
    try:
        code_block = """def calcUuid():
    import uuid
    return str(uuid.uuid4())"""

        arcpy.AddMessage("- Feld object_id für Gebäude generieren...")
        arcpy.CalculateField_management(gebaeude_fc, "object_id", "calcUuid()", "PYTHON3", code_block)
        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Generierung object_id Gebäude: {str(e)}")
        return False


def clean_up_flur_fields(flur_fc):
    """
    Räumt temporäre Felder auf (z.B. flurnummer_l nach Join).

    :param flur_fc: Feature Class der Fluren (v_al_flur)
    """
    try:
        if arcpy.ListFields(flur_fc, "flurnummer_l"):
            arcpy.AddMessage("- Temporäre Felder löschen...")
            arcpy.DeleteField_management(flur_fc, "flurnummer_l")
        return True
    except Exception as e:
        arcpy.AddWarning(f"Warnung bei Löschen temporärer Felder: {str(e)}")
        return True
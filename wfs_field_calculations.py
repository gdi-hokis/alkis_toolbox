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

import arcpy


def calculate_flurnummer_l(flur_fc, flurstueck_fc):
    """
    Berechnet die Flurnummer-ID (flurnummer_l) aus Gemarkung und Flurnummer.
    Format: "080" + gemarkung_id + "00" + flurnummer

    :param flur_fc: Feature Class der Fluren (v_al_flur)
    :param flurstueck_fc: Feature Class der Flurstücke (v_al_flurstueck)
    """
    try:
        arcpy.CalculateField_management(
            flur_fc, "flurnummer_l", '"080"+$feature.gemarkung_id+"00"+$feature.flurnummer', "ARCADE"
        )
        arcpy.AddMessage("Flurnummer-ID für Fluren berechnet")

        arcpy.CalculateField_management(
            flurstueck_fc, "flurnummer_l", '"080"+$feature.gemarkung_id+"00"+$feature.flurnummer', "ARCADE"
        )
        arcpy.AddMessage("Flurnummer-ID für Flurstücke berechnet")

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
        arcpy.JoinField_management(flurstueck_fc, "flurnummer_l", flur_fc, "flurnummer_l", "flurname")
        arcpy.AddMessage("Flurnamen mit Flurstücken verknüpft")
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
        arcpy.AddMessage("Locator-Place für Flurstücke berechnet")
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
      return fsk""",
            "TEXT",
        )
        arcpy.AddMessage("FSK-Kurzform berechnet")
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
        arcpy.CalculateField_management(
            flurstueck_fc,
            "FLSTKEY",
            'str(int(!gemarkung_id!)) + "-" + str(int(!flurnummer!)) + "-" + !flurstueckstext!',
            "PYTHON3",
        )
        arcpy.AddMessage("FLSTKEY berechnet")
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

        arcpy.CalculateField_management(
            bodenschaetzung_fc,
            "label",
            "calcBeschriftung(!bodenart_name!, !nutzungsart_name!, !entstehung_name!, !klima_name!, !wasser_name!, !bodenstufe_name!, !zustand_name!, !sonstige_angaben_name!, !bodenzahl!, !ackerzahl!)",
            "PYTHON3",
            code_block,
        )
        arcpy.AddMessage("Label für Bodenschätzung berechnet")
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

        arcpy.CalculateField_management(gebaeude_fc, "object_id", "calcUuid()", "PYTHON3", code_block)
        arcpy.AddMessage("object_id für Gebäude generiert")
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
            arcpy.DeleteField_management(flur_fc, "flurnummer_l")
            arcpy.AddMessage("Temporäre Felder gelöscht")
        return True
    except Exception as e:
        arcpy.AddWarning(f"Warnung bei Löschen temporärer Felder: {str(e)}")
        return True

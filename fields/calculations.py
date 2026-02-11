"""
Modul für Feldberechnungen auf WFS-Download Daten.
Enthält Funktionen für Berechnungen auf v_al_flurstueck, v_al_bodenschaetzung_f und v_al_gebaeude.
"""

import arcpy


def calculate_flur_id(cfg, target_fc):
    """
    Berechnet die Flurnummer-ID (flurnummer_l) aus Gemarkung und Flurnummer.
    Format: "080" + gemarkung_id + "00" + flurnummer
    :param target_fc: Feature Class der Flurstücke (v_al_flurstueck) oder Fluren (v_al_flur)
    """
    try:
        arcpy.AddMessage("- Berechne Flur-ID ...")
        arcpy.CalculateField_management(
            target_fc,
            "flur_id",
            f'Text(Number($feature.{cfg["flurstueck"]["gemarkung_id"]}), "0000") + Text(Number($feature.{cfg["flurstueck"]["flurnummer"]}), "000")',
            "ARCADE",
        )

        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Berechnung Flurnummer-ID: {str(e)}")
        return False


def join_flurnamen(cfg, flurstueck_fc, flur_fc, delete_flur_id):
    """
    Verknüpft Flurnamen aus Flur-FC mit Flurstück-FC über flurnummer_l.
    :param flurstueck_fc: Feature Class der Flurstücke (v_al_flurstueck)
    :param flur_fc: Feature Class der Fluren (v_al_flur)
    """
    try:
        # Prüfe ob flurnummer_l in beiden Feature Classes vorhanden ist
        for fc in [flurstueck_fc, flur_fc]:
            fields = [f.name for f in arcpy.ListFields(fc)]
            if "flur_id" not in fields:
                calculate_flur_id(cfg, fc)

        arcpy.AddMessage("- Flurnamen mit Flurstücken verknüpfen...")

        # Workaround, weil vor dem JOIN die neuen Felder nicht immer sofort erkannt werden
        flst_path = arcpy.Describe(flurstueck_fc).catalogPath
        flur_path = arcpy.Describe(flur_fc).catalogPath

        arcpy.JoinField_management(flst_path, "flur_id", flur_path, "flur_id", cfg["flur"]["flurname"])
        if delete_flur_id:
            clean_up_flur_id([flur_fc, flurstueck_fc])
        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Join Flurnamen: {str(e)}")
        return False


def calculate_locator_place(cfg, flurstueck_fc):
    """
    Berechnet Locator-Place-Feld für Flurstücke.
    Priorität: Flurname > Gemarkungsname
    :param flurstueck_fc: Feature Class der Flurstücke (v_al_flurstueck)
    """
    try:
        arcpy.AddMessage("- Berechne Locator-Place ...")
        arcpy.CalculateField_management(
            flurstueck_fc,
            "locator_place",
            f"calcPlace(!{cfg["flurstueck"]["gemarkung_name"]}!,!{cfg["flur"]["flurname"]}!)",
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


def calculate_fsk(cfg, flurstueck_fc):
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
            f"replaceZerosInFSK(!{cfg["flurstueck"]["flurstueckskennzeichen"]}!)",
            "PYTHON3",
            """def replaceZerosInFSK(flstId):
      fsk = flstId
      if fsk[6:9] == "000":
          fsk = fsk[:6] + "___" + fsk[9:]
      if fsk[14:18] == "0000":
          fsk = fsk[:14] + "____" + fsk[18:]
      fsk = fsk[:-2]
      return fsk""",
            "TEXT",
        )
        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Berechnung FSK: {str(e)}")
        return False


def calculate_flstkey(cfg, flurstueck_fc):
    """
    Berechnet FLSTKEY aus Gemarkung, Flurnummer und Flurstückstext.
    Format: gemarkung_id + "-" + flurnummer + "-" + flurstueckstext
    :param flurstueck_fc: Feature Class der Flurstücke (v_al_flurstueck)
    """
    try:
        arcpy.AddMessage("- Berechne FLSTKEY...")
        arcpy.CalculateField_management(
            flurstueck_fc,
            "FLSTKEY",
            f'str(int(!{ cfg["flurstueck"]["gemarkung_id"]}!)) + "-" + str(int(!{cfg["flurstueck"]["flurnummer"]}!)) + "-" + !{cfg["flurstueck"]["flurstueckstext"]}!',
            "PYTHON3",
        )
        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Berechnung FLSTKEY: {str(e)}")
        return False


def calculate_label_bodensch(cfg, bodenschaetzung_fc):
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
            f"calcBeschriftung(!{cfg["bodenschaetzung"]["bodenart_name"]}!, !{cfg["bodenschaetzung"]["nutzungsart_name"]}!, !{cfg["bodenschaetzung"]["entstehung_name"]}!, !{cfg["bodenschaetzung"]["klima_name"]}!, !{cfg["bodenschaetzung"]["wasser_name"]}!, !{cfg["bodenschaetzung"]["bodenstufe_name"]}!, !{cfg["bodenschaetzung"]["zustand_name"]}!, !{ cfg["bodenschaetzung"]["sonstige_angaben_name"]}!, !{cfg["bodenschaetzung"]["bodenzahl"]}!, !{cfg["bodenschaetzung"]["ackerzahl"]}!)",
            "PYTHON3",
            code_block,
        )

        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Berechnung Label Bodenschätzung: {str(e)}")
        return False


def clean_up_flur_id(feature_classes):
    """
    Räumt temporäre Felder auf (z.B. flurnummer_l nach Join).
    :param flur_fc: Feature Class der Fluren (v_al_flur)
    """
    try:
        arcpy.AddMessage("- 'flur_id' löschen...")
        for fc in feature_classes:
            if arcpy.ListFields(fc, "flur_id"):
                arcpy.DeleteField_management(fc, "flur_id")
        return True
    except Exception as e:
        arcpy.AddWarning(f"Warnung bei Löschen temporärer Felder: {str(e)}")
        return True

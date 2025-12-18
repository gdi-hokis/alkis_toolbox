# Copyright (c) 2024, Jana Muetsch, Andre Voelkner, LRA Hohenlohekreis
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

import arcpy, os, subprocess


def prepareNutzung(orig_sde):
    print("--------prepare Nutzung---------")
    nutzung = orig_sde + os.sep + "v_al_tatsaechliche_nutzung"
    flurstueck = orig_sde + os.sep + "v_al_flurstueck"

    arcpy.PairwiseIntersect_analysis([nutzung, flurstueck], "nutzung_intersect", "NO_FID", None, "INPUT")
    print(arcpy.GetMessages())
    arcpy.PairwiseDissolve_analysis(
        "nutzung_intersect",
        "nutzung_dissolve",
        "objektart;objektname;unterart_typ;unterart_id;unterart_kuerzel;unterart_name;eigenname;weitere_nutzung_id;weitere_nutzung_name;klasse;flurstueckskennzeichen",
    )
    print(arcpy.GetMessages())

    arcpy.AddField_management(
        "nutzung_dissolve", "sfl", "LONG", None, None, None, "Schnittfläche", "NULLABLE", "NON_REQUIRED", ""
    )
    print("SFL-Feld hinzugefügt")


def prepareBoden(orig_sde):
    print("-----------prepare Bodenschaetzung----------")
    nav_nutzung = orig_sde + os.sep + "navigation_nutzung"
    flurstueck = orig_sde + os.sep + "v_al_flurstueck"
    bodenschaetzung = orig_sde + os.sep + "v_al_bodenschaetzung_f"
    bewertung = orig_sde + os.sep + "v_al_bodenbewertung"

    # FSK Bodenschätzung anlegen
    arcpy.PairwiseIntersect_analysis(
        [bodenschaetzung, flurstueck], "bodenschaetzung_intersect", "NO_FID", None, "INPUT"
    )
    print(arcpy.GetMessages())

    arcpy.PairwiseDissolve_analysis(
        "bodenschaetzung_intersect",
        "fsk_bodenschaetzung",
        "bodenart_id;bodenart_name;nutzungsart_id;nutzungsart_name;entstehung_id;entstehung_name;klima_id;klima_name;wasser_id;wasser_name;bodenstufe_id;bodenstufe_name;zustand_id;zustand_name;sonstige_angaben_id;sonstige_angaben_name;bodenzahl;ackerzahl;flurstueckskennzeichen;amtliche_flaeche",
    )
    print(arcpy.GetMessages())

    arcpy.AddField_management(
        "fsk_bodenschaetzung", "sfl", "LONG", None, None, None, "Schnittfläche", "NULLABLE", "NON_REQUIRED", ""
    )
    arcpy.AddField_management(
        "fsk_bodenschaetzung", "emz", "LONG", None, None, None, "EMZ", "NULLABLE", "NON_REQUIRED", ""
    )

    print("SFL-Feld/ EMZ hinzugefügt")

    # Auschliessen von nicht relevanten Nutzungsarten -> Landwirtschaft, Heide, Sumpf, UnlandVegetationsloseFlaeche und GFLF/ Landwirtschaftliche Betriebsfläche/Forstwirtschaftliche Betriebsfläche und Garten
    arcpy.MakeFeatureLayer_management(
        nav_nutzung,
        "nutzung_lyr",
        where_clause="objektart NOT IN (43001, 43004, 43006, 43007) And Not (objektart = 41006 And unterart_id IN ('2700','7600','6800'))And Not (objektart = 41008 And unterart_id IN ('4460'))",
    )
    # alles erasen ausser Landwirtschaft, Heide, Sumpf, UnlandVegetationsloseFlaeche und GFLF/ Landwirtschaftliche Betriebsfläche/Forstwirtschaftliche Betriebsfläche und Garten
    arcpy.Erase_analysis("fsk_bodenschaetzung", "nutzung_lyr", "schaetzung_relevante_nutz", "0,02 Meters")
    print("relevante Nutzungen herausgefiltert an Bodenschätzung")

    # Auschliessen von Bewertungsflaechen, die nicht mit Bodenschätzung überlagert sein können, siehe VWVLK Anlage 1, Objektart Bewertung
    # Forstwirtschaftliche Nutzung (H), Weinbauliche Nutzung, allgemein (WG), Teichwirtschaft (TEIW), Abbauland der Land- und Forstwirtschaft (LFAB), Geringstland (GER),
    # Unland (U), Nebenfläche des Betriebs der Land- und Forstwirtschaft (NF), u.a.
    arcpy.MakeFeatureLayer_management(
        bewertung, "bewertung_lyr", "klassifizierung_id IN (3100, 3105, 3200, 3411, 3480, 3481, 3482, 3490, 3510, 3520, 3530, 3600, 3611, 3610, 3612, 3613, 3614, 3615, 3616, 3710, 3999)"
    )
  
    arcpy.Erase_analysis("schaetzung_relevante_nutz", "bewertung_lyr", "schaetzung_o_bewertung", "0,02 Meters")

    # Ausschliessen von Kleinstflaechen und null-fsks
    arcpy.MakeFeatureLayer_management("schaetzung_o_bewertung", "schaetzung_o_bewertung_lyr", "shape_Area < 0.5")
    arcpy.DeleteFeatures_management("schaetzung_o_bewertung_lyr")
    print("Bewertungsflächen aus Schätzung ausgeschlossen und Schnipsel gelöscht")

    arcpy.TruncateTable_management("fsk_bodenschaetzung")
    arcpy.Append_management("schaetzung_o_bewertung", "fsk_bodenschaetzung", "NO_TEST", "", "")

    # Verschneiden von Bewertungsflaechen und Kleinstflaechen eliminieren
    arcpy.PairwiseIntersect_analysis([flurstueck, bewertung], "fsk_bewertung", "ALL", None, "INPUT")
    arcpy.MakeFeatureLayer_management(
        "fsk_bewertung",
        "fsk_bewertung_lyr",
        where_clause="shape_Area < 0.5 OR klassifizierung_id NOT IN (3100, 3105, 3200, 3411, 3480, 3481, 3482, 3490, 3510, 3520, 3530, 3600, 3611, 3610, 3612, 3613, 3614, 3615, 3616, 3710, 3999)",
    )
    arcpy.DeleteFeatures_management("fsk_bewertung_lyr")
    arcpy.Erase_analysis("fsk_bewertung", "nutzung_lyr", "fsk_bewertung_relevant", "0,02 Meters")

    print("Layer FSK Bewertung & FSK Bewertung mit relevanten Klassifizierungen erstellt")

    # Bewertungsflaechen in Verschnitt uebernehmen
    # Einzeilig mit r'' da sonst Felder nicht uebernommen werden, vermutlich wegen / im Alias
    arcpy.Append_management(
        "fsk_bewertung",
        "fsk_bodenschaetzung",
        "NO_TEST",
        r'flurstueckskennzeichen "flurstueckskennzeichen" true true false 254 Text 0 0,First,#,{0},flurstueckskennzeichen,0,254;amtliche_flaeche "amtliche_flaeche" true true false 4 Long 0 0,First,#,{0},amtliche_flaeche,-1,-1;nutzungsart_id "nutzungsart_id" true true false 4 Long 0 0,First,#,{0},klassifizierung_id,-1,-1;nutzungsart_name "nutzungsart_name" true true false 254 Text 0 0,First,#,{0},klassifizierung_name,0,254;sonstige_angaben_name "sonstige_angaben_name" true true false 254 Text 0 0,First,#,{0},klassifizierung_name,0,254'.format(
            "fsk_bewertung"
        ),
    )

    print("Bewertungen in Bodenschätzung übernommen")

    # Setzen der konstanten Values fuer angehaengte Bewertungsflaechen
    with arcpy.da.UpdateCursor(
        "fsk_bodenschaetzung", ["bodenzahl", "ackerzahl", "emz", "sonstige_angaben_id"], "bodenart_id IS NULL"
    ) as ucursor:
        for row in ucursor:
            row[0] = "0"  # we1
            row[1] = "0"  # we2
            row[2] = 0  # emz
            row[3] = "9999"  # son
            ucursor.updateRow(row)


def calculateNavNutzungBodensch(workspace, config):
    print("--------calculate Nutzung und Bodenschätzung beginnt --------")

    arcpy.env.workspace = workspace
    arcpy.env.overwriteOutput = True

    orig_sde = config["orig_sde"]
    gemeinden = config["gemeinden"]
    subprocess_path = config["subproc_sfl"]

    prepareNutzung(orig_sde)
    orig_navigation_nutzung = orig_sde + os.sep + "navigation_nutzung"
    arcpy.TruncateTable_management(orig_navigation_nutzung)

    fieldmapping = r'objektart "Objektart" true true false 8 Double 8 38,First,#,{0},objektart,-1,-1;objektname "Nutzung" true true false 255 Text 0 0,First,#,{0},objektname,0,253;unterart_typ "Unterart Typ" true true false 255 Text 0 0,First,#,{0},unterart_typ,0,253;unterart_id "Unterart Schlüssel" true true false 8 Double 8 38,First,#,{0},unterart_id,-1,-1;unterart_kuerzel "Abkürzung" true true false 10 Text 0 0,First,#,{0},unterart_kuerzel,0,49;unterart_name "Unterart" true true false 255 Text 0 0,First,#,{0},unterart_name,0,253;eigenname "Eigenname" true true false 50 Text 0 0,First,#,{0},eigenname,0,253;weitere_nutzung_id "weitere Nutzung Schlüssel" true true false 8 Double 8 38,First,#,{0},weitere_nutzung_id,0,254;weitere_nutzung_name "weitere Nutzung" true true false 255 Text 0 0,First,#,{0},weitere_nutzung_name,0,253;klasse "Klasse" true true false 8 Double 8 38,First,#,{0},klasse,-1,-1;flurstueckskennzeichen "Flurstückskennzeichen" true true false 255 Text 0 0,First,#,{0},flurstueckskennzeichen,0,253;sfl "Fläche [m²]" true true false 4 Long 0 10,First,#,{0},sfl,-1,-1'.format(
        "nutzung_dissolve"
    )

    arcpy.Append_management("nutzung_dissolve", orig_navigation_nutzung, "NO_TEST", fieldmapping)
    print("-----Nutzung vorbereitet---------")

    prepareBoden(orig_sde)
    orig_navigation_bodenschaetzung = orig_sde + os.sep + "navigation_bodenschaetzung"
    arcpy.TruncateTable_management(orig_navigation_bodenschaetzung)
    arcpy.Append_management("fsk_bodenschaetzung", orig_navigation_bodenschaetzung)
    print("--------------Bodenschätzung vorbereitet------------------")

    # Subprocess für Verschneidung -> gemeindeweise da sehr rechenintensive Operation
    for gemeinde in gemeinden:

        arguments = [str(gemeinde), workspace]

        command = ["C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe", subprocess_path]
        command.extend(arguments)

        print(command)

        proc = subprocess.Popen(command, stdin=None, stdout=None, stderr=None)
        return_code = proc.wait()

        if return_code != 0:
            print("Fehler im Subprocess")
            break

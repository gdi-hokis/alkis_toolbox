# Copyright (c) 2024, Jana Muetsch, LRA Hohenlohekreis
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

import sys, os, arcpy, json, uuid

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Config
with open(config_path, "r", encoding="utf-8") as config_file:
    config = json.load(config_file)

abrufdatum = "17.09.2025"

sys.path.append(config["scripts_path"])

import download_wfs_data
import calculate_lage
import calculate_nutzung_bodensch


def calculateFlurnamen(flurstueck, flurstueck_layer):
    # Für Locator und Ortsbeschreibung
    # Muss passieren bevor die Daten in die Produktivdatenbank übertragen werden, da sonst immer das JOIN Field neu hinzugefügt wird, auch wenn es schon da ist
    # arcpy.AddField_management("v_al_flur","flurnummer_l","TEXT")
    arcpy.CalculateField_management(
        "v_al_flur", "flurnummer_l", '"080"+$feature.gemarkung_id+"00"+$feature.flurnummer', "ARCADE"
    )
    print(arcpy.GetMessages())
    arcpy.CalculateField_management(
        flurstueck_layer, "flurnummer_l", '"080"+$feature.gemarkung_id+"00"+$feature.flurnummer', "ARCADE"
    )
    print(arcpy.GetMessages())
    print("Flurnummer-ID vorbereitet")
    # Kann man sich sparen, wenn man das vor dem Append in die Datenbank macht
    arcpy.JoinField_management(flurstueck, "flurnummer_l", "v_al_flur", "flurnummer_l", "flurname")
    print(arcpy.GetMessages())
    arcpy.CalculateField_management(
        flurstueck_layer,
        "locator_place",
        "calcPlace(!gemarkung_name!,!flurname!)",
        "PYTHON3",
        """def calcPlace(gemarkung, flurname):
    if flurname:
        return flurname
    else:
        return gemarkung""",
    )
    print(arcpy.GetMessages())
    arcpy.DeleteField_management("v_al_flur", "flurnummer_l")
    print("-----Fluren übertragen-----")


def calculateLabelBodensch(bodenschaetzung, layer):
    # Wegen Bug bei Esri (sollte eigentlich auch ohne AddField gehen...)
    #arcpy.AddField_management(bodenschaetzung, "label", "TEXT")
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
def calcBeschriftung(bodenart,nutzungsart,entstehung,klimastufe, wasserstufe, bodenstufe, zustandsstufe, sonstiges, bodenzahl, ackerzahl):
                boden = formatWertzahl(bodenzahl)
                acker = formatWertzahl(ackerzahl)
                if "(A)" in nutzungsart or "(AGr)" in nutzungsart:
                        KN1 = extractText(bodenart)
                        KN2 = extractText(zustandsstufe)
                        KN3 = extractText(entstehung)
                        SO = extractText (sonstiges)
                        if "(A)" in nutzungsart:
                                label = KN1+KN2+KN3+"\\n"+boden+"/"+acker
                        elif "(AGr)" in nutzungsart:
                                label = "("+KN1+KN2+KN3+")"+"\\n"+boden+"/"+acker
                        if SO:
                                label = label+"\\n"+SO
                        return label
                elif "(Gr)" in nutzungsart or "(GrA)" in nutzungsart:
                        KN1 = extractText(bodenart)
                        KN2 = extractText(bodenstufe)
                        KN3_1 = extractText(klimastufe)
                        KN3_2 = extractText(wasserstufe)
                        SO = extractText (sonstiges)
                        if "(Gr)" in nutzungsart:
                                label = KN1+KN2+KN3_1+KN3_2+"\\n"+boden+"/"+acker
                        elif "(GrA)" in nutzungsart:
                                label = "("+KN1+KN2+KN3_1+KN3_2+")"+"\\n"+boden+"/"+acker
                        if SO:
                                label = label+"\\n"+SO
                        return label"""
    arcpy.CalculateField_management(
        layer,
        "label",
        "calcBeschriftung(!bodenart_name!,!nutzungsart_name!,!entstehung_name!,!klima_name!,!wasser_name!,!bodenstufe_name!,!zustand_name!,!sonstige_angaben_name!,!bodenzahl!,!ackerzahl!)",
        "PYTHON3",
        code_block,
    )
    print(arcpy.GetMessages())
    print("----------Beschriftung Bodenschätzung fertig------------")


def calculateFsk(flurstueck):
    arcpy.CalculateField_management(
        flurstueck,
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
    print("-------FSK berechnet--------------")

def calculateFLSTKEY(flurstueck):
    arcpy.CalculateField_management(
        flurstueck,
        "FLSTKEY",
        "str(int(!gemarkung_id!)) + '-' + str(int(!flurnummer!)) + '-' + !flurstueckstext!",
        "PYTHON3",
        field_type = "TEXT",
    )
    print("-------FSK berechnet--------------")

def calculateAbrufdatum(flurstueck, abrufdatum):
    arcpy.CalculateField_management(
        flurstueck,
        "abrufdatum",
        expression="datetime.datetime.now()",
    expression_type="PYTHON3",
    code_block="import datetime"
    )
    print("-------Abrufdatum berechnet--------------")



# Workspace erstellen
work_dir = config["work_dir"]
sde = config["orig_sde"]
TEMP_FOLDER = work_dir + os.sep + "alkis_calculation_" + str(uuid.uuid4())
os.mkdir(TEMP_FOLDER)
arcpy.management.CreateFileGDB(TEMP_FOLDER, "alkis_calculation.gdb")
workspace = TEMP_FOLDER + os.sep + "alkis_calculation.gdb"

print("Workspace angelegt: {0}".format(workspace))

TEMP_FOLDER = "E://ALKIS_2024//alkis_calculation_0fcc90ed-f38d-4eca-a6ec-7507c0b3b5be"
workspace = TEMP_FOLDER + os.sep + "alkis_calculation.gdb"

# # WFS-Daten downloaden
arcpy.env.workspace = workspace
sde = config["orig_sde"]
download_wfs_data.downloadWFSData(TEMP_FOLDER + os.sep + "Download_Folder", config["download_wfs"])

# Feature Classes vorbereiten und in SDE ersetzen
print("------Vorbereitung FeatureClasses und Append startet---------")
arcpy.MakeFeatureLayer_management("v_al_kreis", config["kreis"], "kreis_name = '" + config["kreis"] + "'")

fcs = arcpy.ListFeatureClasses()

# Zuschneiden auf Hohenlohekreis
for fc in fcs:
    # if fc not in ["v_al_gebaeude","v_al_flurstueck","v_al_grenzpunkt","v_al_sonstiger_punkt","v_al_bauwerk_einrichtung_p","v_al_bauwerk_einrichtung_l","v_al_bauwerk_einrichtung_f","v_al_festlegung_recht","v_al_strasse_gewann","v_al_lagebezeichnung","v_al_grenzlinie","v_al_flur","v_al_gemarkung","v_al_tatsaechliche_nutzung", "v_al_gemeinde"]:

        # 1km Puffer um Kreis auswählen
        layer_name = os.path.splitext(fc)[0] + "_Layer"
        arcpy.MakeFeatureLayer_management(fc, layer_name)
        arcpy.SelectLayerByLocation_management(layer_name, "INTERSECT", config["kreis"], 1000)
        print(arcpy.GetMessages())
        print(layer_name + " ausgewählt")

        if fc == "v_al_flurstueck":
            calculateFlurnamen(fc, layer_name)
            calculateFsk(layer_name)
            calculateFLSTKEY(layer_name)
            calculateAbrufdatum(layer_name,abrufdatum)

        if fc == "v_al_bodenschaetzung_f":
            calculateLabelBodensch(fc, layer_name)
        if fc == "v_al_gebaeude":
            arcpy.CalculateField_management(
                layer_name,
                "object_id",
                "calcUuid()",
                "PYTHON3",
                code_block="""def calcUuid():
            import uuid
            return str(uuid.uuid4())
            """,
            )
        # Leeren und neu befüllen
        arcpy.TruncateTable_management(sde + os.sep + fc)
        arcpy.Append_management(layer_name, sde + os.sep + fc)
        print(fc + " in Original-SDE übertragen")


# Lage berechnens
calculate_lage.calculateLage(workspace, sde)

# Nutzung berechnen

calculate_nutzung_bodensch.calculateNavNutzungBodensch(workspace, config)

## Übertragen in Transport GDB
update_gdb_path = config["update_gdb"]
arcpy.env.workspace = update_gdb_path
feature_classes_gdb = arcpy.ListFeatureClasses()
tables_gdb = arcpy.ListTables()
print(feature_classes_gdb)

for fc in feature_classes_gdb:
    sde_fc = sde + os.sep + "alkis_nora.sde." + fc
    arcpy.TruncateTable_management(fc)
    arcpy.Append_management(sde_fc, fc)
    print("{0} in ALKIS_NORA.gdb ersetzt".format(fc))

for table in tables_gdb:
    sde_fc = sde + os.sep + "alkis_nora.sde." + table
    arcpy.TruncateTable_management(table)
    arcpy.Append_management(sde_fc, table)
    print("{0} in ALKIS_NORA.gdb ersetzt".format(table))


print("--------------Skript beendet------------------")

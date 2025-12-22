import os
import arcpy

def prepare_csv(input_csv):
    """
    Prepare the csv by removing the first and last five lines (header and code explanation).
    """
    encoding = "utf-8"  # Hier die bekannte Codierung eintragen, z.B. 'utf-8'

    # Temporäre CSV vorbereiten
    output_csv = os.path.join(os.path.dirname(input_csv), "prepared_" + os.path.basename(input_csv))

    # Datei in der bekannten Codierung einlesen
    with open(input_csv, "r", encoding=encoding) as f:
        lines = f.readlines()

    # Entferne die erste und letzten fünf Zeilen
    lines = lines[1:-5]

    # Neue Datei speichern, ebenfalls in der bekannten Codierung
    with open(output_csv, "w", encoding=encoding, newline="") as f:
        f.writelines(lines)
    return output_csv

def spatial_join_gem_flst(gem, flst, tempgdb):
    """
    
    """
    # Buffer wird erstellt
    sql = "kreis_name = 'Hohenlohekreis'"
    arcpy.MakeFeatureLayer_management(gem, "gemeinden_layer", where_clause=sql)
    arcpy.Buffer_analysis("gemeinden_layer", "buffer", "500 METER")

    arcpy.SpatialJoin_analysis(
        target_features=flst,
        join_features="buffer",
        out_feature_class="v_al_flurstueck_SpatialJoin",
        join_operation="JOIN_ONE_TO_ONE",
        join_type="KEEP_ALL",
        field_mapping=r'flstkey "Flurstückskey" true true false 512 Text 0 0,First,#,{0}\v_al_flurstueck,flstkey,0,512;gemeinde_name_1 "Gemeinde" true true false 100 Text 0 0,Join,", ",buffer,gemeinde_name,0,50'.format(tempgdb),
        match_option="INTERSECT",
        search_radius=None,
        distance_field_name="",
    )


def make_eigentuemer_table(gem, flst, prepared_csv, tempgdb, abrufdatum):
    """
    
    """
    arcpy.AddMessage("Aufruf make_eigentuemer_table")
    #  CSV wird in fc konvertiert und dann bearbeitet
    
    # arcpy.TableToTable_conversion(prepared_csv, tempgdb, "eigentuemer")
    arcpy.AddMessage("CSV in Tabelle konvertiert")

    #Calculate FSK
    arcpy.CalculateField_management(
        in_table="eigentuemer",
        field="flstkey",
        expression="calcFLSTKEY(!flurstueck!)",
        expression_type="PYTHON3",
        code_block="""
            def calcFLSTKEY(s):
                teile = s.split("-")
                gemarkung = str(int(teile[0][2:]))             # "080237" → "237"
                flur = str(int(teile[1]))            # "000" → "0"
                zaehler, nenner = teile[2].split("/")  # z.B. "00023/0006"
                zaehler = str(int(zaehler))
                if nenner.strip() == "0000":
                    return f"{gemarkung}-{flur}-{zaehler}"
                else:
                    nenner = str(int(nenner))
                    return f"{gemarkung}-{flur}-{zaehler}/{nenner}"
            """,
        field_type="TEXT",
        enforce_domains="NO_ENFORCE_DOMAINS"
    )
    arcpy.AddMessage("FLSTKEY berechnet")

    # arcpy.AddField_management("fcalkiscsv", "FSK", "TEXT")
    # arcpy.CalculateField_management(
    #     in_table= "eigentuemer",
    #     field = "FSK",
    #     expression="replaceZerosInFSK(!FKZ![1:-1])",
    #     expression_type="PYTHON3",
    #     code_block="""
    #         def replaceZerosInFSK(flstId):
    #             fsk = flstId
    #             if fsk[6:9] == "000":
    #                 fsk = fsk[:6] + "___" + fsk[9:]
    #             if fsk[14:18] == "0000":
    #                 fsk = fsk[:14] + "____" + fsk[18:]
    #             return fsk
    #         """,
    #     field_type="TEXT",
    #     enforce_domains="NO_ENFORCE_DOMAINS",
    # )
    # arcpy.AddMessage("FSK berechnet")
    # arcpy.CalculateField_management(
    #     "eigentuemer",
    #     "abrufdatum",
    #     f'{abrufdatum}',
    #     "PYTHON3",
    #     field_type="DATE"
    # )

    # spatial_join_gem_flst(gem, flst, tempgdb)
    # print("Gemeindepuffer vorbereitet")
    # #Gemeindefelder hinzufügen und umbenennen wie in der Hosted Table
    # arcpy.JoinField_management("eigentuemer", "flstkey", flst, "flstkey", ["gemeinde_name"])
    # arcpy.AlterField_management("eigentuemer", "gemeinde_name", new_field_name="gemeinde")
    # arcpy.DeleteField_management("eigentuemer","gemeinde_name")
    # arcpy.JoinField_management("eigentuemer", "flstkey", "v_al_flurstueck_SpatialJoin", "flstkey", ["gemeinde_name_1"])
    # arcpy.AlterField_management("eigentuemer", "gemeinde_name_1", new_field_name="gemeinde_name")
    # arcpy.DeleteField_management("eigentuemer","gemeinde_name_1")
    # print("Gemeindefelder angepasst")
#------------------------------------------

# def DeleteAppendEigentuemerData(aprx_path):
#     """
    
#     """
#     aprx = arcpy.mp.ArcGISProject(aprx_path)
#     map_obj = aprx.listMaps("Eigentuemer")[0]

#     # Hole die Layer-Objekte anhand ihrer Namen
#     hosted_layer = map_obj.listTables("Eigentuemer_Sichten")[0]
#     source_layer = map_obj.listTables("fcalkiscsv")[0]

#     arcpy.SignInToPortal("https://gdi-hok.de/portal/", "portaladmin", "leuchTURM25oo")
    
#     active_portal_url = arcpy.GetActivePortalURL()
#     print(active_portal_url)

#     arcpy.DeleteFeatures_management(hosted_layer)
#     print(arcpy.GetMessages())
#     print("Alle eigentümer gelöscht")

#     # 2. Hänge die Features vom Quell-Layer in den Ziel-Layer an ----> dauert je nach Größe der FC schonmal eine Stunde
#     arcpy.Append_management(source_layer, hosted_layer, "NO_TEST", field_mapping=r'objectid_1 "OBJECTID" true true false 0 Long 0 0,First,#,{0},OBJECTID,-1,-1;gmk "gmk" true true false 8000 Text 0 0,First,#,{0},Gmk,0,7999;flurstueck "flurstueck" true true false 8000 Text 0 0,First,#,{0},Flurstueck,0,7999;fkz "fkz" true true false 8000 Text 0 0,First,#,{0},FKZ,0,7999;amtlicheflaeche "amtlicheflaeche" true true false 0 Long 0 0,First,#,{0},AmtlicheFlaeche,-1,-1;bodsch "bodsch" true true false 8000 Text 0 0,First,#;fkoord32 "fkoord32" true true false 8000 Text 0 0,First,#;schluessel "schluessel" true true false 8000 Text 0 0,First,#;lage "lage" true true false 8000 Text 0 0,First,#;hausnr "hausnr" true true false 8000 Text 0 0,First,#;laufendenummernachdin "laufendenummernachdin" true true false 8000 Text 0 0,First,#,{0},laufendeNummerNachDIN,0,7999;name "name" true true false 8000 Text 0 0,First,#,{0},Name,0,7999;geburtsdatum "geburtsdatum" true true false 8000 Text 0 0,First,#,{0},Geburtsdatum,0,7999;anschrift "anschrift" true true false 8000 Text 0 0,First,#,{0},Anschrift,0,7999;anteilsverhaeltnis "anteilsverhaeltnis" true true false 8000 Text 0 0,First,#,{0},Anteilsverhaeltnis,0,7999;artderrechtsgemeischaft "artderrechtsgemeischaft" true true false 0 Long 0 0,First,#,{0},ArtderRechtsgemeischaft,-1,-1;blattart "blattart" true true false 0 Long 0 0,First,#,{0},Blattart,-1,-1;buchungsart "buchungsart" true true false 0 Long 0 0,First,#,{0},Buchungsart,-1,-1;buchungsblatt "buchungsblatt" true true false 8000 Text 0 0,First,#,{0},Buchungsblatt,0,7999;lfdnr "lfdnr" true true false 8000 Text 0 0,First,#,{0},LfdNr,-1,-1;anteil "anteil" true true false 8000 Text 0 0,First,#,{0},Anteil,0,7999;fsk "fsk" true true false 8000 Text 0 0,First,#,{0},FSK,0,254;gemeinde "Gemeinde" true true false 8000 Text 0 0,First,#,fcalkiscsv,gemeinde_name_1,0,99'.format("fcalkiscsv"),update_geometry="NOT_UPDATE_GEOMETRY")
#     print(arcpy.GetMessages())
#     print("Die Features aus 'fcalkicsv' wurden erfolgreich in 'Eigentuemer_Sichten' angehängt.")
#     print("fertig")
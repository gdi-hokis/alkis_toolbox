# Copyright (c) 2022, Andre Voelkner, LRA Hohenlohekreis
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

import arcpy, os, math, pyodbc, sys, json



def calculateSFLNutzung (verbesserung, fsk, fsk_afl, navigation_nutzung, max_shred_qm):
    mini_sfl_arr = []
    sfl_sum = 0
    # print('')
    # print('-------------------------------------')
    # print(fsk.fsk + ' (' + str(fsk.afl) + ' qm)' )
    # FSK_Nutzung_Dissolve:     neue Berechnung und SFL-Korrektur Voelkner 01/2023
  
    with arcpy.da.UpdateCursor(navigation_nutzung, ["flurstueckskennzeichen", "SHAPE@", "SHAPE@AREA","sfl","weitere_nutzung_id"], "flurstueckskennzeichen = '{0}' ".format(fsk),sql_clause=(None, "ORDER BY sde.st_area (Shape)")) as ucursor:
        for row in ucursor:
            flurstueck = row[0]
            shape = row[1]
            area = row[2]
            sfl = row[3]   
            
            if area < 2 and fsk_afl > 10:   # Kleinst-Flst ausschliessen
                # mini_sfl += nfl.area               
                print('Nutzung: Kleinstflaeche in ' + str(flurstueck) + '('+ str(area) + ' qm) wird geloescht')
                mini_sfl_arr.append({"a": area, "geom": shape})
                ucursor.deleteRow()

            else:
                overlap = False if row[4]!=1000 else True   
                if not overlap:  
                    if sfl == fsk_afl:
                        break
                    elif len(mini_sfl_arr) > 0:
                        mini_sfl_arr_index = 0
                        adjacent_mini_sfl = 0
                        for mini_sfl in mini_sfl_arr:
                            if shape.touches(mini_sfl["geom"]):
                                adjacent_mini_sfl += mini_sfl["a"]
                                row[2] = shape.union(mini_sfl["geom"])
                                mini_sfl_arr.pop(mini_sfl_arr_index)
                            mini_sfl_arr_index += 1
                        qm = int((area + adjacent_mini_sfl) * verbesserung + 0.5)
                        # print("sfl " + str(nfl.objectid) + ": " + str(row[0]) + " qm + " + str(adjacent_mini_sfl))
                    else:
                    
                        qm = int((area) * verbesserung + 0.5)
                        # print("sfl " + str(nfl.objectid) + ": " + str(row[0]) + " qm")

                    sfl_sum += qm
                    row[3] = qm 
                # Wenn es sich um eine überlagernde Fläche handelt, nicht in Gesamtsumme einrechnen    
                elif overlap:
                    row[3] = int(area)
               
                ucursor.updateRow(row)
    
    if not sfl_sum == fsk_afl:
        delta = int(fsk_afl - sfl_sum)
        # print(fsk.fsk)
        # print("afl: " + str(fsk.afl) + " qm")
        #print('delta: ' + str(delta) + " qm")
        rest_anteil = abs(delta)
        if rest_anteil < 5:     # nur Verschnittflaechen innerhalb des Abrufrahmens korrigieren
            for nfl in db_cursor_ff.execute("SELECT sfl, flurstueckskennzeichen, objectid FROM sde.navigation_nutzung WHERE flurstueckskennzeichen = '%s' ORDER BY sfl DESC" % fsk).fetchall():
            # with arcpy.da.UpdateCursor("nutzung_dissolve", ["sfl", "flurstueck", "objectid"], "flurstueck = '{0}'".format(fsk), sql_clause=(None, "ORDER BY sfl DESC")) as ucursor:
            #     for row in ucursor:

                if nfl.sfl < max_shred_qm:   
                    rest_anteil -= sfl
                    
               
                elif rest_anteil > 0:
                    #print("restanteil: " + str(rest_anteil))
                    # int_anteil = math.ceil(rest_anteil / (len(sfl_arr) - completed_sfl))
                    ratio = 1.0 if nfl.sfl > fsk_afl else float(nfl.sfl) / float(fsk_afl)
                    # print("ratio: " + repr(ratio))
                    int_anteil = math.ceil(abs(delta) * float(ratio))  # works different in Python 2 -> only use in Python 3
                    rest_anteil -= int_anteil

                    if delta < 0: int_anteil = int_anteil * -1

                    # print("sfl " + str(row[2]) + ": " + str(row[0]) + " qm + " + str(int_anteil))
                    nfl.sfl += int_anteil 
                    db_cursor_ff.execute('UPDATE sde.navigation_nutzung SET sfl = {0} WHERE objectid = {1}'.format(nfl.sfl,nfl.objectid))
                    db_con_ff.commit()
                    print("Fläche {0} angeglichen mit {1} qm". format(nfl.objectid, nfl.sfl))
                    #ucursor.updateRow(row)
                    #print("Flächen an Buchfläche angeglichen")
                else:
                    # print("sfl " + str(row[2]) + ": " + str(row[0]) + " qm")
                    break
            if rest_anteil > 0:
                print('Restanteil von ' + str(rest_anteil) + ' qm in ' + fsk + ' (' + str(fsk_afl) + ' qm)' )



def calculateSFLBoden(verbesserung, fsk, fsk_afl, max_shred_qm, db_cursor_ff, navigation_bodenschaetzung): 

    #Schätz AFL berechnen
    schaetz_afl = db_cursor_ff.execute("SELECT SUM(sfl) FROM sde.navigation_nutzung WHERE flurstueckskennzeichen = '%s' AND (objektart IN (43001, 43004, 43006, 43007) Or (objektart = 41006 And unterart_id IN (2700, 6800)) Or (objektart = 41008 And unterart_id IN (4460)))" % fsk).fetchval()
    #print(schaetz_afl)
    if schaetz_afl:
        # nicht relevante Bewertungsflaechen ausschliessen
        with arcpy.da.SearchCursor("fsk_bewertung_relevant", ["flurstueckskennzeichen", "klassifizierung_name", "SHAPE@AREA"], "flurstueckskennzeichen = '{0}' AND shape_Area > 0.5".format(fsk)) as scursor:
            for row in scursor:
              qm = int(row[2] * verbesserung + 0.5)
              #print("bew-ausschluss: " + str(qm) + " qm (" + row[1] + ")")
              schaetz_afl -= int(row[2] * verbesserung + 0.5) #fraglich ob +0.5
        #print("schaetz-afl: " + str(schaetz_afl) + " qm")

    # neue Berechnung und SFL-Korrektur Voelkner 01/2023
    mini_sfl_arr = []
    sfl_sum = 0
    # for bfl in db_cursor_ff.execute("SELECT objectid, sde.st_area(shape) as area FROM sde.FSK_Bodenschaetzung_Dissolve WHERE fsk = '%s' ORDER BY area" % fsk.fsk).fetchall():
    #flaechen = [(row[0], row[1]) for row in arcpy.da.SearchCursor("fsk_bodenschaetzung", ["objectid","SHAPE@AREA"],"flurstueck='{0}'".format(fsk),sql_clause=(None, "ORDER BY shape_area"))]
    
    with arcpy.da.UpdateCursor(navigation_bodenschaetzung, ["flurstueckskennzeichen", "SHAPE@", "SHAPE@AREA","sfl", "ackerzahl", "emz", "sonstige_angaben_id"], "flurstueckskennzeichen = '{0}'".format(fsk),sql_clause=(None, "ORDER BY sde.st_area (Shape)")) as ucursor:
        for row in ucursor:
    #for bfl_id, bfl_area in flaechen:
        #print(bfl_area) 
            flurstueck = row[0]
            shape = row[1]
            area = row[2]
            sfl = row[3] 
            ackerzahl = row[4]
            sonstige = row[6]
            #print(row)      
            if area < max_shred_qm and fsk_afl > max_shred_qm * 2:   # Kleinst-Flst ausschliessen
                # with arcpy.da.UpdateCursor("fsk_bodenschaetzung", ["flurstueck", "SHAPE@"], "objectid = {0}".format(bfl_id)) as ucursor:
                #     for row in ucursor:
                    print('Bodenschaetzung: Kleinstflaeche in ' + str(flurstueck) + '('+ str(area) + ' qm) wird geloescht')
                    mini_sfl_arr.append({"a": area, "geom": shape})
                    ucursor.deleteRow()
            else:

                # with arcpy.da.UpdateCursor("fsk_bodenschaetzung", ["sfl","objectid", "SHAPE@", "ackerzahl", "emz", "sonstige_a"], "objectid = {0}".format(bfl_id)) as ucursor:
                #     for row in ucursor:

                #Bewertungsflaechen
                if sonstige == "9999":
                    qm = int((area) * verbesserung + 0.5)
                    row[3] = qm
                    #print("sfl: " + str(qm) + " qm | EMZ: " + str(row[4]))
                    ucursor.updateRow(row)
                    #print("Bewertungsflaeche upgedated")
                    continue

                #Schaetzungsflaechen
                if sfl == fsk_afl:
                    # print("sfl " + str(bfl.objectid) + ": " + str(row[0]) + " qm")
                    # print("sfl: " + str(row[0]) + "   shp_area: " + row[2].area)
                    qm = sfl
                elif len(mini_sfl_arr) > 0:
                    mini_sfl_arr_index = 0
                    adjacent_mini_sfl = 0
                    for mini_sfl in mini_sfl_arr:
                        if shape.touches(mini_sfl["geom"]):
                            adjacent_mini_sfl += mini_sfl["a"]
                            row[1] = shape.union(mini_sfl["geom"])
                            mini_sfl_arr.pop(mini_sfl_arr_index)
                        mini_sfl_arr_index += 1
                    qm = int((area + adjacent_mini_sfl) * verbesserung + 0.5)
                    # print("sfl " + str(bfl.objectid) + ": " + str(qm) + " qm + " + str(adjacent_mini_sfl))
                else:
                    qm = int((area ) * verbesserung + 0.5)
                    # print("sfl " + str(bfl.objectid) + ": " + str(qm) + " qm")
                sfl_sum += qm

                row[3] = qm
                
                #EMZ
                row[5] = int(round(qm / 100 * int(ackerzahl)))
                # print("sfl: " + str(qm) + " qm | EMZ: " + str(row[4]))
                ucursor.updateRow(row)
                #print("Schätzungsfläche upgedatet mit {0}".format(row))

    # Buchflaechen deltas eliminieren
    if schaetz_afl and not sfl_sum == schaetz_afl and sfl_sum > 0:
        #print("deltas korrigieren")
        delta = schaetz_afl - sfl_sum
        abs_delta = abs(delta)
        # print("")
        #print('delta: ' + str(delta) + " qm")
        if abs_delta < max_shred_qm:  
            
            print("zugehörige Bodenschätzungsflächen zu Flst. {0} gefunden".format(fsk))             
            rest_anteil = abs_delta
            print('delta: ' + str(delta) + " qm")
           
            for bfl in db_cursor_ff.execute("SELECT sfl, flurstueckskennzeichen, CAST(ackerzahl AS INTEGER), emz, objectid FROM sde.navigation_bodenschaetzung WHERE flurstueckskennzeichen = '%s' ORDER BY sfl DESC" % fsk).fetchall():
                print ("flst {0}, objectid {1}".format(bfl.flurstueckskennzeichen, bfl.objectid))
                sfl = bfl.sfl
                acker = bfl.ackerzahl
                #print ("Daten eingelesen: {0}, {1}".format(sfl, acker))

                print("restanteil: " + str(rest_anteil))
                if sfl < max_shred_qm:   # kleine Bewertungsflaechen
                    rest_anteil -= sfl
                elif rest_anteil > 0:
                    ratio = 1.0 if sfl > schaetz_afl else sfl / schaetz_afl
                    # print("ratio: " + repr(ratio))
                    int_anteil = math.ceil(float(abs_delta) * float(ratio))  # works different in Python 2 -> only use in Python 3
                    rest_anteil -= int_anteil

                    if delta < 0: int_anteil = int_anteil * -1

                    # print("sfl " + str(row[2]) + ": " + str(row[0]) + " qm + " + str(int_anteil))
                    sfl += int_anteil
                    #EMZ
                    emz = int(round(sfl / 100 * acker))
                    
                    #print('UPDATE CURSOR objectid {0} sfl = {1}, emz = {2} startet'.format(bfl.objectid, sfl, emz))
                    db_cursor_ff.execute('UPDATE sde.navigation_bodenschaetzung SET sfl = ?, emz = ? WHERE objectid = ?', [sfl, emz, bfl.objectid ])
                    db_con_ff.commit()
                    print("Fläche {0} angeglichen mit {1} qm". format(bfl.objectid, sfl))
                else:
                    break



try:
    #Read inputs    
    print('Subprozess wurde gestartet')
    sys.stdout.flush()
    

    gemeinde      = int(sys.argv[1])
    workspace     = sys.argv[2]

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

    with open(config_path, 'r', encoding='utf-8') as config_file:
        config = json.load(config_file)

    database_sql = config['database_connection']
    navigation_bodenschaetzung = config['orig_sde'] + os.sep + "alkis_nora.sde.navigation_bodenschaetzung"
    navigation_nutzung = config['orig_sde'] + os.sep + "alkis_nora.sde.navigation_nutzung"
    print('Inputs gelesen')

    arcpy.env.workspace = workspace   
    
    db_con_ff= pyodbc.connect(database_sql)
    pyodbc.setDecimalSeparator('.')
    db_cursor_ff =  db_con_ff.cursor()
    fsks = db_cursor_ff.execute("SELECT sde.st_area (Shape) AS area, CAST(amtliche_flaeche AS INTEGER) as afl, flurstueckskennzeichen as fsk FROM sde.v_al_flurstueck WHERE gemeinde_id = {0} ORDER BY flurstueckskennzeichen".format(gemeinde)).fetchall()
    print("Flurstücksliste afl für Gemeinde {0} erstellt".format(gemeinde))

    max_shred_qm = 5

    # Ausgabe der Ergebnisse
    for fsk in fsks:
        verbesserung = float(fsk.afl) / fsk.area
        calculateSFLNutzung(verbesserung, fsk.fsk, fsk.afl, navigation_nutzung, max_shred_qm)
        
        # count = 0
        flurstueck = fsk.fsk
        # with arcpy.da.SearchCursor("fsk_bodenschaetzung", ["objectid"], "flurstueck='{0}'".format(flurstueck)) as cursor:
        #     for row in cursor:
        #         count += 1
        # if count == 0:
        if not db_cursor_ff.execute("SELECT COUNT(objectid) FROM sde.navigation_bodenschaetzung WHERE flurstueckskennzeichen = '%s'" % flurstueck).fetchval():
            print("-> ausserhalb Schaetzungsrahmen")
            continue
          
        
        calculateSFLBoden(verbesserung, fsk.fsk, fsk.afl, max_shred_qm, db_cursor_ff, navigation_bodenschaetzung)

except Exception as e:
    print(e)
     
     

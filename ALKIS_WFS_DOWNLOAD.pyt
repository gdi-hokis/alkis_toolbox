# -*- coding: utf-8 -*-

# Copyright (c) 2025, Jana Mütsch & Jakob Scheppach, LRA Hohenlohekreis
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

from xml.etree import ElementTree as ET
import os
import json
from datetime import datetime
import time
import requests
import arcpy
import importlib
import wfs_field_calculations
import calc_lage
import calc_sfl_optimized

importlib.reload(calc_lage)
importlib.reload(calc_sfl_optimized)


# Konfigurationsparameter
config = {
    "wfs_url": "https://owsproxy.lgl-bw.de/owsproxy/wfs/WFS_LGL-BW_ALKIS",
    "params_capabilities": {"service": "WFS", "request": "GetCapabilities", "version": "2.0.0"},
    "params_feature": {"service": "WFS", "request": "GetFeature", "version": "2.0.0", "outputFormat": "json"},
    "identify_fields": ["gml_id", "gesamtschluessel"],
}
# Gesamtschlüssel für Gewanne/Straßen nötig, da es dort identische Geometrien mit anderen Bezeichnungen gibt...

# Flag, dass GetCapabilities-Aufruf in der Methode updateParameters nicht mehrmals aufgerufen wird
layers_initialized = False

# Flag, dass GetCapabilities-Aufruf in der Methode updateParameters nicht mehrmals aufgerufen wird
layers_initialized = False


class Toolbox:
    def __init__(self):
        """Define the toolbox (the name of the toolbox is the name of the
        .pyt file)."""
        self.label = "ALKIS WFS Download"
        self.alias = "ALKISWFSDownload"
        self.description = "Diese Toolbox enthält Tools für ALKIS-Datenverarbeitung: WFS-Download, Lagebezeichnungen und Flächenberechnungen"

        # List of tool classes associated with this toolbox
        self.tools = [wfs_download, calc_lage_tool, calc_sfl]


class calc_lage_tool:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Lagebezeichnungen zuordnen"
        self.description = "Verknüpft Lagebezeichnungen (Hausnummern, Straßen, Gewanne) mit Flurstücken und erstellt eine Navigation_Lage Tabelle"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Ziel-Geodatabase wählen",
            name="existing_geodatabase",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )

        param1 = arcpy.Parameter(
            displayName="Arbeitsdatenbank für temporäre Daten",
            name="workspace_database",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )

        params = [param0, param1]
        return params

    def isLicensed(self):
        """Set whether the tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal validation is performed."""
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool parameter."""
        workspace_param = parameters[0]

        if workspace_param.value:
            workspace_path = workspace_param.valueAsText
            if not workspace_path.lower().endswith(".gdb"):
                workspace_param.setErrorMessage("Bitte wählen Sie eine File-Geodatabase (.gdb) aus, kein Ordner.")
        return

    def execute(self, parameters, _messages):
        gdb_path = parameters[0].valueAsText
        work_folder = parameters[1].valueAsText

        try:
            arcpy.AddMessage(f"Starte Lagebezeichnungsberechnung für {gdb_path}")

            success = calc_lage.calculate_lage(work_folder, gdb_path)

            if success:
                arcpy.AddMessage("Lagebezeichnungsberechnung erfolgreich abgeschlossen")
            else:
                arcpy.AddError("Lagebezeichnungsberechnung fehlgeschlagen")

            return success

        except Exception as e:
            arcpy.AddError(f"Fehler bei Lagebezeichnungsberechnung: {str(e)}")
            import traceback

            arcpy.AddError(traceback.format_exc())
            return False


class calc_sfl:
    """
    ArcGIS Toolbox Tool für SFL- und EMZ-Berechnung (optimierte Version).
    """

    def __init__(self):
        self.label = "SFL & EMZ Berechnung (optimiert)"
        self.description = """
        Berechnet Schnittflächen (SFL) und Ertragsmesszahlen (EMZ) 
        mit optimierter Pandas-Vectorisierung (~5-10x schneller).
        """
        self.canRunInBackground = True

    def getParameterInfo(self):
        """Definiert die Tool-Parameter."""

        # Parameter 1: GDB Path
        param0 = arcpy.Parameter(
            displayName="Geodatabase",
            name="gdb_path",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["File Geodatabase"]

        # Parameter 2: Workspace
        param1 = arcpy.Parameter(
            displayName="Arbeitsdatenbank",
            name="workspace",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )

        # Parameter 5: Output Message
        param2 = arcpy.Parameter(
            displayName="Ergebnis",
            name="output",
            datatype="GPString",
            parameterType="Derived",
            direction="Output",
        )

        return [param0, param1, param2]

    def isLicensed(self):
        """Lizenzprüfung."""
        # Keine speziellen Extensions erforderlich
        return True

    def updateParameters(self, parameters):
        """Aktualisiere Parameter wenn sich andere Parameter ändern."""
        pass

    def updateMessages(self, parameters):
        """Validiere Parameter."""
        pass

    def execute(self, parameters, messages):
        """Hauptlogik des Tools."""

        try:
            # Parse Parameter
            gdb_path = parameters[0].valueAsText
            workspace = parameters[1].valueAsText

            arcpy.AddMessage("\n" + "=" * 70)
            arcpy.AddMessage("SFL & EMZ BERECHNUNG - OPTIMIERTE VERSION")
            arcpy.AddMessage("=" * 70)

            arcpy.AddMessage("\nStarte OPTIMIERTE Berechnung...")
            success = calc_sfl_optimized.calculate_sfl_optimized(gdb_path, workspace)

            if not success:
                arcpy.AddError("Berechnung fehlgeschlagen!")
                parameters[2].value = "✗ FEHLER"
                return

            arcpy.AddMessage("\n" + "=" * 70)
            arcpy.AddMessage("✓ BERECHNUNG ABGESCHLOSSEN")
            arcpy.AddMessage("=" * 70)

            # Output
            parameters[2].value = "✓ Erfolgreich abgeschlossen"

        except Exception as e:
            arcpy.AddError(f"Fehler: {str(e)}")
            import traceback

            arcpy.AddError(traceback.format_exc())
            parameters[2].value = f"✗ Fehler: {str(e)}"


class wfs_download:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        # Klassenvariablen anlegen
        self.label = "wfs_download"
        self.description = "Dieses Tool lädt ALKIS-Daten im definierten Bereich als GeoJSON herunter und konvertiert diese in eine FGDB"
        self.layers = []
        self.process_data = []
        self.process_fc = []
        self.url = config["wfs_url"]

    def getParameterInfo(self):
        """Define the tool parameters."""

        param0 = arcpy.Parameter(
            displayName="Bereich (nur Polygone)",
            name="in_featureset",
            datatype="GPFeatureRecordSetLayer",
            parameterType="Required",
            direction="Input",
        )

        param0.filter.list = ["Polygon"]

        param1 = arcpy.Parameter(
            displayName="Input Features",
            name="in_features",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True,
        )

        param1.filter.type = "ValueList"
        param2 = arcpy.Parameter(
            displayName="Ziel-Geodatabase wählen",
            name="existing_geodatabase",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )

        param3 = arcpy.Parameter(
            displayName="Speicherordner für JSON Download",
            name="folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )
        param4 = arcpy.Parameter(
            displayName="Verarbeitungsdaten behalten?",
            name="process_data",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        param4.value = True  # standarmäßig werden Verarbeitungsdaten behalten

        param5 = arcpy.Parameter(
            displayName="Max. BoundingBox Seitenlänge",
            name="cell_size",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        param5.value = 20000
        param5.category = "Weitere Parameter"

        param6 = arcpy.Parameter(
            displayName="Timeout", name="timeout", datatype="GPLong", parameterType="Required", direction="Input"
        )
        param6.value = 120
        param6.category = "Weitere Parameter"

        param7 = arcpy.Parameter(
            displayName="Zertifikat verifizieren",
            name="verify_certifikate",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        param7.value = True
        param7.category = "Weitere Parameter"

        params = [param0, param1, param2, param3, param4, param5, param6, param7]
        return params

    def isLicensed(self):
        """Set whether the tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""
        timeout = parameters[6].value

        # Flag, dass GetCapabilities nur bei der Initialisierung aufgerufen wird
        global layers_initialized
        if layers_initialized:
            return

        # URL des WFS-Services
        self.url = config["wfs_url"]
        params = config["params_capabilities"]

        # Capabilites (schon bei Toolaufruf) auslesen und zu Multivaluelist hinzufügen
        response = requests.get(self.url, params=params, timeout=timeout, verify=False)

        if response.status_code == 200:
            # Parste die XML-Antwort
            root = ET.fromstring(response.content)
            # Finde und logge alle verfügbaren Layer
            for layer in root.findall(".//{http://www.opengis.net/wfs/2.0}FeatureType"):
                layer_name = layer.find(".//{http://www.opengis.net/wfs/2.0}Name").text
                self.layers.append((layer_name))
            parameters[1].filter.list = self.layers
            layers_initialized = True
        else:
            parameters[1].setErrorMessage("Fehler bei GetCapabilites. WFS-Dienst nicht erreichbar…")

        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        workspace_param = parameters[2]

        # Prüfen ob Geodatabase ausgewählt wurde (bei Datentyp "DEWorkspace" theoretisch Auswahl eines Ordners möglich)
        if workspace_param.value:
            workspace_path = workspace_param.valueAsText
            # Prüfen, ob der Pfad nicht auf ".gdb" endet
            if not workspace_path.lower().endswith(".gdb"):
                workspace_param.setErrorMessage("Bitte wählen Sie eine File-Geodatabase (.gdb) aus, kein Ordner.")
        return

    def execute(self, parameters, _messages):
        """The source code of the tool."""

        # Get Parameters
        polygon_fc = parameters[0].value
        checked_layers = parameters[1].valueAsText  # semicolon separated string
        gdb_param = parameters[2].valueAsText
        arcpy.env.workspace = parameters[2].valueAsText
        work_dir = parameters[3].valueAsText
        checkbox = parameters[4].value
        cell_size = parameters[5].value
        timeout = parameters[6].value
        verify = parameters[7].value

        if timeout == 0:
            timeout = None

        req_settings = [timeout, verify]

        # Prüfen ob Layernamen des wfs geändert wurden
        layer_list = checked_layers.split(";")
        if not layer_list[0].startswith("nora:"):
            arcpy.AddMessage("!!!Achtung!!! Die Layernamen im Dienst wurden geändert. Bitte beachten!")

        arcpy.AddMessage(f"Workspace ausgewählt: {gdb_param}")
        arcpy.AddMessage(f"Layer ausgewählt: {layer_list}")

        # Schritt 1: Bounding Boxen erstellen
        grid = self.create_grid_from_polygon(polygon_fc, gdb_param, cell_size)

        # Schritt 2: Wfs im Bereich der Bounding Boxen downloaden
        self.download_wfs(grid, layer_list, gdb_param, work_dir, req_settings, polygon_fc)

        # Schritt 3: Verarbeitungsdaten wieder entfernen
        if checkbox is False:
            # Verarbeitungsdaten aus geodatabase entfernen
            for fc in self.process_fc:
                if arcpy.Exists(fc):
                    arcpy.Delete_management(fc, "")

            # Verarbeitungsdaten aus lokalem Ordner entfernen
            for json_file in self.process_data:
                os.remove(json_file)
        return

    def postExecute(self, _parameters):
        """This method takes place after outputs are processed and
        added to the display."""
        return

    def create_grid_from_polygon(self, polygon_fc, gdb, cell_size):
        """
        Erstellt ein Grid aus quadratischen Extents innerhalb eines Polygons.
        Dabei werden drei Fälle unterschieden:
        1. Wenn beide Kantenlängen (x und y) kleiner als cell_size sind,
            wird der Extent übernommen.
        2. Wenn nur eine Dimension kleiner als cell_size ist, wird in dieser Richtung
            nur eine Zelle erzeugt, in der anderen Richtung volle Zellen (cell_size)
            und ggf. eine Restzelle.
        3. Wenn beide Dimensionen größer als cell_size sind, werden volle Zellen plus
            ggf. Restzellen erzeugt.


        :param polygon_fc: Feature-Class des Eingabe-Polygons
        :param gdb: Geodatabase in die die Bounding Box gespeichert wird
        :param cell_size: Seitenlänge der vollen Zellen in Metern (Standard: 20000m)
        """

        # Spatial Reference übernehmen
        spatial_ref = arcpy.Describe(polygon_fc).spatialReference

        # Output-Feature-Class in definierter gdb neu anlegen
        fc_name = arcpy.Describe(polygon_fc).name
        if "." in fc_name:
            fc_name = fc_name.split(".")[0]
        bbox_name = fc_name + "_bbox"
        bbox_fc = os.path.join(gdb, bbox_name)

        # bei Nichtanhaken Löschen der temporären Daten
        self.process_fc.append(bbox_name)

        arcpy.management.MinimumBoundingGeometry(
            in_features=polygon_fc,
            out_feature_class=bbox_fc,
            geometry_type="ENVELOPE",
            group_option="ALL",
            group_field=None,
            mbg_fields_option="NO_MBG_FIELDS",
        )

        desc = arcpy.Describe(bbox_fc)
        extent = desc.extent
        polygon_extent = arcpy.Extent(extent.lowerLeft.X, extent.lowerLeft.Y, extent.upperRight.X, extent.upperRight.Y)

        # Extent-Koordinaten des Eingabe-Polygons
        min_x, min_y, max_x, max_y = extent.lowerLeft.X, extent.lowerLeft.Y, extent.upperRight.X, extent.upperRight.Y
        edge_x = max_x - min_x  # Kantenlängen
        edge_y = max_y - min_y

        # Liste zur Speicherung der Extents-Strings
        bboxes = []

        # Fall 1: Beide Kantenlängen kleiner als cell_size → gesamter Extent
        if edge_x < cell_size and edge_y < cell_size:
            num_x = 1
            num_y = 1

        # Fall 2 und 3
        else:
            # Ermittlung der Anzahl Zellen in X- und Y-Richtung
            if edge_x <= cell_size:
                num_x = 1
            else:
                num_x = int(edge_x // cell_size)
                if edge_x % cell_size > 0:
                    num_x += 1

            if edge_y <= cell_size:
                num_y = 1
            else:
                num_y = int(edge_y // cell_size)
                if edge_y % cell_size > 0:
                    num_y += 1

        # Grid-Zellen erzeugen und Extents als String speichern
        with arcpy.da.InsertCursor(bbox_fc, ["SHAPE@"]) as insert_cursor:
            for i in range(num_x):
                # Für alle außer des letzten Grids: cell_size, sonst Restlänge
                current_width = cell_size if i < num_x - 1 else (edge_x - i * cell_size)
                for j in range(num_y):
                    # Für alle außer des letzten Grids: cell_size, sonst Restlänge
                    current_height = cell_size if j < num_y - 1 else (edge_y - j * cell_size)
                    x1 = min_x + i * cell_size
                    y1 = min_y + j * cell_size
                    x2 = x1 + current_width
                    y2 = y1 + current_height

                    square = arcpy.Polygon(
                        arcpy.Array(
                            [
                                arcpy.Point(x1, y1),
                                arcpy.Point(x2, y1),
                                arcpy.Point(x2, y2),
                                arcpy.Point(x1, y2),
                                arcpy.Point(x1, y1),
                            ]
                        ),
                        spatial_ref,
                    )

                    # Füge die Zelle nur hinzu, wenn sie das Input-Polygon schneidet
                    # if square.overlaps(polygon_geom) or square.within(polygon_geom) or polygon_geom.contains(square):
                    if not square.disjoint(polygon_extent):
                        insert_cursor.insertRow([square])
                        # Extents-String für das aktuelle Rechteck
                        bboxes.append(f"{x1},{y1},{x2},{y2}")

        arcpy.AddMessage(
            f"Grid mit {num_x * num_y} Zellen (max. Kantenlänge {cell_size}m) erstellt und in {bbox_name} gespeichert."
        )
        return bboxes

    def download_wfs(self, grid, layer_list, gdb, work_dir, req_settings, polygon_fc):
        """
        Führt den Download von Layern vom WFS in Form von json-Dateien im durch die Bounding Boxen begrenzten Bereich durch
        und speichert diese in Feature Klassen in der übergebenen gdb

        :param grid: Feature Class des Bereichs als Rechteck(e)
        :param layer_list: Liste der zu downloadenden Layer
        :param gdb: Geodatabase in die die Bounding Box gespeichert wird
        :param work_dir: lokal ausgewählter Ordner für die json-files
        :param req_settings: Liste mit Einstellungen zum Request: [timeout(int), verify(boolean)]
        :param polygon_fc: Feature-Class des Eingabe-Polygons (zum Löschen von vollständig außerhalb liegenden Polygonen)
        """

        # Bounding Boxen
        arcpy.env.overwriteOutput = True

        # Layer downloaden
        for layer in layer_list:

            wildcards = []

            for index, bbox in enumerate(grid):
                layer_files = self.downloadJson(bbox, layer, work_dir, index, req_settings)

                if layer_files:
                    # für Filtern der Merge Feature Klassen und Benennung
                    for layer_file in layer_files:
                        wildcard = "*" + layer_file + "_*"
                        if not wildcard in wildcards:
                            wildcards.append(wildcard)

            # Merge pro Geometrietyp durchführen
            for wildcard in wildcards:
                fc = arcpy.ListFeatureClasses(wildcard)
                # Extrahiere den Ausgabename ohne Geometrietyp bei gleichen Typen
                parts = wildcard.rsplit("_", 2)
                output_fc = parts[0][1:]
                # Mit Geometrietyp
                if len(wildcards) > 1:
                    output_fc = wildcard[1:-2]

                arcpy.Merge_management(fc, output_fc)

            # Alle Felder auflisten
            fields = arcpy.ListFields(output_fc)
            field_names = [field.name for field in fields]

            identify_fields = ["Shape"]
            for identity_field in config["identify_fields"]:
                if identity_field in field_names:
                    identify_fields.append(identity_field)

            param = ";".join(identify_fields)
            arcpy.DeleteIdentical_management(output_fc, "{0}".format(param))

            arcpy.AddField_management(in_table=output_fc, field_name="Abrufdatum", field_type="DATE")

            self.shorten_string_fields(output_fc, fields)

            output_fc_2D = output_fc + "_tmp"
            arcpy.env.outputZFlag = "Disabled"
            arcpy.env.outputMFlag = "Disabled"

            arcpy.AddMessage(f"Start: FeatureClassToFeatureClass_conversion (2D-Konvertierung)...")
            fc_start = time.time()
            arcpy.FeatureClassToFeatureClass_conversion(in_features=output_fc, out_path=gdb, out_name=output_fc_2D)
            fc_time = time.time() - fc_start
            arcpy.AddMessage(f"2D-Konvertierung abgeschlossen in {fc_time:.2f} Sekunden")

            arcpy.Delete_management(output_fc)
            arcpy.Rename_management(output_fc_2D, output_fc)

            arcpy.AddMessage("Z-Werte wurden entfernt")

            self.intersect(polygon_fc, output_fc)
        # Feldberechnungen für spezifische Layer durchführen
        fc = arcpy.ListFeatureClasses()
        for output_fc in fc:
            self.perform_field_calculations(output_fc, gdb)

    def getDifferentGeometryTypes(self, json_file):
        """
        Teilt Layer mit verschiedenen Geometrietypen auf
        """
        geometry_types = []
        with open(json_file, "r", encoding="utf-8") as geojson_file:
            geojson_data = json.load(geojson_file)
            for feature in geojson_data["features"]:
                geometry_type = feature["geometry"]["type"]
                if not geometry_type in geometry_types:
                    geometry_types.append(geometry_type)
        return {"geometry_types": geometry_types, "geojson_data": geojson_data}

    def saveExtraJson(self, layer_name, geojson_data, geometry_type, work_dir):
        """
        Bei mehreren Geometrietypen werden die JSON-Daten separat gespeichert
        """
        json_data = {
            "type": "FeatureCollection",
            "features": [],
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::25832"}},
        }
        for feature in geojson_data["features"]:
            if feature["geometry"]["type"] == geometry_type:
                json_data["features"].append(feature)

        with open(work_dir + os.sep + "{0}.json".format(layer_name), "w", encoding="utf-8") as geometry_file:
            json.dump(json_data, geometry_file)

    def downloadJson(self, bbox, layer, work_dir, index, req_settings):
        """
        Führt den Download eines Rechteckes durch

        :param bbox: Bounding Box eines Rechteckes
        :param layer: zu downloadender Layer
        :param work_dir: lokal ausgewählter Ordner für die json-files
        :param index: iterieren der Dateinamen (bei mehr als einem Rechteck notwendig)
        """
        params = config["params_feature"]
        params["typename"] = layer
        params["bbox"] = bbox

        timeout = req_settings[0]
        verify = req_settings[1]

        # Request ausführen
        response = requests.get(self.url, params=params, timeout=timeout, verify=verify)

        v_al_layer = layer.replace(":", "_")  # Doppelpunkt in Dateipfad unzulässig
        layer_name = v_al_layer + "_" + str(index)

        if not response.status_code == 200:
            arcpy.AddWarning(f"Error {response.status_code}: {response.reason} beim Downloadversuch des Layers {layer}")
            return

        # Datei speichern
        json_file = work_dir + os.sep + "{0}.json".format(layer_name)
        self.process_data.append(json_file)
        with open(json_file, "wb") as f:
            f.write(response.content)

        # verschiedene Geometrietypen im JSON finden und auftrennen, wenn nötig --> v_al_vergleichsstueck
        layer_files = []
        geometry_info = self.getDifferentGeometryTypes(json_file)
        geometry_types = geometry_info["geometry_types"]
        geojson_data = geometry_info["geojson_data"]
        arcpy.AddMessage(f"Der Layer {v_al_layer} enthält folgende Geometrietypen: {geometry_types}")

        for geometry_type in geometry_types:
            layer_name_geometry = v_al_layer + "_" + geometry_type + "_" + str(index)
            if len(geometry_types) == 1:
                arcpy.JSONToFeatures_conversion(json_file, layer_name_geometry)
                layer_files.append(layer_name_geometry.rsplit("_", 1)[0])

            # in getrennte Dateien schreiben und dann erst in Feature Class konvertieren
            elif len(geometry_types) > 1:
                self.saveExtraJson(layer_name_geometry, geojson_data, geometry_type, work_dir)

                arcpy.JSONToFeatures_conversion(
                    work_dir + os.sep + "{0}.json".format(layer_name_geometry), layer_name_geometry
                )
                # Dateiname für später ohne Bounding Box Info (nötig, weil sonst der Zusatz Geometrietyp fehlt)
                layer_files.append(layer_name_geometry.rsplit("_", 1)[0])

                # Ursprünglich Downgeloadete Daten mit beiden FeatureTypes löschen, sonst Verwirrung
                arcpy.Delete_management(layer_name)

            # fügt Namen der erzeugten Feature Class einer Liste hinzu, zum Löschen (je nach Checkbox) der temporären Daten
            self.process_fc.append(layer_name_geometry)

        arcpy.AddMessage(f"Layer {v_al_layer} erfolgreich gedownloaded und als json-file in {work_dir} gespeichert")

        return layer_files

    def shorten_string_fields(self, output_fc, fields):

        # Liste für die Feldzuordnung
        field_mappings = []

        # Feldlänge der Felder mit Dateityp String von 20000000 auf 255 kürzen
        e = 0
        # neues temp-Feld anlegen und Layername zu Liste hinzufügen
        # Felder sammeln, die hinzugefügt werden sollen (nur neue Temp-Felder)
        fields_to_add = []

        for field in fields:
            if field.type == "String" and field.length > 255:
                new_field = field.name + "_temp"

                # AddFields erwartet: [name, type, precision, scale, length]
                fields_to_add.append([new_field, "TEXT", "", 255])

                # Deine bestehende Zuordnung bleibt unverändert
                field_mappings.append((field.name, new_field))

                e += 1
        if fields_to_add:
            arcpy.management.AddFields(output_fc, fields_to_add)

        if field_mappings:
            arcpy.AddMessage(f"Start: Kopiere {e} Felder mit {len(field_mappings)} Feldpaaren in {output_fc}...")

            start_time = time.time()

            cursor_fields = []
            for field, field_temp in field_mappings:
                cursor_fields.extend([field, field_temp])
            cursor_fields.append("Abrufdatum")

            row_count = 0
            with arcpy.da.UpdateCursor(output_fc, cursor_fields) as cursor:
                for row in cursor:
                    # Für jedes Paar (new_field, old_field) wird der Wert vom alten in das neue Feld kopiert.
                    for i in range(0, len(cursor_fields) - 1, 2):
                        row[i + 1] = row[i]
                    row[-1] = datetime.now()
                    cursor.updateRow(row)
                    row_count += 1

            cursor_time = time.time() - start_time
            arcpy.AddMessage(
                f"UpdateCursor abgeschlossen: {row_count} Zeilen in {cursor_time:.2f} Sekunden ({row_count/cursor_time:.0f} Zeilen/Sek)"
            )

            # alte Felder löschen, temp-Felder umbenennen
            arcpy.AddMessage(f"Start: Lösche alte Felder und benenne {e} Felder um...")
            delete_start = time.time()

            # alte Felder löschen, temp-Felder umbenennen
            fields_to_delete = [field for field, _ in field_mappings]
            arcpy.DeleteField_management(output_fc, ";".join(fields_to_delete))  # EINE Operation!

            # Dann umbenennen (leider muss das einzeln, aber schneller weil FC kleiner):
            for field, field_temp in field_mappings:
                arcpy.AlterField_management(output_fc, field_temp, new_field_name=field)

            delete_time = time.time() - delete_start
            arcpy.AddMessage(f"Feldoperationen abgeschlossen in {delete_time:.2f} Sekunden")

    def perform_field_calculations(self, output_fc, gdb):
        """
        Führt spezifische Feldberechnungen für die heruntergeladenen Layer durch.
        Behandelt:
        - v_al_flurstueck: Flurnummer-ID, FSK, FLSTKEY, locator_place
        - v_al_bodenschaetzung_f: Label-Beschriftung
        - v_al_gebaeude: object_id UUID

        :param output_fc: Name der Feature Class
        :param gdb: Geodatabase-Pfad
        """
        try:
            output_fc_path = os.path.join(gdb, output_fc)

            # Flurstücke - Feldberechnungen
            if output_fc == "nora_v_al_flurstueck":
                arcpy.AddMessage("Starte Feldberechnungen für Flurstücke...")

                # Flurnummer-Berechnung benötigt auch v_al_flur
                if arcpy.Exists(os.path.join(gdb, "nora_v_al_flur")):
                    flur_fc_path = os.path.join(gdb, "nora_v_al_flur")
                    wfs_field_calculations.calculate_flurnummer_l(flur_fc_path, output_fc_path)
                    wfs_field_calculations.join_flurnamen(output_fc_path, flur_fc_path)
                    wfs_field_calculations.calculate_locator_place(output_fc_path)
                    wfs_field_calculations.clean_up_flur_fields(flur_fc_path)

                # FSK und FLSTKEY
                wfs_field_calculations.calculate_fsk(output_fc_path)
                wfs_field_calculations.calculate_flstkey(output_fc_path)
                arcpy.AddMessage("Feldberechnungen für Flurstücke abgeschlossen")

            # Bodenschätzung - Label-Berechnung
            elif output_fc == "nora_v_al_bodenschaetzung_f":
                arcpy.AddMessage("Starte Feldberechnungen für Bodenschätzung...")
                wfs_field_calculations.calculate_label_bodensch(output_fc_path)
                arcpy.AddMessage("Feldberechnungen für Bodenschätzung abgeschlossen")

            # Gebäude - object_id Generierung
            elif output_fc == "nora_v_al_gebaeude":
                arcpy.AddMessage("Starte Feldberechnungen für Gebäude...")
                wfs_field_calculations.calculate_gebaeude_object_id(output_fc_path)
                arcpy.AddMessage("Feldberechnungen für Gebäude abgeschlossen")

        except Exception as e:
            arcpy.AddWarning(f"Feldberechnungen für {output_fc} konnten nicht durchgeführt werden: {str(e)}")

    def intersect(self, polygon_fc, output_fc):
        """
        Löscht alle Polygone des outputs des wfs, die vollständig außerhalb des Eingabe-Fensters liegen
        (Aufgrund des Abrufs der wfs-Daten mit der Bounding-Box wird in der Regel deutlich über den Eingabe-Bereich abgerufen und gedownloaded)

        :param polygon_fc: Feature-Class des Eingabe-Polygons
        :param output_fc: Feature-Class des Downloads des WFS
        """
        input_lyr = "lyr_input_tmp"
        arcpy.MakeFeatureLayer_management(polygon_fc, input_lyr)
        output_lyr = "lyr_output_tmp"
        arcpy.MakeFeatureLayer_management(output_fc, output_lyr)

        arcpy.SelectLayerByLocation_management(
            in_layer=output_lyr,
            overlap_type="INTERSECT",
            select_features=input_lyr,
            selection_type="NEW_SELECTION",
            invert_spatial_relationship="INVERT",
        )

        arcpy.DeleteFeatures_management(output_lyr)
        arcpy.Delete_management(input_lyr)
        arcpy.Delete_management(output_lyr)

        arcpy.AddMessage(
            f"Abgerufene Daten des WFS-Dienstes, die vollständig außerhalb von {polygon_fc} liegen, wurden entfernt."
        )

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
import requests
import arcpy
import importlib
import config.config_loader
import wfs.download

# Konfigurationsparameter
cfg = config.config_loader.FieldConfigLoader.load_config()

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
        self.tools = [
            wfs_download,
            calc_flurnummer_id,
            calc_locator_place,
            join_flurnamen,
            calc_fsk,
            calc_flstkey,
            calc_gebaeude_id,
            calc_bodenschaetzung_label,
        ]


class wfs_download:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        # Klassenvariablen anlegen
        self.label = "1. WFS-Daten herunterladen"
        self.description = "Dieses Tool lädt ALKIS-Daten im definierten Bereich als GeoJSON herunter und konvertiert diese in eine FGDB"
        self.layers = []

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
            name="target_geodatabase",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        param2.filter.list = ["File Geodatabase"]

        param3 = arcpy.Parameter(
            displayName="Geodatabase für temporäre Arbeitsdaten",
            name="workspace_database",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        param3.filter.list = ["File Geodatabase"]

        param4 = arcpy.Parameter(
            displayName="Speicherordner für JSON Download",
            name="folder",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input",
        )

        param5 = arcpy.Parameter(
            displayName="Verarbeitungsdaten behalten?",
            name="process_data",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input",
        )
        param5.value = True  # standarmäßig werden Verarbeitungsdaten behalten

        param6 = arcpy.Parameter(
            displayName="Max. BoundingBox Seitenlänge",
            name="cell_size",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        param6.value = 20000
        param6.category = "Weitere Parameter"

        param7 = arcpy.Parameter(
            displayName="Timeout", name="timeout", datatype="GPLong", parameterType="Required", direction="Input"
        )
        param7.value = 120
        param7.category = "Weitere Parameter"

        param8 = arcpy.Parameter(
            displayName="Zertifikat verifizieren",
            name="verify_certifikate",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        param8.value = True
        param8.category = "Weitere Parameter"

        params = [param0, param1, param2, param3, param4, param5, param6, param7, param8]
        return params

    def isLicensed(self):
        """Set whether the tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""
        timeout = parameters[7].value

        # Flag, dass GetCapabilities nur bei der Initialisierung aufgerufen wird
        global layers_initialized
        if layers_initialized:
            return

        # URL des WFS-Services
        url = cfg["wfs_config"]["wfs_url"]
        params = cfg["wfs_config"]["params_capabilities"]
        parameters[0].value = url

        # Capabilites (schon bei Toolaufruf) auslesen und zu Multivaluelist hinzufügen
        response = requests.get(url, params=params, timeout=timeout, verify=False)

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
        return

    def execute(self, parameters, _messages):
        """The source code of the tool."""
        importlib.reload(config.config_loader)
        importlib.reload(wfs.download)

        # Get Parameters
        polygon_fc = parameters[0].value
        checked_layers = parameters[1].valueAsText  # semicolon separated string
        target_gdb = parameters[2].valueAsText
        workspace_gdb = parameters[3].valueAsText
        work_dir = parameters[4].valueAsText
        checkbox = parameters[5].value
        cell_size = parameters[6].value
        timeout = parameters[7].value
        verify = parameters[8].value
        wfs.download.wfs_download(
            polygon_fc, checked_layers, target_gdb, workspace_gdb, work_dir, checkbox, cell_size, timeout, verify, cfg
        )

        return

    def postExecute(self, _parameters):
        """This method takes place after outputs are processed and
        added to the display."""
        return


class calc_flurnummer_id:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Flurnummer-ID berechnen"
        self.description = "Flurnummer-ID für Flurstücke oder Fluren berechnen"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Feature Class der Flurstücke oder Fluren",
            name="in_fc",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]

        params = [param0]
        return params

    def execute(self, parameters, _messages):
        import wfs.field_calculations

        fc_layer = parameters[0].value

        wfs.field_calculations.calculate_flurnummer_l(fc_layer)


class calc_locator_place:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Locator Place für Flurstücke berechnen"
        self.description = "Berechnet den Locator Place für ALKIS-Flurstücke"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Feature Class der Flurstücke",
            name="in_flst",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]
        params = [param0]
        return params

    def execute(self, parameters, _messages):
        import wfs.field_calculations

        flst_layer = parameters[0].value
        wfs.field_calculations.calculate_locator_place(flst_layer)


class join_flurnamen:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Flurnamen zu Flurstücken zuordnen"
        self.description = "Führt einen Join der Flurnamen zu den Flurstücken durch"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Feature Class der Flurstücke",
            name="in_flst",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]

        param1 = arcpy.Parameter(
            displayName="Feature Class der Flurnamen",
            name="in_flurnamen",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param1.filter.list = ["Polygon"]

        params = [param0, param1]
        return params

    def execute(self, parameters, _messages):
        import wfs.field_calculations

        flst_layer = parameters[0].value
        flurnamen_layer = parameters[1].value

        wfs.field_calculations.join_flurnamen(flst_layer, flurnamen_layer)


class calc_fsk:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "FSK für Flurstücke berechnen"
        self.description = "Berechnet FSK für ALKIS-Flurstücke"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Feature Class der Flurstücke",
            name="in_flst",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]
        params = [param0]
        return params

    def execute(self, parameters, _messages):
        import wfs.field_calculations

        flst_layer = parameters[0].value
        wfs.field_calculations.calculate_fsk(flst_layer)


class calc_flstkey:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "FLSTKEY für Flurstücke berechnen"
        self.description = "Berechnet FLSTKEY für ALKIS-Flurstücke"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Feature Class der Flurstücke",
            name="in_flst",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]
        params = [param0]
        return params

    def execute(self, parameters, _messages):
        import wfs.field_calculations

        flst_layer = parameters[0].value
        wfs.field_calculations.calculate_flstkey(flst_layer)


class calc_gebaeude_id:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Gebäude-ID für Gebäude berechnen"
        self.description = "Berechnet die Gebäude-ID für ALKIS-Gebäude"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Feature Class der Gebäude",
            name="in_geb",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]
        params = [param0]
        return params

    def execute(self, parameters, _messages):
        import wfs.field_calculations

        gebaeude_layer = parameters[0].value
        wfs.field_calculations.calculate_gebaeude_object_id(gebaeude_layer)


class calc_bodenschaetzung_label:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Lagebeschriftung Bodenschätzung berechnen"
        self.description = "Berechnet die Lagebeschriftung Bodenschätzung"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Feature Class der Bodenschätzung",
            name="in_bodensch",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]
        params = [param0]
        return params

    def execute(self, parameters, _messages):
        import wfs.field_calculations

        bodensch_layer = parameters[0].value
        wfs.field_calculations.calculate_label_bodensch(bodensch_layer)

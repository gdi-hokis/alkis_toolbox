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
            import calc_lage

            importlib.reload(calc_lage)
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
            import calc_sfl_optimized

            importlib.reload(calc_sfl_optimized)
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
        self.label = "1. wfs_download"
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

        wfs.download.wfs_download(polygon_fc, checked_layers, gdb_param, work_dir, checkbox, cell_size, timeout, verify, cfg)

        return

    def postExecute(self, _parameters):
        """This method takes place after outputs are processed and
        added to the display."""
        return

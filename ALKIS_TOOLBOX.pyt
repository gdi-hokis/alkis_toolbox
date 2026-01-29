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
import importlib
import requests
import arcpy

import config.config_loader
import wfs.download

import utils

importlib.reload(utils)
importlib.reload(config.config_loader)


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
        self.label = "ALKIS Toolbox"
        self.alias = "ALKISToolbox"
        self.description = "Diese Toolbox enthält Tools für ALKIS-Datenverarbeitung: WFS-Download, Lagebezeichnungen, Flächenberechnungen, Beschriftungen und weitere Feldberechnungen"

        # List of tool classes associated with this toolbox
        self.tools = [
            WfsDownload,
            CalcLage,
            CalcSflNutzung,
            CalcSflBodenschaetzung,
            ExtractVnFromNas,
            CalcFlurId,
            CalcLocatorPlace,
            JoinFlurnamen,
            CalcFSK,
            CalcFLSTKEY,
            CalcBodenschaetzungLabel,
        ]


class WfsDownload:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        # Klassenvariablen anlegen
        self.label = "WFS-Daten herunterladen"
        self.description = "Dieses Tool lädt ALKIS-Daten im definierten Bereich als GeoJSON herunter und konvertiert diese in eine FGDB"
        self.layers = []
        self.category = "Download (WFS)"

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
            displayName="Arbeitsdatenbank für temporäre Daten",
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
        param5.value = False

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
        if not layers_initialized:

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

        if parameters[1].valueAsText and parameters[2].valueAsText:
            layers = [layer.replace(":", "_") for layer in parameters[1].valueAsText.split(";")]
            utils.warn_overwriting_existing_layers(parameters[2], layers)

        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        if parameters[1].valueAsText and parameters[2].valueAsText:
            layers = [layer.replace(":", "_") for layer in parameters[1].valueAsText.split(";")]
            utils.warn_overwriting_existing_layers(parameters[2], layers)
        return

    def execute(self, parameters, _messages):
        """The source code of the tool."""
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


class CalcFlurId:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Flurstücke / Fluren: Flur-ID berechnen"
        self.description = "Flurstücke/ Fluren: Flur-ID berechnen"
        self.category = "Feldberechnungen"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Flurstücke oder Fluren",
            name="in_fc",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]

        params = [param0]
        return params

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        if parameters[0].valueAsText:
            utils.check_required_fields(
                parameters[0], [cfg["flurstueck"]["gemarkung_id"], cfg["flurstueck"]["flurnummer"]]
            )
        return

    def execute(self, parameters, _messages):
        import fields.calculations

        fc_layer = parameters[0].value

        fields.calculations.calculate_flur_id(cfg, fc_layer)


class CalcLocatorPlace:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Flurstücke: Ortsnamen (locator_place) berechnen"
        self.description = "Berechnet einen Ortsnamen für ALKIS-Flurstücke"
        self.category = "Feldberechnungen"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Flurstücke",
            name="in_flst",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]
        params = [param0]
        return params

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        if parameters[0].valueAsText:
            utils.check_required_fields(parameters[0], [cfg["flurstueck"]["gemarkung_name"], cfg["flur"]["flurname"]])
        return

    def execute(self, parameters, _messages):
        import fields.calculations

        flst_layer = parameters[0].value
        fields.calculations.calculate_locator_place(cfg, flst_layer)


class JoinFlurnamen:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Flurstücke: Flurnamen zuordnen"
        self.description = "Führt einen Join der Flurnamen zu den Flurstücken durch"
        self.category = "Feldberechnungen"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Flurstücke",
            name="in_flst",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]

        param1 = arcpy.Parameter(
            displayName="Fluren",
            name="in_flurnamen",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param1.filter.list = ["Polygon"]

        param2 = arcpy.Parameter(
            displayName="Flur-ID nach JOIN löschen?",
            name="delete_flur_id",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        param2.value = True
        params = [param0, param1, param2]
        return params

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        if parameters[0].valueAsText:
            utils.check_existing_fields(parameters[0], cfg["flur"]["flurname"])
        return

    def execute(self, parameters, _messages):
        import fields.calculations

        importlib.reload(fields.calculations)

        flst_layer = parameters[0].value
        flurnamen_layer = parameters[1].value
        delete_flur_id = parameters[2].value

        fields.calculations.join_flurnamen(cfg, flst_layer, flurnamen_layer, delete_flur_id)


class CalcFSK:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Flurstücke: FSK berechnen"
        self.description = "Berechnet FSK (ohne Folgennummer) für ALKIS-Flurstücke"
        self.category = "Feldberechnungen"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Flurstücke",
            name="in_flst",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]
        params = [param0]
        return params

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        if parameters[0].valueAsText:
            utils.check_required_fields(parameters[0], [cfg["flurstueck"]["flurstueckskennzeichen"]])
        return

    def execute(self, parameters, _messages):
        import fields.calculations

        importlib.reload(fields.calculations)
        flst_layer = parameters[0].value
        fields.calculations.calculate_fsk(cfg, flst_layer)


class CalcFLSTKEY:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Flurstücke: FLSTKEY berechnen"
        self.description = "Berechnet FLSTKEY für ALKIS-Flurstücke"
        self.category = "Feldberechnungen"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Flurstücke",
            name="in_flst",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]
        params = [param0]
        return params

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        if parameters[0].valueAsText:
            utils.check_required_fields(
                parameters[0],
                [
                    cfg["flurstueck"]["gemarkung_id"],
                    cfg["flurstueck"]["flurnummer"],
                    cfg["flurstueck"]["flurstueckstext"],
                ],
            )
        return

    def execute(self, parameters, _messages):
        import fields.calculations

        flst_layer = parameters[0].value
        fields.calculations.calculate_flstkey(cfg, flst_layer)


class CalcBodenschaetzungLabel:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Bodenschätzung: Beschriftung (Label) berechnen"
        self.description = "Berechnet die Beschriftung pro Bodenschätzungsfläche"
        self.category = "Feldberechnungen"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Bodenschätzungsflächen",
            name="in_bodensch",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Polygon"]
        params = [param0]
        return params

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        if parameters[0].valueAsText:
            utils.check_required_fields(
                parameters[0],
                [
                    cfg["bodenschaetzung"]["bodenart_name"],
                    cfg["bodenschaetzung"]["nutzungsart_name"],
                    cfg["bodenschaetzung"]["entstehung_name"],
                    cfg["bodenschaetzung"]["klima_name"],
                    cfg["bodenschaetzung"]["wasser_name"],
                    cfg["bodenschaetzung"]["bodenstufe_name"],
                    cfg["bodenschaetzung"]["zustand_name"],
                    cfg["bodenschaetzung"]["sonstige_angaben_name"],
                    cfg["bodenschaetzung"]["bodenzahl"],
                    cfg["bodenschaetzung"]["ackerzahl"],
                ],
            )
        return

    def execute(self, parameters, _messages):
        import fields.calculations

        importlib.reload(fields.calculations)
        bodensch_layer = parameters[0].value
        fields.calculations.calculate_label_bodensch(cfg, bodensch_layer)


class CalcLage:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Verschnitt Flurstück & Lagebezeichnung"
        self.description = "Verknüpft Lagebezeichnungen (Hausnummern, Straßen, Gewanne) mit Flurstücken und erstellt eine fsk_x_lage Tabelle"
        self.category = "Flurstücks-Verschnitte"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="Ziel-Geodatabase wählen",
            name="existing_geodatabase",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["File Geodatabase"]

        param1 = arcpy.Parameter(
            displayName="Arbeitsdatenbank für temporäre Daten",
            name="workspace_database",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        param1.filter.list = ["File Geodatabase"]

        param2 = arcpy.Parameter(
            displayName="Verarbeitungsdaten behalten?",
            name="keep_work_data",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        param2.value = False

        param3 = arcpy.Parameter(
            displayName="Mit Geometrie speichern?",
            name="save_fc",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        param3.value = False

        params = [param0, param1, param2, param3]
        return params

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool parameter."""
        utils.warn_overwriting_existing_layers(parameters[0], "fsk_x_lage")
        layers = cfg["alkis_layers"]
        utils.check_required_layers(
            parameters[0],
            [layers["flurstueck"], layers["lagebezeichnung"], layers["strasse_gewann"], layers["gebaeude"]],
        )

    def execute(self, parameters, _messages):
        gdb_path = parameters[0].valueAsText
        work_folder = parameters[1].valueAsText
        keep_workdata = parameters[2].value
        save_fc = parameters[3].value

        try:
            import lage.calc_lage

            importlib.reload(lage.calc_lage)
            success = lage.calc_lage.calculate_lage(cfg, work_folder, gdb_path, keep_workdata, save_fc)

            if not success:
                return False

        except Exception as e:
            arcpy.AddError(f"Fehler beim Aufruf des Werkzeugs Verschnitt Flurstück & Lagebezeichnung: {str(e)}")
            return False


class CalcSflBodenschaetzung:
    def __init__(self):
        self.label = "Verschnitt Flurstück & Bodenschätzung"
        self.description = """
        Berechnet Schnittflächen (SFL) und Ertragsmesszahlen (EMZ) von den Flurstücken mit der Bodenschätzung und Bodenschätzungsbewertung.
        """
        self.canRunInBackground = True
        self.category = "Flurstücks-Verschnitte"

    def getParameterInfo(self):
        """Definiert die Tool-Parameter."""

        # Parameter 1: GDB Path
        param0 = arcpy.Parameter(
            displayName="Ziel-Geodatabase wählen",
            name="gdb_path",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["File Geodatabase"]

        # Parameter 2: Workspace
        param1 = arcpy.Parameter(
            displayName="Arbeitsdatenbank für temporäre Daten",
            name="workspace",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        param1.filter.list = ["File Geodatabase"]

        param2 = arcpy.Parameter(
            displayName="Verarbeitungsdaten behalten?",
            name="keep_work_data",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        param2.value = False

        param3 = arcpy.Parameter(
            displayName="XY-Toleranz für Überschneidungen",
            name="xy_tolerance",
            datatype="GPLinearUnit",
            parameterType="Required",
            direction="Input",
        )
        param3.value = "0.005 Meters"
        param3.category = "Schwellenwerte Kleinstflächen"

        param4 = arcpy.Parameter(
            displayName="größter erlaubter Flächenformindex",
            name="flaechenformindex",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        param4.value = 40
        param4.category = "Schwellenwerte Kleinstflächen"

        param5 = arcpy.Parameter(
            displayName="Kleinstflächenprüfung ab... (m² - Ganzzahl)",
            name="max_shred_area",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input",
        )
        param5.value = 5
        param5.category = "Schwellenwerte Kleinstflächen"

        param6 = arcpy.Parameter(
            displayName="Verschmelzen ohne Flächenformprüfung bis... (m² - Ganzzahl)",
            name="merge_area",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        param6.value = 2
        param6.category = "Schwellenwerte Kleinstflächen"

        param7 = arcpy.Parameter(
            displayName="Komplett löschen ohne Prüfung bis... (m² - Dezimalzahl)",
            name="delete_area",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input",
        )
        param7.value = 0.1
        param7.category = "Schwellenwerte Kleinstflächen"

        param8 = arcpy.Parameter(
            displayName="Nicht gemergte Kleinstflächen löschen?",
            name="delete_not_merged_mini",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        param8.value = True
        param8.category = "Schwellenwerte Kleinstflächen"

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8]

    def updateMessages(self, parameters):
        """Validiere Parameter."""
        utils.warn_overwriting_existing_layers(parameters[0], "fsk_x_bodenschaetzung")
        layers = cfg["alkis_layers"]
        utils.check_required_layers(
            parameters[0],
            [layers["flurstueck"], layers["bodenschaetzung"], layers["bewertung"], "fsk_x_nutzung"],
        )

    def execute(self, parameters, messages):
        """Hauptlogik des Tools."""

        try:
            import sfl.calc_sfl_bodenschaetzung

            importlib.reload(sfl.calc_sfl_bodenschaetzung)
            # Parse Parameter
            gdb_path = parameters[0].valueAsText
            workspace = parameters[1].valueAsText
            keep_workdata = parameters[2].value
            flaechenformindex = parameters[4].value
            max_shred_area = parameters[5].value
            min_merge_area = parameters[6].value
            max_delete_area = parameters[7].value
            delete_not_merged_minis = parameters[8].value
            xy_tolerance = parameters[3].valueAsText

            success = sfl.calc_sfl_bodenschaetzung.calculate_sfl_bodenschaetzung(
                cfg,
                gdb_path,
                workspace,
                keep_workdata,
                flaechenformindex,
                max_shred_area,
                min_merge_area,
                delete_not_merged_minis,
                max_delete_area,
                xy_tolerance,
            )

            if not success:
                return False

        except Exception as e:
            arcpy.AddError(f"Fehler: {str(e)}")


class CalcSflNutzung:
    def __init__(self):
        self.label = "Verschnitt Flurstück & Nutzung"
        self.description = """
        Berechnet Schnittflächen (SFL) von den Flurstücken mit der tatsächlichen Nutzung.
        """
        self.canRunInBackground = True
        self.category = "Flurstücks-Verschnitte"

    def getParameterInfo(self):
        """Definiert die Tool-Parameter."""

        # Parameter 1: GDB Path
        param0 = arcpy.Parameter(
            displayName="Ziel-Geodatabase wählen",
            name="gdb_path",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["File Geodatabase"]

        # Parameter 2: Workspace
        param1 = arcpy.Parameter(
            displayName="Arbeitsdatenbank für temporäre Daten",
            name="workspace",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        param1.filter.list = ["File Geodatabase"]

        param2 = arcpy.Parameter(
            displayName="Verarbeitungsdaten behalten?",
            name="keep_work_data",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        param2.value = False

        param3 = arcpy.Parameter(
            displayName="XY-Toleranz für Überschneidungen",
            name="xy_tolerance",
            datatype="GPLinearUnit",
            parameterType="Required",
            direction="Input",
        )
        param3.value = "0.001 Meters"
        param3.category = "Schwellenwerte Kleinstflächen"

        param4 = arcpy.Parameter(
            displayName="größter erlaubter Flächenformindex",
            name="flaechenformindex",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        param4.value = 40
        param4.category = "Schwellenwerte Kleinstflächen"

        param5 = arcpy.Parameter(
            displayName="Kleinstflächenprüfung ab... (m² - Ganzzahl)",
            name="max_shred_area",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input",
        )
        param5.value = 5
        param5.category = "Schwellenwerte Kleinstflächen"

        param6 = arcpy.Parameter(
            displayName="Verschmelzen ohne Flächenformprüfung bis... (m² - Ganzzahl)",
            name="merge_area",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        param6.value = 1
        param6.category = "Schwellenwerte Kleinstflächen"

        param7 = arcpy.Parameter(
            displayName="Komplett löschen ohne Prüfung bis... (m² - Dezimalzahl)",
            name="delete_area",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input",
        )
        param7.value = 0.1
        param7.category = "Schwellenwerte Kleinstflächen"

        param8 = arcpy.Parameter(
            displayName="Nicht gemergte Kleinstflächen löschen?",
            name="delete_not_merged_mini",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        param8.value = True
        param8.category = "Schwellenwerte Kleinstflächen"

        return [param0, param1, param2, param3, param4, param5, param6, param7, param8]

    def updateMessages(self, parameters):
        """Validiere Parameter."""
        utils.warn_overwriting_existing_layers(parameters[0], "fsk_x_nutzung")
        layers = cfg["alkis_layers"]
        utils.check_required_layers(parameters[0], [layers["flurstueck"], layers["nutzung"]])

    def execute(self, parameters, messages):
        """Hauptlogik des Tools."""

        try:
            import sfl.calc_sfl_nutzung

            importlib.reload(sfl.calc_sfl_nutzung)
            # Parse Parameter
            gdb_path = parameters[0].valueAsText
            workspace = parameters[1].valueAsText
            keep_workdata = parameters[2].value
            xy_tolerance = parameters[3].valueAsText
            flaechenformindex = parameters[4].value
            max_shred_area = parameters[5].value
            merge_area = parameters[6].value
            delete_area = parameters[7].value
            not_merged_mini_delete = parameters[8].value

            success = sfl.calc_sfl_nutzung.calculate_sfl_nutzung(
                cfg,
                gdb_path,
                workspace,
                keep_workdata,
                flaechenformindex,
                max_shred_area,
                merge_area,
                not_merged_mini_delete,
                delete_area,
                xy_tolerance,
            )

            if not success:
                return False

        except Exception as e:
            arcpy.AddError(f"Fehler beim Einlesen des Werkzeugs Verschnitt Flurstück & Nutzung: {str(e)}")


class ExtractVnFromNas:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Veränderungsnummern aus NAS auslesen"
        self.description = "Liest die Veränderungsnummern von Flurstücken und Gebäuden aus den NAS-Dateien aus und speichert diese in zwei Tabellen."
        self.category = "NAS-Verarbeitungen"

    def getParameterInfo(self):
        """Define the tool parameters."""
        param0 = arcpy.Parameter(
            displayName="NAS-Verzeichnis",
            name="nas_folder",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        param0.filter.list = ["Folder"]

        param1 = arcpy.Parameter(
            displayName="Ausgabeworkspace (GDB oder Ordner)",
            name="output_workspace",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )

        param2 = arcpy.Parameter(
            displayName="Arbeitsordner für temporäre Daten",
            name="workspace",
            datatype="DEWorkspace",
            parameterType="Required",
            direction="Input",
        )
        param2.filter.list = ["Folder"]

        param3 = arcpy.Parameter(
            displayName="Verarbeitungsdaten behalten?",
            name="keep_work_data",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        param3.value = False

        params = [param0, param1, param2, param3]
        return params

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool parameter."""
        utils.warn_overwriting_existing_layers(parameters[1], ["fsk_x_vn", "geb_x_vn"])

    def execute(self, parameters, _messages):
        nas_path = parameters[0].valueAsText
        output_workspace = parameters[1].valueAsText
        work_folder = parameters[2].valueAsText
        keep_workdata = parameters[3].value
        import vn.extract_vn

        importlib.reload(vn.extract_vn)

        try:
            success = vn.extract_vn.extract_vn(cfg, nas_path, output_workspace, work_folder, keep_workdata)

            if not success:
                return False

        except Exception as e:
            arcpy.AddError(f"Fehler beim Aufruf des Werkzeugs Veränderungsnummern aus NAS auslesen: {str(e)}")
            return False

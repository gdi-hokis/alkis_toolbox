import xml.etree.ElementTree as ET
import csv, os, arcpy
from utils import add_step_message


def extract_xml_data(ax_objekt, namespaces):
    veraenderungsnummer = ax_objekt.find(
        ".zeigtAufExternes/AA_Fachdatenverbindung/fachdatenobjekt/AA_Fachdatenobjekt/name", namespaces
    )

    #     <zeigtAufExternes>
    #      <AA_Fachdatenverbindung>
    #        <art>urn:bw:fdv:1000</art>
    #        <fachdatenobjekt>
    #          <AA_Fachdatenobjekt>
    #            <name>0300201900016V</name>
    #          </AA_Fachdatenobjekt>
    #        </fachdatenobjekt>
    #      </AA_Fachdatenverbindung>
    #    </zeigtAufExternes>

    if veraenderungsnummer is not None:
        veraenderungsnummern = veraenderungsnummer.text.split(";")
        benoetigte_nummern = set()
        for vn in veraenderungsnummern:
            if vn[-1] in ("F", "V"):
                benoetigte_nummern.add(vn)

        veraenderungsnummern_ausgabe = "|".join(benoetigte_nummern)
        return veraenderungsnummern_ausgabe


# Daten in ALKIS sde überschreiben
def finalize_results(database, flurstueck_vn_csv, gebaeude_vn_csv, keep_workdata):
    arcpy.env.workspace = database
    if arcpy.Exists("geb_x_vn"):
        arcpy.TruncateTable_management(database + os.sep + "geb_x_vn")
        arcpy.Append_management(
            gebaeude_vn_csv, database + os.sep + "geb_x_vn", "TEST", update_geometry="NOT_UPDATE_GEOMETRY"
        )
    else:
        arcpy.CopyRows_management(gebaeude_vn_csv, database + os.sep + "geb_x_vn")
    if arcpy.Exists("fsk_x_vn"):
        arcpy.TruncateTable_management(database + os.sep + "fsk_x_vn")
        arcpy.Append_management(
            flurstueck_vn_csv, database + os.sep + "fsk_x_vn", "TEST", update_geometry="NOT_UPDATE_GEOMETRY"
        )
    else:
        arcpy.CopyRows_management(flurstueck_vn_csv, database + os.sep + "fsk_x_vn")

    if not keep_workdata:
        add_step_message("CLEANUP: Lösche temporäre CSV-Dateien")
        os.remove(flurstueck_vn_csv)
        os.remove(gebaeude_vn_csv)


def extract_vn(cfg, nas_folder, output_workspace, scratch_folder, keep_workdata):
    try:
        save_in_gdb = ".gdb" in output_workspace.lower()
        total_steps = 3

        if not save_in_gdb:
            scratch_folder = output_workspace
            total_steps = 3

        flurstueck_vn_csv = scratch_folder + os.sep + "fsk_x_vn.csv"  # Pfad zur Ausgabe-CSV-Datei
        gebaeude_vn_csv = scratch_folder + os.sep + "geb_x_vn.csv"  # Pfad zur Ausgabe-CSV-Datei

        namespaces = cfg["nas"]["namespaces"]
        gml_namespace = cfg["nas"]["namespaces"]["gml"]

        # XML-Datei einlesen und analysieren
        add_step_message("Erstelle leere CSV-Dateien", 1, total_steps)
        with open(flurstueck_vn_csv, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["gmlid", "veraenderungsnummer", "fsk"])

        with open(gebaeude_vn_csv, mode="w", newline="", encoding="utf-8") as csv_file_geb:
            writer = csv.writer(csv_file_geb)
            writer.writerow(["gmlid", "veraenderungsnummer"])

        add_step_message("Extrahiere VN aus NAS-Dateien", 2, total_steps)
        for nas_file in os.listdir(nas_folder):
            if nas_file.endswith(".xml"):  # Nur XML-Dateien verarbeiten
                data = []
                geb_data = []
                nas_file_path = os.path.join(nas_folder, nas_file)
                arcpy.AddMessage(f"- Verarbeite {nas_file}...")

                tree = ET.parse(nas_file_path)
                root = tree.getroot()

                # Gleiche Suche für AX_Gebaeude(falls enthalten)
                for geb_element in root.findall(".//adv:AX_Gebaeude", namespaces):
                    gml_id = geb_element.get(f"{{{gml_namespace}}}id")
                    veraenderungsnummern_ausgabe = extract_xml_data(geb_element, namespaces)

                    if gml_id and veraenderungsnummern_ausgabe:
                        geb_data.append([gml_id, veraenderungsnummern_ausgabe])

                # Gleiche Suche für AX_Flurstueck (falls enthalten)
                for flst_element in root.findall(".//adv:AX_Flurstueck", namespaces):
                    gml_id = flst_element.get(f"{{{gml_namespace}}}id")
                    flst_kennzeichen = flst_element.find(".flurstueckskennzeichen", namespaces).text
                    veraenderungsnummern_ausgabe = extract_xml_data(flst_element, namespaces)

                    if gml_id and veraenderungsnummern_ausgabe:
                        data.append([gml_id, veraenderungsnummern_ausgabe, flst_kennzeichen[:-2]])

                # Schreibe die gesammelten Daten einmalig in die CSV-Datei
                arcpy.AddMessage(
                    f"- Anhängen der Gemarkungsergebnisse an die bestehende CSV: {len(data)} Flurstücke mit Veränderungsnummern und {len(geb_data)} Gebäude..."
                )
                with open(flurstueck_vn_csv, mode="a", newline="", encoding="utf-8") as csv_file:
                    writer = csv.writer(csv_file)
                    writer.writerows(data)
                with open(gebaeude_vn_csv, mode="a", newline="", encoding="utf-8") as csv_file_geb:
                    writer = csv.writer(csv_file_geb)
                    writer.writerows(geb_data)

        if save_in_gdb:
            add_step_message("Schreibe Ergebnisse in die Geodatabase", 3, total_steps)
            finalize_results(output_workspace, flurstueck_vn_csv, gebaeude_vn_csv, keep_workdata)
        return True
    except Exception as e:
        arcpy.AddError(f"Fehler bei Extraktion der Veränderungsnummern: {str(e)}")
        return False

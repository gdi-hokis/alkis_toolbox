import os
import requests
import arcpy
from arcgis.gis import GIS
from utils import add_step_message


def get_portal_connection():
    """
    Stellt Portal-Verbindung her und gibt Portal-Objekt und Benutzer zurück.

    Returns:
        tuple: (portal, user, token, portal_url) oder (None, None, None, None) bei Fehler
    """
    try:
        arcpy.AddMessage("- Prüfe Portal-Anmeldung...")
        portal_url = arcpy.GetActivePortalURL()

        signed_in = arcpy.GetSigninToken()
        if not signed_in:
            arcpy.AddError("Nicht angemeldet! Bitte im ArcGIS Pro anmelden.")
            return None, None, None, None

        token = signed_in["token"]
        portal = GIS(portal_url, token=token)
        user = portal.users.me

        return portal, user, token, portal_url

    except Exception as e:
        arcpy.AddError(f"Fehler beim Verbinden mit Portal: {str(e)}")
        return None, None, None, None


def check_publish_permissions(user):
    """
    Prüft, ob der Benutzer Berechtigungen zum Veröffentlichen von Services hat.

    Args:
        user: GIS User-Objekt

    Returns:
        bool: True wenn Berechtigungen vorhanden, sonst False
    """
    arcpy.AddMessage("- Prüfe Veröffentlichungsrechte des Nutzers...")
    can_publish = "portal:publisher:publishServerServices" in user.privileges
    is_admin = user.role == "org_admin"

    if is_admin or can_publish:
        return True
    else:
        arcpy.AddError(
            "Benutzer hat keine Berechtigung zum Veröffentlichen von Services! Benötigt: Administrator oder Publisher-Rechte"
        )
        return False


def find_locator_item(portal, locator_item_url, user):
    """
    Sucht Locator-Item im Portal anhand der URL oder des Namens.

    Args:
        portal: GIS Portal-Objekt
        locator_item_url: URL des Locator-Items
        user: GIS User-Objekt

    Returns:
        tuple: (item_id, service_name) oder (None, None) bei Fehler
    """
    try:
        # Suche anhand der URL
        arcpy.AddMessage("- Suche Item anhand der Service-URL...")

        # Normalisiere Input-URL: Kürze auf GeocodeServer
        if "/GeocodeServer" in locator_item_url:
            base_url = locator_item_url.split("/GeocodeServer")[0] + "/GeocodeServer"
        else:
            base_url = locator_item_url.rstrip("/")

        locators = portal.content.search(query='type:"Geocode Service"', max_items=10)

        search_results = [item for item in locators if item.url and item.url.rstrip("/") == base_url.rstrip("/")]

        if len(search_results) == 0:
            arcpy.AddError("Locator-Item nicht gefunden!")
            return None, None

        item = search_results[0]
        arcpy.AddMessage(f"- Item gefunden: {item.title}")

        # Prüfe Besitzerrechte
        if item.owner != user.username and user.role != "org_admin":
            arcpy.AddError(f"Benutzer '{user.username}' ist nicht Besitzer des Locator-Items!")
            return None, None

        return item.id, item.title

    except Exception as e:
        arcpy.AddError(f"Fehler beim Abrufen des Locator-Items: {str(e)}")
        return None, None


def create_locator(cfg, flst, locator_path):
    """
    Erstellt einen neuen Locator.

    Args:
        cfg: Konfigurationsobjekt
        flst: Feature Class mit Flurstücken
        locator_path: Zielpfad für den Locator

    Returns:
        bool: True bei Erfolg, False bei Fehler
    """
    try:
        arcpy.env.overwriteOutput = True
        arcpy.AddMessage("- Neuen Locator erstellen...")
        flst_fc_name = os.path.basename(flst)

        arcpy.geocoding.CreateLocator(
            country_code="DEU",
            primary_reference_data=rf"{flst} Parcel",
            field_mapping=[
                f'Parcel.PARCEL_NAME {flst_fc_name}.{cfg["flurstueck"]["flurstueckstext"]}',
                f'Parcel.NEIGHBORHOOD {flst_fc_name}.{cfg["flurstueck"]["gemeinde_name"]}',
                f'Parcel.DISTRICT_JOIN_ID {flst_fc_name}.{cfg["flurstueck"]["gemarkung_id"]}',
                f'Parcel.DISTRICT {flst_fc_name}.{cfg["flurstueck"]["gemarkung_name"]}',
                f'Parcel.CITY {flst_fc_name}.{cfg["flur"]["flurname"]}',
                f"Parcel.Ortsname {flst_fc_name}.locator_place",
            ],
            out_locator=locator_path,
            language_code="GER",
            alternatename_tables=None,
            alternate_field_mapping=None,
            custom_output_fields="Ortsname",
            precision_type="GLOBAL_EXTRA_HIGH",
            version_compatibility="CURRENT_VERSION",
        )
        return True

    except Exception as e:
        arcpy.AddError(f"Fehler beim Erstellen des Locators: {str(e)}")
        return False


def rebuild_or_recreate_locator(cfg, flst, locator_path):
    """
    Versucht einen Locator zu rebuilden, bei Fehler wird er neu erstellt.

    Args:
        cfg: Konfigurationsobjekt
        flst: Feature Class mit Flurstücken
        locator_path: Pfad zum vorhandenen Locator

    Returns:
        bool: True bei Erfolg, False bei Fehler
    """
    arcpy.AddMessage("- Lokalen Locator überschreiben...")
    arcpy.env.overwriteOutput = True

    try:
        arcpy.RebuildAddressLocator_geocoding(locator_path)
        return True

    except Exception as rebuild_error:
        arcpy.AddWarning("Fehler beim Überschreiben des Locators.")
        arcpy.AddWarning(f"{str(rebuild_error)}")
        return create_locator(cfg, flst, locator_path)


def create_and_stage_service_definition(locator_path, service_name, temp_folder, locator_item_url=None):
    """
    Erstellt und staged die Service Definition für den Locator.

    Args:
        locator_path: Pfad zum Locator
        service_name: Name des Services
        temp_folder: Temporäres Verzeichnis für .sddraft und .sd Dateien

    Returns:
        str: Pfad zur .sd Datei oder None bei Fehler
    """
    try:
        sddraft_file = os.path.join(temp_folder, "Flurstuecke_Locator.sddraft")
        sd_file = os.path.join(temp_folder, "Flurstuecke_Locator.sd")

        arcpy.AddMessage("- Service Definition Draft erstellen...")

        # SD Draft erstellen
        analyze_messages = arcpy.CreateGeocodeSDDraft(
            locator_path,
            sddraft_file,
            service_name,
            copy_data_to_server=True,
            overwrite_existing_service=bool(locator_item_url),
        )

        # Prüfe auf Fehler
        if analyze_messages["errors"] != {}:
            arcpy.AddError("Fehler bei der Analyse des Service Definition Draft:")
            arcpy.AddError(analyze_messages["errors"])
            return None

        # Stage Service
        arcpy.AddMessage("- Service-Definition erstellen...")
        arcpy.server.StageService(sddraft_file, sd_file)

        return sd_file

    except Exception as e:
        arcpy.AddError(f"Fehler beim Erstellen der Service Definition: {str(e)}")
        return None


def upload_service_definition(sd_file, portal_url):
    """
    Lädt die Service Definition zum Portal hoch.

    Args:
        sd_file: Pfad zur .sd Datei
        portal_url: URL des Portals

    Returns:
        bool: True bei Erfolg, False bei Fehler
    """
    try:
        arcpy.AddMessage("- Service Definition hochladen...")
        arcgis_server = portal_url.replace("/portal", "/server")
        arcpy.server.UploadServiceDefinition(sd_file, arcgis_server, in_public="PUBLIC")
        return True

    except arcpy.ExecuteError:
        arcpy.AddError("Fehler beim Upload der Service Definition")
        arcpy.AddError(arcpy.GetMessages(2))
        return False


def share_locator_item(item_id, token, portal_url, user):
    """
    Teilt das Locator-Item öffentlich.

    Args:
        item_id: ID des Locator-Items
        token: Portal-Token
        portal_url: URL des Portals

    Returns:
        bool: True bei Erfolg, False bei Fehler
    """
    try:
        arcpy.AddMessage("- Öffentliche Freigabe...")
        user_portal = user.username
        share_url = f"{portal_url}/sharing/rest/content/users/{user_portal}/items/{item_id}/share"
        share_params = {
            "f": "json",
            "everyone": "true",
            "token": token,
        }

        response = requests.post(share_url, data=share_params, timeout=600)
        return response.status_code == 200

    except Exception as e:
        arcpy.AddWarning(f"Fehler beim Teilen des Items: {str(e)}")
        return False


def publish_locator(
    portal, user, token, portal_url, locator_path, service_name, temp_folder, locator_item_url=None, publish_item=True
):
    """
    Veröffentlicht oder aktualisiert einen Locator im Portal.

    Args:
        portal: GIS Portal-Objekt (bereits verbunden)
        user: GIS User-Objekt (bereits authentifiziert)
        token: Portal-Token
        portal_url: URL des Portals
        locator_path: Pfad zum lokalen Locator
        service_name: Name des Services
        temp_folder: Temporäres Verzeichnis für Service Definition
        locator_item_url: URL des bestehenden Locator-Items (für Update)

    Returns:
        bool: True bei Erfolg, False bei Fehler
    """
    arcpy.env.overwriteOutput = True

    # Bestehenden Service suchen (optional)
    item_id = None
    if locator_item_url:
        arcpy.AddMessage("- Update des bestehenden Locator-Item...")
        item_id, found_service_name = find_locator_item(portal, locator_item_url, user)
        if not item_id:
            return False
        service_name = found_service_name

    # Service Definition erstellen und stagen
    sd_file = create_and_stage_service_definition(locator_path, service_name, temp_folder, locator_item_url)
    if not sd_file:
        return False

    # Service hochladen
    if not upload_service_definition(sd_file, portal_url):
        return False

    # Item-ID abrufen, wenn nicht bereits gesetzt
    if not item_id:
        arcpy.AddMessage("- Suche das veröffentlichte Locator-Item...")
        query = f'title:"{service_name}" AND type:"Geocode Service" AND owner:{user.username}'
        items = portal.content.search(query=query, max_items=5, sort_field="modified", sort_order="desc")

        if items:
            item_id = items[0].id

    # Sharing aktualisieren
    if publish_item:
        if not get_current_sharing_status(item_id, portal):
            share_locator_item(item_id, token, portal_url, user)

    return True


def get_current_sharing_status(item_id, portal):
    """
    Prüft, ob ein Item öffentlich freigegeben ist.

    Args:
        item_id: ID des Items
        portal: GIS Portal-Objekt

    Returns:
        bool: True wenn öffentlich, False wenn nicht öffentlich, None bei Fehler
    """
    try:
        item = portal.content.get(item_id)
        is_public = item.shared_with.get("everyone", False)

        status = "Öffentlich" if is_public else "Nicht öffentlich"
        arcpy.AddMessage(f"- Aktueller Freigabe-Status: {status}")

        return is_public

    except Exception as e:
        arcpy.AddWarning(f"Fehler beim Abrufen des Sharing-Status: {str(e)}")
        return None


def build_update_locator(cfg, flst, temp_folder, locator, locator_item, overwrite_locator, publish_item=True):
    """
    Hauptfunktion zum Erstellen oder Aktualisieren eines Flurstücks-Locators.

    Args:
        cfg: Konfigurationsobjekt mit Feldnamen
        flst: Feature Class mit Flurstücken
        temp_folder: Temporäres Verzeichnis für Locator und Service Definition
        locator: Pfad zu bestehendem Locator (None für neuen Locator)
        locator_item: URL des bestehenden Locator-Items im Portal (optional)
        overwrite_locator: True um Locator im Portal zu veröffentlichen/aktualisieren

    Returns:
        bool: True bei Erfolg, False bei Fehler
    """
    try:
        # Portal-Anmeldung und Berechtigungen ZUERST prüfen, wenn Veröffentlichung gewünscht
        portal = None
        user = None
        token = None
        portal_url = None

        if overwrite_locator:
            add_step_message("Portal-Anmeldung und Berechtigungen prüfen", 1, 3)

            portal, user, token, portal_url = get_portal_connection()
            if not portal:
                return False

            if not check_publish_permissions(user):
                return False

        # Locator-Pfad bestimmen
        locator_path = locator if locator else os.path.join(temp_folder, "Flurstuecke_Locator.loc")

        # Locator erstellen oder rebuilden
        if overwrite_locator:
            add_step_message("Locator erstellen/aktualisieren", 2, 3)
        else:
            add_step_message("Locator erstellen/aktualisieren", 1, 1)

        if not locator:
            if not create_locator(cfg, flst, locator_path):
                return False
        else:
            if not rebuild_or_recreate_locator(cfg, flst, locator_path):
                return False

        # Im Portal veröffentlichen (nur wenn gewünscht UND Anmeldung erfolgreich)
        if overwrite_locator:
            add_step_message("Locator im Portal veröffentlichen", 3, 3)

            if not publish_locator(
                portal,
                user,
                token,
                portal_url,
                locator_path,
                "Flurstuecke_Locator",
                temp_folder,
                locator_item,
                publish_item,
            ):
                return False

        return True

    except Exception as e:
        arcpy.AddError(f"Fehler beim Erstellen/Updaten des Locators: {str(e)}")
        return False

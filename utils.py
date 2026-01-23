import os
import time
import arcpy


def add_step_message(message, step=None, total_steps=None):
    """Fügt eine formatierte Schritt-Nachricht im Log hinzu."""
    if step is None or total_steps is None:
        message = f"{message}..."
    else:
        message = f"Schritt {step} von {total_steps} -- {message}..."
    arcpy.AddMessage("-" * 40)
    arcpy.AddMessage(message)
    arcpy.AddMessage("-" * 40)


def progress_message(divider, current, total, current_time):
    # Progress alle 50k Gruppen (oder am Ende)
    if not current % divider or current == total:
        elapsed = time.time() - current_time
        arcpy.AddMessage(f"- Fortschritt: {current}/{total} FSKs ({elapsed:.1f}s)")


def warn_overwriting_existing_layers(parameter, layer_names):
    """
    Prüft, ob Layer bereits im Workspace existieren und setzt automatisch eine Warnung am Parameter.

    :param parameter: arcpy.Parameter-Objekt, dessen Wert als Workspace geprüft wird
    :param layer_names: Liste der zu prüfenden Layer-Namen oder einzelner Layer-Name als String
    """
    workspace = parameter.valueAsText

    if not workspace:
        return

    if isinstance(layer_names, str):
        layer_names = [layer_names]

    existing_layers = []

    for layer_name in layer_names:
        layer_path = os.path.join(workspace, layer_name)
        if arcpy.Exists(layer_path):
            existing_layers.append(layer_name)

    if existing_layers:
        if len(existing_layers) == 1:
            warning = f"'{existing_layers[0]}' existiert bereits in der Geodatabase und wird überschrieben."
        else:
            layer_list = "', '".join(existing_layers)
            warning = f"'{layer_list}' existieren bereits in der Geodatabase und werden überschrieben."

        parameter.setWarningMessage(warning)


def check_required_layers(parameter, required_layers):
    gdb_path = parameter.valueAsText
    if not gdb_path:
        return

    missing_layers = []

    for layer_name in required_layers:
        layer_path = os.path.join(gdb_path, layer_name)
        if not arcpy.Exists(layer_path):
            missing_layers.append(layer_name)

    if len(missing_layers) > 0:
        parameter.setErrorMessage(f"Folgende erforderlichen Layer fehlen in der GDB: {', '.join(missing_layers)}")

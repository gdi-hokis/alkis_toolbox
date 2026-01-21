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

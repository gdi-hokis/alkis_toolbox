# -*- coding: utf-8 -*-

# Copyright (c) 2024, Jana Muetsch, Andre Voelkner, LRA Hohenlohekreis
# All rights reserved.

"""
Config Loader - Lädt und verwaltet Feldname-Konfigurationen.
"""

import arcpy
import os
import json


class FieldConfigLoader:
    """
    Singleton-Klasse zum Laden und Verwalten der Feldname-Konfiguration.
    """

    _config = None

    @classmethod
    def load_config(cls, config_path=None):
        """Lädt die Konfiguration einmalig (Singleton-Pattern)."""
        if cls._config is not None:
            return cls._config

        if config_path is None:
            # Standard: sfl/config/fields_config.json
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(script_dir, "config.json")

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cls._config = json.load(f)
            arcpy.AddMessage(f"Feldkonfiguration geladen: {config_path}")
            return cls._config
        except Exception as e:
            arcpy.AddError(f"Fehler beim Laden der Feldkonfiguration: {str(e)}")
            raise

    @classmethod
    def get(cls, *keys):
        """
        Greift auf Config mit verschachtelter Notation zu.
        Beispiel: FieldConfigLoader.get("flurstueck", "flurstueckskennzeichen")
        """
        if cls._config is None:
            cls.load_config()

        value = cls._config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value

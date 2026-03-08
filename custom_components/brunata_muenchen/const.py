"""Constants for the Brunata München integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import Platform, UnitOfEnergy, UnitOfVolume

DOMAIN = "brunata_muenchen"

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Config keys
CONF_BASE_URL = "base_url"
CONF_SAP_CLIENT = "sap_client"
CONF_SAP_LANGUAGE = "sap_language"
CONF_SCAN_INTERVAL = "scan_interval"

# Defaults
DEFAULT_BASE_URL = "https://nutzerportal.brunata-muenchen.de"
DEFAULT_SAP_CLIENT = "201"
DEFAULT_SAP_LANGUAGE = "DE"
DEFAULT_SCAN_INTERVAL = timedelta(days=1)
DEFAULT_SCAN_INTERVAL_SECONDS = int(DEFAULT_SCAN_INTERVAL.total_seconds())

# Attributes
ATTR_PERIODS = "periods"
ATTR_LAST_UPDATE_SUCCESS = "last_update_success"

# Mapping der SAP-Präfixe auf HA-Klassen (weiterhin für Kaltwasser benötigt)
METER_MAPPING = {
    "HZ": {
        "device_class": SensorDeviceClass.ENERGY,
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "name": "Heizung",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "WW": {
        "device_class": SensorDeviceClass.WATER,
        "unit": UnitOfVolume.CUBIC_METERS,
        "name": "Warmwasser",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "KW": {
        "device_class": SensorDeviceClass.WATER,
        "unit": UnitOfVolume.CUBIC_METERS,
        "name": "Kaltwasser",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
}

# Sensor-Typen die erstellt werden
SENSOR_TYPE_METER = "meter"
SENSOR_TYPE_MONTHLY = "monthly"
SENSOR_TYPE_CUMULATIVE = "cumulative"
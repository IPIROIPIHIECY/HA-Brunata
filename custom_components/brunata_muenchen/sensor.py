"""Sensoren für die Brunata München Integration.

Erstellt und verwaltet alle HA-Sensoren basierend auf den verfügbaren
Brunata-Zählern, Verbrauchsvergleichen, Prognosen und Raum-Auswertungen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from brunata_api.models import (
    ConsumptionComparison,
    ConsumptionForecast,
    MeterReading,
    Reading,
    RoomConsumption,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, METER_MAPPING
from .coordinator import BrunataMuenchenCoordinator

_LOGGER = __import__("logging").getLogger(__name__)

# Anzahl der History-Einträge, die als Attribut gespeichert werden
_MAX_HISTORY_EINTRAEGE = 24

# Typ-Alias für verschiedene Reading-Typen
Messwert = Reading | MeterReading


@dataclass(frozen=True)
class SensorBeschreibung:
    """Beschreibt einen zu erstellenden Brunata-Sensor."""

    schluessel: str
    anzeigename: str
    kategorie: str
    geraeteklasse: SensorDeviceClass | None = None
    zustandsklasse: SensorStateClass | None = None
    entitaets_kategorie: EntityCategory | None = None


def _letzter_wert(werte: list[Messwert]) -> Messwert | None:
    """Gibt den letzten Eintrag einer Liste zurück oder None."""
    return werte[-1] if werte else None


def _verlauf_als_attribute(werte: list[Messwert]) -> dict[str, Any]:
    """Erstelle ein History-Attribut aus den letzten Messwerten."""
    auswahl = werte[-_MAX_HISTORY_EINTRAEGE:]
    eintraege = []
    for messung in auswahl:
        eintrag: dict[str, Any] = {
            "timestamp": messung.timestamp.isoformat(),
            "value": messung.value,
            "unit": messung.unit,
            "kind": messung.kind.value,
        }
        if isinstance(messung, MeterReading):
            eintrag["cost_type"] = messung.cost_type
        eintraege.append(eintrag)
    return {"history": eintraege}


def _kostenart_label(kostenart: str) -> str:
    """Bestimme den Anzeigenamen basierend auf dem Kostenart-Präfix.

    Nutzt METER_MAPPING als primäre Quelle (enthält Kaltwasser),
    fällt auf präfixbasierte Zuordnung zurück.
    """
    praefix = kostenart[:2] if len(kostenart) >= 2 else kostenart
    mapping = METER_MAPPING.get(praefix)
    if mapping:
        return mapping.get("name", kostenart)
    _PRAEFIX_LABELS = {"HZ": "Heizung", "WW": "Warmwasser"}
    return _PRAEFIX_LABELS.get(praefix, kostenart)


# ─── Sensor-Definitionen für jeden Typ ────────────────────────────────────

def _sensor_monat(kostenart: str, label: str) -> SensorBeschreibung:
    return SensorBeschreibung(
        schluessel=f"monthly_{kostenart.lower()}",
        anzeigename=f"{label} – {kostenart} – Monatsverbrauch (kWh)",
        kategorie=f"monthly:{kostenart}",
        geraeteklasse=SensorDeviceClass.ENERGY,
        zustandsklasse=SensorStateClass.TOTAL,
    )


def _sensor_zaehler(kostenart: str, label: str, geraeteklasse: SensorDeviceClass | None) -> SensorBeschreibung:
    return SensorBeschreibung(
        schluessel=f"meter_{kostenart.lower()}",
        anzeigename=f"{label} – {kostenart} – Zählerstand",
        kategorie=f"meter:{kostenart}",
        geraeteklasse=geraeteklasse,
        zustandsklasse=SensorStateClass.TOTAL_INCREASING,
    )


def _sensor_kumulativ(kostenart: str, label: str) -> SensorBeschreibung:
    return SensorBeschreibung(
        schluessel=f"kwh_total_{kostenart.lower()}",
        anzeigename=f"{label} – {kostenart} – Verbrauch (kumulativ, kWh)",
        kategorie=f"kwh_total:{kostenart}",
        geraeteklasse=SensorDeviceClass.ENERGY,
        zustandsklasse=SensorStateClass.TOTAL_INCREASING,
    )


# Vergleichs-Sensor-Definitionen (Typ, Schlüssel-Suffix, Name-Suffix)
_VERGLEICH_VARIANTEN = [
    ("your", "your_value", "Verbrauch (kWh/m²)"),
    ("building", "building_avg", "Gebäudedurchschnitt"),
    ("national", "national_avg", "Bundesdurchschnitt"),
]

# Prognose-Sensor-Definitionen (Typ, Schlüssel-Suffix, Name, StateClass)
_PROGNOSE_VARIANTEN = [
    ("current", "current", "Aktuell (YTD)", SensorStateClass.TOTAL),
    ("previous", "previous_year", "Vorjahr", SensorStateClass.MEASUREMENT),
    ("forecast", "forecast", "Prognose", SensorStateClass.MEASUREMENT),
    ("difference", "difference", "Mehrverbrauch", SensorStateClass.MEASUREMENT),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sensoren basierend auf den verfügbaren Zählern dynamisch erstellen."""
    koordinator: BrunataMuenchenCoordinator = hass.data[DOMAIN][entry.entry_id]
    daten = koordinator.data or {}

    # Verfügbare Datensätze laden
    zaehler = dict(daten.get("meter_readings_by_cost_type") or {})
    monatlich = dict(daten.get("monthly_by_cost_type") or {})
    kwh_historien = dict(daten.get("kwh_histories_by_cost_type") or {})
    kaltwasser = dict(daten.get("cold_water_data") or {})
    vergleiche = dict(daten.get("comparison_by_cost_type") or {})
    prognosen = dict(daten.get("forecast_by_cost_type") or {})
    raeume = dict(daten.get("room_by_cost_type") or {})

    # Alle verfügbaren Kostenarten sammeln
    alle_kostenarten = sorted({
        *zaehler, *monatlich, *kaltwasser,
        *vergleiche, *prognosen, *raeume,
    })

    sensoren: list[BrunataMuenchenSensor] = []

    # Diagnostik-Sensor für Dashboard-Perioden
    sensoren.append(
        BrunataMuenchenSensor(
            koordinator, entry,
            SensorBeschreibung(
                schluessel="dashboard_dates",
                anzeigename="Dashboard-Perioden",
                kategorie="dashboard_dates",
                entitaets_kategorie=EntityCategory.DIAGNOSTIC,
            ),
        )
    )

    for kostenart in alle_kostenarten:
        label = _kostenart_label(kostenart)
        praefix = kostenart[:2] if len(kostenart) >= 2 else kostenart
        mapping = METER_MAPPING.get(praefix, {})

        # Monatsverbrauch
        if monatlich.get(kostenart):
            sensoren.append(
                BrunataMuenchenSensor(koordinator, entry, _sensor_monat(kostenart, label))
            )

        # Zählerstand
        if zaehler.get(kostenart) or kaltwasser.get(kostenart):
            gk = mapping.get("device_class")
            if not gk and kostenart.startswith("WW"):
                gk = SensorDeviceClass.WATER
            sensoren.append(
                BrunataMuenchenSensor(koordinator, entry, _sensor_zaehler(kostenart, label, gk))
            )

        # Kumulativer Verbrauch
        if kwh_historien.get(kostenart) or monatlich.get(kostenart):
            sensoren.append(
                BrunataMuenchenSensor(koordinator, entry, _sensor_kumulativ(kostenart, label))
            )

        # Verbrauchsvergleich
        if vergleiche.get(kostenart):
            for variante, suffix, bezeichnung in _VERGLEICH_VARIANTEN:
                sensoren.append(
                    BrunataMuenchenSensor(
                        koordinator, entry,
                        SensorBeschreibung(
                            schluessel=f"comparison_{suffix}_{kostenart.lower()}",
                            anzeigename=f"{label} – {kostenart} – {bezeichnung}",
                            kategorie=f"comparison_{variante}:{kostenart}",
                            zustandsklasse=SensorStateClass.MEASUREMENT,
                        ),
                    )
                )

        # Prognosen
        if prognosen.get(kostenart):
            for variante, suffix, bezeichnung, zustandskl in _PROGNOSE_VARIANTEN:
                sensoren.append(
                    BrunataMuenchenSensor(
                        koordinator, entry,
                        SensorBeschreibung(
                            schluessel=f"forecast_{suffix}_{kostenart.lower()}",
                            anzeigename=f"{label} – {kostenart} – {bezeichnung}",
                            kategorie=f"forecast_{variante}:{kostenart}",
                            geraeteklasse=SensorDeviceClass.ENERGY,
                            zustandsklasse=zustandskl,
                        ),
                    )
                )

        # Raum-Verbrauch
        for raum in raeume.get(kostenart) or []:
            raum_id = (raum.room_id or "").strip() or "unbekannt"
            raum_name = (raum.room_name or "").strip() or raum_id
            sicherer_key = raum_id.replace(" ", "_").lower()
            sensoren.append(
                BrunataMuenchenSensor(
                    koordinator, entry,
                    SensorBeschreibung(
                        schluessel=f"room_{sicherer_key}_{kostenart.lower()}",
                        anzeigename=f"Raum: {raum_name} – {kostenart}",
                        kategorie=f"room:{kostenart}:{raum_id}",
                        zustandsklasse=SensorStateClass.MEASUREMENT,
                    ),
                )
            )

    async_add_entities(sensoren)
    _LOGGER.info("Brunata München: %d Sensoren erstellt", len(sensoren))


class BrunataMuenchenSensor(CoordinatorEntity[BrunataMuenchenCoordinator], SensorEntity):
    """Repräsentation eines einzelnen Brunata München Sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        koordinator: BrunataMuenchenCoordinator,
        eintrag: ConfigEntry,
        beschreibung: SensorBeschreibung,
    ) -> None:
        super().__init__(koordinator)
        self._eintrag = eintrag
        self._beschreibung = beschreibung

        uid = eintrag.unique_id or eintrag.entry_id
        self._attr_unique_id = f"{uid}_{beschreibung.schluessel}"
        self._attr_name = beschreibung.anzeigename
        self._attr_device_class = beschreibung.geraeteklasse
        self._attr_state_class = beschreibung.zustandsklasse
        self._attr_entity_category = beschreibung.entitaets_kategorie

    @property
    def device_info(self) -> DeviceInfo:
        """Ordnet alle Sensoren einem gemeinsamen Gerät zu."""
        uid = self._eintrag.unique_id or self._eintrag.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, uid)},
            name="Brunata München Nutzeinheit",
            manufacturer="Brunata Metrona",
            model="Digitales Nutzerportal",
        )

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Einheit des Sensors bestimmen."""
        kat = self._beschreibung.kategorie

        if kat == "dashboard_dates":
            return None

        # Spezial-Sensoren (Vergleich, Prognose, Raum)
        spezial_einheit = self._einheit_spezial()
        if spezial_einheit is not None:
            return spezial_einheit

        # Zählerstand: Einheit aus METER_MAPPING (wichtig für Kaltwasser m³)
        if kat.startswith("meter:"):
            kostenart = kat.split(":", 1)[1]
            praefix = kostenart[:2] if len(kostenart) >= 2 else kostenart
            mapping = METER_MAPPING.get(praefix, {})
            if mapping.get("unit"):
                return mapping["unit"]

        # Fallback: aus den Readings selbst
        aktuell = _letzter_wert(self._messwerte_laden())
        return aktuell.unit if aktuell else None

    @property
    def native_value(self) -> float | int | str | None:
        """Aktuellen Messwert des Sensors zurückgeben."""
        kat = self._beschreibung.kategorie

        if kat == "dashboard_dates":
            perioden = _perioden_extrahieren(
                self.coordinator.data.get("dashboard_dates")
            )
            return len(perioden)

        # Spezial-Sensoren
        spezial_wert = self._wert_spezial()
        if spezial_wert is not None:
            return spezial_wert

        # Standard: letzter Reading-Wert
        aktuell = _letzter_wert(self._messwerte_laden())
        if aktuell is not None:
            return aktuell.value if hasattr(aktuell, "value") else aktuell
        return None

    @property
    def last_reset(self) -> datetime | None:
        """Reset-Zeitpunkt für periodische Sensoren."""
        kat = self._beschreibung.kategorie

        if kat.startswith("monthly:"):
            letzte_messung = _letzter_wert(self._messwerte_laden())
            if not isinstance(letzte_messung, Reading):
                return None
            monatsanfang = dt_util.as_utc(letzte_messung.timestamp)
            return monatsanfang.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )

        if kat.startswith("forecast_current:"):
            jetzt = dt_util.now()
            return jetzt.replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Zusätzliche Attribute für den Sensor."""
        kat = self._beschreibung.kategorie

        if kat == "dashboard_dates":
            return {
                "periods": _perioden_extrahieren(
                    self.coordinator.data.get("dashboard_dates")
                )
            }

        # Raum-spezifische Attribute
        raum_attrs = self._attribute_raum()
        if raum_attrs is not None:
            return raum_attrs

        # Standard: Verlaufs-Attribute
        messreihe = self._messwerte_laden()
        attribute = _verlauf_als_attribute(messreihe)
        aktuell = _letzter_wert(messreihe)
        if aktuell is not None:
            if hasattr(aktuell, "timestamp"):
                attribute["timestamp"] = aktuell.timestamp.isoformat()
            if isinstance(aktuell, MeterReading):
                attribute["cost_type"] = aktuell.cost_type
        return attribute

    # ─── Spezial-Sensor Logik ─────────────────────────────────────────────

    def _wert_spezial(self) -> float | None:
        """Wert für Vergleichs-, Prognose- oder Raum-Sensoren ermitteln."""
        daten = self.coordinator.data or {}
        kat = self._beschreibung.kategorie

        # Verbrauchsvergleich
        if kat.startswith("comparison_"):
            teil, kostenart = kat.split(":", 1)
            vergleich: ConsumptionComparison | None = (
                daten.get("comparison_by_cost_type") or {}
            ).get(kostenart)
            if not vergleich:
                return None
            zuordnung = {
                "comparison_your": vergleich.your_value,
                "comparison_building": vergleich.building_average,
                "comparison_national": vergleich.national_average,
            }
            return zuordnung.get(teil)

        # Prognose
        if kat.startswith("forecast_"):
            teil, kostenart = kat.split(":", 1)
            prognose: ConsumptionForecast | None = (
                daten.get("forecast_by_cost_type") or {}
            ).get(kostenart)
            if not prognose:
                return None
            zuordnung = {
                "forecast_current": prognose.current,
                "forecast_previous": prognose.previous_year,
                "forecast_forecast": prognose.forecast,
                "forecast_difference": prognose.difference,
            }
            return zuordnung.get(teil)

        # Raum
        if kat.startswith("room:"):
            raum = self._raum_finden()
            return raum.value if raum else None

        return None

    def _einheit_spezial(self) -> str | None:
        """Einheit für Vergleichs-, Prognose- oder Raum-Sensoren ermitteln."""
        daten = self.coordinator.data or {}
        kat = self._beschreibung.kategorie

        if kat.startswith("comparison_"):
            kostenart = kat.split(":", 1)[1]
            vergleich: ConsumptionComparison | None = (
                daten.get("comparison_by_cost_type") or {}
            ).get(kostenart)
            return (vergleich.unit if vergleich else None) or "kWh/m²"

        if kat.startswith("forecast_"):
            kostenart = kat.split(":", 1)[1]
            prognose: ConsumptionForecast | None = (
                daten.get("forecast_by_cost_type") or {}
            ).get(kostenart)
            return (prognose.unit if prognose else None) or "kWh"

        if kat.startswith("room:"):
            raum = self._raum_finden()
            return raum.unit if raum else None

        return None

    def _attribute_raum(self) -> dict[str, Any] | None:
        """Gibt Raum-spezifische Attribute zurück oder None."""
        if not self._beschreibung.kategorie.startswith("room:"):
            return None
        raum = self._raum_finden()
        if not raum:
            return {}
        return {
            "room_id": raum.room_id,
            "room_name": raum.room_name,
            "share_percent": raum.share_percent,
            "cost_type": raum.cost_type,
        }

    def _raum_finden(self) -> RoomConsumption | None:
        """Finde den passenden Raum-Eintrag für diesen Sensor."""
        daten = self.coordinator.data or {}
        _, kostenart, raum_id = self._beschreibung.kategorie.split(":", 2)
        raum_liste: list[RoomConsumption] = (
            daten.get("room_by_cost_type") or {}
        ).get(kostenart) or []
        for raum in raum_liste:
            if (raum.room_id or "").strip() == raum_id:
                return raum
        return None

    # ─── Daten-Zugriff ────────────────────────────────────────────────────

    def _messwerte_laden(self) -> list[Messwert]:
        """Lade die Messwerte für die Kategorie dieses Sensors."""
        daten = self.coordinator.data or {}
        kat = self._beschreibung.kategorie

        if kat.startswith("monthly:"):
            kostenart = kat.split(":", 1)[1]
            monatlich = dict(daten.get("monthly_by_cost_type") or {})
            return list(monatlich.get(kostenart) or [])

        if kat.startswith("meter:"):
            kostenart = kat.split(":", 1)[1]
            zaehler = dict(daten.get("meter_readings_by_cost_type") or {})
            messung = zaehler.get(kostenart)
            if messung:
                return [messung]
            # Fallback auf Kaltwasser-Daten
            kw_daten = daten.get("cold_water_data") or {}
            kw_messung = kw_daten.get(kostenart)
            return [kw_messung] if kw_messung else []

        if kat.startswith("kwh_total:"):
            kostenart = kat.split(":", 1)[1]
            historien = dict(daten.get("kwh_histories_by_cost_type") or {})
            return list(historien.get(kostenart) or [])

        return []


# ─── Dashboard-Perioden Extraktion ─────────────────────────────────────────


def _perioden_extrahieren(dashboard_daten: Any) -> list[dict[str, Any]]:
    """Extrahiere eine kompakte Liste der Abrechnungsperioden.

    Verarbeitet die verschachtelte OData-Struktur der Brunata Dashboard-API.
    """
    if not isinstance(dashboard_daten, dict):
        return []

    ergebnisse = (dashboard_daten.get("d") or {}).get("results")
    if not isinstance(ergebnisse, list):
        return []

    perioden: list[dict[str, Any]] = []
    for periode in ergebnisse:
        if not isinstance(periode, dict):
            continue

        # Kostenarten aus den Units extrahieren
        einheiten_daten = periode.get("Units")
        einheiten_liste = (
            (einheiten_daten.get("results") or [])
            if isinstance(einheiten_daten, dict)
            else []
        )
        kostenarten = sorted({
            eintrag.get("CostType")
            for eintrag in einheiten_liste
            if isinstance(eintrag, dict)
            and isinstance(eintrag.get("CostType"), str)
            and eintrag.get("CostType")
        })

        perioden.append({
            "from": periode.get("Abdatum"),
            "to": periode.get("Bisdatum"),
            "cost_types": kostenarten,
        })

    return perioden
"""Statistik-Hilfsfunktionen für die Brunata München Integration.

Ermöglicht den Import historischer Verbrauchsdaten in das Home Assistant
Recorder-System über die externe Statistik-API. So werden vergangene Werte
auch rückwirkend im Energie-Dashboard dargestellt.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from homeassistant.components.recorder.models.statistics import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Unterstützte Einheiten-Konverter für die Zuordnung
_UNIT_CONVERTERS = [
    (EnergyConverter.VALID_UNITS, EnergyConverter.UNIT_CLASS),
    (VolumeConverter.VALID_UNITS, VolumeConverter.UNIT_CLASS),
]


def _stunde_utc(zeitpunkt: datetime) -> datetime:
    """Zeitstempel auf volle Stunde in UTC normalisieren."""
    utc = dt_util.as_utc(zeitpunkt)
    return utc.replace(minute=0, second=0, microsecond=0)


def _einheiten_klasse(einheit: str | None) -> str | None:
    """Ordne eine Maßeinheit der passenden HA-Einheitenklasse zu."""
    if not einheit:
        return None
    for gueltige_einheiten, klasse in _UNIT_CONVERTERS:
        if einheit in gueltige_einheiten:
            return klasse
    return None


def _erstelle_metadaten(
    *,
    statistik_id: str,
    name: str,
    einheit: str | None,
    hat_summe: bool,
) -> StatisticMetaData:
    """Erstelle ein StatisticMetaData-Objekt mit den gegebenen Parametern."""
    return StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=hat_summe,
        name=name,
        source=DOMAIN,
        statistic_id=statistik_id,
        unit_class=_einheiten_klasse(einheit),
        unit_of_measurement=einheit,
    )


def _importiere_statistiken(
    hass: HomeAssistant,
    *,
    metadaten: StatisticMetaData,
    datenpunkte: list[StatisticData],
    statistik_id: str,
) -> None:
    """Übermittle Statistikdaten an den Recorder."""
    if not datenpunkte:
        return
    try:
        _LOGGER.info(
            "Importiere %d Statistik-Datenpunkte für %s (%s)",
            len(datenpunkte),
            statistik_id,
            metadaten.unit_of_measurement or "keine Einheit",
        )
        async_add_external_statistics(
            hass=hass, metadata=metadaten, statistics=datenpunkte
        )
    except Exception:
        _LOGGER.warning(
            "Statistik-Import für %s fehlgeschlagen", statistik_id, exc_info=True
        )


def statistik_als_zustand(
    hass: HomeAssistant,
    *,
    statistik_id: str,
    name: str,
    einheit: str | None,
    messpunkte: Iterable[tuple[datetime, float]],
) -> None:
    """Importiere Messwerte als reine Zustands-Statistiken (ohne kumulierte Summe)."""
    datenpunkte = [
        StatisticData(start=_stunde_utc(ts), state=float(wert))
        for ts, wert in messpunkte
    ]
    metadaten = _erstelle_metadaten(
        statistik_id=statistik_id, name=name, einheit=einheit, hat_summe=False
    )
    _importiere_statistiken(
        hass, metadaten=metadaten, datenpunkte=datenpunkte, statistik_id=statistik_id
    )


def statistik_als_summe(
    hass: HomeAssistant,
    *,
    statistik_id: str,
    name: str,
    einheit: str | None,
    messpunkte: Iterable[tuple[datetime, float]],
) -> None:
    """Importiere Messwerte als kumulative Summen-Statistiken."""
    datenpunkte = [
        StatisticData(start=_stunde_utc(ts), state=float(wert), sum=float(wert))
        for ts, wert in messpunkte
    ]
    metadaten = _erstelle_metadaten(
        statistik_id=statistik_id, name=name, einheit=einheit, hat_summe=True
    )
    _importiere_statistiken(
        hass, metadaten=metadaten, datenpunkte=datenpunkte, statistik_id=statistik_id
    )


def als_float(wert: Any) -> float | None:
    """Versuche einen Wert in float zu konvertieren, sonst None."""
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None

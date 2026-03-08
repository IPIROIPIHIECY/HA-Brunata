"""DataUpdateCoordinator für die Brunata München Integration.

Zentraler Datenabruf-Koordinator, der die Brunata API abfragt und alle
Verbrauchsdaten, Vergleiche, Prognosen und Raum-Auswertungen sammelt.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from brunata_api import BrunataClient, ReadingKind
from brunata_api.errors import LoginError
from brunata_api.models import MeterReading, Reading
import httpx
from homeassistant.components.recorder.statistics import async_list_statistic_ids
from homeassistant.components.recorder.util import (
    get_instance as get_recorder_instance,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_BASE_URL, CONF_SAP_CLIENT, CONF_SAP_LANGUAGE, DOMAIN
from .statistics_import import statistik_als_summe

_LOGGER = logging.getLogger(__name__)

# Zuordnung Kostenart-Präfix → ReadingKind
_READING_KIND_MAP: dict[str, ReadingKind] = {
    "HZ": ReadingKind.heating,
    "WW": ReadingKind.hot_water,
}


def _reading_kind_fuer(kostenart: str) -> ReadingKind:
    """Bestimme den ReadingKind anhand des Kostenart-Präfixes."""
    for praefix, kind in _READING_KIND_MAP.items():
        if kostenart.startswith(praefix):
            return kind
    return ReadingKind.heating


def _monatsreihe_kumulieren(
    kostenart: str, monatswerte: list[Reading]
) -> tuple[str | None, list[MeterReading]]:
    """Berechne eine kumulative kWh-Reihe aus monatlichen Einzelwerten.

    Returns:
        Tuple aus (Einheit, Liste der kumulierten MeterReadings).
    """
    if not monatswerte:
        return None, []

    chronologisch = sorted(monatswerte, key=lambda r: r.timestamp)
    einheit = chronologisch[-1].unit or "kWh"
    kind = _reading_kind_fuer(kostenart)

    laufende_summe = 0.0
    ergebnis: list[MeterReading] = []

    for messung in chronologisch:
        laufende_summe += float(messung.value)
        ergebnis.append(
            MeterReading(
                timestamp=messung.timestamp,
                value=round(laufende_summe, 6),
                unit=einheit,
                cost_type=kostenart,
                kind=kind,
            )
        )

    return einheit, ergebnis


class BrunataMuenchenCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Koordinator für den zentralen Datenabruf der Brunata München API."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry: ConfigEntry,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.entry = entry
        self._client: BrunataClient | None = None
        self._zugriffs_sperre = asyncio.Lock()
        self._veraltete_statistiken_bereinigt = False

    async def async_shutdown(self) -> None:
        """API-Client beim Entladen der Integration schließen."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _client_bereitstellen(self) -> BrunataClient:
        """API-Client erstellen oder den bestehenden zurückgeben.

        Die Client-Erstellung erfolgt im Executor, da der SSL-Handshake
        den Event-Loop blockieren kann.
        """
        if self._client is not None:
            return self._client

        async with self._zugriffs_sperre:
            # Erneute Prüfung nach Sperre (Double-Check Locking)
            if self._client is not None:
                return self._client

            konfiguration = self.entry.data
            self._client = await self.hass.async_add_executor_job(
                lambda: BrunataClient(
                    base_url=konfiguration[CONF_BASE_URL],
                    username=konfiguration[CONF_USERNAME],
                    password=konfiguration[CONF_PASSWORD],
                    sap_client=konfiguration.get(CONF_SAP_CLIENT, "201"),
                    sap_language=konfiguration.get(CONF_SAP_LANGUAGE, "DE"),
                )
            )
            return self._client

    async def _monatsdaten_aller_perioden(
        self, client: BrunataClient, perioden: list
    ) -> dict[str, list[Reading]]:
        """Lade monatliche Verbrauchsdaten über alle Abrechnungsperioden hinweg.

        So entsteht eine lückenlose Serie, die im Energy Dashboard keinen
        Reset beim Jahreswechsel verursacht.
        """
        gesammelt: dict[str, list[Reading]] = {}

        for index in range(len(perioden)):
            heizung, warmwasser = await asyncio.gather(
                client.get_monthly_consumptions(
                    ReadingKind.heating, in_kwh=True, period_index=index
                ),
                client.get_monthly_consumptions(
                    ReadingKind.hot_water, in_kwh=True, period_index=index
                ),
            )
            for quelle in (heizung, warmwasser):
                for kostenart, werte in (quelle or {}).items():
                    gesammelt.setdefault(kostenart, []).extend(werte)

        # Chronologisch sortieren
        for kostenart in gesammelt:
            gesammelt[kostenart].sort(key=lambda r: r.timestamp)

        return gesammelt

    async def _kaltwasser_abrufen(
        self, client: BrunataClient, unterstuetzte_typen: dict | None
    ) -> dict[str, Any]:
        """Lade Kaltwasser-Zählerstände separat über die KW-Präfix-Kostenarten."""
        kaltwasser: dict[str, Any] = {}
        if not unterstuetzte_typen:
            return kaltwasser

        letzte_periode = list(unterstuetzte_typen.keys())[-1]
        zaehler_ids = unterstuetzte_typen[letzte_periode]

        for zaehler_id in zaehler_ids:
            if not zaehler_id.startswith("KW"):
                continue
            try:
                daten = await client.get_monthly_consumption(cost_type=zaehler_id)
                if daten:
                    kaltwasser[zaehler_id] = daten[-1]
            except Exception as fehler:
                _LOGGER.debug(
                    "Kaltwasserdaten für %s nicht verfügbar: %s", zaehler_id, fehler
                )

        return kaltwasser

    def _veraltete_statistiken_entfernen(self, uid: str) -> None:
        """Einmalig veraltete Statistik-IDs aus früheren Versionen bereinigen."""
        if self._veraltete_statistiken_bereinigt:
            return
        self._veraltete_statistiken_bereinigt = True

        async def _bereinigen() -> None:
            try:
                alle_ids = await async_list_statistic_ids(self.hass)
                praefix = f"{DOMAIN}:{uid}_"
                veraltete = [
                    eintrag["statistic_id"]
                    for eintrag in alle_ids
                    if eintrag.get("statistic_id", "").startswith(praefix)
                    and any(
                        marker in eintrag.get("statistic_id", "")
                        for marker in ("_meter_", "_monthly_")
                    )
                ]
                if veraltete:
                    get_recorder_instance(self.hass).async_clear_statistics(veraltete)
                    _LOGGER.debug(
                        "%d veraltete Statistik-Einträge entfernt", len(veraltete)
                    )
            except Exception:
                _LOGGER.debug("Bereinigung veralteter Statistiken fehlgeschlagen", exc_info=True)

        self.hass.async_create_task(_bereinigen())

    def _kwh_historien_backfill(
        self,
        uid: str,
        historien: dict[str, list[MeterReading]],
    ) -> None:
        """Importiere kumulative kWh-Serien als externe Statistiken."""
        for kostenart, verlauf in historien.items():
            if not verlauf:
                continue
            kind = _reading_kind_fuer(kostenart)
            bezeichnung = "Heizung" if kind == ReadingKind.heating else "Warmwasser"
            statistik_als_summe(
                self.hass,
                statistik_id=f"{DOMAIN}:{uid}_kwh_total_{kostenart.lower()}",
                name=(
                    f"Brunata München {uid} – {bezeichnung} – "
                    f"{kostenart} – Verbrauch (kumulativ, kWh)"
                ),
                einheit=verlauf[-1].unit if verlauf else None,
                messpunkte=(
                    (eintrag.timestamp, float(eintrag.value)) for eintrag in verlauf
                ),
            )

    async def _async_update_data(self) -> dict[str, Any]:
        """Alle Daten von der Brunata API abrufen und zusammenstellen."""
        client = await self._client_bereitstellen()

        try:
            # Account-Daten sichern (erzwingt auch den Login)
            konto = await client.get_account()

            # Paralleler Abruf der Basisdaten
            (
                dashboard_daten,
                zaehlerstaende,
                perioden,
                unterstuetzte_typen,
            ) = await asyncio.gather(
                client.get_dashboard_dates(),
                client.get_meter_readings(),
                client.get_periods(),
                client.get_supported_cost_types(),
            )

            # Monatsdaten über alle Perioden sammeln
            monatsdaten = await self._monatsdaten_aller_perioden(client, perioden)

            # Kaltwasser separat laden
            kaltwasser = await self._kaltwasser_abrufen(client, unterstuetzte_typen)

            # Vergleichs-, Prognose- und Raumdaten parallel laden
            vergleich, prognose, raeume = await asyncio.gather(
                client.get_consumption_comparison(),
                client.get_consumption_forecast(),
                client.get_room_consumption(),
            )

            # Kumulative kWh-Historien berechnen
            kwh_historien: dict[str, list[MeterReading]] = {}
            kwh_summen: dict[str, MeterReading] = {}
            for kostenart, monats_werte in monatsdaten.items():
                if not monats_werte:
                    continue
                _, verlauf = _monatsreihe_kumulieren(kostenart, monats_werte)
                if verlauf:
                    kwh_historien[kostenart] = verlauf
                    kwh_summen[kostenart] = verlauf[-1]

            # Gesamtdatenstruktur
            ergebnis: dict[str, Any] = {
                "account": konto,
                "dashboard_dates": dashboard_daten,
                "meter_readings_by_cost_type": zaehlerstaende or {},
                "monthly_by_cost_type": monatsdaten,
                "cold_water_data": kaltwasser,
                "comparison_by_cost_type": vergleich or {},
                "forecast_by_cost_type": prognose or {},
                "room_by_cost_type": raeume or {},
                "kwh_histories_by_cost_type": kwh_historien,
                "kwh_totals_by_cost_type": kwh_summen,
            }

            # Statistik-Bereinigung und Backfill
            uid = self.entry.unique_id or self.entry.entry_id
            self._veraltete_statistiken_entfernen(uid)
            self._kwh_historien_backfill(uid, kwh_historien)

            _LOGGER.debug(
                "Brunata München – Daten aktualisiert: "
                "%d Zähler, %d Monatsserien, %d KW-Zähler, "
                "%d Vergleiche, %d Prognosen, %d Räume",
                len(zaehlerstaende or {}),
                len(monatsdaten),
                len(kaltwasser),
                len(vergleich or {}),
                len(prognose or {}),
                len(raeume or {}),
            )

            return ergebnis

        except LoginError as fehler:
            raise ConfigEntryAuthFailed(
                "Brunata München Authentifizierung fehlgeschlagen"
            ) from fehler
        except (httpx.HTTPError, TimeoutError) as fehler:
            raise UpdateFailed(
                f"Brunata München Verbindungsfehler: {fehler}"
            ) from fehler
        except Exception as fehler:
            raise UpdateFailed(
                f"Unerwarteter Brunata München Fehler: {fehler}"
            ) from fehler

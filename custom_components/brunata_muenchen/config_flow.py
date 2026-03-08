"""Config Flow für die Brunata München Integration.

Ermöglicht die Einrichtung über die Home Assistant UI mit Login-Validierung
und bietet einen Options Flow zum Anpassen des Update-Intervalls.
"""

from __future__ import annotations

import logging
from typing import Any

from brunata_api import BrunataClient
from brunata_api.errors import LoginError
import httpx
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers.selector import DurationSelector, DurationSelectorConfig
import voluptuous as vol

from .const import (
    CONF_BASE_URL,
    CONF_SAP_CLIENT,
    CONF_SAP_LANGUAGE,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_SAP_CLIENT,
    DEFAULT_SAP_LANGUAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Mindest-Intervall für Updates (in Sekunden)
_MIN_INTERVALL_SEKUNDEN = 60


def _sekunden_als_dauer(gesamt_sekunden: int) -> dict[str, int]:
    """Wandle Sekunden in die Struktur für den DurationSelector um."""
    gesamt = max(0, int(gesamt_sekunden))
    tage, rest = divmod(gesamt, 86400)
    stunden, rest = divmod(rest, 3600)
    minuten, sekunden = divmod(rest, 60)
    return {"days": tage, "hours": stunden, "minutes": minuten, "seconds": sekunden}


async def _zugangsdaten_pruefen(
    hass: HomeAssistant, eingabe: dict[str, Any]
) -> str:
    """Prüfe die Zugangsdaten und gib die eindeutige Nutzereinheit-ID zurück.

    Raises:
        LoginError: Bei ungültigen Zugangsdaten oder fehlender NutzerID.
    """
    client = await hass.async_add_executor_job(
        lambda: BrunataClient(
            base_url=eingabe[CONF_BASE_URL],
            username=eingabe[CONF_USERNAME],
            password=eingabe[CONF_PASSWORD],
            sap_client=eingabe[CONF_SAP_CLIENT],
            sap_language=eingabe[CONF_SAP_LANGUAGE],
        )
    )
    try:
        konto = await client.get_account()
        nutzer_id = str(konto.get("UserUnitID") or "").strip()
        if not nutzer_id:
            raise LoginError("Keine UserUnitID im Account gefunden")
        return nutzer_id
    finally:
        await client.aclose()


# Fehlerkategorien für den Config Flow
_FEHLER_ZUORDNUNG: dict[type, str] = {
    LoginError: "invalid_auth",
    httpx.HTTPError: "cannot_connect",
    TimeoutError: "cannot_connect",
}


class BrunataMuenchenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Konfigurationsdialog für Brunata München."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Verarbeite den Einrichtungsdialog."""
        fehler: dict[str, str] = {}

        if user_input is not None:
            fehler_code = await self._validiere_eingabe(user_input)
            if fehler_code:
                fehler["base"] = fehler_code
            # Bei Erfolg wurde bereits ein Entry erstellt (return in _validiere)

            if not fehler:
                return await self._eintrag_erstellen(user_input)

        formular = vol.Schema(
            {
                vol.Optional(
                    CONF_BASE_URL, default=DEFAULT_BASE_URL
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                ),
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_SAP_CLIENT, default=DEFAULT_SAP_CLIENT): cv.string,
                vol.Optional(
                    CONF_SAP_LANGUAGE, default=DEFAULT_SAP_LANGUAGE
                ): cv.string,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=formular, errors=fehler
        )

    async def _validiere_eingabe(self, eingabe: dict[str, Any]) -> str | None:
        """Prüfe die Eingabe und gib den Fehlercode zurück (oder None bei Erfolg)."""
        try:
            self._nutzer_id = await _zugangsdaten_pruefen(self.hass, eingabe)
            return None
        except tuple(_FEHLER_ZUORDNUNG.keys()) as fehler:
            return _FEHLER_ZUORDNUNG.get(type(fehler), "unknown")
        except Exception:
            _LOGGER.exception("Unerwarteter Fehler bei der Brunata Validierung")
            return "unknown"

    async def _eintrag_erstellen(self, eingabe: dict[str, Any]) -> FlowResult:
        """Erstelle den Config Entry nach erfolgreicher Validierung."""
        await self.async_set_unique_id(self._nutzer_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Brunata München ({self._nutzer_id})",
            data=eingabe,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Options Flow für nachträgliche Einstellungen."""
        return BrunataMuenchenOptionsFlow(config_entry)


class BrunataMuenchenOptionsFlow(config_entries.OptionsFlow):
    """Einstellungsdialog für Brunata München (Update-Intervall)."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._eintrag = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Zeige den Einstellungsdialog oder speichere die Änderungen."""
        if user_input is not None:
            return self._intervall_speichern(user_input)

        aktuell = self._eintrag.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
        )
        if not isinstance(aktuell, (int, float)):
            aktuell = int(DEFAULT_SCAN_INTERVAL.total_seconds())

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=_sekunden_als_dauer(int(aktuell)),
                ): DurationSelector(DurationSelectorConfig(enable_day=True))
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    def _intervall_speichern(self, eingabe: dict[str, Any]) -> FlowResult:
        """Validiere und speichere das neue Update-Intervall."""
        dauer = cv.time_period(eingabe[CONF_SCAN_INTERVAL])
        sekunden = max(_MIN_INTERVALL_SEKUNDEN, int(dauer.total_seconds()))
        return self.async_create_entry(
            title="", data={CONF_SCAN_INTERVAL: sekunden}
        )
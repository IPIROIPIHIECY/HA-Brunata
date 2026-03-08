"""Brunata München Integration für Home Assistant."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import BrunataMuenchenCoordinator


def _entry_scan_interval(entry: ConfigEntry) -> timedelta:
    """Return entry scan interval as timedelta."""
    raw = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)
    if isinstance(raw, (int, float)):
        return timedelta(seconds=float(raw))
    if isinstance(raw, timedelta):
        return raw
    return DEFAULT_SCAN_INTERVAL


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Brunata München from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = BrunataMuenchenCoordinator(
        hass,
        entry=entry,
        update_interval=_entry_scan_interval(entry),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    coordinator: BrunataMuenchenCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.update_interval = _entry_scan_interval(entry)
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: BrunataMuenchenCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok
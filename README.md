# Brunata München Integration für Home Assistant

Diese Integration ermöglicht es, Verbrauchsdaten (Heizung, Warmwasser, Kaltwasser) aus dem **Brunata München Nutzerportal** direkt in Home Assistant einzubinden.

Die Integration erkennt automatisch alle in deinem Account hinterlegten Zähler und stellt sie als Sensoren zur Verfügung. Dank der korrekten Zuweisung von `device_class` und **automatischem Recorder-Backfill** können die Werte direkt im **Home Assistant Energie-Dashboard** verwendet werden – inklusive historischer Daten.

## 🚀 Features
- **Automatisches Discovery:** Erkennt alle Zähler (HZ01, WW01, KW01, etc.) ohne manuelle Konfiguration.
- **Energie-Dashboard Ready:** Unterstützung für Energie- (kWh) und Wasser-Entitäten (m³) mit historischem Backfill.
- **Verbrauchsvergleich:** Eigener Verbrauch (kWh/m²), Gebäudedurchschnitt und Bundesdurchschnitt.
- **Prognosen:** Aktueller Verbrauch (YTD), Vorjahr, Forecast und Mehrverbrauch.
- **Raum-Verbrauch:** Aufschlüsselung pro Raum und Kostenart.
- **Multi-Perioden:** Daten über alle historischen Abrechnungszeiträume (kein Reset im Energy Dashboard beim Jahreswechsel).
- **Konfigurierbares Update-Intervall:** Über den Options Flow nach der Einrichtung anpassbar (Standard: 1 Tag).
- **Sicheres Polling:** Nutzt einen effizienten Koordinator, um die Brunata-Server nicht zu überlasten.
- **Duplikat-Schutz:** Verhindert doppelte Konfigurationseinträge über eine eindeutige Account-ID.
- **Einfache Einrichtung:** Konfiguration direkt über die Home Assistant Benutzeroberfläche (Config Flow).

## 🛠 Basis
Diese Integration basiert auf dem Python-Client **[brunata-nutzerportal-api](https://github.com/fjfricke/brunata-api)** von fjfricke. Ohne diese Vorarbeit bei der Entschlüsselung der SAP OData-Schnittstelle wäre diese Integration nicht möglich gewesen.

## 📦 Installation

### Über HACS (Empfohlen)
1. Öffne **HACS** in deinem Home Assistant.
2. Klicke auf die drei Punkte oben rechts und wähle **Benutzerdefinierte Repositories**.
3. Füge die URL dieses Repositories hinzu und wähle als Kategorie `Integration`.
4. Suche nach `Brunata München` und klicke auf **Herunterladen**.
5. Starte Home Assistant neu.

### Manuell
1. Lade dieses Repository als ZIP-Datei herunter.
2. Kopiere den Ordner `custom_components/brunata_muenchen` in dein `config/custom_components/` Verzeichnis.
3. Starte Home Assistant neu.

## ⚙️ Konfiguration
1. Gehe zu **Einstellungen** -> **Geräte & Dienste**.
2. Klicke auf **Integration hinzufügen** unten rechts.
3. Suche nach **Brunata München**.
4. Gib deine Zugangsdaten ein:
   - **Portal URL**: `https://nutzerportal.brunata-muenchen.de`
   - **E-Mail / Benutzername**: Deine E-Mail vom Brunata Portal.
   - **Passwort**: Dein Portal-Passwort.
   - **SAP Mandant**: In der Regel `201`.
   - **SAP Sprache**: In der Regel `DE`.

### Update-Intervall ändern
Nach der Einrichtung kannst du das Update-Intervall unter **Einstellungen** -> **Geräte & Dienste** -> **Brunata München** -> **Optionen** anpassen.

## 📊 Sensoren
Nach erfolgreicher Einrichtung werden folgende Sensoren (je nach Verfügbarkeit in deinem Account) angelegt:

| Sensor | Beschreibung | Einheit |
|---|---|---|
| Heizung – HZxx – Zählerstand | Aktueller Zählerstand | kWh |
| Heizung – HZxx – Monatsverbrauch | Monatlicher Verbrauch | kWh |
| Heizung – HZxx – Verbrauch (kumulativ) | Kumulativer Verbrauch über alle Perioden | kWh |
| Warmwasser – WWxx – Zählerstand | Aktueller Zählerstand | m³ |
| Warmwasser – WWxx – Monatsverbrauch | Monatlicher Verbrauch | kWh |
| Kaltwasser – KWxx – Zählerstand | Aktueller Zählerstand | m³ |
| Verbrauch (kWh/m²) | Eigener Verbrauch pro m² | kWh/m² |
| Gebäudedurchschnitt | Durchschnitt des Gebäudes | kWh/m² |
| Bundesdurchschnitt | Nationaler Durchschnitt | kWh/m² |
| Aktuell (YTD) | Verbrauch im laufenden Jahr | kWh |
| Vorjahr | Verbrauch im Vorjahr | kWh |
| Prognose | Hochrechnung auf das Gesamtjahr | kWh |
| Mehrverbrauch | Differenz zur Prognose | kWh |
| Raum: [Name] | Verbrauch pro Raum | - |
| Dashboard-Perioden | Verfügbare Abrechnungsperioden (Diagnostik) | - |

## 🔋 Energie-Dashboard
Die kumulativen kWh-Sensoren werden automatisch als externe Statistiken in den HA Recorder importiert. Dadurch sind historische Daten sofort im Energie-Dashboard verfügbar – auch rückwirkend.

## ⚠️ Disclaimer
Dies ist eine inoffizielle Integration. Sie steht in keiner Verbindung zur BRUNATA-METRONA GmbH oder BRUdirekt. Die Nutzung erfolgt auf eigene Gefahr. Alle Markennamen gehören ihren jeweiligen Eigentümern.
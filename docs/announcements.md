# FITAGE v1.4.1 announcement drafts

These texts are final drafts for review. Nothing in this file has been published. FITAGE is an independent custom integration and is not affiliated with or supported by Home Assistant, FITAGE, QingNiu, or QNClouds. FITAGE v1.4.1 requires Home Assistant 2025.12.0 or newer.

## Home Assistant Community Forum

Target category: **Share your Projects**

### Title

```text
FITAGE – Home Assistant integration for FITAGE/QNClouds smart scales
```

### Post

```markdown
I would like to share FITAGE v1.4.1, an independent Home Assistant custom integration for measurements available through the FITAGE/QNClouds cloud. It requires Home Assistant 2025.12.0 or newer.

FITAGE represents each linked profile as a separate Home Assistant device and exposes the data returned for that profile, including weight, BMI, body-composition measurements, heart rate, goals, and scale information. Existing entity IDs remain stable when upgrading.

![FITAGE integration overview with two fictional profiles](https://raw.githubusercontent.com/lampje25/ha-fitage/main/docs/images/fitage-integration-overview.png)

Version 1.4.1 synchronizes historical measurements while preserving their exact source timestamps. Administrators can query exact locally stored history through privacy-filtered, read-only websocket commands. Selected profiles can also be published as long-term statistics for native Recorder graphs. Because body-composition history is health data, statistics are disabled by default and require an explicit opt-in.

![Fictional FITAGE history dashboard for weight, BMI, and body fat](https://raw.githubusercontent.com/lampje25/ha-fitage/main/docs/images/fitage-history-dashboard.png)

Highlights:

- multiple linked profiles, each with its own device;
- weight, BMI, body-composition, heart-rate, goal, and scale sensors when supplied by the cloud;
- incremental historical synchronization with exact timestamps;
- admin-only exact-history access without exposing FITAGE user IDs;
- optional long-term statistics with readable profile and metric names;
- explicit privacy opt-in for Recorder statistics.

![FITAGE statistics privacy option disabled by default](https://raw.githubusercontent.com/lampje25/ha-fitage/main/docs/images/fitage-statistics-privacy-option.png)

### Install through HACS as a custom repository

1. Open HACS.
2. Open **Custom repositories**.
3. Add `https://github.com/lampje25/ha-fitage`.
4. Select **Integration** as the type.
5. Install FITAGE.
6. Restart Home Assistant.
7. Add FITAGE through **Settings → Devices & services**.

A request to include FITAGE in the default HACS repository list is [open and still pending](https://github.com/hacs/default/pull/10599). The custom-repository step will no longer be needed if that request is accepted. FITAGE is not currently available in the default HACS list.

Release: https://github.com/lampje25/ha-fitage/releases/tag/v1.4.1

Repository and documentation: https://github.com/lampje25/ha-fitage

For support, feedback, and compatibility reports, please use GitHub Issues: https://github.com/lampje25/ha-fitage/issues. Do not include credentials, account identifiers, email addresses, device identifiers, or real health data in reports.

This is an independent community custom integration. It is not an official Home Assistant integration and is not affiliated with or supported by Home Assistant, FITAGE, QingNiu, or QNClouds.
```

## Reddit (`r/homeassistant`)

### Title

```text
FITAGE smart scale integration for Home Assistant – history and long-term statistics
```

### Post

```markdown
I have released FITAGE v1.4.1, an independent Home Assistant custom integration for measurements available through the FITAGE/QNClouds cloud. It requires Home Assistant 2025.12.0 or newer.

It supports separate devices for multiple profiles, weight and body-composition sensors, historical measurements with their exact source timestamps, and optional long-term Recorder statistics. Statistics are disabled by default and require an explicit privacy opt-in. Existing entity IDs remain stable when upgrading.

![Fictional FITAGE history dashboard for weight, BMI, and body fat](https://raw.githubusercontent.com/lampje25/ha-fitage/main/docs/images/fitage-history-dashboard.png)

Install it through HACS as a custom repository:

1. Open **Custom repositories** in HACS.
2. Add `https://github.com/lampje25/ha-fitage` as an **Integration**.
3. Install FITAGE, restart Home Assistant, and add it through **Settings → Devices & services**.

The request for inclusion in the default HACS list is still pending: https://github.com/hacs/default/pull/10599

GitHub and release: https://github.com/lampje25/ha-fitage

Feedback and compatibility reports are welcome through GitHub Issues: https://github.com/lampje25/ha-fitage/issues

FITAGE is an independent custom integration, not an official Home Assistant or FITAGE integration.
```

## Nederlandse Home Assistant Facebookgroep

```markdown
Voor gebruikers van een slimme weegschaal waarvan de metingen via FITAGE/QNClouds beschikbaar zijn, is FITAGE v1.4.1 uitgebracht als custom integration voor Home Assistant 2025.12.0 en nieuwer.

De integratie maakt per gekoppeld profiel een apart apparaat aan en toont onder andere gewicht, BMI, lichaamssamenstelling, hartslag en doelen als deze door de cloud worden geleverd. Historische metingen behouden hun oorspronkelijke tijdstip. Je kunt geselecteerde profielen optioneel als langetermijnstatistieken in Recorder gebruiken; vanwege de privacy van gezondheidsdata staat dit standaard uit en moet je het bewust inschakelen. Bestaande entity-ID’s blijven bij een upgrade stabiel.

Installeren kan via HACS als custom repository: open **Custom repositories**, voeg `https://github.com/lampje25/ha-fitage` toe als **Integration**, installeer FITAGE, herstart Home Assistant en voeg FITAGE toe via **Instellingen → Apparaten & diensten**.

De aanvraag voor opname in de standaardlijst van HACS is nog in behandeling. Als die wordt geaccepteerd, vervalt de stap met de custom repository.

GitHub: https://github.com/lampje25/ha-fitage

Dit is een onafhankelijke custom integration en geen officiële integratie van Home Assistant, FITAGE of QNClouds. Ervaringen en compatibiliteitsmeldingen zijn welkom via GitHub Issues.
```

Suggested image: `docs/images/fitage-integration-overview.png`

## Korte persoonlijke Facebook- of LinkedIn-post

```text
FITAGE v1.4.1 voor Home Assistant is uit: meerdere profielen, lichaamssamenstelling en historische metingen met optionele langetermijnstatistieken. Privacy blijft voorop: Recorder-import staat standaard uit. Installeren kan via HACS als custom repository; de aanvraag voor de standaard HACS-lijst loopt nog. Meer informatie: https://github.com/lampje25/ha-fitage
```

## GitHub / Ko-fi update

```markdown
## FITAGE v1.4.1: history and long-term statistics

FITAGE v1.4.1 adds historical measurement synchronization while preserving exact source timestamps. Administrators can access exact locally stored history through privacy-filtered read-only websocket commands, and selected profiles can optionally publish readable long-term statistics to Home Assistant Recorder. Statistics remain disabled by default and require explicit opt-in. Existing entity IDs remain stable when upgrading.

A request to add FITAGE to the default HACS repository list is open and still pending. Until it is accepted, install FITAGE through HACS as a custom repository.

Thank you to everyone who tested the history and Recorder flows, reported issues, and shared feedback.

Release: https://github.com/lampje25/ha-fitage/releases/tag/v1.4.1

HACS request: https://github.com/hacs/default/pull/10599

Repository: https://github.com/lampje25/ha-fitage

If you would like to support continued open-source work: https://ko-fi.com/familiebeheer
```

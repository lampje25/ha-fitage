# Announcement drafts

These drafts are for review only. FITAGE is an independent custom integration and must not be presented as an official Home Assistant, FITAGE, QingNiu, or QNClouds integration.

## Home Assistant Community Forum

Target category: **Share your Projects**

### Title

```text
FITAGE: smart-scale body composition and historical measurements in Home Assistant
```

### Draft

```markdown
I would like to share FITAGE, an independent Home Assistant custom integration for people whose smart-scale measurements are available through the FITAGE/QNClouds cloud.

FITAGE creates separate devices for linked profiles and exposes the measurements returned by the cloud, including weight, BMI, body composition, heart rate, goals, and scale information. It uses the cloud connection rather than Bluetooth, so the FITAGE app can continue to be used alongside Home Assistant.

Version 1.4.0 adds historical synchronization with the original measurement timestamps. Exact stored history is available to administrators through read-only websocket commands. An optional long-term-statistics import makes selected metrics available to Recorder and standard Home Assistant graphs. Because this is health data, Recorder statistics are disabled by default and require an explicit profile-and-metric opt-in. Raw history remains in a private Home Assistant Store.

Highlights:

- multiple linked profiles, each represented by its own device;
- weight and body-composition sensors;
- incremental historical synchronization and deletion handling;
- exact historical timestamps;
- optional external long-term statistics with readable profile and metric names;
- privacy-filtered, admin-only exact-history access.

Installation through HACS:

1. Open HACS and choose **Custom repositories**.
2. Add `https://github.com/lampje25/ha-fitage` as an **Integration**.
3. Download FITAGE, restart Home Assistant, and add the integration under **Settings → Devices & services**.

Repository and documentation: https://github.com/lampje25/ha-fitage

[Screenshot: integration overview with fictional profiles]

[Screenshot: fictional body-composition sensors]

[Screenshot: fictional weight statistics graph]

Please report problems through GitHub Issues: https://github.com/lampje25/ha-fitage/issues. Do not include credentials, account identifiers, email addresses, device identifiers, or real health data in reports.

This is an independent community custom integration. It is not an official Home Assistant or FITAGE integration and is not affiliated with or supported by FITAGE, QingNiu, or QNClouds.
```

## Reddit (`r/homeassistant`)

### Title

```text
FITAGE smart-scale custom integration: multi-profile sensors and history for Home Assistant
```

### Draft

```markdown
I have released FITAGE v1.4.1, an independent Home Assistant custom integration for smart-scale data available through the FITAGE/QNClouds cloud.

It supports separate devices for multiple profiles, weight and body-composition sensors, and historical synchronization with the original timestamps. Selected profiles and metrics can optionally be imported as long-term Recorder statistics; that health-data feature is disabled by default and requires explicit opt-in.

Install it through HACS as a custom integration repository:
https://github.com/lampje25/ha-fitage

[Screenshot: fictional weight graph]

Issues and documentation are on GitHub. Please do not share credentials, identifiers, or real health data in issue reports.

This is a community custom integration, not an official Home Assistant or FITAGE integration.
```

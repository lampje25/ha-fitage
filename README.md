# FITAGE for Home Assistant

FITAGE is a custom integration that brings body-composition measurements from the FITAGE cloud into Home Assistant. It connects to the FITAGE/QNClouds backend with your FITAGE account; no Bluetooth or BLE connection to the scale is required. You can continue using the official FITAGE app normally alongside this integration.

This is an independent community project. It is not an official integration and is not affiliated with or supported by FITAGE, QingNiu, or QNClouds.

## Available sensors

Depending on the data returned for your profile and scale, the integration provides:

- Profile: account name, profile weight, height, birthday, and email
- Goals: weight, body-fat, and water goals returned by the cloud API
- Measurements: weight, BMI, body fat, body-fat mass, hydration, body-water mass, muscle percentage, muscle mass, muscle ratio, muscle storage capacity, protein percentage, protein mass, bone mass, bone ratio, fat-free weight, subcutaneous fat, visceral fat, BMR, metabolic age, health score, heart rate, timestamp, and body shape
- FITAGE report values: muscle control, fat control, weight control, and recommended weight
- Linked scale information

The report-control sensors reproduce the verified normal FITAGE calculation route (`mea_category = 0`). They are unavailable for unsupported measurement categories rather than using an unverified calculation.

## Installation with HACS

1. Install [HACS](https://hacs.xyz/) if it is not already available.
2. Open HACS in Home Assistant and select **Custom repositories** from the menu.
3. Add `https://github.com/lampje25/ha-fitage` with category **Integration**.
4. Find **FITAGE** in HACS and download it.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration**, search for **FITAGE**, and enter your FITAGE account credentials.

## Manual installation

Copy `custom_components/fitage` into the `custom_components` directory of your Home Assistant configuration, restart Home Assistant, and add **FITAGE** from **Settings → Devices & services**.

## How it works

The integration polls the FITAGE/QNClouds API for linked profiles, goals, devices, and the latest measurement. The cloud connection requires internet access and valid FITAGE account credentials. No direct BLE communication is performed.

For troubleshooting, inspect Home Assistant logs for `custom_components.fitage`. Please avoid sharing credentials, authorization headers, tokens, account identifiers, email addresses, or device MAC addresses in issue reports.

Issues can be reported at [lampje25/ha-fitage](https://github.com/lampje25/ha-fitage/issues).

## Origin and license

This integration is based on [Sanji78/feelfit](https://github.com/Sanji78/feelfit), used and adapted under the MIT License. The original copyright and license attribution are preserved in [LICENSE.md](LICENSE.md).

# Repository discoverability proposal

This is a reviewable proposal only. It does not change GitHub repository settings.

## Description

```text
Home Assistant custom integration for FITAGE/QNClouds smart scales with multiple profiles, body-composition sensors and historical statistics.
```

This names the supported cloud context and the principal verified features without implying official affiliation or broader hardware compatibility.

## Topics

Proposed final topic set:

```text
body-composition
fitage
fitage-scale
hacs
health
home-assistant
home-assistant-custom-component
qnclouds
smart-scale
weight
```

All describe implemented functionality or the repository's ecosystem. The existing `hacs-integration` topic is valid but redundant with `hacs` and `home-assistant-custom-component`; the proposal replaces it for a more specific set.

## Commands requiring later approval

Run only after rechecking the live settings and receiving explicit approval:

```shell
gh repo edit lampje25/ha-fitage \
  --description "Home Assistant custom integration for FITAGE/QNClouds smart scales with multiple profiles, body-composition sensors and historical statistics."

gh repo edit lampje25/ha-fitage \
  --remove-topic hacs-integration \
  --add-topic body-composition \
  --add-topic fitage \
  --add-topic fitage-scale \
  --add-topic hacs \
  --add-topic health \
  --add-topic home-assistant \
  --add-topic home-assistant-custom-component \
  --add-topic qnclouds \
  --add-topic smart-scale \
  --add-topic weight
```

No homepage change is proposed yet. The repository has no separate documentation website, and a redundant repository URL would not improve navigation. The README remains the documentation entry point.

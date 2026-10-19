# FITAGE v1.6.2

FITAGE v1.6.2 adds Home Assistant reauthentication for expired or rejected FITAGE credentials and updates installation guidance for the HACS default catalog.

## Reauthentication

When FITAGE reports an invalid or expired token, Home Assistant asks for the account password again. A successful login refreshes only the stored authentication token and expiry metadata. Existing profile selections, options, entity identities, history, and statistics are preserved.

Network failures remain retryable connection errors. Other FITAGE API failures do not trigger reauthentication.

## HACS

FITAGE is available directly from the standard HACS integration catalog. Adding the repository as a custom repository is no longer required. The bundled dashboard card remains at `v0.6.4`.
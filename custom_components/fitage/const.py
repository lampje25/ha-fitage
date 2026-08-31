"""Constants for the FITAGE integration."""

from datetime import timedelta

DOMAIN = "fitage"
PLATFORMS = ["sensor"]
LOGGER = "custom_components.fitage"

SCAN_INTERVAL = timedelta(seconds=120)

CONF_SELECTED_PROFILES = "selected_profiles"
CONF_PROFILES_LIST = "profiles_list"

PROFILE_METRICS = ("account_name", "weight", "height", "birthday", "email")
GOAL_METRICS = ("weight", "bodyfat", "water")
MEASUREMENT_METRICS = (
    "weight",
    "bodyfat",
    "bmi",
    "bmr",
    "bodyage",
    "fat_free_weight",
    "muscle",
    "protein",
    "sinew",
    "subfat",
    "visfat",
    "water",
    "bone",
    "heart_rate",
    "score",
    "time_stamp",
    "body_water_mass",
    "protein_mass",
    "body_fat_mass",
    "muscle_ratio",
    "bone_ratio",
    "muscle_storage_capacity",
    "body_shape",
    "muscle_control",
    "fat_control",
    "weight_control",
    "recommended_weight",
)

API_BASE = "https://fitage.qnclouds.com/api/v4"

DEFAULT_QUERY_PARAMS: dict[str, str] = {
    "app_revision": "4.16.0",
    "html_version": "14.16.0",
    "cellphone_type": "samsung SM-T510",
    "system_type": "11_30",
    "zone": "Europe/Amsterdam",
    "area_code": "NL",
    "locale": "nl",
    "app_id": "Fitage",
    "platform": "android",
}

PATH_LOGIN = "/users/sign_in"
PATH_USER_SETTINGS = "/user_settings/show_common_setting"
PATH_GOALS = "/goals/list_goal"
PATH_DEVICE_BINDS = "/device_binds/list_device_bind"
PATH_MEASUREMENTS = "/measurements/list_measurement"
PATH_GET_PRIMARY_USER = "/users/get_primary_user"

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC+25I2upukpfQ7rIaaTZtVE744
u2zV+HaagrUhDOTq8fMVf9yFQvEZh2/HKxFudUxP0dXUa8F6X4XmWumHdQnum3zm
Jr04fz2b2WCcN0ta/rbF2nYAnMVAk2OJVZAMudOiMWhcxV1nNJiKgTNNr13de0EQ
IiOL2CUBzu+HmIfUbQIDAQAB
-----END PUBLIC KEY-----"""

COMMON_HEADERS: dict[str, str] = {
    "Accept-Encoding": "gzip",
    "Connection": "Keep-Alive",
    "Host": "fitage.qnclouds.com",
    "User-Agent": "okhttp/4.9.1",
}

LOGIN_HEADERS: dict[str, str] = {
    **COMMON_HEADERS,
    "Authorization": "Bearer",
    "Content-Type": "application/json;charset=UTF-8",
}

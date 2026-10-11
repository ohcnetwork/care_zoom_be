from django.apps import AppConfig

PLUGIN_NAME = "care_zoom"


class CareZoomConfig(AppConfig):
    name = PLUGIN_NAME
    verbose_name = "Care Zoom"

    def ready(self):
        from care_zoom import signals  # noqa: F401

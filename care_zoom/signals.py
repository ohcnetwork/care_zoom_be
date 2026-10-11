from secrets import token_urlsafe

from django.db.models.signals import pre_save
from django.dispatch import receiver

from care.emr.models.scheduling.booking import TokenBooking
from care_zoom.appointments import eligibility


@receiver(pre_save, sender=TokenBooking)
def set_meeting_passcode(sender, instance, raw=False, **kwargs):
    if raw or not instance._state.adding or not eligibility(instance)[0]:
        return
    if isinstance(instance.meta, dict) and isinstance(
        instance.meta.get("care_zoom", {}), dict
    ):
        instance.meta.setdefault("care_zoom", {})["meeting_passcode"] = token_urlsafe(
            32
        )

"""Stateless appointment eligibility and Zoom Video SDK authorization."""

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

import jwt
from django.utils import timezone

from care_zoom.settings import plugin_settings

ALLOWED_STATUSES = {"booked", "arrived", "checked_in", "in_consultation"}


def configured():
    return bool(
        plugin_settings.ZOOM_ENABLED
        and plugin_settings.ZOOM_VIDEO_SDK_KEY
        and plugin_settings.ZOOM_VIDEO_SDK_SECRET
    )


def schedule_video_enabled(schedule):
    meta = schedule.meta
    config = meta.get("care_zoom") if isinstance(meta, dict) else None
    return isinstance(config, dict) and config.get("video_enabled") is True


def eligibility(booking, now=None):
    """One policy for both metadata and every token request; window is inclusive."""
    now = now or timezone.now()
    slot = booking.token_slot
    resource = slot.resource
    opens = slot.start_datetime - timedelta(minutes=15)
    closes = slot.end_datetime + timedelta(minutes=60)
    reason = None
    if resource.resource_type != "practitioner" or not resource.user_id:
        reason = "This appointment has no assigned practitioner."
    elif not resource.user.is_active:
        reason = "The assigned practitioner is inactive."
    elif not slot.availability_id or not schedule_video_enabled(
        slot.availability.schedule
    ):
        reason = "Video calls are not enabled for this appointment's schedule."
    elif booking.status not in ALLOWED_STATUSES:
        reason = "Video calls are unavailable for this appointment status."
    elif slot.end_datetime <= slot.start_datetime:
        reason = "This appointment has an invalid time range."
    eligible = reason is None
    if eligible and now < opens:
        reason = "This video appointment has not opened yet."
    elif eligible and now > closes:
        reason = "This video appointment has closed."
    return eligible, reason, opens, closes


def mint_token(booking, *, patient, now=None):
    now = now or timezone.now()
    person = booking.patient if patient else booking.token_slot.resource.user
    role = "participant" if patient else "host"
    session_key = str(booking.external_id)
    expires = int(now.timestamp()) + 1800
    claims = {
        "app_key": plugin_settings.ZOOM_VIDEO_SDK_KEY,
        "tpc": f"care-{session_key}",
        "session_key": session_key,
        "role_type": 0 if patient else 1,
        "version": 1,
        "iat": int(now.timestamp()) - 30,
        "exp": expires,
        # Zoom limits user_key to 36 characters; namespacing avoids staff/patient overlap.
        "user_key": str(uuid5(NAMESPACE_URL, f"care:{role}:{person.external_id}")),
        "video_webrtc_mode": 1,
        "audio_webrtc_mode": 1,
    }
    if plugin_settings.ZOOM_GEO_REGIONS:
        claims["geo_regions"] = plugin_settings.ZOOM_GEO_REGIONS
    display_name = person.name if patient else person.get_full_name() or person.username
    return {
        "token": jwt.encode(
            claims, plugin_settings.ZOOM_VIDEO_SDK_SECRET, algorithm="HS256"
        ),
        "session_name": claims["tpc"],
        "session_key": session_key,
        "display_name": display_name[:200],
        "role": role,
        "expires_at": timezone.datetime.fromtimestamp(
            expires, tz=timezone.get_current_timezone()
        ),
    }

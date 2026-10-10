from django.urls import path

from care_zoom.views import (
    AppointmentTokenView,
    AppointmentView,
    GuestAppointmentTokenView,
    GuestAppointmentView,
    OTPAppointmentTokenView,
    OTPAppointmentView,
    ScheduleVideoView,
)

urlpatterns = [
    path(
        "facility/<uuid:facility_id>/schedules/<uuid:schedule_id>/video/",
        ScheduleVideoView.as_view(),
        name="zoom-schedule-video",
    ),
    path(
        "appointments/<uuid:booking_id>/",
        AppointmentView.as_view(),
        name="zoom-appointment",
    ),
    path(
        "appointments/<uuid:booking_id>/token/",
        AppointmentTokenView.as_view(),
        name="zoom-token",
    ),
    path(
        "otp/appointments/<uuid:booking_id>/",
        OTPAppointmentView.as_view(),
        name="zoom-otp-appointment",
    ),
    path(
        "otp/appointments/<uuid:booking_id>/token/",
        OTPAppointmentTokenView.as_view(),
        name="zoom-otp-token",
    ),
    path(
        "guest/appointments/<uuid:booking_id>/",
        GuestAppointmentView.as_view(),
        name="zoom-guest-appointment",
    ),
    path(
        "guest/appointments/<uuid:booking_id>/token/",
        GuestAppointmentTokenView.as_view(),
        name="zoom-guest-token",
    ),
]

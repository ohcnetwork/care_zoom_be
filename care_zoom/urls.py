from django.urls import path

from care_zoom.views import (
    AppointmentTokenView,
    AppointmentView,
    OTPAppointmentTokenView,
    OTPAppointmentView,
)

urlpatterns = [
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
]

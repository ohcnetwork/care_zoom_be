"""Four read-only/token routes. Nothing writes appointment or encounter state."""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from care.emr.models.scheduling.booking import TokenBooking
from care.security.authorization import AuthorizationController
from config.patient_otp_authentication import (
    JWTTokenPatientAuthentication,
    OTPAuthenticatedPermission,
)

from care_zoom.appointments import configured, eligibility, mint_token


class ZoomUnavailable(APIException):
    status_code = 503
    default_detail = "Video appointments are not configured. Contact your care team."


class AppointmentBaseView(APIView):
    patient = False

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        response["Pragma"] = "no-cache"
        return response

    def get_booking(self, request, booking_id):
        # Related default managers do not filter soft-deleted rows in JOINs.
        bookings = (
            TokenBooking.objects.filter(
                deleted=False,
                patient__deleted=False,
                token_slot__deleted=False,
                token_slot__resource__deleted=False,
                token_slot__resource__resource_type="practitioner",
                token_slot__resource__facility__deleted=False,
            )
            .filter(
                Q(token_slot__resource__user__isnull=True)
                | Q(token_slot__resource__user__deleted=False),
            )
            .filter(
                Q(token_slot__availability__isnull=True)
                | Q(
                    token_slot__availability__deleted=False,
                    token_slot__availability__schedule__deleted=False,
                    token_slot__availability__schedule__resource__deleted=False,
                    token_slot__availability__schedule__resource__facility__deleted=False,
                ),
            )
            .select_related(
                "patient",
                "token_slot__resource__user",
                "token_slot__resource__facility",
                "token_slot__availability__schedule__resource",
            )
        )
        if self.patient:
            bookings = bookings.filter(patient__phone_number=request.user.phone_number)
        booking = get_object_or_404(bookings, external_id=booking_id)
        if not self.patient:
            if request.user.deleted or not request.user.is_active:
                raise PermissionDenied("Your staff account is inactive.")
            resource = booking.token_slot.resource
            if not AuthorizationController.call(
                "can_list_booking", resource, request.user
            ):
                raise PermissionDenied(
                    "You do not have permission to read this appointment."
                )
        return booking

    def caller_role(self, request, booking):
        if self.patient:
            return "participant"
        if booking.token_slot.resource.user_id == request.user.pk:
            return "host"
        return "observer"


class AppointmentView(AppointmentBaseView):
    def get(self, request, booking_id):
        booking = self.get_booking(request, booking_id)
        eligible, reason, opens, closes = eligibility(booking)
        role = self.caller_role(request, booking)
        is_configured = configured()
        if reason is None and role == "observer":
            reason = "Only the assigned practitioner can join this video appointment."
        if reason is None and not is_configured:
            reason = ZoomUnavailable.default_detail
        slot = booking.token_slot
        doctor = slot.resource.user
        response = Response(
            {
                "booking_id": booking.external_id,
                "status": booking.status,
                "patient_name": booking.patient.name,
                "practitioner_name": (doctor.get_full_name() or doctor.username)
                if doctor
                else "",
                "start_datetime": slot.start_datetime,
                "end_datetime": slot.end_datetime,
                "join_opens_at": opens,
                "join_closes_at": closes,
                "join_path": f"/teleconsult/{booking.external_id}",
                "eligible": eligible,
                "can_join": reason is None,
                "caller_role": role,
                "reason": reason,
                "configured": is_configured,
            }
        )
        if not self.patient:
            response.data["staff_context"] = {
                "facility_id": slot.resource.facility.external_id,
                "patient_id": booking.patient.external_id,
            }
        return response


class AppointmentTokenView(AppointmentBaseView):
    def post(self, request, booking_id):
        booking = self.get_booking(request, booking_id)
        if self.caller_role(request, booking) == "observer":
            raise PermissionDenied(
                "Only the assigned practitioner can join this video appointment."
            )
        now = timezone.now()
        _, reason, _, _ = eligibility(booking, now)
        if reason:
            raise ValidationError({"detail": reason})
        if not configured():
            raise ZoomUnavailable()
        return Response(mint_token(booking, patient=self.patient, now=now))


class OTPAppointmentView(AppointmentView):
    patient = True
    authentication_classes = [JWTTokenPatientAuthentication]
    permission_classes = [OTPAuthenticatedPermission]


class OTPAppointmentTokenView(AppointmentTokenView):
    patient = True
    authentication_classes = [JWTTokenPatientAuthentication]
    permission_classes = [OTPAuthenticatedPermission]

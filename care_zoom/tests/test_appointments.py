"""Run with CARE's isolated PostgreSQL test database, never a production database."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import jwt
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from care.emr.models.scheduling.booking import TokenBooking, TokenSlot
from care.emr.models.scheduling.schedule import (
    Availability,
    SchedulableResource,
    Schedule,
)
from care.security.permissions.schedule import SchedulePermissions
from care.utils.tests.base import CareAPITestBase
from config.patient_otp_token import PatientToken

TEST_KEY = "test-video-sdk-key"
TEST_SECRET = "test-video-sdk-secret-only-not-a-real-credential"
TEST_CONFIG = {
    "care_zoom": {"ZOOM_VIDEO_SDK_KEY": TEST_KEY, "ZOOM_VIDEO_SDK_SECRET": TEST_SECRET}
}


@override_settings(ROOT_URLCONF="config.urls", PLUGIN_CONFIGS=TEST_CONFIG)
class AppointmentTests(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.doctor = self.create_user(
            first_name="Assigned", last_name="Practitioner", is_active=True
        )
        self.other = self.create_user(is_active=True)
        self.facility = self.create_facility(user=self.doctor)
        self.organization = self.create_facility_organization(facility=self.facility)
        self.patient = self.create_patient(
            name="Video Patient", phone_number="+919999999999"
        )
        self.resource = SchedulableResource.objects.create(
            facility=self.facility,
            resource_type="practitioner",
            user=self.doctor,
        )
        self.schedule = Schedule.objects.create(
            resource=self.resource,
            name="Video appointments",
            valid_from=self.now - timedelta(days=1),
            valid_to=self.now + timedelta(days=1),
            is_public=True,
        )
        self.availability = Availability.objects.create(
            schedule=self.schedule,
            name="Appointments",
            slot_type="appointment",
            availability={},
        )
        self.slot = TokenSlot.objects.create(
            resource=self.resource,
            availability=self.availability,
            start_datetime=self.now,
            end_datetime=self.now + timedelta(minutes=30),
        )
        self.booking = TokenBooking.objects.create(
            token_slot=self.slot,
            patient=self.patient,
            status="booked",
        )
        role = self.create_role_with_permissions(
            [SchedulePermissions.can_list_booking.name]
        )
        self.attach_role_facility_organization_user(
            self.organization, self.doctor, role
        )
        self.attach_role_facility_organization_user(self.organization, self.other, role)
        self.staff(self.doctor)

    def staff(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}"
        )

    def otp(self, phone=None, expired=False):
        token = PatientToken()
        token["phone_number"] = phone or self.patient.phone_number
        if expired:
            token.set_exp(
                from_time=self.now - timedelta(hours=2), lifetime=timedelta(minutes=1)
            )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def url(self, *, otp=False, token=False, booking=None):
        name = "zoom-" + ("otp-" if otp else "") + ("token" if token else "appointment")
        return reverse(
            name, kwargs={"booking_id": (booking or self.booking).external_id}
        )

    def assert_denied_without_token(self, response, status):
        self.assertEqual(response.status_code, status, response.data)
        self.assertNotIn("token", response.data)
        self.assertNotIn("staff_context", response.data)
        self.assertEqual(response["Cache-Control"], "no-store")

    def claims(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        return jwt.decode(response.data["token"], TEST_SECRET, algorithms=["HS256"])

    def test_assigned_practitioner_and_patient_share_session_and_server_derived_roles(
        self,
    ):
        before = (self.booking.status, self.booking.associated_encounter_id)
        info = self.client.get(self.url())
        self.assertEqual(info.status_code, 200)
        self.assertTrue(info.data["can_join"])
        self.assertEqual(info.data["caller_role"], "host")
        self.assertEqual(
            info.data["join_path"], f"/teleconsult/{self.booking.external_id}"
        )
        self.assertNotIn("token", info.data)
        host = self.client.post(
            self.url(token=True), {"role_type": 0, "session_name": "attacker"}
        )
        host_claims = self.claims(host)
        self.otp()
        patient = self.client.post(
            self.url(otp=True, token=True), {"role_type": 1, "user_key": "attacker"}
        )
        patient_claims = self.claims(patient)
        for claims in (host_claims, patient_claims):
            self.assertEqual(claims["tpc"], f"care-{self.booking.external_id}")
            self.assertEqual(claims["session_key"], str(self.booking.external_id))
            self.assertEqual(claims["version"], 1)
            self.assertEqual(claims["app_key"], TEST_KEY)
            self.assertEqual(claims["exp"] - claims["iat"], 1830)
            self.assertAlmostEqual(
                claims["exp"] - timezone.now().timestamp(), 1800, delta=10
            )
            self.assertEqual(len(claims["user_key"]), 36)
            self.assertEqual(claims["video_webrtc_mode"], 1)
            self.assertEqual(claims["audio_webrtc_mode"], 1)
            self.assertNotIn("geo_regions", claims)
            self.assertNotIn(self.patient.phone_number, str(claims))
        self.assertEqual(host_claims["role_type"], 1)
        self.assertEqual(patient_claims["role_type"], 0)
        self.assertNotEqual(host_claims["user_key"], patient_claims["user_key"])
        self.assertEqual(host.data["display_name"], "Assigned Practitioner")
        self.assertEqual(patient.data["display_name"], "Video Patient")
        self.assertEqual(host["Cache-Control"], "no-store")
        self.booking.refresh_from_db()
        self.assertEqual(
            (self.booking.status, self.booking.associated_encounter_id), before
        )

    def test_booking_read_permission_does_not_grant_call_access(self):
        self.staff(self.other)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["eligible"])
        self.assertFalse(response.data["can_join"])
        self.assertEqual(response.data["caller_role"], "observer")
        self.assert_denied_without_token(self.client.post(self.url(token=True)), 403)

    def test_staff_route_context_is_only_returned_to_authorized_staff(self):
        for user in (self.doctor, self.other):
            with self.subTest(user=user.username):
                self.staff(user)
                response = self.client.get(self.url())
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json()["staff_context"],
                    {
                        "facility_id": str(self.facility.external_id),
                        "patient_id": str(self.patient.external_id),
                    },
                )
        self.otp()
        response = self.client.get(self.url(otp=True))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("staff_context", response.data)

    def test_assigned_practitioner_also_needs_booking_read_permission(self):
        self.doctor.facilityorganizationuser_set.all().delete()
        for token in (False, True):
            with self.subTest(token=token):
                response = (
                    self.client.post(self.url(token=True))
                    if token
                    else self.client.get(self.url())
                )
                self.assert_denied_without_token(response, 403)

    def test_unrelated_staff_cannot_read(self):
        self.staff(self.create_user(is_active=True))
        self.assert_denied_without_token(self.client.get(self.url()), 403)

    def test_unrelated_phone_cannot_read_or_mint_even_with_caller_supplied_scope(self):
        self.otp("+918888888888")
        self.assert_denied_without_token(
            self.client.get(
                self.url(otp=True), {"patient": str(self.patient.external_id)}
            ),
            404,
        )
        self.assert_denied_without_token(
            self.client.post(
                self.url(otp=True, token=True),
                {"phone_number": self.patient.phone_number},
            ),
            404,
        )

    def test_shared_family_phone_is_authorized_like_care_patient_portal(self):
        family_patient = self.create_patient(
            name="Family Patient", phone_number=self.patient.phone_number
        )
        family_booking = TokenBooking.objects.create(
            token_slot=self.slot, patient=family_patient, status="booked"
        )
        self.otp()
        response = self.client.post(
            self.url(otp=True, token=True, booking=family_booking)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["display_name"], "Family Patient")

    def test_missing_invalid_expired_and_wrong_token_types_are_rejected(self):
        for header in (None, "Bearer invalid"):
            self.client.credentials(
                **({"HTTP_AUTHORIZATION": header} if header else {})
            )
            for otp in (False, True):
                for token in (False, True):
                    with self.subTest(header=header, otp=otp, token=token):
                        url = self.url(otp=otp, token=token)
                        response = (
                            self.client.post(url) if token else self.client.get(url)
                        )
                        self.assertIn(response.status_code, (401, 403))
                        self.assertNotIn("token", response.data)
        self.otp(expired=True)
        self.assert_denied_without_token(
            self.client.post(self.url(otp=True, token=True)), 401
        )
        self.otp()
        self.assert_denied_without_token(self.client.post(self.url(token=True)), 403)
        self.staff(self.doctor)
        self.assert_denied_without_token(
            self.client.post(self.url(otp=True, token=True)), 401
        )

    def test_all_appointment_statuses_use_the_same_policy_for_both_roles(self):
        allowed = {"booked", "arrived", "checked_in", "in_consultation"}
        denied = {
            "proposed",
            "pending",
            "fulfilled",
            "cancelled",
            "noshow",
            "entered_in_error",
            "waitlist",
            "rescheduled",
        }
        for status in sorted(allowed | denied):
            self.booking.status = status
            self.booking.save(update_fields=["status"])
            for otp in (False, True):
                with self.subTest(status=status, otp=otp):
                    self.otp() if otp else self.staff(self.doctor)
                    metadata = self.client.get(self.url(otp=otp))
                    self.assertEqual(metadata.status_code, 200)
                    self.assertEqual(metadata.data["eligible"], status in allowed)
                    response = self.client.post(self.url(otp=otp, token=True))
                    self.assertEqual(
                        response.status_code, 200 if status in allowed else 400
                    )

    def test_exact_inclusive_issuance_boundaries(self):
        opens = self.slot.start_datetime - timedelta(minutes=15)
        closes = self.slot.end_datetime + timedelta(minutes=60)
        for now, allowed in (
            (opens - timedelta(microseconds=1), False),
            (opens, True),
            (closes, True),
            (closes + timedelta(microseconds=1), False),
        ):
            for otp in (False, True):
                with (
                    self.subTest(now=now, otp=otp),
                    patch("care_zoom.appointments.timezone.now", return_value=now),
                ):
                    self.otp() if otp else self.staff(self.doctor)
                    metadata = self.client.get(self.url(otp=otp))
                    self.assertTrue(metadata.data["eligible"])
                    self.assertEqual(metadata.data["can_join"], allowed)
                    response = self.client.post(self.url(otp=otp, token=True))
                    self.assertEqual(response.status_code, 200 if allowed else 400)

    def test_deleted_scheduling_records_are_never_returned(self):
        for obj in (
            self.booking,
            self.patient,
            self.slot,
            self.resource,
            self.facility,
            self.doctor,
            self.availability,
            self.schedule,
        ):
            with self.subTest(model=type(obj).__name__):
                obj.deleted = True
                obj.save(update_fields=["deleted"])
                self.staff(self.other)
                self.assert_denied_without_token(self.client.get(self.url()), 404)
                self.assert_denied_without_token(
                    self.client.post(self.url(token=True)), 404
                )
                self.otp()
                self.assert_denied_without_token(
                    self.client.get(self.url(otp=True)), 404
                )
                self.assert_denied_without_token(
                    self.client.post(self.url(otp=True, token=True)), 404
                )
                obj.deleted = False
                obj.save(update_fields=["deleted"])

    def test_no_availability_or_encounter_is_required(self):
        self.slot.availability = None
        self.slot.save(update_fields=["availability"])
        self.assertIsNone(self.booking.associated_encounter_id)
        self.assertEqual(self.client.post(self.url(token=True)).status_code, 200)

    def test_missing_or_inactive_practitioner_cannot_issue_tokens(self):
        self.otp()
        self.resource.user = None
        self.resource.save(update_fields=["user"])
        self.assertFalse(self.client.get(self.url(otp=True)).data["eligible"])
        self.assert_denied_without_token(
            self.client.post(self.url(otp=True, token=True)), 400
        )
        self.staff(self.other)
        # Missing assignment must not crash the core booking permission controller.
        self.assertIn(self.client.get(self.url()).status_code, (200, 403))
        self.assert_denied_without_token(self.client.post(self.url(token=True)), 403)
        self.otp()
        self.resource.user = self.doctor
        self.resource.save(update_fields=["user"])
        self.doctor.is_active = False
        self.doctor.save(update_fields=["is_active"])
        self.assertFalse(self.client.get(self.url(otp=True)).data["eligible"])
        self.assert_denied_without_token(
            self.client.post(self.url(otp=True, token=True)), 400
        )

    def test_non_practitioner_resource_cannot_issue_tokens(self):
        self.resource.resource_type = "location"
        self.resource.save(update_fields=["resource_type"])
        self.otp()
        self.assert_denied_without_token(self.client.get(self.url(otp=True)), 404)
        self.assert_denied_without_token(
            self.client.post(self.url(otp=True, token=True)), 404
        )
        self.staff(self.doctor)
        self.assert_denied_without_token(self.client.get(self.url()), 404)
        self.assert_denied_without_token(self.client.post(self.url(token=True)), 404)

    def test_reassignment_reauthorizes_each_request(self):
        original = self.client.post(self.url(token=True))
        self.assertEqual(original.status_code, 200)
        self.resource.user = self.other
        self.resource.save(update_fields=["user"])
        self.assert_denied_without_token(self.client.post(self.url(token=True)), 403)
        self.staff(self.other)
        replacement = self.client.post(self.url(token=True))
        self.assertEqual(replacement.status_code, 200)
        self.assertNotEqual(
            self.claims(original)["user_key"], self.claims(replacement)["user_key"]
        )
        # Stateless issuance cannot revoke the token that was already issued.
        self.assertEqual(self.claims(original)["role_type"], 1)

    def test_rescheduled_old_link_is_rejected_and_new_booking_has_new_session(self):
        self.booking.status = "rescheduled"
        self.booking.save(update_fields=["status"])
        replacement = TokenBooking.objects.create(
            token_slot=self.slot, patient=self.patient, status="booked"
        )
        self.assert_denied_without_token(self.client.post(self.url(token=True)), 400)
        self.otp()
        self.assert_denied_without_token(
            self.client.post(self.url(otp=True, token=True)), 400
        )
        new = self.claims(
            self.client.post(self.url(otp=True, token=True, booking=replacement))
        )
        self.assertEqual(new["tpc"], f"care-{replacement.external_id}")
        self.assertNotEqual(new["session_key"], str(self.booking.external_id))

    def test_phone_ownership_is_rechecked_before_issuing_another_token(self):
        self.otp()
        self.assertEqual(
            self.client.post(self.url(otp=True, token=True)).status_code, 200
        )
        self.patient.phone_number = "+918888888888"
        self.patient.save(update_fields=["phone_number"])
        self.assert_denied_without_token(
            self.client.post(self.url(otp=True, token=True)), 404
        )

    def test_invalid_slot_interval_is_not_joinable(self):
        self.slot.end_datetime = self.slot.start_datetime
        self.slot.save(update_fields=["end_datetime"])
        self.otp()
        self.assertFalse(self.client.get(self.url(otp=True)).data["eligible"])
        self.assert_denied_without_token(
            self.client.post(self.url(otp=True, token=True)), 400
        )

    def test_unknown_booking_and_malformed_uuid(self):
        self.assertEqual(
            self.client.get(f"/api/care_zoom/appointments/{uuid4()}/").status_code, 404
        )
        self.assertEqual(
            self.client.get("/api/care_zoom/appointments/not-a-uuid/").status_code, 404
        )

    @override_settings(
        PLUGIN_CONFIGS={
            "care_zoom": {
                "ZOOM_ENABLED": True,
                "ZOOM_VIDEO_SDK_KEY": "",
                "ZOOM_VIDEO_SDK_SECRET": "",
            }
        }
    )
    def test_missing_configuration_is_explicit_and_returns_no_token(self):
        response = self.client.get(self.url())
        self.assertTrue(response.data["eligible"])
        self.assertFalse(response.data["configured"])
        self.assertFalse(response.data["can_join"])
        self.assert_denied_without_token(self.client.post(self.url(token=True)), 503)

    @override_settings(
        PLUGIN_CONFIGS={
            "care_zoom": {**TEST_CONFIG["care_zoom"], "ZOOM_GEO_REGIONS": "IN"}
        }
    )
    def test_optional_configured_region(self):
        self.assertEqual(
            self.claims(self.client.post(self.url(token=True)))["geo_regions"], "IN"
        )

    def test_info_endpoint_cannot_mint_and_token_endpoint_cannot_get(self):
        self.assertEqual(self.client.post(self.url()).status_code, 405)
        self.assertEqual(self.client.get(self.url(token=True)).status_code, 405)

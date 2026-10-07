"""The browser verification fixture must satisfy the core appointment contracts."""

from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.utils import timezone
from model_bakery import baker
from rest_framework_simplejwt.tokens import AccessToken

from care.emr.models.patient import PatientIdentifier, PatientIdentifierConfig
from care.emr.models.scheduling.booking import TokenBooking
from care.emr.models.scheduling.schedule import Schedule
from care.emr.resources.scheduling.schedule.spec import AvailabilityForScheduleSpec
from care.security.permissions.schedule import SchedulePermissions
from care.utils.tests.base import CareAPITestBase
from care_zoom.tests.seed_local import fixture_id, seed


@override_settings(DEBUG=True, ROOT_URLCONF="config.urls")
class LocalSeedTests(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.doctor = self.create_user(username="care-doctor", is_active=True)
        self.role = self.create_role_with_permissions(
            [
                SchedulePermissions.can_list_booking.name,
                SchedulePermissions.can_list_schedule.name,
                SchedulePermissions.can_write_schedule.name,
            ]
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(self.doctor)}"
        )

    def seed_and_read(self):
        with redirect_stdout(StringIO()):
            seed()
        booking = TokenBooking.objects.get(external_id=fixture_id("booking"))
        facility = booking.token_slot.resource.facility
        if not self.doctor.facilityorganizationuser_set.filter(role=self.role).exists():
            self.attach_role_facility_organization_user(
                facility.default_internal_organization, self.doctor, self.role
            )
        base = f"/api/v1/facility/{facility.external_id}"
        appointment = self.client.get(f"{base}/appointments/{booking.external_id}/")
        self.assertEqual(appointment.status_code, 200, appointment.data)
        self.assertIsInstance(appointment.data["note"], str)
        self.assertIsInstance(appointment.data["patient"]["facility_identifiers"], list)
        schedules = self.client.get(
            f"{base}/schedule/",
            {"resource_type": "practitioner", "resource_id": self.doctor.external_id},
        )
        self.assertEqual(schedules.status_code, 200, schedules.data)
        self.assertEqual(schedules.data["count"], 1)
        availability = schedules.data["results"][0]["availabilities"][0]
        # Fixture UUIDs are deterministic UUID5; validate the editable fields
        # against core's input schema, without its UUID4 identifier constraint.
        spec = AvailabilityForScheduleSpec.model_validate(
            {key: value for key, value in availability.items() if key != "id"}
        )
        self.assertEqual(len(spec.availability), 1)
        window = spec.availability[0]
        self.assertEqual(
            window.day_of_week,
            timezone.localtime(booking.token_slot.start_datetime).weekday(),
        )
        self.assertEqual(
            window.start_time,
            timezone.localtime(booking.token_slot.start_datetime).time(),
        )
        self.assertEqual(
            window.end_time, timezone.localtime(booking.token_slot.end_datetime).time()
        )
        return booking, appointment.data

    def test_new_and_legacy_fixture_are_valid_and_preserve_existing_data(self):
        booking, data = self.seed_and_read()
        self.assertEqual(data["patient"]["gender"], "male")
        self.assertEqual(data["patient"]["date_of_birth"], "1990-01-01")
        availability = booking.token_slot.availability
        schedule = availability.schedule
        schedule.external_id = fixture_id("schedule")
        schedule.save(update_fields=["external_id"])
        availability.availability = {}
        availability.reason = None
        availability.save(update_fields=["availability", "reason"])
        booking.note = None
        booking.save(update_fields=["note"])
        patient = booking.patient
        patient.facility_identifiers = {}
        patient.gender = ""
        patient.date_of_birth = None
        patient.year_of_birth = None
        patient.save(
            update_fields=[
                "facility_identifiers",
                "gender",
                "date_of_birth",
                "year_of_birth",
            ]
        )
        booking, data = self.seed_and_read()
        self.assertEqual(data["note"], "")
        self.assertEqual(data["patient"]["gender"], "male")
        self.assertEqual(data["patient"]["date_of_birth"], "1990-01-01")
        schedule.refresh_from_db()
        self.assertEqual(schedule.external_id.version, 4)
        self.assertEqual(booking.token_slot.availability.schedule_id, schedule.pk)
        self.assertEqual(Schedule.objects.count(), 1)
        booking.note = "Keep this test appointment note"
        booking.save(update_fields=["note"])
        patient = booking.patient
        patient.gender = "female"
        patient.date_of_birth = date(1985, 2, 3)
        patient.year_of_birth = 1985
        patient.save(update_fields=["gender", "date_of_birth", "year_of_birth"])
        facility = booking.token_slot.resource.facility
        config = baker.make(
            PatientIdentifierConfig,
            facility=facility,
            status="active",
            config={"display": "Test MRN", "system": "urn:zoom:test:mrn"},
        )
        identifier = PatientIdentifier.objects.create(
            patient=patient, facility=facility, config=config, value="ZOOM-123"
        )
        _, data = self.seed_and_read()
        self.assertEqual(data["note"], "Keep this test appointment note")
        self.assertEqual(data["patient"]["gender"], "female")
        self.assertEqual(data["patient"]["date_of_birth"], "1985-02-03")
        self.assertIn(
            identifier.value,
            [item["value"] for item in data["patient"]["facility_identifiers"]],
        )
        self.assertEqual(
            TokenBooking.objects.filter(external_id=fixture_id("booking")).count(), 1
        )
        identifier.refresh_from_db()
        self.assertEqual(identifier.value, "ZOOM-123")

    def test_late_night_fixture_does_not_make_an_invalid_midnight_availability(self):
        now = datetime(2026, 10, 7, 23, 45, tzinfo=ZoneInfo("Asia/Kolkata"))
        with (
            timezone.override("Asia/Kolkata"),
            patch("care_zoom.tests.seed_local.timezone.now", return_value=now),
        ):
            booking, _ = self.seed_and_read()
        self.assertLess(booking.token_slot.start_datetime, now)
        self.assertGreater(booking.token_slot.end_datetime + timedelta(hours=1), now)

    def test_fixture_schedule_accepts_a_new_availability_through_core_api(self):
        booking, _ = self.seed_and_read()
        existing = booking.token_slot.availability
        schedule = existing.schedule
        facility = booking.token_slot.resource.facility
        response = self.client.post(
            f"/api/v1/facility/{facility.external_id}/schedule/{schedule.external_id}/availability/",
            {
                "name": "Extra test availability",
                "slot_type": "appointment",
                "slot_size_in_minutes": 30,
                "tokens_per_slot": 1,
                "availability": [
                    {
                        "day_of_week": (existing.availability[0]["day_of_week"] + 1)
                        % 7,
                        "start_time": "09:00:00",
                        "end_time": "10:00:00",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(schedule.availability_set.count(), 2)
        booking.refresh_from_db()
        self.assertEqual(booking.external_id, fixture_id("booking"))
        self.assertEqual(booking.token_slot.availability_id, existing.pk)

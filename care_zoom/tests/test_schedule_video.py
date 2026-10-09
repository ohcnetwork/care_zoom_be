"""Schedule video opt-in uses CARE schedule permissions and preserves metadata."""

from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from care.emr.models.scheduling.schedule import SchedulableResource, Schedule
from care.security.permissions.schedule import SchedulePermissions
from care.utils.lock import Lock
from care.utils.tests.base import CareAPITestBase
from config.patient_otp_token import PatientToken


@override_settings(ROOT_URLCONF="config.urls")
class ScheduleVideoTests(CareAPITestBase):
    def setUp(self):
        super().setUp()
        self.doctor = self.create_user(is_active=True)
        self.editor = self.create_user(is_active=True)
        self.facility = self.create_facility(user=self.doctor)
        self.organization = self.create_facility_organization(facility=self.facility)
        self.resource = SchedulableResource.objects.create(
            facility=self.facility, resource_type="practitioner", user=self.doctor
        )
        self.schedule = Schedule.objects.create(
            resource=self.resource,
            name="Clinic appointments",
            valid_from=timezone.now(),
            valid_to=timezone.now() + timedelta(days=1),
            created_by=self.doctor,
        )
        self.grant(
            self.doctor,
            SchedulePermissions.can_list_schedule.name,
            SchedulePermissions.can_write_schedule.name,
        )
        self.grant(
            self.editor,
            SchedulePermissions.can_list_schedule.name,
            SchedulePermissions.can_write_schedule.name,
        )
        self.staff(self.editor)
        self.url = self.schedule_url(self.facility)

    def schedule_url(self, facility):
        return reverse(
            "zoom-schedule-video",
            kwargs={
                "facility_id": facility.external_id,
                "schedule_id": self.schedule.external_id,
            },
        )

    def grant(self, user, *permissions):
        role = self.create_role_with_permissions(list(permissions))
        self.attach_role_facility_organization_user(self.organization, user, role)

    def staff(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}"
        )

    def test_get_and_patch_preserve_unrelated_metadata_and_record_editor(self):
        self.schedule.meta = {
            "other_plugin": {"enabled": True},
            "care_zoom": {"retained": "value"},
        }
        self.schedule.save(update_fields=["meta"])
        before = self.schedule.modified_date
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.json(),
            {"schedule_id": str(self.schedule.external_id), "video_enabled": False},
        )
        for enabled in (True, False):
            response = self.client.patch(
                self.url, {"video_enabled": enabled}, format="json"
            )
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response["Cache-Control"], "no-store")
            self.assertEqual(response.data["video_enabled"], enabled)
            self.assertEqual(self.client.get(self.url).data["video_enabled"], enabled)
            self.schedule.refresh_from_db()
            self.assertEqual(
                self.schedule.meta,
                {
                    "other_plugin": {"enabled": True},
                    "care_zoom": {"retained": "value", "video_enabled": enabled},
                },
            )
        self.assertEqual(self.schedule.created_by, self.doctor)
        self.assertEqual(self.schedule.updated_by, self.editor)
        self.assertGreater(self.schedule.modified_date, before)

    def test_schedule_read_and_write_permissions_are_checked_independently(self):
        for permission, read_status, write_status in (
            (SchedulePermissions.can_list_schedule.name, 200, 403),
            (SchedulePermissions.can_write_schedule.name, 403, 200),
            (SchedulePermissions.can_list_booking.name, 403, 403),
        ):
            with self.subTest(permission=permission):
                user = self.create_user(is_active=True)
                self.grant(user, permission)
                self.staff(user)
                self.assertEqual(self.client.get(self.url).status_code, read_status)
                self.assertEqual(
                    self.client.patch(
                        self.url, {"video_enabled": True}, format="json"
                    ).status_code,
                    write_status,
                )
        self.staff(self.create_user(is_active=True))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(
            self.client.patch(
                self.url, {"video_enabled": True}, format="json"
            ).status_code,
            403,
        )

    def test_facility_scope_and_deleted_related_rows_are_enforced(self):
        wrong_url = self.schedule_url(self.create_facility(user=self.editor))
        self.assertEqual(self.client.get(wrong_url).status_code, 404)
        self.assertEqual(
            self.client.patch(
                wrong_url, {"video_enabled": True}, format="json"
            ).status_code,
            404,
        )
        for obj in (self.schedule, self.resource, self.facility, self.doctor):
            with self.subTest(model=type(obj).__name__):
                obj.deleted = True
                obj.save(update_fields=["deleted"])
                self.assertEqual(self.client.get(self.url).status_code, 404)
                self.assertEqual(
                    self.client.patch(
                        self.url, {"video_enabled": True}, format="json"
                    ).status_code,
                    404,
                )
                obj.deleted = False
                obj.save(update_fields=["deleted"])

    def test_only_active_practitioner_schedules_can_be_configured(self):
        for field, value in (("resource_type", "location"), ("user", None)):
            with self.subTest(field=field):
                previous = getattr(self.resource, field)
                setattr(self.resource, field, value)
                self.resource.save(update_fields=[field])
                self.assertEqual(self.client.get(self.url).status_code, 404)
                self.assertEqual(
                    self.client.patch(
                        self.url, {"video_enabled": True}, format="json"
                    ).status_code,
                    404,
                )
                setattr(self.resource, field, previous)
                self.resource.save(update_fields=[field])
        self.doctor.is_active = False
        self.doctor.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_boolean_is_required_without_coercion(self):
        for data in (
            {},
            [],
            {"video_enabled": None},
            {"video_enabled": "true"},
            {"video_enabled": 1},
            {"video_enabled": "false"},
        ):
            with self.subTest(data=data):
                response = self.client.patch(self.url, data, format="json")
                self.assertEqual(response.status_code, 400, response.data)
                self.schedule.refresh_from_db()
                self.assertEqual(self.schedule.meta, {})

    def test_malformed_metadata_defaults_false_and_is_not_destroyed_on_write(self):
        for meta in ([], {"care_zoom": "legacy"}):
            with self.subTest(meta=meta):
                self.schedule.meta = meta
                self.schedule.save(update_fields=["meta"])
                self.assertFalse(self.client.get(self.url).data["video_enabled"])
                response = self.client.patch(
                    self.url, {"video_enabled": True}, format="json"
                )
                self.assertEqual(response.status_code, 400, response.data)
                self.schedule.refresh_from_db()
                self.assertEqual(self.schedule.meta, meta)

    def test_unauthenticated_patient_and_inactive_staff_cannot_configure(self):
        patient_token = PatientToken()
        patient_token["phone_number"] = "+919999999999"
        self.editor.is_active = False
        self.editor.save(update_fields=["is_active"])
        for token in (None, patient_token, AccessToken.for_user(self.editor)):
            self.client.credentials(
                **({"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {})
            )
            for method in (self.client.get, self.client.patch):
                response = method(self.url, {"video_enabled": True}, format="json")
                self.assertIn(response.status_code, (401, 403), response.data)
                self.assertEqual(response["Cache-Control"], "no-store")
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.meta, {})

    def test_core_booking_lock_prevents_concurrent_schedule_changes(self):
        with Lock(f"booking:resource:{self.resource.pk}"):
            response = self.client.patch(
                self.url, {"video_enabled": True}, format="json"
            )
        self.assertEqual(response.status_code, 423, response.data)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.meta, {})

"""Explicit local verification fixture; never imported or executed by plugin startup.

After core load_fixtures, run only in the isolated development stack:
  python manage.py shell -c 'from care_zoom.tests.seed_local import seed; seed()'

Uses the existing fixture-only care-doctor login and emits no credentials or tokens.
Reruns refresh this fixture's appointment window and repair its legacy malformed fields.
"""

import json
from datetime import date, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from model_bakery import baker

from care.emr.models import Patient
from care.emr.models.organization import FacilityOrganizationUser
from care.emr.models.scheduling.booking import TokenBooking, TokenSlot
from care.emr.models.scheduling.schedule import (
    Availability,
    SchedulableResource,
    Schedule,
)
from care.emr.resources.scheduling.schedule.spec import AvailabilityForScheduleSpec
from care.facility.models import Facility
from care.security.models import PermissionModel, RoleModel, RolePermission
from care.security.permissions.schedule import SchedulePermissions
from care.users.models import User


def fixture_id(name):
    return uuid5(NAMESPACE_URL, f"care-zoom-local-verification:{name}")


@transaction.atomic
def seed():
    if not settings.DEBUG:
        raise RuntimeError("Local Zoom verification fixtures require DEBUG=True.")
    doctor = User.objects.get(username="care-doctor", is_active=True)
    facility = Facility.objects.filter(external_id=fixture_id("facility")).first()
    if facility is None:
        facility = baker.make(
            Facility,
            external_id=fixture_id("facility"),
            name="Zoom Verification Clinic",
            created_by=doctor,
        )
    role, _ = RoleModel.objects.get_or_create(name="Zoom local booking reader")
    permission = PermissionModel.objects.get(
        slug=SchedulePermissions.can_list_booking.name
    )
    RolePermission.objects.get_or_create(role=role, permission=permission)
    FacilityOrganizationUser.objects.get_or_create(
        organization=facility.default_internal_organization,
        user=doctor,
        role=role,
    )
    patient = Patient.objects.filter(external_id=fixture_id("patient")).first()
    if patient is None:
        patient = baker.make(
            Patient,
            external_id=fixture_id("patient"),
            name="Zoom Verification Patient",
            phone_number="+919999999990",
            gender="male",
            date_of_birth=date(1990, 1, 1),
            year_of_birth=1990,
        )
    if not patient.gender:
        patient.gender = "male"
    if not patient.date_of_birth and not patient.year_of_birth:
        patient.date_of_birth = date(1990, 1, 1)
        patient.year_of_birth = 1990
    patient.build_facility_identifiers(facility.id)
    patient.save(
        update_fields=[
            "facility_identifiers",
            "gender",
            "date_of_birth",
            "year_of_birth",
        ]
    )
    resource, _ = SchedulableResource.objects.get_or_create(
        facility=facility,
        resource_type="practitioner",
        user=doctor,
    )
    now = timezone.now()
    slot_start = timezone.localtime(now).replace(second=0, microsecond=0)
    slot_end = slot_start + timedelta(hours=1)
    # A core availability cannot span midnight; the call remains joinable for an
    # hour after its end when seeding during the final hour of the day.
    if slot_end.date() != slot_start.date():
        slot_start -= timedelta(hours=1)
        slot_end -= timedelta(hours=1)
    # Core's availability-create input requires a UUID4 schedule ID. Normalize
    # only this legacy fixture's ID in place, retaining its row and booked slots.
    schedule_id = UUID(int=fixture_id("schedule").int, version=4)
    Schedule.objects.filter(external_id=fixture_id("schedule")).update(
        external_id=schedule_id
    )
    schedule, _ = Schedule.objects.update_or_create(
        external_id=schedule_id,
        defaults={
            "resource": resource,
            "name": "Zoom verification",
            "is_public": True,
            "valid_from": now - timedelta(days=1),
            "valid_to": now + timedelta(days=1),
        },
    )
    schedule.meta.setdefault("care_zoom", {})["video_enabled"] = True
    schedule.save(update_fields=["meta"])
    availability_data = AvailabilityForScheduleSpec(
        name="Zoom verification",
        slot_type="appointment",
        slot_size_in_minutes=60,
        tokens_per_slot=1,
        availability=[
            {
                "day_of_week": slot_start.weekday(),
                "start_time": slot_start.time(),
                "end_time": slot_end.time(),
            }
        ],
    ).model_dump(mode="json", exclude={"id", "meta"})
    availability, _ = Availability.objects.update_or_create(
        external_id=fixture_id("availability"),
        defaults={"schedule": schedule, **availability_data},
    )
    slot, _ = TokenSlot.objects.update_or_create(
        external_id=fixture_id("slot"),
        defaults={
            "resource": resource,
            "availability": availability,
            "start_datetime": slot_start,
            "end_datetime": slot_end,
            "allocated": 1,
        },
    )
    booking, _ = TokenBooking.objects.update_or_create(
        external_id=fixture_id("booking"),
        defaults={
            "patient": patient,
            "token_slot": slot,
            "status": "booked",
            "booked_by": doctor,
        },
    )
    if booking.note is None:
        booking.note = ""
        booking.save(update_fields=["note"])
    print(  # noqa: T201 - explicit local fixture summary
        json.dumps(
            {
                "booking_id": str(booking.external_id),
                "facility_id": str(facility.external_id),
                "username": doctor.username,
            }
        )
    )

"""Explicit local verification fixture; never imported or executed by plugin startup.

After core load_fixtures, run only in the isolated development stack:
  python manage.py shell -c 'from care_zoom.tests.seed_local import seed; seed()'

Uses the existing fixture-only care-doctor login and emits no credentials or tokens.
Reruns refresh only this fixture's appointment window so it remains joinable.
"""

import json
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

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
        )
    resource, _ = SchedulableResource.objects.get_or_create(
        facility=facility,
        resource_type="practitioner",
        user=doctor,
    )
    now = timezone.now()
    schedule, _ = Schedule.objects.update_or_create(
        external_id=fixture_id("schedule"),
        defaults={
            "resource": resource,
            "name": "Zoom verification",
            "is_public": True,
            "valid_from": now - timedelta(days=1),
            "valid_to": now + timedelta(days=1),
        },
    )
    availability, _ = Availability.objects.get_or_create(
        external_id=fixture_id("availability"),
        defaults={
            "schedule": schedule,
            "name": "Zoom verification",
            "slot_type": "appointment",
            "slot_size_in_minutes": 60,
            "tokens_per_slot": 1,
            "availability": {},
        },
    )
    slot, _ = TokenSlot.objects.update_or_create(
        external_id=fixture_id("slot"),
        defaults={
            "resource": resource,
            "availability": availability,
            "start_datetime": now,
            "end_datetime": now + timedelta(hours=1),
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
    print(
        json.dumps(
            {
                "booking_id": str(booking.external_id),
                "facility_id": str(facility.external_id),
                "username": doctor.username,
            }
        )
    )

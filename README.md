# care_zoom

Current implementation, setup and remaining work: [implementation handoff](./IMPLEMENTATION.md).

Zoom Video SDK calls for CARE practitioner appointments on video-enabled schedules, without
persisted call sessions. Requires CARE revision
`3fe704930d9b2d7b6ffdc212cbf6a6a72bfaede4` and the companion `care_zoom_fe` frontend.

The assigned active practitioner may join as host; a meeting-passcode link or an existing CARE
patient OTP session may join as participant. OTP access requires the patient's authenticated phone number. Family records follow CARE's existing shared
phone access model. Staff with booking-read permission may view/copy the appointment link, but
only the assigned practitioner may obtain a host token. Both checks run on every token request.

No models, migrations, scheduled jobs, recording, transcripts,
webhooks, reminders or link-delivery messages are added. Joining and leaving never changes
appointment status. An encounter is not required; the booking's slot must belong to an
availability under a video-enabled schedule.

## Guest links

Copy Link and the patient portal use `/teleconsult/<booking_uuid>?passcode=<random-secret>`.
The existing call page accepts this link without CARE login. Signed-in staff continue to use
CARE permissions and the facility host route. Links without a passcode retain the OTP flow.

A plugin `pre_save` signal writes a random 256-bit URL-safe passcode to
`TokenBooking.meta["care_zoom"]["meeting_passcode"]` when an eligible video appointment is
created, as part of the original insert. Existing appointments (including schedules switched to
video later) receive a passcode on the first authorized staff/OTP metadata read. This fallback
locks the booking while preserving other metadata; no migration or bulk backfill is needed.
Ordinary booking updates keep the passcode. Rescheduling creates a new booking and passcode.

The passcode is a bearer credential for this appointment's call metadata and participant token;
it does not prove the caller's identity or grant patient-record, staff, or host access. Anyone
with the link can use it. Guest token requests apply the same schedule, status, related-record,
configuration and time-window checks as authenticated requests. Cancellation prevents new
tokens; already issued Zoom tokens and active sessions are unaffected.

Guest API requests use `Authorization: Bearer <meeting_passcode>` rather than a query parameter.
The call page and API fetches suppress referrers. Deploy with HTTPS and redact `passcode` from
frontend access/analytics logs: the initial page URL and browser history still contain it. Store
and share links as credentials. The passcode is kept in metadata so authorized users can recopy
the same link; it is separate from the short-lived Zoom SDK token. No manual passcode input,
rotation UI, or new page is added.

## Schedule consultation mode

In Schedule Management, use **Consultation mode** beside the native **Edit** action to choose
**In person** or **Video call** for the whole practitioner schedule. The default is in person.
The plugin stores only `Schedule.meta["care_zoom"]["video_enabled"]`; only the boolean `true`
enables video. Missing flags leave existing and newly created schedules in person. Use separate
schedules for different modes; there are no per-time-block overrides or booking snapshots.

The setting applies immediately to all existing and future bookings under that schedule.
For eligible video appointments, the assigned practitioner sees **Join Video Call** beside the
native Check-In/action group; staff with booking-read access may copy the link. In-person
appointments have no Zoom actions, and both staff and patient direct token requests are denied.
Changing to in person does not revoke already issued Zoom tokens or disconnect running calls.

This is plugin code plus external runtime registration, with **zero tracked core changes**.
The flag is consultation configuration, not a meeting ID or credential. It uses the existing
core metadata field and schedule permissions, without migrations or signals. Existing video
schedules must be explicitly enabled during rollout; no bulk opt-in runs automatically.

## Configuration

Register externally through CARE's `ADDITIONAL_PLUGS`; do not edit core `plug_config.py`:

```json
[{"name":"care_zoom","package_name":"/plugins/care_zoom","version":"","configs":{}}]
```

Mount this repository at `/plugins/care_zoom` in both backend and Celery and install with
`python -m pip install -e /plugins/care_zoom` at each service startup. The scaffold bootstrap's
external `.agent/plugin.compose.yaml` handles this. Configure backend-only environment values:

```dotenv
ZOOM_VIDEO_SDK_KEY=your-video-sdk-app-key
ZOOM_VIDEO_SDK_SECRET=your-video-sdk-app-secret
# Optional; enable only after confirming the region is enabled in your Zoom account.
# ZOOM_GEO_REGIONS=IN
```

`ZOOM_ENABLED` defaults to `True`. Missing credentials or a disabled plugin leave appointment
metadata available with `configured=false`, `can_join=false`; token requests return HTTP 503.
Configuration precedence is `PLUGIN_CONFIGS["care_zoom"]`, environment, defaults. Credentials are
never returned as configuration; the public SDK app key is necessarily included in the signed
Zoom JWT. Keep the secret out of frontend environment, source control and logs. A selected Zoom
region is a connection preference, not a guarantee of end-to-end data residency.

For this workspace, store local credentials in ignored
`/Users/gigin/care_scaffold/care/care_zoom/.env`; backend and Celery load it through the external
Compose override. Recreate services after changing environment configuration:

```bash
/Users/gigin/care_scaffold/.agent/compose.sh up -d --wait backend celery
```

## API

All routes are beneath `/api/care_zoom/`; authenticated requests carry `Authorization: Bearer <CARE token>`.
Use staff access tokens for schedule and staff appointment routes, and CARE patient-login
tokens for the OTP variants.

| Method | Path | Access |
| --- | --- | --- |
| GET | `facility/<facility_uuid>/schedules/<schedule_uuid>/video/` | Core `can_list_schedule(resource, user)` permission |
| PATCH | `facility/<facility_uuid>/schedules/<schedule_uuid>/video/` | Core `can_write_schedule(resource, user)` permission |
| GET | `appointments/<uuid>/` | Core `can_list_booking(resource, user)` permission |
| POST | `appointments/<uuid>/token/` | Same permission plus assigned practitioner |
| GET | `otp/appointments/<uuid>/` | Core `JWTTokenPatientAuthentication`, `OTPAuthenticatedPermission`, matching patient phone |
| POST | `otp/appointments/<uuid>/token/` | Same phone ownership and current eligibility |
| GET | `guest/appointments/<uuid>/` | Matching meeting passcode in the bearer header; no CARE login |
| POST | `guest/appointments/<uuid>/token/` | Same passcode plus current eligibility; participant only |

The schedule routes return `{ "schedule_id": "<uuid>", "video_enabled": false }`. PATCH accepts
`{ "video_enabled": true }` or `{ "video_enabled": false }`, requires a JSON boolean, and
preserves other metadata.
The facility must match the schedule's active practitioner resource. This endpoint uses staff
authentication only; patient OTP tokens cannot read or change consultation mode.

Appointment GET returns `booking_id`, `status`, `patient_name`, `practitioner_name`, `start_datetime`,
`end_datetime`, `join_opens_at`, `join_closes_at`, `join_path`, `eligible`, `can_join`,
`caller_role` (`host`, `participant`, `observer`), `reason` and `configured`.
`eligible` describes schedule/resource/status eligibility independently of the clock, caller role and
configuration. `can_join` includes those checks. Eligible staff/OTP responses include the
passcode in `join_path`; guest responses omit it. The frontend resolves the path against its own origin.

POST needs no body and derives all identities and claims from current database records.
It returns `token`, `session_name`, `session_key`, `display_name`, `role` (`host` or
`participant`) and `expires_at`. Keep this response only in browser memory. All view responses,
including errors, use `Cache-Control: no-store`.

Bookings are eligible only with a practitioner resource and an active assigned user, an
availability under a video-enabled schedule, a valid slot interval and status `booked`,
`arrived`, `checked_in` or `in_consultation`. Issuance opens
at midnight on the slot's start date in CARE's timezone (`Asia/Kolkata` in this workspace) and
closes 60 minutes after slot end, including both exact boundary instants. Staff, OTP patients
and passcode guests can therefore join earlier on the appointment day. Soft-deleted booking,
patient, slot, resource, facility, assigned user and any present
availability/schedule are rejected with 404. Non-practitioner resources also return 404. Unrelated patient phones also receive 404.
Unauthorized staff receive 403, state/window failures 400, missing configuration 503.

Zoom session names are `care-<booking_uuid>` and `session_key` is the UUID. HS256 JWTs contain
`version=1`, numeric `role_type`, stable namespaced UUID `user_key`, and WebRTC audio/video flags.
They expire 30 minutes after issuance, with `iat` backdated 30 seconds for clock skew, satisfying
Zoom's minimum 1,800-second interval. See the [official authorization contract](https://developers.zoom.us/docs/video-sdk/auth/).

A reschedule creates a new booking and link; the old booking's `rescheduled` status prevents
new tokens. Reassignment prevents the former practitioner obtaining another host token. Changes
to schedule mode, state, phone ownership or assignment **do not revoke already issued tokens**
or disconnect a running call. Host End for everyone ends the current session; a subsequently authorized caller
can start another session while the booking remains eligible.

## Verification

The suite uses real CARE access/patient JWTs and permission records, with test-only Zoom
credentials. It covers authorized roles, unrelated phones and staff, shared family phone,
expired/invalid/wrong token types, all appointment statuses, exact issuance boundaries,
soft-deleted scheduling relationships, missing/inactive practitioner, absent encounter,
rejected missing availability and in-person schedules, reassignment, rescheduled links,
server-derived claims, signing and no appointment status mutation. Guest coverage includes
passcode creation/backfill, stable links, malformed/wrong/cross-booking credentials, participant-only
claims, status/window/deletion checks and preservation of other metadata. Schedule tests cover separate
read/write permissions, strict booleans, facility scoping and preservation of other metadata.
The explicit DEBUG-only local seed opts in only its synthetic Zoom fixture schedule.

Run against this scaffold's isolated services (never another workspace):

```bash
/Users/gigin/care_scaffold/.agent/compose.sh exec backend \
  python manage.py test care_zoom.tests --settings=config.settings.test --noinput
/Users/gigin/care_scaffold/.agent/compose.sh exec backend \
  python manage.py makemigrations --check --dry-run
```

Django creates a separate PostgreSQL test database. Live acceptance additionally needs real Zoom
Video SDK credentials, two independent authenticated browsers, and HTTPS outside localhost.
Verify audio/video, denied permissions, reconnect, host ending, Android Chrome and iOS Safari.
Automated authorization tests do not establish successful live media interoperability.

Pinned scaffold authentication/extension-point corrections are tracked in
[care_scaffold issue #5](https://github.com/ohcnetwork/care_scaffold/issues/5).

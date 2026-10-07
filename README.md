# care_zoom

Current implementation, setup and remaining work: [implementation handoff](./IMPLEMENTATION.md).

Stateless Zoom Video SDK calls for CARE practitioner appointments. Requires CARE revision
`3fe704930d9b2d7b6ffdc212cbf6a6a72bfaede4` and the companion `care_zoom_fe` frontend.

The assigned active practitioner may join as host; an existing CARE patient OTP session may join
for a patient with the authenticated phone number. Family records follow CARE's existing shared
phone access model. Staff with booking-read permission may view/copy the appointment link, but
only the assigned practitioner may obtain a host token. Both checks run on every token request.

No models, migrations, signals, scheduled jobs, appointment writes, recording, transcripts,
webhooks, reminders or link-delivery messages are added. Joining and leaving never changes
appointment status. An encounter and slot availability are not required.

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

All routes are beneath `/api/care_zoom/`; requests carry `Authorization: Bearer <CARE token>`.
Use staff access tokens for the first two and CARE patient-login tokens for the OTP variants.

| Method | Path | Access |
| --- | --- | --- |
| GET | `appointments/<uuid>/` | Core `can_list_booking(resource, user)` permission |
| POST | `appointments/<uuid>/token/` | Same permission plus assigned practitioner |
| GET | `otp/appointments/<uuid>/` | Core `JWTTokenPatientAuthentication`, `OTPAuthenticatedPermission`, matching patient phone |
| POST | `otp/appointments/<uuid>/token/` | Same phone ownership and current eligibility |

GET returns `booking_id`, `status`, `patient_name`, `practitioner_name`, `start_datetime`,
`end_datetime`, `join_opens_at`, `join_closes_at`, `join_path`, `eligible`, `can_join`,
`caller_role` (`host`, `participant`, `observer`), `reason` and `configured`.
`eligible` describes resource/status eligibility independently of the clock, caller role and
configuration. `can_join` includes those checks. The path is `/teleconsult/<booking_uuid>`;
the frontend resolves it against its own origin, so links never contain credentials.

POST needs no body and derives all identities and claims from current database records.
It returns `token`, `session_name`, `session_key`, `display_name`, `role` (`host` or
`participant`) and `expires_at`. Keep this response only in browser memory. All view responses,
including errors, use `Cache-Control: no-store`.

Bookings are eligible only with a practitioner resource and an active assigned user, a valid
slot interval and status `booked`, `arrived`, `checked_in` or `in_consultation`. Issuance opens
15 minutes before slot start and closes 60 minutes after slot end, including both exact boundary
instants. Soft-deleted booking, patient, slot, resource, facility, assigned user and any present
availability/schedule are rejected with 404. Non-practitioner resources also return 404. Unrelated patient phones also receive 404.
Unauthorized staff receive 403, state/window failures 400, missing configuration 503.

Zoom session names are `care-<booking_uuid>` and `session_key` is the UUID. HS256 JWTs contain
`version=1`, numeric `role_type`, stable namespaced UUID `user_key`, and WebRTC audio/video flags.
They expire 30 minutes after issuance, with `iat` backdated 30 seconds for clock skew, satisfying
Zoom's minimum 1,800-second interval. See the [official authorization contract](https://developers.zoom.us/docs/video-sdk/auth/).

A reschedule creates a new booking and link; the old booking's `rescheduled` status prevents
new tokens. Reassignment prevents the former practitioner obtaining another host token. Changes
to state, phone ownership or assignment **do not revoke already issued tokens** or disconnect a
running call. Host End for everyone ends the current session; a subsequently authorized caller
can start another session while the booking remains eligible.

## Verification

The suite uses real CARE access/patient JWTs and permission records, with test-only Zoom
credentials. It covers authorized roles, unrelated phones and staff, shared family phone,
expired/invalid/wrong token types, all appointment statuses, exact issuance boundaries,
soft-deleted scheduling relationships, missing/inactive practitioner, no encounter/availability,
reassignment, rescheduled links, server-derived claims, signing and no appointment mutation.

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

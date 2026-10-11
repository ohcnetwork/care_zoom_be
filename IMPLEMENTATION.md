# CARE Zoom v1 — implementation handoff

Last updated: 11 October 2026. This is the starting point for continuing the Zoom plugin in a new
session. Read the workspace `AGENTS.md`, then `skills/care-plugin-architecture/SKILL.md`, before
editing. The verified v1 baseline works with the core revisions below; newer working-tree
additions are identified separately. Live two-party audio/video and mobile acceptance remain open.

## Workspace and repository ownership

The authoritative workspace is `/Users/gigin/care_scaffold`. The current layout is:

```text
care_scaffold/
├── AGENTS.md, README.md, skills/, templates/, scripts/  # reusable scaffold
├── care/                                               # independent core backend repo
│   └── care_zoom/                                      # independent plugin backend repo
│       ├── IMPLEMENTATION.md                           # this handoff
│       ├── README.md
│       ├── .env                                        # ignored local Zoom credentials
│       └── care_zoom/                                  # Django package
├── care_fe/                                            # independent core frontend repo
├── care_zoom_fe/                                       # independent plugin frontend repo
├── care-scaffold.env                                   # ignored paths/ports/stack identity
└── .agent/                                             # ignored runtime config and evidence
```

`care/` and `care_fe/` are independent ignored checkouts, **not submodules**. The scaffold's
root-anchored `/care/` and `/care_*/` ignores exclude application repositories from scaffold
commits. Core's local `.git/info/exclude` excludes `/care_zoom/`; this does not ignore source
inside the plugin's own Git repository. Run Git commands in the intended Git root.

Older briefs, verification logs and screenshots may mention `/Users/gigin/care_zoom` or
`/Users/gigin/care_zoom_fe`, or call core directories submodules. Those describe the original
layout; use the paths in this document for current work. Preserve repository histories,
uncommitted work, local credentials, dependencies and this workspace's database when moving or
restarting. Do not regenerate existing repositories or reset fixtures/database to fix paths.

| Repository | Branch / revision recorded before relocation |
| --- | --- |
| `care/care_zoom` | `codex/zoom-v1`, `b50f4ec804e68584446fc4fc5c018ff3d01f16c9` |
| `care_zoom_fe` | `codex/zoom-v1`, `58e8d4e096b36d48a889abdb89c5a07307493894` |
| `care` | `3fe704930d9b2d7b6ffdc212cbf6a6a72bfaede4` |
| `care_fe` | `f30bb8647215adecdfcc80926334348f69712be3` |

The plugin commits are the initial implementation. Subsequent fixes were uncommitted at the
start of relocation: backend `care_zoom/tests/seed_local.py` and new `test_seed_local.py`;
frontend `README.md`, `package.json`, `playwright.config.ts`, `src/components/ZoomCall.tsx`,
`tests/zoom-call.test.tsx` and new `tests/host-live.spec.ts`. Documentation/path migration adds
further changes. Do not discard these changes or assume HEAD contains the fixes. No plugin
remote was added and no plugin code was pushed. The scaffold has independent pre-existing work.

Additional staff appointment and picture-in-picture edits appeared during the final relocation
checks. They were preserved; see the concurrent-work snapshot below. This file and the relocation
fixes are also uncommitted. Inspect current Git status before continuing; the file list above is
the starting snapshot, not an exhaustive list of current changes.

**Relocation verified on 7 October 2026:** both repositories were moved intact (58 source
files checked, original HEADs and uncommitted changes preserved). The ignored credentials file
was preserved byte-for-byte with mode 600; old sibling directories are no longer used. Both
core tracked trees remain clean. Backend and Celery are healthy and import
`/plugins/care_zoom/care_zoom/__init__.py`; real staff and OTP metadata/token requests return 200.
The frontend serves its manifest and all imported chunks from the new path, including after a
watch rebuild. The real-backend appointment/schedule browser regression passed after relocation (1 test, 4.8 seconds).
Evidence: `.agent/zoom-layout-migration.json`, `.agent/zoom-relocation-http.log`.
These results establish the relocated runtime and baseline regression; they do not establish
acceptance of the concurrent feature additions described below.

## Implemented scope and product behavior

This is an **appointment-bound** integration with Zoom Video SDK, without persisted call
sessions. CARE's existing `TokenBooking` is the appointment. There is no separate Video Consultation model, scheduling
system or persistence layer. A stable same-origin `/teleconsult/<booking_uuid>` URL is shared by
staff and patients; newer working-tree code redirects authorized staff to the facility appointment
route described below. Joining/leaving never changes appointment or encounter state;
an encounter is not required. Video requires an explicit opt-in for the booking's whole schedule,
as described below.

The UI is **custom CARE-styled React UI using `@zoom/videosdk` 2.5.0**, not Zoom's prebuilt UI
Toolkit or the Zoom Meeting SDK. It loads the SDK lazily after **Prepare for call**. It includes
camera preview, microphone level check, device selection where supported, audio/mute/camera
controls, participant presence, reconnect feedback, Leave and host End for everyone. Speaker
selection is capability-dependent; mobile camera choices use facing modes. Media/listeners/SDK
client are disposed on leave, unmount, logout and identity change.

No plugin models, schema migrations, background jobs, appointment status writes, recordings,
transcripts, Scribe integration, consent persistence, reminders, link-delivery SMS, chat, screen
sharing, waiting room or native apps were added. Existing CARE patient OTP authentication still
uses core's OTP/SMS mechanism; passcode links now also support guest access as described below.

### Guest access (11 October 2026)

- `signals.py`, registered from `AppConfig.ready()`, uses `pre_save` on new eligible video
  bookings to store `meta.care_zoom.meeting_passcode` in the original insert. Passcodes use
  `secrets.token_urlsafe(32)`. Existing bookings receive one on authorized staff/OTP metadata
  reads, under a row lock that preserves other metadata. No migrations or bulk backfill.
- Eligible staff/OTP `join_path` values now include `?passcode=...`. Staff Copy Link and patient
  portal links use that returned path. The same CallPage/PublicRouter handles guests; no new
  page or UI input. Signed-in staff keep the existing host authorization and facility redirect.
- `/api/care_zoom/guest/appointments/<uuid>/` and its `/token/` variant accept the passcode in
  `Authorization: Bearer ...`, with constant-time comparison before exposing metadata. No CARE
  token is sent on guest requests. Guest metadata omits `staff_context` and does not echo the
  passcode; SDK tokens remain participant-only. All existing eligibility/window checks apply.
- The link is a bearer credential, not verified identity. It gives access to the appointment's
  displayed names/time and its participant call, never clinical records or host privileges.
  Keep it private, use HTTPS, and redact the query parameter from hosting/analytics logs.
  Referrers are suppressed by the call page and plugin API client, but initial navigation and
  browser history still contain the query. No rotation UI is included.
- Links without passcodes keep OTP compatibility. Passcode or booking changes unmount an active
  guest call. Existing SDK tokens/calls are not revoked by cancellation or a changed passcode;
  subsequent issuance rechecks the current booking and credential.
- See the backend README's Guest links section for the current contract. Older verification
  and "no signal/appointment writes" statements below describe the previous baseline.
- Verification on 11 October: 40 backend tests, 64 frontend tests, seven existing mocked-API
  host browser tests, production build and migration check passed. Real HTTP checked a temporary
  synthetic booking's staff link, guest metadata/token, missing passcode and cancellation, then
  deleted only those test rows. In the real host, Copy Link succeeded; after logout the fixture's
  passcode opened this same page, and an invalid passcode exposed no appointment details. That
  fixture was past its join window, correctly showing a closed appointment. Real guest Zoom
  media/two-party calling was not exercised. Both tracked core trees and revisions are unchanged.

**Open UX followup:** staff Join/Copy actions are inside native appointment details, but the
patient portal currently adds a separate **Video appointments** panel above the existing portal.
It lists the same core appointments. The user explicitly questioned this separation and expects
video actions to feel part of Appointments. The panel was the initial fallback for missing action
slots; this patient-panel concern has not been resolved by the newer staff-page changes. Inspect current extension points and
`.agent/zoom-original-build-request.txt` before deciding how to integrate existing appointment cards. Do
not treat a separate consultation workflow as a requirement or modify core to add a slot.

### Schedule consultation mode (8 October 2026)

- A whole practitioner schedule is **In person** by default or **Video call** when
  `Schedule.meta["care_zoom"]["video_enabled"]` is the boolean `true`. No availability override,
  booking snapshot, plugin model, migration or signal is added. The flag contains no credentials.
- The plugin's `EditScheduleTemplateSheet` override retains the native Edit component through
  `__base` and adds **Consultation mode** beside it. The dialog explains that saving applies to
  all existing and future bookings under the schedule. Different modes use separate schedules.
- `PatientInfoCard` groups its original `children` with Join/Copy actions, preserving native
  Check-In, permissions and menus. Join is shown to the assigned practitioner for eligible video
  appointments; booking-read staff can copy the link. In-person appointments show no Zoom actions.
- Shared backend eligibility rejects in-person appointments and bookings without schedule
  availability for staff and patient token requests, including direct links. Existing schedules
  require explicit opt-in. The DEBUG fixture seed enables only its synthetic Zoom schedule.
- Changing mode affects subsequent authorization; it does not revoke an issued Zoom token or
  disconnect an active call. Joining still does not check in or change appointment status.
- All application changes belong to the two plugin repositories. The host override allowlist
  changes only in external `.agent/frontend.env`; **zero tracked core changes** are required.

Current schedule-mode checks and earlier baseline results are recorded separately below.

### Concurrent work observed at handoff

The following code was present in the working tree at the end of relocation on 7 October 2026.
It is recorded from source inspection, **not independently validated by the relocation task**.
Preserve it and inspect its current tests/results before further changes:

- Authorized staff metadata adds `staff_context` with `facility_id` and `patient_id`; patient
  OTP metadata and denied responses do not receive those fields. The frontend uses this context
  to resolve the staff route
  `/facility/:facilityId/patient/:patientId/appointments/:bookingId/video`.
- `StaffAppointmentDetails.tsx` reads the core facility/booking APIs, checks matching identities
  and staff permissions, displays appointment notes/status/patient/time, and links to CARE's
  native appointment and encounter workflows in a new tab. It refreshes on window focus.
  `CallPage.tsx`, appointment actions, the manifest, API/types and translations were updated
  alongside it. The patient portal's separate panel remains unchanged.
- `useCallPictureInPicture.ts` and `ZoomCall.tsx` add capability-gated Document Picture-in-Picture.
  A stable React portal moves live call nodes to the floating document and restores them when
  it closes. A Media Session action is registered where supported; actual automatic tab-switch
  behavior and real media in the floating window remain acceptance checks. Navigating away in
  the call tab still unmounts the call.
- Associated test changes include backend `test_appointments.py`, frontend
  `staff-appointment-details.test.tsx`, `entrypoints.test.tsx`, `zoom-call.test.tsx` and
  `host.spec.ts`. Do not infer their current pass count from the older results below.

The staff redirect requires the matching backend and frontend changes together. These additions
do not create a separate consultation model or change the plugin's appointment-write policy.

## Backend contract

Source: `care_zoom/appointments.py` owns shared eligibility/JWT construction;
`care_zoom/views.py` owns record filtering and access; `care_zoom/urls.py` exposes the routes.
All are beneath `/api/care_zoom/`, with `Authorization: Bearer <CARE token>` except guest routes:

| Method / route | Required access |
| --- | --- |
| `GET facility/<facility_uuid>/schedules/<schedule_uuid>/video/` | Staff JWT plus core `can_list_schedule(resource, user)` |
| `PATCH facility/<facility_uuid>/schedules/<schedule_uuid>/video/` | Staff JWT plus core `can_write_schedule(resource, user)` |
| `GET appointments/<uuid>/` | Staff JWT plus core `can_list_booking(resource, user)` |
| `POST appointments/<uuid>/token/` | Same, plus staff is the assigned active practitioner |
| `GET otp/appointments/<uuid>/` | Core `JWTTokenPatientAuthentication` and `OTPAuthenticatedPermission`, matching appointment patient phone |
| `POST otp/appointments/<uuid>/token/` | Same phone ownership plus current eligibility |
| `GET guest/appointments/<uuid>/` | Meeting passcode bearer; no CARE login |
| `POST guest/appointments/<uuid>/token/` | Same passcode and eligibility; participant only |

Staff with booking-read permission may copy a link but cannot join unless assigned. Family
patient records sharing the OTP-authenticated phone follow core's existing shared-phone access
model. The backend derives display identity, session, role and user key from current records;
clients cannot supply overrides. POST has no required body.

Schedule GET/PATCH return `schedule_id` and `video_enabled`. PATCH requires a JSON boolean in
`video_enabled`, preserves unrelated metadata and records the modifying staff user. The schedule
must belong to the requested facility and an active practitioner resource; patient OTP tokens
cannot use this endpoint. Only an explicit boolean `true` enables video, including when reading
older or malformed metadata.

- Eligible statuses: `booked`, `arrived`, `checked_in`, `in_consultation`.
- Required resource: practitioner, active assigned user, valid positive slot interval and
  availability under an explicitly video-enabled schedule.
- Token issuance window: **midnight on the slot's start date in CARE's timezone through
  60 minutes after slot end**, including both exact boundary instants. The opening time was
  changed on 11 October for staff, OTP patients and passcode guests; this workspace uses
  `Asia/Kolkata`. `join_opens_at` remains a timestamp, with no frontend or schema change.
  All 40 backend tests passed after this change, including exact local-midnight/end boundaries.
  Real HTTP also confirmed a temporary same-day appointment could join 30 minutes early.
- Soft-deleted booking, patient, slot, resource, facility, assigned user, and any present
  availability/schedule relationship are rejected. Missing availability makes video ineligible.
- Missing/non-practitioner/deleted records and another patient phone return 404; unauthorized
  staff return 403; state/time-window rejection returns 400; disabled/unconfigured Zoom returns
  503. Missing credentials leave metadata readable with `configured=false`, `can_join=false`.
- Every response, including errors, has `Cache-Control: no-store` and `Pragma: no-cache`.

GET returns booking/status/names/slot times, `join_opens_at`, `join_closes_at`, `join_path`,
`eligible`, `can_join`, `caller_role` (`host`, `participant`, `observer`), `reason`, `configured`.
The newer working-tree staff response also includes `staff_context` as described above.
`eligible` describes schedule/resource/status validity; `can_join` also considers clock, role and setup.
POST returns `token`, `session_name`, `session_key`, `display_name`, `role`, `expires_at`.

JWTs use HS256 and backend-only Video SDK credentials. Session name is `care-<booking_uuid>`;
`session_key` is the booking UUID. Claims include numeric `role_type` (host 1, participant 0),
`version=1`, stable role-namespaced UUID `user_key`, and WebRTC audio/video flags. Expiry is
30 minutes after issuance; `iat` is backdated 30 seconds. Optional `ZOOM_GEO_REGIONS` is sent
only when configured. Browser Zoom tokens stay in memory, never storage, links or logs.

Reauthorization occurs on each new token request. Reassignment prevents the former host from
getting another token; rescheduling creates a new booking/link and the old `rescheduled` booking
cannot get a token. **Already issued tokens and running calls are not revoked** by appointment
or schedule-mode changes. Host End ends the current session; eligible callers can start another afterward.

## Frontend integration and source map

`src/manifest.tsx` is the sole federation export. It registers staff routes and four existing
core overrides. Every wrapper preserves the injected `__base` implementation.

| File | Responsibility |
| --- | --- |
| `src/components/PatientInfoCard.tsx` | Preserve original props and group native action children with Zoom actions only for `tagEntityType="appointment"` |
| `src/components/AppointmentActions.tsx` | Eligible video appointment Join/Copy actions beside native controls; assigned-practitioner Join |
| `src/components/ScheduleVideoSettings.tsx` | Override `EditScheduleTemplateSheet`, preserve native Edit and add the schedule-wide consultation-mode dialog |
| `src/components/PatientPortalIndex.tsx` | Existing portal plus video-appointments panel; phone-scoped pagination and in-progress bookings |
| `src/components/PublicRouter.tsx`, `src/utils/routes.ts` | Strict UUID call route; preserve other public routes; core patient-router fallback supports OTP patients |
| `src/pages/CallPage.tsx` | Auth branches, metadata, prejoin/call lifecycle and login return |
| `src/components/PatientLogin.tsx` | Existing CARE five-digit OTP send/login APIs |
| `src/hooks/useCareAuth.ts`, `src/utils/api.ts` | Reactive host auth context and corresponding staff/patient bearer key; no mixing of auth contexts |
| `src/hooks/useAppointment.ts` | Metadata fetch/poll every 30 seconds, aborts, retries and identity isolation |
| `src/components/ZoomCall.tsx` | Lazy SDK lifecycle, prejoin, participants, media, teardown and safe diagnostics |
| `src/components/StaffAppointmentDetails.tsx` | New staff appointment context and native encounter links; concurrent work |
| `src/hooks/useCallPictureInPicture.ts` | New Document PiP lifecycle and Media Session action; concurrent work |

Staff login return must be an encoded **absolute same-origin** URL on this core revision; a
relative redirect is rejected. `window.AuthUserContext` provides identity and patientLogin. Core
OTP APIs are `/api/v1/otp/send/`, `/api/v1/otp/login/`; the panel reads
`/api/v1/otp/slots/get_appointments/`. Pagination is restricted to the same API origin.
The known staff-expiry `403 token_not_valid` is handled for login recovery. An active call stays
mounted when metadata eligibility changes, consistent with the no-revocation policy.

Styles are scoped under `.care-zoom-container`, no global Tailwind preflight; translations use
`zoom__` keys in `public/locale/en.json`. React is shared with the host. The approximately 1 MB
SDK chunk is lazy and absent from the initial manifest payload.

## Runtime, credentials and startup

The current local credential file is:
`/Users/gigin/care_scaffold/care/care_zoom/.env` (ignored; preserve mode 600).
It contains `ZOOM_VIDEO_SDK_KEY`, `ZOOM_VIDEO_SDK_SECRET`, optionally `ZOOM_ENABLED` (default
true) and `ZOOM_GEO_REGIONS`. The user has configured live Video SDK credentials. Never print
or copy their values into docs, logs or frontend settings. `.env.example` contains placeholders.
Settings precedence is `PLUGIN_CONFIGS["care_zoom"]`, environment, defaults. An optional India
region requires account support and is not a guarantee of end-to-end residency.

`care-scaffold.env` is authoritative for core paths, saved ports and Compose identity.
`.agent/paths.env` points `PLUGIN_BE` and `PLUGIN_FE` at the nested plugin repositories.
`.agent/plugin.compose.yaml` mounts the backend at `/plugins/care_zoom`, registers external
`ADDITIONAL_PLUGS`, loads its `.env`, and installs the editable package at backend/Celery startup.
The shared external environment sets `PYTHONPATH=/plugins/care_zoom`: otherwise the outer
repository at `/app/care_zoom` shadows the editable Python package as an empty namespace.
Keep this provision for both services. Never edit core `plug_config.py`, settings or frontend
env files.

| Service | Saved port |
| --- | --- |
| CARE API | 25416 |
| CARE frontend host | 25417 |
| Zoom frontend remote | 25418 |
| PostgreSQL / Redis | 25419 / 25420 |
| MinIO API / console | 25421 / 25422 |
| Debugger | 25423 |

Compose project: `care_scaffold_c183fb930177`. Use **only** `.agent/compose.sh` for backend
operations; bare core Compose/Make commands omit workspace isolation. Do not stop another
workspace or remove volumes. Host and remote bind loopback with strict ports.

Start the following in separate terminals after verifying ports/processes:

```sh
cd /Users/gigin/care_scaffold
./.agent/compose.sh up -d --wait
```

```sh
cd /Users/gigin/care_scaffold
./.agent/frontend.sh
```

```sh
cd /Users/gigin/care_scaffold/care_zoom_fe
npm ci # only if dependencies need installation
npm run dev
```

Use Node 24; this machine has `/Users/gigin/.nvm/versions/node/v24.18.0/bin` if PATH needs repair.
`npm run dev` starts one Vite watch build, waits for the initial successful build, then starts
preview on 25418. Do not restore the old separate initial-build plus watch-build sequence:
it dropped federation's exposed modules. `npm run build` followed by `npm run preview` serves
a fixed build. Hard-refresh the host after rebuilding the remote.
After editing backend credential env values, recreate backend/Celery through the wrapper:
`./.agent/compose.sh up -d --wait backend celery`.

`.agent/frontend.env` contains these values; merge rather than replace other plugins if added:

```dotenv
REACT_ENABLED_APPS=ohcnetwork/care_zoom_fe@localhost:25418/assets/remoteEntry.js
REACT_MFE_REGISTERED_COMPONENTS=PatientInfoCard,PatientPortalIndex,PublicRouter,EditScheduleTemplateSheet
```

The host launcher supplies `REACT_CARE_API_URL` and its explicit strict port. The override
allowlist is applied at host startup/build time. The build-time remote registration is necessary
for the call URL to work before login. Restart the host after changing this allowlist; a remote
rebuild alone does not register a new host override.

## Local fixtures and repeatable checks

Development fixtures only: staff **`care-doctor` / `Ohcn@123`**, patient phone
**`+919999999990`**, core development OTP **`45612`**. Clinic: **Zoom Verification Clinic**.
Use independent doctor/patient browser profiles. Never use this fixed OTP/password as production
configuration. `CARE_TEST_PASSWORD` overrides the browser regression's local staff password.

Stable call URL:
`http://localhost:25417/teleconsult/bd2953dc-53b6-5455-b779-41ef60172504`.
The appointment time window expires naturally. Explicitly refresh only this DEBUG fixture:

```sh
cd /Users/gigin/care_scaffold
./.agent/compose.sh exec backend python manage.py shell -c 'from care_zoom.tests.seed_local import seed; seed()'
```

The seed is never run at startup. It maintains stable fixture booking/patient/facility IDs,
repairs invalid old synthetic data, and preserves existing note/identifier/demographic values.
It explicitly enables video on its synthetic schedule, preserving other metadata; it does not
opt in ordinary schedules. Running it again restores video for that fixture if it was disabled.
The schedule's legacy UUID5 external ID was converted in place to UUID4 to satisfy core's
availability-create validator; the stable call URL did not change.

```sh
cd /Users/gigin/care_scaffold
./.agent/compose.sh exec backend python manage.py test care_zoom.tests --settings=config.settings.test --noinput
./.agent/compose.sh exec backend python manage.py makemigrations --check --dry-run
cd /Users/gigin/care_scaffold/care_zoom_fe
npm test
npm run typecheck
npm run build
CARE_FE_URL=http://localhost:25417 PLAYWRIGHT_CHANNEL=chrome npm run test:host
# Opt in after refreshing the local fixture; real backend, no Zoom join:
CARE_FE_URL=http://localhost:25417 PLAYWRIGHT_CHANNEL=chrome npm run test:host:live
```

Django creates a separate test database. `test:host` uses API fixtures against the real host.
`test:host:live` uses actual staff login and API responses, temporarily switches only the synthetic
Zoom schedule to in person, and restores its original flag in `finally`. It does not reset the
database, change appointment status or request a Zoom token. Authentication traces are disabled
in the latter. Installed Chrome is selected above; otherwise install Playwright's matching browser.

## Schedule-mode verification — 8 October 2026

- Backend: **34 tests passed**, including schedule permissions, strict booleans, metadata
  preservation, missing availability and in-person token rejection for both roles. Migration
  check reported no changes.
- Frontend: **58 unit tests passed**; a focused **18-test rerun** passed after clearing stale
  eligibility on metadata polling failures. TypeScript and production build passed.
- Chrome against the pinned host: **7 mocked-API scenarios passed**, including adjacent
  appointment actions and the native Check-In request; **1 real-backend scenario passed**,
  saving in-person mode through the dialog, verifying existing appointment Zoom actions disappear,
  restoring the fixture's prior flag and verifying Join returns.
- Desktop (1280 px) and mobile (390 px) screenshots were inspected; no horizontal overflow was
  found. Evidence: `.agent/output/playwright/zoom-schedule-video-appointment.png`,
  `zoom-schedule-video-appointment-mobile.png`, `zoom-schedule-video-settings.png` and
  `zoom-schedule-video-settings-mobile.png`. The commands above reproduce these checks.
- Tracked core backend and frontend files remained unchanged. No live two-party audio/video,
  mobile-device media or automatic PiP acceptance was performed for this change.

## Historical verification evidence and bugs already fixed

Evidence is recorded in `.agent/zoom-verification.md`, `.agent/zoom-backend-tests.log`,
`.agent/zoom-migration-check.log`, `.agent/output/playwright/`, and frontend `test-results/`.
These are the 7 October baseline results. Do not infer live-media acceptance or verification of
the 8 October schedule-mode change from mocked tests or historic logs.

- **24 backend tests passed** after fixture repair. Tests exercise real CARE JWT/permission
  records, role/phone scoping, shared family phones, invalid/expired/wrong token types, statuses,
  exact time boundaries, soft deletion, absent/inactive doctors, reassignment/rescheduling,
  server-derived signing, no appointment writes and valid idempotent fixture repair. Actual core
  availability creation returned 200. Migration check reported no changes; Ruff passed.
- **32 frontend unit tests passed** after the SDK join fix; TypeScript and production build
  passed. Tests cover auth/entry points and mocked SDK lifecycle, errors, devices, reconnect,
  host end, teardown, realistic join return values and safe diagnostics.
- **6 mocked-API host browser scenarios passed** during initial implementation: staff login
  return, OTP fallback, preserved native appointment/portal controls, unrelated public routes
  and real lazy SDK prejoin with denied camera permission without a token request.
- **Real-backend browser regression passed** for seeded appointment Join/Copy, original
  Check-In/tags, patient popover and Schedule Management. Screenshots:
  `zoom-appointment-repaired.png`, `zoom-schedule-repaired.png` in `.agent/output/playwright/`.
- **One real doctor Zoom join and leave succeeded with camera/microphone off.** One participant
  and expected controls were visible; Leave returned to the prejoin flow. Evidence:
  `.agent/output/playwright/zoom-real-join-fixed.png`. This proves authentication/SDK join, not
  bidirectional AV. No Zoom tokens or participant payload values were retained in diagnostics.

Reported failures were fixed in plugin code/test data:

1. **Doctor PatientInfoCard warning and broken Schedule Management.** Our initial fixture had a
   null booking note (`.trim()` crash in core actions rendered inside the wrapper), `{}` instead
   of interval-array availability (`.some()`/`.map()` crash), invalid patient identifier cache,
   missing synthetic demographics and a UUID5 schedule rejected by core's UUID4 input schema.
   `seed_local.py` now repairs and validates these records; `test_seed_local.py` and
   `host-live.spec.ts` regress them. Do not hide invalid core children by bypassing the wrapper.
2. **Generic “Could not join” after successful Zoom requests.** Zoom SDK 2.5.0's real join
   resolved a participant object even though its declaration said empty-string success. The
   plugin mistakenly threw all truthy results. `checked()` now detects known resolved SDK
   failure objects by error type/reason, accepting participant success objects. Caught errors
   log fixed operation names, allowlisted types/native names and integer codes only. Media
   setup errors after successful join report media feedback instead of a false join failure.

3. **Relocation startup failures.** The nested backend repository shadowed its editable import;
   external `PYTHONPATH` fixed discovery in backend and Celery. The generated frontend launcher
   called Vite build twice in one process and dropped exposed chunks; the plugin's `dev.mjs`
   now uses a single watch build and starts preview after its first success. Both startup and
   subsequent rebuild were checked. No scaffold template or tracked core file was patched.

The pinned host has emitted initial asset-origin 404s before federation retries at the remote;
these were observed alongside passing flows. A remote-entry connection refusal is a real
runtime failure: inspect this workspace's remote listener/build, not Zoom credentials.
`.agent/verify-http.py` is historical: it expects missing-credentials 503 responses. Do not run
it unchanged against the now-configured backend or treat that expected-status mismatch as a bug.

## Remaining work and new-session entrypoint

1. Confirm the current nested Git roots/status, saved configuration and service mounts before
   editing. Read this file, plugin READMEs and relevant scaffold skills. Preserve all pending
   fixes; core tracked files must stay unchanged.
2. Complete real assigned-doctor plus OTP-patient two-party acceptance: same session, both media
   directions, patient-before-doctor, denied live permissions, reconnect, expired auth/rejoin,
   host ending, clean leave, Android Chrome and iOS Safari. Current local servers bind loopback;
   mobile/deployment testing requires reachable HTTPS host/API/remote and correct CORS/CSP for
   Zoom assets, workers and services. Do not claim acceptance until these are observed.
3. Verify the concurrent staff route, appointment details and picture-in-picture work above;
   resolve the remaining patient appointment integration concern using existing supported
   extension points or overrides. Keep the underlying booking, link, authorization and clinical
   workflow unified.
   Schedule-mode verification is recorded above. Rollout still requires explicit opt-in of
   existing video schedules.
4. Review/commit the existing fixes and documentation in their respective plugin repositories
   when ready. Repository destination/visibility for publication has not been supplied.
5. Expand scope only when requested; recording/transcripts/SMS/jobs are not unfinished v1 work.

Suggested next-session instruction: “Read `AGENTS.md` and
`care/care_zoom/IMPLEMENTATION.md`; inspect both plugin Git statuses; continue the requested Zoom
work in the nested independent repositories with zero tracked core changes.”

Known scaffold reports are [issue #4](https://github.com/ohcnetwork/care_scaffold/issues/4)
(repository isolation/layout guidance) and
[issue #5](https://github.com/ohcnetwork/care_scaffold/issues/5) (extension-point and authentication
guidance differed from the checked-out core). These links record prior work; their current issue
status is not asserted here. Reuse matching reports. New missing core capabilities are blockers
to report via the scaffold feedback policy, not permission to patch core. If filing is unavailable,
record the report in `.agent/scaffold-issues.md` and state that filing remains pending.


Relocation exposed two additional scaffold defects, reported as
[issue #6](https://github.com/ohcnetwork/care_scaffold/issues/6) (frontend watch startup drops
federated modules) and [issue #7](https://github.com/ohcnetwork/care_scaffold/issues/7) (nested
backend repo shadows its editable import). Local fixes are in the plugin launcher and external
Compose configuration; reusable scaffold fixes remain separate work.

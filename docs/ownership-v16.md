# V16-020…V16-026 — every CRM customization is owned by the app

Status: **done and proven on both sites.** Gate: `tools/v16-probe.py` prints
`RESULT PASS` on `flowire.local` *and* on a fresh `fresh.localhost`
(frappe + erpnext + flowire, **no** `crm` app).

Bench this was measured on: frappe 16.50.0 · erpnext 16.54.0 · crm 1.86.0 · flowire
(installed apps on the reference site: frappe, crm, erpnext, hrms, flowire).

## What was wrong

| Symptom (before) | Why it mattered |
|---|---|
| `Lead.source`, `Lead.campaign_name`, `Opportunity.source`, `Opportunity.campaign` were Custom Fields with a **blank module** | The fixture filter keys off `module = Flowire`, so they were never exported and were invisible to ownership checks |
| `Lead Source` was a **custom** DocType (`custom=1`, `module=CRM`) created through the REST API by `docker/frappe/setup/attach-frontend.mjs` | A custom DocType is a database row, not a file: absent on a fresh site, so every `source` link there pointed at nothing |
| The 14 `Lead Source` rows were copied out of the `crm` app by the same setup script | A Flowire site must not need the `crm` app to have selectable Lead Sources |

Measured on `flowire.local` before the change — `RESULT FAIL (2)`:

```
DOCTYPE Lead Source      module=CRM        custom=1
CF      Lead             total=11  Flowire=9   unowned=2   -> campaign_name, source
CF      Opportunity      total=39  Flowire=37  unowned=2   -> campaign, source
```

On the fresh site the same probe showed the deeper half of the problem:
`DOCTYPE Lead Source MISSING`, `CF Lead total=9`, `CF Opportunity total=37` — no Source
or Campaign field at all, so the frontend's Lead form had nothing to bind to.

## What changed

| File | Change |
|---|---|
| `flowire/flowire/doctype/lead_source/` | **new** — `Lead Source` ships as an app DocType (definition copied verbatim from the live row: `source_name` Data reqd/unique, `details` Small Text, three role permissions, autoname `field:source_name`) |
| `flowire/fixtures/lead_source.json` | **new** — the 14 rows, exported with `bench export-fixtures` |
| `flowire/patches/v1_0/own_lead_source.py` | **new**, `[pre_model_sync]` — flips the existing custom row to `custom=0, module=Flowire` and reloads the definition from the shipped file. Does **not** delete the DocType (deleting a DocType drops its table and the rows with it); it refuses to continue if the row count drops |
| `flowire/patches/v1_0/tag_flowire_records.py` | the four version-dependent fields added to the allow-list, so an existing site stamps `module=Flowire` on them |
| `flowire/setup/schema.py` | **new** — creates the four version-dependent fields per site, guarded (Custom Field → adopt; stock DocField → leave; bare column → leave; none → create). Fixtures cannot express this: a fixture would add a second column on ERPNext v15, where the doctype still owns those names |
| `flowire/setup/install.py` | `after_install` / `after_migrate` now run `schema.sync()` before `notifications.sync()` |
| `flowire/hooks.py` | fixtures: Custom Field filter excludes the four version-dependent names; Custom DocPerm parents extended to Prospect, Company Bidder, EM Banks; `Lead Source` added |
| `flowire/fixtures/*.json` | re-exported (Custom Field 46 rows — same set, export order differs; Custom DocPerm 8; Property Setter 2; Lead Source 14) |
| `flowire/tools/parity.py` | gains `compare()` / `compare_files()` / `cli()` — **exit 1 on any difference**; snapshot now includes per-doctype Custom Field ownership and the five status/stage option lists; automation scoped to what this app owns |
| `flowire/tests/` | **new** — 12 `IntegrationTestCase` tests covering the same invariants as the probe |
| `tools/v16-probe.py` | the ownership probe, copied into this repo so the gate can be run from here |

## Evidence

### 1. `flowire.local` (the reference site, migrated in place)

```
$ docker cp tools/v16-probe.py flowire-frappe-backend:/tmp/v16-probe.py
$ docker exec --user frappe flowire-frappe-backend bash -lc \
    'cd frappe-bench/sites && ../env/bin/python /tmp/v16-probe.py flowire.local'

DOCTYPE Lead Source      module=Flowire    custom=0
CF      Lead             total=11  Flowire=11  unowned=0
CF      Opportunity      total=39  Flowire=39  unowned=0
PSETTER Property Setter module=Flowire: 2
PERM    Custom DocPerm (our parents): 6
LEADSRC Lead Source rows: 14
SCRIPT  Server Scripts: 5 total, 0 enabled
RESULT PASS — every CRM customization is owned by an app
```

`bench --site flowire.local migrate` ran `flowire.patches.v1_0.own_lead_source`,
synced the fixtures, and did **not** orphan the DocType:

```
Executing flowire.patches.v1_0.own_lead_source in flowire.local (_66603709ee5fd2ba)
Success: Done in 0.51s
Updating DocTypes for flowire       : [========================================] 100%
Syncing fixtures...
Removing orphan doctypes...
Executing `after_migrate` hooks...
```

### 2. `fresh.localhost` (frappe + erpnext + flowire, no `crm` app)

Site reinstalled from scratch with the new code (`bench --site fresh.localhost reinstall`):

```
DOCTYPE Lead Source      module=Flowire    custom=0
CF      Lead             total=11  Flowire=11  unowned=0
CF      Opportunity      total=39  Flowire=39  unowned=0
LEADSRC Lead Source rows: 14
CORE    CRM Lead doctype present (standalone crm app): False
SCRIPT  Server Scripts: 0 total, 0 enabled
RESULT PASS — every CRM customization is owned by an app          (exit 0)
```

### 3. Parity — reference vs fresh is a gate now

```
$ bench --site flowire.local execute flowire.tools.parity.cli \
    --kwargs '{"left": "/tmp/parity-flowire.json", "right": "/tmp/parity-fresh.json", "out": "docs/parity-report.txt"}'
PARITY PASS — the two sites are identical where it matters
```

Both snapshots are byte-identical (93,356 bytes): 7 doctypes (schema, permissions,
property setters, Custom Field ownership), the 5 status/stage option lists, and the
app's own automation. Artifacts: `docs/parity-after.json`, `docs/parity-fresh.json`,
`docs/parity-report.txt`.

First run of the new comparison reported 52 differences — **all** of them stock
erpnext/hrms Notifications and Email Templates, i.e. `hrms` is installed on
`flowire.local` and not on the fresh site. That is not this app's data, so
`_automation()` now compares only the app's own set (declared once, in
`flowire/setup/notifications.py`) plus "no enabled Server Script on our doctypes",
which is the invariant that actually matters. Everything else is compared in full.

### 4. Tests

```
$ bench --site flowire.local run-tests --app flowire
Running 12 integration tests for flowire
✔ test_lead_source_is_owned_by_the_app          ✔ test_every_custom_field_on_our_doctypes_is_ours
✔ test_lead_source_definition_ships_as_a_file   ✔ test_every_app_doctype_has_a_definition_file
✔ test_lead_source_rows_survived                ✔ test_status_options_are_unchanged
✔ test_lead_source_rows_ship_as_a_fixture       ✔ test_behaviour_lives_in_doc_events_not_server_scripts
✔ test_fixtures_cover_lead_source_and_...       ✔ test_schema_sync_is_idempotent
✔ test_version_dependent_fields_are_not_...     ✔ test_version_dependent_fields_exist_and_are_owned
Ran 12 tests in 0.252s — OK
```

`test_every_app_doctype_has_a_definition_file` is the guard for the one way this app
could still lose data: a DocType with `module=Flowire, custom=0` and no file in the app
is deleted — table and rows — by `remove_orphan_doctypes()` during the next migrate.

## v16 conformance notes

* `has_permission` hooks: this app registers **none**, so there is no `None` return to
  make explicit. Access is granted with DocShare rows (`flowire/crm/sharing.py`) —
  correctly, because `has_permission` can only restrict.
* `override_doctype_class`: not used.
* Packaging: `pyproject.toml` only (flit), `frappe = ">=15.0.0,<17.0.0"`; no `setup.py`.
* Tests: `frappe.tests.IntegrationTestCase`, no data left behind (`bench run-tests`
  requires `allow_tests` on the site).

## Left open (not this job)

1. `flowire/setup/data/` does not exist, so `notifications.sync()` logs a warning and
   returns: the four CRM Notifications and two Email Templates the app declares have
   never been captured from a reference site. Capture them with
   `bench --site <reference> execute flowire.setup.notifications.capture`.
2. `docker/frappe/setup/attach-frontend.mjs` still creates `Lead Source` and copies the
   `crm` rows. It lives in the bench/setup repo, not here. Once that block is removed,
   the two paths cannot disagree; until then the patch makes the app win.
3. Production (ERPNext v15) was not touched. `Contact.search_fields` (§2b of the
   inventory) is still an open ruling.

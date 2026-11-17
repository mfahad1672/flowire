# flowire

Frappe app for **Flowire CRM** — installed on **every tenant site**.

Part of the Flowire multi-tenant platform. This repository is deliberately separate from the
Next.js frontend repository (`flowire-crm`) so that:

- it can be installed with `bench get-app` straight from git,
- it can be versioned, released and moved independently of the frontend,
- it is obvious which code is *backend schema* and which is *frontend UI*.

See `docs/multitenancy-plan.md` in the `flowire-crm` repository for the full plan.

## What lives here

| Path | Purpose |
|---|---|
| `flowire/hooks.py` | `fixtures`, `doc_events`, `scheduler_events`, `before_request` |
| `flowire/fixtures/` | Custom Fields, Property Setters, Custom DocPerm, Roles, Workflows |
| `flowire/flowire/doctype/` | Custom DocTypes shipped as code, including CRM and Project Costing |
| `flowire/flowire/project_costing.py` | Project costing, effective employee rates, and resource summary APIs |
| `flowire/patches/` | Replayable migrations (e.g. tagging customizations with `module = Flowire`) |
| `pyproject.toml` | Package metadata read by `bench new-app` / `bench get-app` |

## Install

```bash
bench get-app https://github.com/<org>/flowire.git
bench --site <site> install-app flowire
```

A site created with both apps must be identical to the reference CRM:

```bash
bench new-site acme.flowire.app \
  --install-app erpnext \
  --install-app flowire
```

## Rules this app enforces

1. **All DocType customizations ship here** — as fixtures or as code. Never customize through
   Desk on a tenant site.
2. **Fixtures filter by `module`** (Custom Field, Property Setter), **never by `dt` alone** — a
   `dt` filter would capture a tenant's own custom fields and then push them to every other tenant.
3. **Custom DocPerm fixtures filter by `parent`**, listing every doctype that has *any* Custom
   DocPerm row and exporting *all* rows for it. Filtering by `role` silently revokes access from
   the roles that were omitted, because Frappe ignores a doctype's standard permissions as soon
   as it has a single Custom DocPerm row.
4. **Schema is never created at runtime.** Nothing in this app may create a Custom Field on
   request or page load.
5. **Project costing stays additive.** Its DocTypes, validations, and Timesheet event handlers
   live here; ERPNext and HRMS source records remain the source of truth.

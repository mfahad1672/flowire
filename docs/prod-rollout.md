# Production rollout — `flowire` app

Written during Track A. **Nothing here has been run against production.** Production
is changed only by the human, or on their explicit instruction.

The app is additive: it installs fixtures, two DocTypes, six patches and a
handful of `doc_events`. It does not modify `apps/frappe` or `apps/erpnext`.

---

## 0. Before you start

| Check | Command | Expected |
|---|---|---|
| Prod versions | `bench --site <prod> version` | frappe / erpnext `version-15` |
| Installed apps | `bench --site <prod> list-apps` | `frappe`, `erpnext` |
| Rehearsal passed | — | `docs/` snapshot diff empty; smoke test green |

Do **not** run this without a rehearsal on a restored copy. The patches act on
`Server Script`, `Notification Settings` and `DocShare` rows; on a live site those
are not reversible by re-running a patch.

---

## 1. Backup first (non-negotiable)

```bash
bench --site <prod> backup --with-files
ls -lh sites/<prod>/private/backups/
```

Three files: `-database.sql.gz`, `-files.tar`, `-private-files.tar`. Copy them off
the box before proceeding. **This backup is the rollback.**

---

## 2. Install the app

```bash
cd /home/frappe/frappe-bench
bench get-app https://<git-host>/flowire.git --branch main
bench --site <prod> install-app flowire
```

`install-app` runs `after_install` → `flowire.setup.install.after_install`, which
calls `notifications.sync()`. That requires the frontend URL to be configured
**first**, otherwise sync logs a warning and does nothing (by design — it never
breaks an install):

```bash
bench --site <prod> set-config flowire_frontend_url "https://<prod-frontend>"
```

## 3. Migrate

```bash
bench --site <prod> migrate
bench --site <prod> clear-cache
```

`migrate` runs, in this order:

| Patch | Effect |
|---|---|
| `tag_flowire_records` (pre_model_sync) | sets `module = "Flowire"` on the approved Custom Fields / Property Setters |
| `disable_legacy_server_scripts` | `disabled = 1` on the 6 Server Scripts — **not** deleted |
| `disable_builtin_assignment_emails` | `enable_email_assignment = 0` for existing users |
| `backfill_assignment_shares` | DocShare for every open ToDo assignment |

The `doc_events` in `hooks.py` go live in the same migrate that disables the old
scripts, so sharing never runs twice.

---

## 4. Smoke test (as a Sales User **and** a Sales Manager)

- [ ] Open an existing Lead; all custom fields and tabs render, values intact
- [ ] Create a Lead → save → no error; appears in the list
- [ ] Open an Opportunity; EM / PG tabs present; bidder and bank links populate
- [ ] Create an Opportunity; save; re-open
- [ ] Assign a Lead to a Sales User → they can open **and edit** it
- [ ] Cancel that assignment → they lose access
- [ ] Re-assign, then delete the ToDo → access is removed
- [ ] Set `lead_owner` / `opportunity_owner` to another user → they get access
- [ ] A new user's Notification Settings shows assignment email off
- [ ] Assignment sends **exactly one** email (check Email Queue)
- [ ] CRM dashboard counts match the pre-migration numbers
- [ ] `bench --site <prod> execute flowire.tools.parity.snapshot` still equals the rehearsal snapshot

---

## 5. Rollback

**`uninstall-app` is NOT a rollback.** It drops the two DocTypes and their tables
— i.e. `tabCompany Bidder` and `tabEM Banks` and every record in them. Never run
it on production.

| Situation | Action |
|---|---|
| Anything is wrong at all | Restore the backup from §1: `bench --site <prod> restore <db.sql.gz>` (+ files), then `migrate` |
| Only sharing misbehaves | Re-enable the 6 Server Scripts in Desk (they are disabled, not deleted) and `bench --site <prod> clear-cache` — the Python handlers are idempotent, so a brief overlap is harmless |
| Notifications wrong | `bench --site <prod> console` → `frappe.get_doc("Notification", "<name>").save()` after editing; or restore the backup |

---

## 6. What must never happen

- Editing `apps/frappe` or `apps/erpnext` on prod
- `bench uninstall-app flowire` on prod
- Installing the app before setting `flowire_frontend_url`
- Deploying the code without the `disable_legacy_server_scripts` patch (both
  handlers would run)
- Restoring a v15 dump into a v16 bench, or vice versa

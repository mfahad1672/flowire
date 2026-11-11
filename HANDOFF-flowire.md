# Handoff — the `flowire` app work (V16-020…V16-026)

Everything below happens in **`D:\CRM\flowire`** (the backend app repo) on the **local bench**
(`flowire.local`, container `flowire-frappe-backend`). It cannot be done from the frontend chat:
that folder is outside its scope and its writes are refused by the runtime.

## How to start that chat

1. In Asterxa Code, **open the folder** `D:\CRM\flowire` (folder switcher → Open folder).
2. Start a **new chat** in it, and paste the prompt in §1 below as-is.
3. When the agent asks for evidence, point it at this document and at
   `D:\CRM\flowire-crm - Copy\docs\setup-notes.md` §4 (the same rows, measured).

## 1. Prompt to paste into the new chat

```
Work only in this repo (D:\CRM\flowire) and on the local bench (flowire.local, container
flowire-frappe-backend). Never touch apps/frappe or apps/erpnext, never touch production, never
rename a field. Read D:\CRM\flowire-crm - Copy\docs\setup-notes.md §4 and
D:\CRM\flowire-crm - Copy\docs\v16-progress.md first: they contain the measured gap and the exact
rows to fix.

Goal: every CRM customization is owned by this app, provably, on a fresh site.

  1. Stamp module="Flowire" on the four Custom Fields that currently have a blank module:
       Lead.source, Lead.campaign_name, Opportunity.source, Opportunity.campaign
  2. Own "Lead Source": it exists today only as a script-created custom doctype
     (custom=1, module=CRM) with 14 rows. Ship it in flowire (doctype file, and the rows as a
     fixture), keeping the same name so every `source` link keeps working.
  3. In docker/frappe/setup/attach-frontend.mjs (the copy inside this bench's setup): remove the
     code that creates Lead Source and copies CRM Lead Source rows.
  4. hooks.py fixtures: include Custom Field, Property Setter (filter module=Flowire) and
     Custom DocPerm (parents: Lead, Opportunity, Prospect, Company Bidder, EM Banks). Then
     `bench --site flowire.local export-fixtures --app flowire` and commit the JSON.
  5. Write tools/parity.py: compares two sites on fields (name, type, options, reqd, hidden),
     select options of the five status/stage fields, Custom DocPerm rows and Property Setters.
     Exit 1 on any difference.
  6. Fresh site proof: bench new-site fresh.localhost --install-app erpnext --install-app flowire
     (the crm app must NOT be installed), then run the probe and parity against it.
  7. v16 conformance: has_permission hooks return an explicit True (never None),
     override_doctype_class targets inherit from what they override, packaging is pyproject.toml
     only, tests use IntegrationTestCase + frappe.in_test.

Exit check for every step: paste the command and its output. The gate that matters is
`python D:\CRM\flowire-crm - Copy\scripts\v16-probe.py` on the fresh site reporting RESULT PASS
(today it reports RESULT FAIL (2) on flowire.local). Do not mark anything done without that output.
```

## 2. What the agent will find (measured, so it cannot be argued with)

```
DOCTYPE Lead              module=CRM      custom=0
DOCTYPE Opportunity       module=CRM      custom=0
DOCTYPE Lead Source       module=CRM      custom=1     <- created by the setup script
DOCTYPE Company Bidder    module=Flowire  custom=0
DOCTYPE EM Banks          module=Flowire  custom=0

CF Lead         total=11  Flowire=9   unowned: campaign_name, source
CF Opportunity  total=39  Flowire=37  unowned: campaign, source
PSETTER module=Flowire: 2   PERM (our parents): 6   Lead Source rows: 14
SCRIPT Server Scripts: 5 total, 0 enabled   (behaviour lives in doc_events — leave them disabled)
```

## 3. Commands it will need (verified working from this machine)

```powershell
docker exec --user frappe flowire-frappe-backend bash -lc "cd frappe-bench && bench --site flowire.local export-fixtures --app flowire"
docker exec --user frappe flowire-frappe-backend bash -lc "cd frappe-bench && bench --site flowire.local migrate"
docker cp scripts/v16-probe.py flowire-frappe-backend:/tmp/v16-probe.py
docker exec --user frappe flowire-frappe-backend bash -lc "cd frappe-bench && bench --site flowire.local console < /tmp/probe-oneliner.py"
```

The probe one-liner (needed because `bench console` executes stdin line by line) is:

```python
exec(open("/tmp/v16-probe.py").read(), {"__name__": "__main__", "sys": __import__("sys")})
```

## 4. What comes back to this frontend repo afterwards

1. `python scripts/v16-probe.py` must print `RESULT PASS`.
2. Re-run `docs/baseline/crm-checklist.md` §8.1 and §8.3 against the site.
3. Mark V16-020…V16-026 done in `TASKS.md`, and move the `BLOCKED` rows in
   `docs/QA-REPORT.md` §8 to their evidence.
4. With a production backup on the rehearsal bench, `tools/parity.py` closes R-1.2, R-9.3, R-9.4,
   R-11 and R-13.2 — the last of the plan's gates.

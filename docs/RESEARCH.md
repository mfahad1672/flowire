# RESEARCH.md — Flowire CRM: the tender-CRM domain, the platform, the alternatives

**Pass 1.** Feeds the `requirements` step. Every finding is numbered `F-n` and ends in a numbered
requirement `R-n` in §7, each with the check that proves it. Requirement ids here use the `R-2x`
range so they cannot be confused with the plan ids already on record (§8).

**What was measured, not assumed:** `flowire.local` — frappe **16.50**, erpnext **16.54**, apps
`frappe, crm, erpnext, hrms, flowire`; **50** app-owned Custom Fields (46 fixtures + 4 created in
code), **Lead Source** with **14** rows, **2** Property Setters, **8** Custom DocPerm rows in scope,
**5** Server Scripts (0 enabled), **0** Notifications of ours.

**Constraints that shaped every requirement below** (they are not negotiable, and half the
findings are only interesting because of them):

1. Never rename a field — the Next.js frontend binds ~50 fieldnames, several of them misspelled.
2. Never touch `apps/frappe` or `apps/erpnext`.
3. Every customization must exist on a **fresh** site where the standalone `crm` app is **not**
   installed, and on a **v15** production site where four of those fields are native.

---

## 1. Method

- 8 web searches; 5 pages read in full (reader mode). Snippets-only sources are marked in §2 and
  are never the sole support for a requirement that changes code.
- Local ground truth read from `docs/inventory.md`, `docs/ownership-v16.md`,
  `docs/parity-report.txt`, `flowire/hooks.py`, `tools/v16-probe.py`.
- Confidence legend used in the matrix (§4): **OK** read in a source this pass · **doc** well
  documented, not re-verified this pass · **?** not established — do not build on it.

## 2. Sources

| # | Source | What it established | Conf |
|---|---|---|---|
| S1 | https://github.com/frappe/crm | Frappe CRM feature set: all-in-one lead/deal page, Kanban, custom views, Twilio + Exotel + WhatsApp (via `frappe_whatsapp`), ERPNext integration. Releases: `main` v1.x is compatible with Frappe **v15.x and v16.x**, `develop` targets v17. | OK |
| S2 | https://discuss.frappe.io/t/version-16-release-plan/142686 | v16 plan thread; the accepted schedule in it is beta **15 Nov 2025**, final **6 Dec 2025**. Content is mostly discussion — the dates come from the thread summary. | OK |
| S3 | https://frappe.io/erpnext/version-16 | v16 is "almost two years since the last release", 600+ contributors, 50+ features, positioned on stability / performance / safer defaults. The page is JS-rendered — the feature list itself did not extract. | OK |
| S4 | https://fwcpk.com/bank-guarantee-register/ | A working contractor guarantee register: tracks bid / PG / advance / retention / CDR, warns at **60/30/15/7 days + overdue**, checks a bid security covers **28 days past bid validity**, flags securities **overdue for release**, holds **claim period**, totals **exposure and cash margin by bank**, estimates commission, drafts release/extension/reduction letters. Quotes the rules: PPR 2026 **R.36** (bid security ≤ 5% of estimated value up to PKR 250 M, 2% above), **R.51** (PG ≤ 10% of contract), SBD Works 2024 **ITB 18/19** (security valid 28 days past bid validity; unsuccessful bidder paid back ≤ 30 days after bid validity ends; winner discharged on contract + PG). | OK |
| S5 | https://www.melonslab.com/guides/hubspot-salesforce-alternatives | Measured head-to-head of the two credible self-hosted alternatives: **Twenty 2.46.0** (custom fields + custom objects, workflows, dashboards, API and webhooks **in the free version**; "own deals only" is **paid**; AGPL-3.0 with some commercial files; 1.49 GB RAM at rest; no GDPR "find everywhere" tool) vs **Odoo 20 Community** (CRM free, own-deals-only **free**, custom fields need **developer mode** and a drag-and-drop view is Enterprise Studio; LGPL-3; 244 MB at rest). Also documents how hard CSV migration from HubSpot/Salesforce is (object-per-file, ID matching by domain/unique field). | OK |
| S6 | https://docs.frappe.io/erpnext/lead_source | ERPNext documents Lead Source as the master behind a lead's origin — the v15 lineage our `source` / `campaign_name` fields were built against. | doc (snippet) |
| S7 | https://discuss.frappe.io/t/field-missing-in-version-16/162618 | Fields present in v15 but missing in v16 is a known, reported class of v16 breakage (reported on Payment Entry). | doc (snippet) |
| S8 | https://discuss.frappe.io/t/what-is-best-practice-to-create-custom-fields-fixtures-or-coding/135904 | Community answer on fixtures vs code for Custom Fields; the recurring caveat is that fixtures are hard to maintain and that "Module (for export)" is what scopes them to an app. | doc (snippet) |
| S9 | https://pakistantender.com/blog/bid-security-earnest-money-pakistan | Market guide: bid security / earnest money in Pakistani tenders, accepted instruments include **CDR and bank guarantee** (our `EM Banks` master and `custom_em_pg_bank` link assume exactly this). | doc (snippet) |
| S10 | https://github.com/tridz-dev/huf/issues/792 | The v16 conformance point from the handoff, independently reported: `has_permission` hooks that end in `return None` must `return True` explicitly. | doc (snippet) |
| S11 | https://twenty.com/product · https://docs.twenty.com/developers/self-host/self-host | Twenty's pitch: "pipelines, custom objects, native API on top of Postgres", self-hostable, objects declarable as code. | doc (snippet) |
| S12 | https://bwerp.co.in/tutorials/bank-guarantee-bg-types-validity-extension-release-contractors | BG taxonomy for contractors — PBG, EMD BG, advance BG, validity, extension, release; the same four operations our `custom_pg_*` fields encode. | doc (snippet) |
| S13 | https://frappe.io/releases/version-16 | v16 shipped as a major release across ERPNext, Framework and HR. | doc (snippet) |
| S14 | `docs/inventory.md`, `docs/ownership-v16.md`, `docs/parity-report.txt`, `tools/v16-probe.py` (this repo) | The measured state of the reference site and of the fresh site; the invariants the probe enforces today. | OK |

---

## 3. Findings

### 3.1 The domain — what a bid desk actually has to keep straight

**F-1 · The money rules are regulated, so the ceilings are known and the app checks neither.**
PPR 2026 R.36 caps a bid security at 5% of the estimated value up to PKR 250 M and 2% above;
R.51 caps a performance guarantee at 10% of the contract amount (S4; the guarantees themselves
come as CDR, pay order or bank guarantee — S9). In our schema `custom_estimated_value`,
`custom_bid_security`, `custom_pg_amount` and `custom_performance_gaurantee` are plain Currency
fields with no relationship, and nothing anywhere compares them. A typo (`2 500 000` typed for
`250 000`) is silently accepted and becomes the number a bid is priced against.
→ **R-20.1, R-20.2**

**F-2 · The bid-security deadline is derivable only if a field that does not exist exists.**
The 28-day rule (security must remain valid 28 days past the end of bid validity; an
unsuccessful bidder's security is due back within 30 days after bid validity ends — S4, SBD Works
2024 ITB 18/19) needs *bid validity in days*. The Opportunity carries a submission date
(`custom_submission_date`), a valid-till (`custom_valid_till`) and a release date
(`custom_release_date`) but **no bid-validity length**, so neither "does this security cover the
window" nor "when is it due back" can be computed — both are retyped by hand.
→ **R-20.3, R-20.4**

**F-3 · The four dates we store are exactly the four alert axes of every register in the market,
and nothing fires.**
The reference register warns at 60/30/15/7 days and on overdue, flags securities overdue for
release, and tracks extension (S4; S12 for the same lifecycle in banking terms). `flowire/hooks.py`
declares **no `scheduler_events`** — `README.md` claims one that does not exist — so an expiring
performance guarantee, a bid security nobody claimed back, and an expired CDR are all silent.
The cost is concrete: cash margin blocked, bank limit tied up, commission still running (S4).
→ **R-20.5, R-20.6**

**F-4 · Guarantee data is modelled three times in parallel, with three overlapping status
vocabularies — and it cannot be renamed.**
Measured on the reference site: a top-level track (`custom_bid_security`, `custom_submission_date`,
`custom_valid_till`, `custom_release_date`, `custom_status_pendingreleased`), an EM/PG track
(`custom_em_pg_*`: type, amount, bank, submitting entity, submitting person, status, submission
date, valid till), and a PG track (`custom_pg_*`: 12 fields including bidder, PO number, account
manager, remarks). Status options are `Not Required / Pending / Submitted / Released` **twice**
(`custom_status_pendingreleased`, `custom_pg_status`) and `Pending / Released` once
(`custom_em_pg_status`), on top of `custom_opportunity_status` and `custom_lead_status`. That is
not a model, it is three snapshots of the same object taken by three people. Because the frontend
binds every one of those names, the deliverable is **freeze + document + derive**, not consolidate:
one coherent alert engine over all three tracks now, one child table for guarantees only after an
approved frontend change.
→ **R-20.7, R-20.8**

**F-5 · Instrument type and claim period decide when a guarantee stops costing money — neither is
recorded.**
A CDR or pay order ties up the full amount while a bank guarantee ties up a margin (S4, S9), and a
guarantee with a claim period keeps the bank liable (and the margin blocked) after its expiry date
(S4). `custom_em_pg_type` distinguishes Bid Security from Performance Guarantee, but no field says
*how* the security was furnished, and no field holds claim days. Consequence for the alerts in
R-20.5: they must not treat the expiry date as the last day of exposure, and the gap has to be
recorded as a known limitation rather than guessed at.
→ **R-20.9**

### 3.2 The platform — Frappe / ERPNext v16

**F-6 · v16 removed four fields this CRM depends on, and a measured probe is the only reliable
inventory of what is left.**
On erpnext **16.54** there is no DocField `Lead.source`, `Lead.campaign_name`,
`Opportunity.source` or `Opportunity.campaign`; on v15 there is. Fields vanishing between majors
is a reported class of v16 breakage (S7), and `bench update` replaces `apps/erpnext` wholesale, so
anything that exists only as a database row is gone on a fresh site. Measured after the fix: `CF
Lead total=11 Flowire=11 unowned=0`, `CF Opportunity total=39 Flowire=39 unowned=0` on
`flowire.local` **and** on `fresh.localhost`. → **R-21.1** (met)

**F-7 · Fixtures are the supported ownership mechanism, and `module` is the only safe scope.**
The community answer on fixtures-vs-code turns on the same point as our own rule: a Custom Field is
exported for an app because its **Module (for export)** names that app (S8). Our four fields had a
blank module — that is precisely why the probe counted them unowned while they worked perfectly on
the reference site. A `dt`-only fixture filter would be worse than unowned: it would push a
tenant's own UI-created field into every other tenant. → **R-21.2** (met)

**F-8 · One Custom DocPerm row replaces the doctype's standard permissions — which makes
`if_owner` a free feature competitors charge for.**
Frappe ignores a doctype's standard permissions as soon as a single Custom DocPerm row exists, so a
role-filtered export silently revokes access (our README rule 3; measured: 8 rows across Lead,
Opportunity, Communication, ToDo). Those rows include `Sales User … if_owner=1` — own-records-only
scoping. Twenty charges for exactly that ("own deals only" is in its paid plan) and Odoo gives it
free (S5); we get it for free and must not lose it to a bad fixture filter.
→ **R-22.1, R-22.2** (met)

**F-9 · Behaviour cannot ship as Server Scripts, and the probe already enforces that.**
Server Scripts, Client Scripts, Notifications and Email Templates are database rows: a fresh site
gets none of them, so the five `CRM …` Server Scripts had to be ported to `doc_events`
(`flowire/crm/sharing.py`). The probe fails the gate if any Server Script is enabled.
→ **R-22.3** (met)

**F-10 · v16 wants an explicit decision from permission hooks, and this app correctly has none.**
A `has_permission` hook that falls through to `return None` for an unhandled `ptype` is reported as
a v16 defect to fix by returning `True` (S10). `flowire` registers **no** `has_permission` hook at
all: per-document access is granted with DocShare rows because `has_permission` can only *restrict*
(`flowire/crm/sharing.py`). The requirement is therefore a guard, not a rewrite — if a hook is ever
added it must return an explicit `True`, and a test asserts the current set stays empty or explicit.
→ **R-22.4**

**F-11 · Two majors must be supported at once, so schema has to be version-guarded rather than
declared.**
Production is v15, the target is v16, and the wider ecosystem ships the same way — `frappe/crm`
declares one stable line compatible with **v15.x and v16.x** (S1) and v16 itself landed as a
stability-and-defaults release (S3, S13). That is why the four F-6 fields are created per site by
`flowire/setup/schema.py` (adopt / leave / create) instead of travelling as fixtures: a fixture
would add a duplicate column on v15. Measured clean on both majors.
→ **R-21.3** (met)

**F-12 · The standalone `crm` app must remain optional, and the overlap is by name.**
`frappe/crm` is a separate product with its own `CRM Lead` doctype and its own pipeline UI (S1);
this stack's Lead/Opportunity come from ERPNext. A tenant site that installs only `erpnext` +
`flowire` must be complete, so the probe prints and gates on
`CORE CRM Lead doctype present: False` on `fresh.localhost`.
→ **R-21.5** (met)

### 3.3 The alternatives — where this product has to be at least as good

**F-13 · Kanban and custom views are table stakes; a messaging channel and per-record scoping are
where the fight actually is.**
Frappe CRM sells Kanban + custom views + Twilio/Exotel/WhatsApp (S1); Twenty sells pipelines,
custom objects and "agents" on Postgres (S11); Odoo gives own-deals-only away and charges for
Studio (S5). Our schema already stores `custom_whatsapp_no` and `custom_stage_1` (a Link to the
`Sales Stage` master), but there is no sending integration and no guarantee that the `Sales Stage`
master exists on a fresh site. The pipeline the user sees must be driven by **one** stage source,
not by four status selects that disagree.
→ **R-23.1, R-23.2**

**F-14 · Self-hosting is the differentiator, and the only way to keep that promise is a
reproducible per-tenant schema.**
The reason a contractor picks a self-hosted CRM over Salesforce/HubSpot is control of the data and
the deployment (S5). That promise dies the first time two tenant sites — one built from a backup,
one built fresh — differ in a field's options or a permission row. Nothing in a chat window proves
that; only a diff that **exits non-zero** does.
→ **R-24.1, R-24.2, R-24.3**

---

## 4. Competitor / feature matrix

Legend — **OK** verified in a source read this pass (S#) · **doc** documented behaviour, not
re-verified this pass · **?** not established · **—** absent from that product's published feature
set.

| Feature | **Flowire (this app)** | Frappe CRM | ERPNext Lead/Opp | Salesforce | HubSpot | Pipedrive | Zoho CRM | Odoo CRM | Twenty |
|---|---|---|---|---|---|---|---|---|---|
| Custom fields without paying for an edition | **OK** — ships as fixtures (S14) | OK (S1) | doc | doc | doc | doc | doc | **doc — needs developer mode** (S5) | **OK — Settings › Data model** (S5) |
| Custom objects / doctypes as code | **OK** — DocType files in the app | doc | doc | doc | doc | ? | ? | ? | **OK — "objects as code"** (S11) |
| Kanban pipeline | doc (frontend, `custom_stage_1`) | **OK** (S1) | doc | doc | doc | doc | doc | doc | **OK** (S11) |
| Validity / expiry reminder automation | **— (F-3: nothing fires)** | ? | doc (Notifications) | doc (Flows) | doc (Workflows) | ? | doc | doc | **OK — workflows free** (S5) |
| Bid security / guarantee register as first-class data | **OK — the reason this product exists** | — | — | — | — | — | — | — | — |
| Own-records-only scoping at no extra cost | **OK** (`if_owner=1` Custom DocPerm, S14) | ? | doc | doc | doc | doc | doc | **OK — free** (S5) | **doc — paid plan** (S5) |
| Self-hosted | **OK** | **OK** (S1) | **OK** | — | — | — | — | **OK** (S5) | **OK** (S11) |
| Licence | proprietary app; Frappe framework + ERPNext underneath | doc (GPL-3) | doc (GPL-3) | — | — | — | — | **OK LGPL-3, Enterprise proprietary** (S5) | **OK AGPL-3 + commercial files** (S5) |
| WhatsApp / messaging channel | **— field only** (`custom_whatsapp_no`) | **OK** via `frappe_whatsapp` + Twilio/Exotel (S1) | — | doc | doc | ? | doc | ? | ? |
| Reproducible per-tenant schema (diffable) | **OK** — probe + parity, exit 1 (S14) | ? | ? | n/a | n/a | n/a | n/a | ? | ? |

---

## 5. What this pass did not establish

1. **No customer interviews.** Everything about how the bid desk works today is inferred from the
   schema the frontend drives plus published procurement rules. The field names say `custom_pg_*`
   and `custom_em_pg_*`; they do not say which one the desk actually fills in, or whether
   `custom_status_pendingreleased` is still used at all.
2. **Nothing on the four missing Notifications.** The reference bench has **0** of the 4 CRM
   notifications and both email templates (`docs/inventory.md` §4), so the alert content can be
   captured only from a production backup. R-20.5 therefore specifies *behaviour*, not wording.
3. **Salesforce / HubSpot / Pipedrive / Zoho cells are `doc`, not verified** — one comparison
   article (S5) covers only Twenty and Odoo in depth. No pricing claim is made anywhere; pricing in
   this market changes monthly and is not a differentiator we can win on.
4. **The provider-side rules are jurisdiction-specific.** S4 summarises federal PPR 2026 and the
   four provincial variants. If tenants bid outside Pakistan, the ceilings in R-20.1/R-20.2 must be
   configurable per site, not constants.
5. **Frappe v16 framework internals were not read from source.** The `has_permission` point in
   F-10 rests on a third-party issue report (S10) plus the fact that this app registers no such
   hook — which is a safe position either way.

## 6. Decisions this research forces

These are the user's to make, and each one changes what gets built.

- **D-1 · Consolidate the three guarantee tracks into one child table?** Recommended: **no, not
  now.** Three parallel field sets are live on production and bound by the frontend; a
  consolidation is a data migration plus a frontend release. Requirements below treat the
  duplication as frozen contract (R-20.7) and put the intelligence in one alert engine instead
  (R-20.5).
- **D-2 · Add `Opportunity.custom_bid_validity_days`?** Recommended: **yes.** Without it the
  28-day and 30-day rules in F-2 cannot be computed at all, and it is an *addition* — no rename,
  no data migration, `reqd=0`, so every existing record stays valid. Needed for R-20.3/R-20.4.
- **D-3 · Add an instrument type and a claim-period field?** Recommended: **claim days yes**
  (default 0 = "no claim period", the SBD 2024 default), **instrument type later** — it changes how
  exposure is *read*, not how alerts fire, and adding it invites a second source of truth before
  D-1 is settled. Needed for R-20.9.
- **D-4 · Fix `custom_pg_amount`'s dangling `options = "currency"` on a Currency field?**
  Recommended: **leave it, freeze it in the parity snapshot.** It is inert (a Currency field
  ignores `options`), the frontend may read it, and changing it buys nothing but risk.

## 7. Requirements register

`state` — **met** = the gate for it passes today on both sites (S14) · **open** = not built ·
**deferred** = deliberately not now, with the decision that defers it.

### 7.1 Domain: bid securities and guarantees

| id | Requirement | From | Acceptance (the check that proves it) | State |
|---|---|---|---|---|
| **R-20.1** | On Opportunity `validate`, reject a bid security above the rule ceiling — 5% of `custom_estimated_value` up to PKR 250,000,000, 2% above — unless the site config key `flowire_bid_security_override` is set; the ceilings come from site config so a tenant bidding outside Pakistan is not blocked. | F-1 (S4) | `IntegrationTestCase` asserting pass / throw / override for: below cap, over cap, and a value straddling the 250 M breakpoint. | open |
| **R-20.2** | Warn (never throw) when a performance guarantee exceeds 10% of the opportunity's estimated value; the bid data sheet governs, and the contract amount is usually unknown at bid time. | F-1 (S4) | `IntegrationTestCase` asserting one `msgprint`/log row and **no** exception. | open |
| **R-20.3** | Ship `Opportunity.custom_bid_validity_days` (Int, `module=Flowire`, default 0) and validate `custom_valid_till >= custom_submission_date + custom_bid_validity_days + 28` days, warning (not blocking) with the computed minimum date in the message. | F-2 (S4), D-2 | Probe reports the new Custom Field owned by Flowire on both sites; `tools/parity.py` sees it on both; test asserts the computed minimum date and the warning text. | open |
| **R-20.4** | Compute the release-due date as `custom_submission_date + custom_bid_validity_days + 30` days and expose it to R-20.5 — computed, **not stored**, so no new column and no backfill. | F-2 (S4) | Unit test over a table of (submission date, validity days) → expected due date, including a leap day. | open |
| **R-20.5** | A `daily` scheduler job evaluates **all three** guarantee tracks on every open Opportunity (top-level `custom_valid_till` / `custom_release_date`; `custom_em_pg_valid_till`; `custom_pg_validity` / `custom_pg_release_date`) and raises one Notification Log per (record, field, threshold) per day at 60/30/15/7/0 days and overdue; re-running the same day creates nothing. Thresholds and the receiver role come from site config. | F-3 (S4, S12) | `IntegrationTestCase` with a frozen date: assert counts per threshold, assert a second run adds zero rows, assert `is_enabled` respected for closed opportunities. | open |
| **R-20.6** | A read-only exposure view: open securities grouped by `custom_em_pg_bank` / EM Banks, with count, total amount, and how many are past `custom_valid_till` — the number the desk loses money on when it is wrong. | F-3 (S4) | Query test over fixture rows: two banks, one expired, totals and past-expiry count asserted. | open |
| **R-20.7** | Freeze the measured contract: the 50 field names, the five status/stage option lists and the three guarantee tracks are frozen as-is; `tools/parity.py` must fail on any drift, including a *helpful* rename. | F-4, constr. 1 | `python tools/parity.py flowire.local fresh.localhost` exits 0 today; a deliberately renamed option list exits 1 (verified by a negative test). | met |
| **R-20.8** | Consolidate the three guarantee tracks into one `Opportunity Guarantee` child table — **only** after a frontend release is scoped, with a data migration and a rollback. Not started, deliberately. | F-4, D-1 | n/a while deferred; reopening requires an approved change request that names this id. | deferred |
| **R-20.9** | Ship `Opportunity.custom_claim_days` (Int, default 0) and have R-20.5 treat `expiry + claim_days` as the end of exposure, so a guarantee with a claim period is not reported as "returned" the day it expires. | F-5 (S4), D-3 | Test: claim_days=0 → exposure ends at expiry; claim_days=30 → ends 30 days later and the alert text names the claim date. | open |
| **R-20.10** | Keep every misspelled name (`custom_performance_gaurantee`, `custom_pg_submitted_by__person`, `custom_submitted_by__person`, `custom_em__pg_details`) and pin them in a test that lists them as contract, so nobody "fixes" one and silently breaks the frontend. | F-4, constr. 1 | Test asserts the exact set of frozen names is present; a missing one fails the suite. | open |
| **R-20.11** | Leave `custom_pg_amount`'s inert `options = "currency"` alone and pin it in the parity snapshot. | F-4, D-4 | Parity snapshot contains the value; changing it exits 1. | met |

### 7.2 Platform: ownership and upgrade safety

| id | Requirement | From | Acceptance | State |
|---|---|---|---|---|
| **R-21.1** | Own the four fields ERPNext v16 dropped (`Lead.source`, `Lead.campaign_name`, `Opportunity.source`, `Opportunity.campaign`) as `module=Flowire` Custom Fields, created per site against what the doctype actually has. | F-6, F-11 | `python scripts/v16-probe.py` on `flowire.local` and on `fresh.localhost`: `CF Lead total=11 Flowire=11 unowned=0`, `CF Opportunity total=39 Flowire=39 unowned=0`, `RESULT PASS`. | met |
| **R-21.2** | Own `Lead Source`: ship the DocType as a file in `flowire/flowire/doctype/lead_source/` plus the 14 rows as a fixture, **same name**, so every `source` link keeps resolving. | F-7 | Probe prints `DOCTYPE Lead Source module=Flowire custom=0` and `LEADSRC Lead Source rows: 14` on both sites; `bench --site flowire.local migrate` runs the ownership patch with no orphan removal. | met |
| **R-21.3** | Support v15 and v16 simultaneously: the four version-dependent fields are created in `flowire/setup/schema.py` (adopt / leave / create) and excluded from the Custom Field fixture by name; `hooks.VERSION_DEPENDENT_FIELDS` and `schema.OUR_VERSION_FIELDS` may never drift apart. | F-11 | `flowire/tests/test_ownership.py` asserts the two lists match and that a stock DocField is never shadowed. | met |
| **R-21.4** | Fixtures filter Custom Field and Property Setter by `module=Flowire` and Custom DocPerm by `parent` — never by `dt` or by `role`. | F-7, F-8 | Test asserts the `module` filter exists and that no fixture entry filters by `dt` alone. | met |
| **R-21.5** | A site with `erpnext` + `flowire` only is complete: the standalone `crm` app is not required, and its `CRM Lead` doctype must be absent. | F-12 | Probe on `fresh.localhost`: `CORE CRM Lead doctype present: False` and `RESULT PASS`. | met |
| **R-21.6** | Packaging is `pyproject.toml` (flit) only, `frappe = ">=15.0.0,<17.0.0"`, no `setup.py`. | F-11 | `bench get-app` / `bench install-app` from a clean bench; no `setup.py` in the tree. | met |
| **R-21.7** | Schema is created only from install/migrate hooks, never on request: `create_custom_field` appears nowhere outside `flowire/setup/schema.py`, and that module is called only from `after_install` / `after_migrate`. | F-9, README rule 4 | `grep -rn create_custom_field` returns one file; review asserts the call sites are the two hooks. | met |

### 7.3 Permissions and behaviour

| id | Requirement | From | Acceptance | State |
|---|---|---|---|---|
| **R-22.1** | Export **every** Custom DocPerm row for each parent in the list (Lead, Opportunity, Communication, ToDo, Prospect, Company Bidder, EM Banks) — a role filter would revoke access. | F-8 | `flowire/fixtures/custom_docperm.json` contains all rows for each parent; parity compares the full set. | met |
| **R-22.2** | Keep `Sales User … if_owner=1` owner-scoping intact on Lead and Opportunity — it is a paid feature at Twenty and must not be lost to a fixture change. | F-8, S5 | Parity compares Custom DocPerm rows including `if_owner`; a modified row exits 1. | met |
| **R-22.3** | Behaviour ships as `doc_events`, never as Server Scripts / Client Scripts / Notifications: zero enabled Server Scripts on any site. | F-9 | Probe prints `SCRIPT Server Scripts: N total, 0 enabled` and fails the gate on any enabled script. | met |
| **R-22.4** | No `has_permission` hook returns a bare `None` for an unhandled `ptype`: either the app registers none (today) or every hook ends in an explicit `True`. | F-10, S10 | Test asserts the registered `has_permission` set is empty **or** that each entry's source ends in `return True`. | met |

### 7.4 Pipeline and channels

| id | Requirement | From | Acceptance | State |
|---|---|---|---|---|
| **R-23.1** | The pipeline the user sees has one stage source. `custom_stage_1` (Link → `Sales Stage`) is it; the `Sales Stage` master must exist **with its rows** on a fresh site, and the mapping from the four status selects onto stages is documented rather than inferred. | F-13 (S1, S11) | Fixture for `Sales Stage` rows; parity compares the stage domain; doc updated with the mapping table. | open |
| **R-23.2** | Keep `custom_whatsapp_no` and normalise it to E.164 on save; a sending integration is a separate decision (Frappe CRM does it through `frappe_whatsapp`). | F-13 (S1) | Test: `0300-1234567` with a site-config default country stores `+923001234567`; invalid input is rejected. | open |

### 7.5 Proof and ship

| id | Requirement | From | Acceptance | State |
|---|---|---|---|---|
| **R-24.1** | `tools/parity.py` compares two sites on field inventory (name, type, options, reqd, hidden), the five status/stage option lists, Custom DocPerm rows and Property Setters, and **exits 1** on any difference. | F-14 | `python tools/parity.py flowire.local fresh.localhost` exits 0 with identical snapshots; a deliberately altered option list exits 1. | met |
| **R-24.2** | The probe is a gate, not a report: non-zero exit blocks the step that produced it. | F-14, S14 | `python scripts/v16-probe.py` prints `RESULT PASS` and exits 0 on the fresh site; `RESULT FAIL (n)` exits 1. | met |
| **R-24.3** | CI runs migrate → probe → parity on a **throwaway** site created from scratch (erpnext + flowire, no crm app) for every change to `flowire/**`. | F-14 | Pipeline config in the repo; a deliberately broken fixture turns the job red. | open |
| **R-24.4** | Rehearse against a production backup on a separate bench before the first rollout: probe + parity there, then the fixture export is authoritative. | F-14 | `tools/parity.py <prod-rehearsal> flowire.local` exits 0; the diff (if any) is triaged before shipping. | open |

---

## 8. Traceability

The only requirement ids already on record are in `HANDOFF-flowire.md` §4.4 (they come from the
separation plan in the `flowire-crm` repo). They map onto this register as follows — nothing new is
claimed, the plan's gates are just expressed as checks here:

| Plan id | Closed by | Evidence |
|---|---|---|
| R-1.2 (schema parity with the reference CRM) | R-21.1, R-21.2, R-24.1 | identical parity snapshots; probe `RESULT PASS` on both sites |
| R-9.3 / R-9.4 (v16 field loss) | R-21.1, R-21.3 | `setup/schema.py` guarded creation + the list-equality test |
| R-11 (permissions owned by the app) | R-22.1, R-22.2 | `custom_docperm.json` + parity on `if_owner` rows |
| R-13.2 (fixtures, not scripts) | R-21.4, R-22.3 | fixture filters + probe's zero-enabled-Server-Scripts gate |
| R-23.3 (probe gates a phase) | R-24.2 | probe exit code |

**Open set for the next step** (12 of 28 requirements — 15 met, 1 deferred): R-20.1 – R-20.6, R-20.9, R-20.10 (domain
guarantee engine), R-23.1, R-23.2 (pipeline + WhatsApp), R-24.3, R-24.4 (CI + rehearsal). R-20.8 is
deferred by D-1. Everything in §7.2, §7.3 and R-24.1/R-24.2 is **met and gated today** — those are
the ownership guarantees the v16 work was for, and they are the reason a fresh site can now be
proven identical instead of assumed to be.

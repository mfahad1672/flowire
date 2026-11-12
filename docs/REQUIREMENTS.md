# REQUIREMENTS — Flowire CRM (backend app)

**Input:** `docs/RESEARCH.md` (pass 1, commit `34b910d`) — 14 findings `F-n`, 14 sources `S-n`, and a
28-item register `R-n`. This document is the implementable form of that register: every `R-` id
below has a statement, the business rule, the data it touches, its edge cases, the named tests that
prove it, and a priority. Nothing here renames a field, touches `apps/frappe` / `apps/erpnext`, or
assumes the standalone `crm` app is installed.

**Status legend:** `met` = a gate in this repo already proves it · `open` = to build · `deferred` =
deliberately not now, with the decision that defers it.

---

## 1. Actors and vocabulary

| Actor | Sees | Source of that scope |
|---|---|---|
| System Manager | everything, deletes | Custom DocPerm `System Manager` rows |
| Sales Manager | everything in the tenant, deletes and shares | Custom DocPerm `Sales Manager` rows |
| Sales User | **own records only** (`if_owner = 1`) | Custom DocPerm `Sales User` rows |
| Scheduled job (`Administrator`) | evaluates every open Opportunity | `scheduler_events["daily"]` |

| Term | Meaning in this product |
|---|---|
| **Lead / Prospect / Opportunity** | ERPNext doctypes; the bid desk works in Opportunity |
| **Bid security / EM** | money or a guarantee lodged with the bid (CDR, pay order or bank guarantee — S9) |
| **PG** | performance guarantee, ≤ 10% of the contract amount (S4, PPR 2026 R.51) |
| **EM / PG** | our middle track: both instruments modelled on one tab (`custom_em_pg_*`) |
| **Claim period** | days after expiry in which the beneficiary may still demand payment (S4) |
| **Exposure** | security not yet released — the number that costs cash margin and bank limit |

---

## 2. Functional requirements

### 2.1 The guarantee lifecycle — all `open`

FR numbering follows the requirement ids, so **FR-7 and FR-8 do not exist**: they would have been
R-20.7 (already met by the parity gate, §4) and R-20.8 (deferred, §5). A gap in the numbers is
intentional traceability, not a missing requirement.

#### FR-1 · Bid-security ceiling check — **R-20.1** (from F-1, S4)

- **Statement.** When an Opportunity is validated, an amount above the statutory ceiling for bid
  security is rejected, with both numbers in the message, unless the tenant switched the check off.
- **Rule.** `cap = estimated * 5%` when `estimated <= 250,000,000`, else `estimated * 2%`
  (PPR 2026 R.36). `estimated = custom_estimated_value`. Reject when
  `round(custom_bid_security, 2) > round(cap, 2)` and site config `flowire_bid_security_override` is
  falsy. Message: *"Bid security 2,500,000 exceeds the ceiling 1,250,000 (5% of estimated 25,000,000,
  PPR 2026 R.36)."*
- **Config (site config, per tenant).** `flowire_security_cap_threshold` = 250000000,
  `flowire_security_cap_low` = 0.05, `flowire_security_cap_high` = 0.02,
  `flowire_bid_security_override` = 0. Constants live in `flowire/crm/validity.py` behind one
  accessor, so a tenant bidding outside Pakistan changes config, not code.
- **Edge cases.** No estimated value (0/None) → skip silently. Negative estimate → skip and log once.
  Bid security 0/None → skip. Exactly at the cap → pass. At the 250 M breakpoint the **low** rate
  applies (≤). Non-PKR currency → ceilings still applied, and the message names the percentage and
  the threshold so a misapplication is visible rather than silent.
- **Tests.** `test_bid_security_below_cap`, `test_bid_security_above_cap_throws`,
  `test_bid_security_at_cap_passes`, `test_bid_security_breakpoint_uses_low_rate`,
  `test_bid_security_override_skips`, `test_bid_security_no_estimate_skips`.
- **Priority.** Must.

#### FR-2 · Performance-guarantee warning — **R-20.2** (from F-1, S4)

- **Statement.** A PG above 10% of the opportunity value (PPR 2026 R.51) is **reported, never
  blocked** — the bid data sheet governs and the contract amount is usually unknown at bid time.
- **Rule.** Warn when `custom_pg_amount > 10% * custom_estimated_value`, and for
  `custom_performance_gaurantee` where it carries an amount. One `msgprint` per save, orange, naming
  both numbers.
- **Edge cases.** Both amounts empty → nothing. Both tracks over → two distinct messages. The warning
  must not fire during `bench migrate` or inside a patch.
- **Tests.** `test_pg_warning_fires`, `test_pg_warning_does_not_block`,
  `test_pg_warning_silent_when_no_data`.
- **Priority.** Must.
#### FR-3 · Bid-validity days + 28-day cover check — **R-20.3** (from F-2, S4, decision D-2)

- **Statement.** Store how long the bid stays valid, and warn when the bid security does not cover
  the required window.
- **Data.** New Custom Field `Opportunity.custom_bid_validity_days`: `Int`, label *Bid Validity
  (Days)*, `insert_after = custom_submission_date`, `module = Flowire`, `reqd = 0`, `default = 0`,
  created by the same per-site, version-guarded path as R-21.1 — never as a bare fixture that could
  collide on v15.
- **Rule.** `required_valid_till = custom_submission_date + custom_bid_validity_days + 28 days`
  (SBD Works 2024 ITB 19). Warn when `custom_valid_till < required_valid_till`, naming the computed
  minimum date. Warning only: a bid can be lodged before an extension is agreed, and blocking would
  stop data capture.
- **Edge cases.** Missing submission date, validity 0, or empty `custom_valid_till` → skip. Raising
  the validity days must re-warn against the new date, not remember the old verdict. Leap day handled
  by `add_days`, never by calendar arithmetic on day counts.
- **Tests.** `test_validity_cover_warns_when_short`, `test_validity_cover_passes_at_exactly_28`,
  `test_validity_cover_skips_without_dates`, `test_validity_cover_leap_day`.
- **Priority.** Must.

#### FR-4 · Release-due date — **R-20.4** (from F-2, S4)

- **Statement.** Compute when an unsuccessful bidder's security is due back, without storing it.
- **Rule.** `release_due = custom_submission_date + custom_bid_validity_days + 30 days` (SBD Works
  2024: no later than 30 days after bid validity ends).
- **Edge cases.** Returns `None` — not a date in 1970 — when either input is missing, so callers skip
  instead of computing nonsense. Pure function, no DB access, no caching.
- **Tests.** `test_release_due_table` (table-driven, incl. leap day and year boundary).
- **Priority.** Must.

#### FR-5 · Daily guarantee alert job — **R-20.5** (from F-3, S4/S12)

- **Statement.** Every day, on every open Opportunity, the desk is told which securities expire soon,
  which have expired, and which are overdue for release — once, not once per run.
- **Tracks watched (all three; F-4 froze them all).**

  | Track | Expiry field | Release field | Label in the message |
  |---|---|---|---|
  | Top level | `custom_valid_till` | `custom_release_date` | Bid security |
  | EM / PG | `custom_em_pg_valid_till` | — | EM / PG |
  | PG | `custom_pg_validity` | `custom_pg_release_date` | Performance guarantee |

- **Thresholds.** 60, 30, 15, 7 and 0 days before the date, plus `overdue` once passed — configurable
  via `flowire_alert_thresholds`, defaulting to that list.
- **Closed opportunities.** `custom_opportunity_status` in (`Converted`, `Won`, `Lost`) → skipped; a
  module constant, so a new terminal option is a one-line change.
- **Idempotency.** One Notification Log per `(document, field, threshold, day)`, deduplicated on a
  token in the subject, so a re-run after a failure adds nothing.
- **Receivers.** The opportunity owner plus every user with `flowire_alert_role` (default
  `Sales Manager`, optionally `Sales User` scoped to their own). A user who muted notifications gets
  none, and the job does not fail because of it.
- **Exposure, not just expiry.** Where FR-9 claim days apply, the message states the last claim date;
  "expired" is never reported as "returned".
- **Performance (NFR-5).** One candidate query (any of six dates within 60 days or in the past), then
  bounded per-record work. Target ≤ 2 s per 1,000 open opportunities, measured once and recorded in
  the job's docstring.
- **Tests.** `test_alert_thresholds_fire_once_each`, `test_alert_second_run_is_silent`,
  `test_alert_skips_closed_opportunities`, `test_alert_respects_claim_days`,
  `test_alert_covers_all_three_tracks`.
- **Priority.** Must.

#### FR-6 · Exposure by bank — **R-20.6** (from F-3, S4)

- **Statement.** Answer "how much of our bank limits is tied up, at which bank, and how much of it
  should already have come back".
- **Rule.** Group open guarantees by `custom_em_pg_bank` (Link → EM Banks) and return bank, open
  count, total amount, count past expiry, earliest expiry. Read-only — no writes, no new doctype.
- **Edge cases.** Uncategorised rows appear under an explicit `(unset)` bucket rather than
  disappearing; a bank with only expired items is still listed — that is the point.
- **Tests.** `test_exposure_totals_by_bank`, `test_exposure_counts_past_expiry`,
  `test_exposure_includes_unset_bank`.
- **Priority.** Should.

#### FR-9 · Claim days — **R-20.9** (from F-5, S4, decision D-3)

- **Statement.** A guarantee with a claim period keeps the bank liable after its expiry date; the
  register must not report it as returned.
- **Data.** New Custom Field `Opportunity.custom_claim_days`: `Int`, label *Claim Period (Days)*,
  `default 0`, same per-site guarded path as FR-3.
- **Rule.** `exposure_end = valid_till + claim_days`; alerts continue to that date. `0` means demands
  must reach the bank by expiry (the SBD 2024 default), so existing records behave unchanged.
- **Edge cases.** Negative → treated as 0 and logged. Claim days on a track with no expiry date → no
  exposure date computed.
- **Tests.** `test_exposure_end_without_claim_period`, `test_exposure_end_with_claim_period`,
  `test_claim_days_negative_is_zero`.
- **Priority.** Should.

#### FR-10 · Frozen-name contract — **R-20.10** (from F-4, hard constraint)

- **Statement.** The misspelled fieldnames are public schema and must never be "corrected".
- **Rule.** A test lists `custom_performance_gaurantee`, `custom_pg_submitted_by__person`,
  `custom_submitted_by__person`, `custom_em__pg_details`, plus the three a human would most want to
  tidy — `custom_currency_name`, `custom_status_pendingreleased`, `custom_pg_account_manager_` — as
  contract, and asserts each exists on its intended doctype.
- **Tests.** `test_frozen_field_names_present`.
- **Priority.** Must.

### 2.2 Pipeline and channel — all `open`

#### FR-11 · One stage source with its master data — **R-23.1** (from F-13, S1/S11)

- **Statement.** The board the user drags deals across is driven by one field, and the master it links
  to exists on a fresh site **with its rows**.
- **Rule.** `Opportunity.custom_stage_1` (Link → `Sales Stage`) is the stage. `Sales Stage` rows ship
  as a fixture; the probe asserts the doctype exists. The mapping from the four status selects onto
  stages is documented in `docs/inventory.md`, not inferred at runtime.
- **Edge cases.** An Opportunity with no stage appears in an explicit "Unstaged" column, never
  disappears from the board. A stage row deleted on a site fails parity before it ships.
- **Tests.** `test_sales_stage_rows_exist`, `test_stage_link_options_match_fixture`.
- **Priority.** Must (the frontend depends on it; no schema change).

#### FR-12 · WhatsApp number normalisation — **R-23.2** (from F-13, S1)

- **Statement.** Store a dialable number, because the channel integration (Frappe CRM does it through
  `frappe_whatsapp`) will need one.
- **Rule.** On save, `custom_whatsapp_no` is normalised to E.164 using site config
  `flowire_default_country_code` (default `+92`): strip spaces, dashes, brackets and a leading `00`;
  replace a leading national trunk `0` with the country code.
- **Edge cases.** Empty → untouched. Already `+…` → validated and kept. Unparseable (letters, too
  short, too long) → rejected with the failing value in the message, never silently stored.
- **Tests.** `test_whatsapp_local_format_normalised`, `test_whatsapp_international_kept`,
  `test_whatsapp_invalid_rejected`, `test_whatsapp_empty_untouched`.
- **Priority.** Should.

---

## 3. Non-functional requirements

| id | Requirement | How it is checked |
|---|---|---|
| **NFR-1** | **Tenant isolation.** No fixture may capture a row a tenant created: Custom Field and Property Setter scoped by `module = Flowire`, Custom DocPerm by the explicit parent list. | fixture inspection test; parity compares the full owned set |
| **NFR-2** | **Upgrade safety.** v15 and v16 both work: version-dependent fields are created per site (adopt / leave / create), never as fixtures; nothing under `apps/frappe` or `apps/erpnext` is edited; every patch is idempotent. | probe on both sites; `migrate` twice in CI |
| **NFR-3** | **Behaviour is code, not data.** No Server Script, Client Script, Notification or Email Template is required for correct operation. | probe fails on any enabled Server Script |
| **NFR-4** | **Deterministic time.** All date logic goes through `frappe.utils` (`today`, `add_days`, `getdate`), so tests freeze time and no tenant timezone shifts an alert by a day. | tests freeze `frappe.utils.nowdate` |
| **NFR-5** | **Alert job cost.** <= 2 s per 1,000 open opportunities; one candidate query plus bounded per-record reads. | measured once; the number goes in the job docstring |
| **NFR-6** | **Auditability.** Every rejection names the rule and both numbers (PPR 2026 R.36/R.51, SBD ITB 19), so a user can paste it into a bid clarification. | assertion on message text |
| **NFR-7** | **No renames, ever.** The field inventory is contract; parity exits 1 on any drift, including a rename that looks like a fix. | parity + FR-10 |
| **NFR-8** | **Reproducible fresh site.** `bench new-site ... --install-app erpnext --install-app flowire` reproduces the reference schema byte-for-byte in the parity snapshot. | probe `RESULT PASS` + parity exit 0 |

---

## 4. Already met — no rework

These carry the ownership guarantee the v16 work was for; each is gated today on `flowire.local`
**and** `fresh.localhost`.

| id | Requirement (short) | Gate |
|---|---|---|
| R-20.7 | the 50 fieldnames, five option lists and three tracks are frozen | `tools/parity.py` exits 0; a renamed option list exits 1 |
| R-20.11 | `custom_pg_amount`'s inert `options="currency"` is pinned, not fixed (D-4) | parity snapshot contains it |
| R-21.1 | the four v16-dropped fields are owned by Flowire | probe: `unowned=0` on both doctypes, both sites |
| R-21.2 | `Lead Source` is an app DocType with its 14 rows | probe: `module=Flowire custom=0`, `rows: 14` |
| R-21.3 | v15/v16 dual support via guarded per-site creation | `test_ownership.py` list-equality test |
| R-21.4 | fixtures scoped by `module` / `parent`, never `dt` / `role` | fixture inspection test |
| R-21.5 | a fresh site needs no `crm` app | probe: `CRM Lead doctype present: False` |
| R-21.6 | packaging is `pyproject.toml` only | no `setup.py`; install from a clean bench |
| R-21.7 | schema created only from install/migrate hooks | `create_custom_field` only in `flowire/setup/schema.py` |
| R-22.1 | every Custom DocPerm row per parent is exported | `custom_docperm.json` + parity |
| R-22.2 | `Sales User ... if_owner=1` owner-scoping survives | parity compares `if_owner` |
| R-22.3 | behaviour ships as `doc_events`, zero enabled Server Scripts | probe gate |
| R-22.4 | no bare `None` from a permission hook (none registered) | conformance test |
| R-24.1 | `tools/parity.py` exits 1 on any difference | run against two sites |
| R-24.2 | the probe is a gate, not a report | `RESULT PASS` / exit 0 |

---

## 5. Deferred and out of scope

| Item | Why | Reopens by |
|---|---|---|
| **R-20.8** — consolidate the three guarantee tracks into one `Opportunity Guarantee` child table | three live field sets bound by the frontend; needs a data migration **and** a frontend release | an approved change request naming R-20.8, with D-1 re-decided |
| Instrument-type field (CDR vs pay order vs bank guarantee) | changes how exposure is *read*, not whether alerts fire; would create a second source of truth before D-1 | same change request as R-20.8 |
| WhatsApp **sending** integration | `frappe_whatsapp` is a separate app with its own ownership question; FR-12 only makes the data ready | a new requirement once a channel is chosen |
| Email / call logging, commission estimation, release-letter drafting (all seen in S4) | valuable, but each is frontend-led; nothing in the current schema blocks them | a new research pass with the bid desk |
| Pricing / edition parity with Salesforce, HubSpot, Zoho | not a differentiator this product can win on (S5 shows how volatile it is) | — |

---

## 6. Verification plan

1. **Per requirement:** the named test in its section — `IntegrationTestCase`, wrapped in
   `frappe.in_test` where it touches the DB — run with
   `bench --site fresh.localhost run-tests --app flowire`.
2. **Per change:** `python scripts/v16-probe.py` prints `RESULT PASS` (exit 0) on `flowire.local`
   and on a **freshly created** site; `python tools/parity.py flowire.local fresh.localhost` exits 0.
3. **Per release:** migrate twice (idempotency, NFR-2); the parity snapshot is committed as that
   release's baseline.
4. **CI (R-24.3):** a throwaway site per change — create, migrate, probe, parity, tests; a
   deliberately broken fixture must turn the job red.
5. **Before production (R-24.4):** rehearse against a production backup on a separate bench; parity
   against `flowire.local` must exit 0, or the diff must be triaged and recorded.

---

## 7. Traceability

| Requirement | Spec | Finding | Sources | Proof |
|---|---|---|---|---|
| R-20.1 | FR-1 | F-1 | S4 | 6 tests |
| R-20.2 | FR-2 | F-1 | S4 | 3 tests |
| R-20.3 | FR-3 | F-2 | S4 | probe + parity + 4 tests |
| R-20.4 | FR-4 | F-2 | S4 | 1 table-driven test |
| R-20.5 | FR-5 | F-3 | S4, S12 | 5 tests |
| R-20.6 | FR-6 | F-3 | S4 | 3 tests |
| R-20.7 | — | F-4 | S14 | parity, negative test |
| R-20.8 | — | F-4 | — | deferred (D-1) |
| R-20.9 | FR-9 | F-5 | S4 | 3 tests |
| R-20.10 | FR-10 | F-4 | — | 1 test |
| R-20.11 | — | F-4 | S14 | parity snapshot |
| R-21.1 – R-21.7 | — | F-6, F-7, F-9, F-11, F-12 | S1, S3, S7, S8, S13 | probe, parity, `test_ownership.py` |
| R-22.1 – R-22.4 | — | F-8, F-10 | S5, S10 | parity, probe, conformance test |
| R-23.1 | FR-11 | F-13 | S1, S11 | 2 tests + fixture |
| R-23.2 | FR-12 | F-13 | S1 | 4 tests |
| R-24.1 | — | F-14 | S14 | parity exit code |
| R-24.2 | — | F-14 | S14 | probe exit code |
| R-24.3 | §6.4 | F-14 | — | CI job red on a broken fixture |
| R-24.4 | §6.5 | F-14 | — | parity against the rehearsal bench |

**Definition of done for this step:** the 12 open requirements have an implementable spec, a named
proof and a priority; the 15 met ones are evidenced; the 1 deferred one names the decision that
blocks it. Next step is `architecture` — the module layout for FR-1...FR-12 (where `validity.py`, the
alert job and the two new Custom Fields live, and how they stay version-guarded).

---

*Derived from `docs/RESEARCH.md` (commit 34b910d). Ids are stable: a requirement is never renumbered,
it is superseded and the successor names it.*

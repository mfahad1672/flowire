# Inventory — reference-site customizations

Generated from `audit-before.json` (read-only dump of **`flowire.local`** on 2026-11-06).
Regenerate with `bench --site flowire.local execute flowire.tools.audit_reference.summary`.

**Versions:** 
**Installed apps:** frappe, crm, erpnext, hrms, flowire

> Unlike the plan's assumptions, this reference bench is **Frappe/ERPNext v16**, and
> it is a *reconstruction*, not production. The numbers below are what actually
> exists here — several diverge from §1 of the separation plan, and each divergence
> is called out. Production will need its own audit before it is touched.

---

## 1. Custom Fields to own

`dt in (Lead, Opportunity)`, `is_system_generated = 0`, `fieldname like 'custom\_%'`.
**46 to export** (plan expected 44; this bench has 9 Lead + 37 Opportunity).

| # | name | dt | fieldname | type | options | reqd | insert_after |
|---|---|---|---|---|---|---|---|
| 1 | Lead-custom_currency_name | Lead | custom_currency_name | Link | Currency | 0 | custom_probability |
| 2 | Lead-custom_estimated_value | Lead | custom_estimated_value | Currency |  | 0 | custom_expected_close_date |
| 3 | Lead-custom_expected_close_date | Lead | custom_expected_close_date | Date |  | 0 | custom_submission_date |
| 4 | Lead-custom_lead_status | Lead | custom_lead_status | Select | New
Contacted
Nurturing
Qualified
Unqualified
Converted
Lost | 0 | status |
| 5 | Lead-custom_probability | Lead | custom_probability | Percent |  | 0 | custom_estimated_value |
| 6 | Lead-custom_project_name | Lead | custom_project_name | Data |  | 1 | company_name |
| 7 | Lead-custom_stage_1 | Lead | custom_stage_1 | Link | Sales Stage | 0 | custom_lead_status |
| 8 | Lead-custom_submission_date | Lead | custom_submission_date | Date |  | 0 | expected_close_date |
| 9 | Lead-custom_whatsapp_no | Lead | custom_whatsapp_no | Data |  | 0 | mobile_no |
| 10 | Opportunity-custom_account_manager | Opportunity | custom_account_manager | Link | User | 0 | custom_submitted_by__person |
| 11 | Opportunity-custom_bid_security | Opportunity | custom_bid_security | Currency |  | 0 | source |
| 12 | Opportunity-custom_bidder_name | Opportunity | custom_bidder_name | Link | Company Bidder | 0 | language |
| 13 | Opportunity-custom_company_name | Opportunity | custom_company_name | Data |  | 0 | custom_project_name |
| 14 | Opportunity-custom_em__pg_details | Opportunity | custom_em__pg_details | Tab Break |  | 0 | items |
| 15 | Opportunity-custom_em_pg_account_manager | Opportunity | custom_em_pg_account_manager | Link | User | 0 | custom_em_pg_submitted_by_person |
| 16 | Opportunity-custom_em_pg_amount | Opportunity | custom_em_pg_amount | Currency |  | 0 | custom_em_pg_submission_date |
| 17 | Opportunity-custom_em_pg_bank | Opportunity | custom_em_pg_bank | Link | EM Banks | 0 | custom_em_pg_submitted_by_entity |
| 18 | Opportunity-custom_em_pg_status | Opportunity | custom_em_pg_status | Select | 
Pending
Released | 0 | custom_em_pg_type |
| 19 | Opportunity-custom_em_pg_submission_date | Opportunity | custom_em_pg_submission_date | Date |  | 0 | custom_em_pg_status |
| 20 | Opportunity-custom_em_pg_submitted_by_entity | Opportunity | custom_em_pg_submitted_by_entity | Link | Company Bidder | 0 | custom_em_pg_valid_till |
| 21 | Opportunity-custom_em_pg_submitted_by_person | Opportunity | custom_em_pg_submitted_by_person | Link | User | 0 | custom_em_pg_bank |
| 22 | Opportunity-custom_em_pg_type | Opportunity | custom_em_pg_type | Select | 
Bid Security
Performance Guarantee | 0 | custom_bidder_name |
| 23 | Opportunity-custom_em_pg_valid_till | Opportunity | custom_em_pg_valid_till | Date |  | 0 | custom_em_pg_amount |
| 24 | Opportunity-custom_em_submission_date | Opportunity | custom_em_submission_date | Date |  | 0 | custom_status_pendingreleased |
| 25 | Opportunity-custom_opportunity_status | Opportunity | custom_opportunity_status | Select | New
Open
In Review
Converted
Won
Lost | 0 | status |
| 26 | Opportunity-custom_performance_gaurantee | Opportunity | custom_performance_gaurantee | Tab Break |  | 0 | custom_remarks |
| 27 | Opportunity-custom_pg_account_manager_ | Opportunity | custom_pg_account_manager_ | Link | User | 0 | custom_pg_submitted_by__person |
| 28 | Opportunity-custom_pg_amount | Opportunity | custom_pg_amount | Currency | currency | 0 | custom_pg_status |
| 29 | Opportunity-custom_pg_bidder_name | Opportunity | custom_pg_bidder_name | Link | Company Bidder | 0 | custom_performance_gaurantee |
| 30 | Opportunity-custom_pg_po_no | Opportunity | custom_pg_po_no | Data |  | 0 | custom_pg_account_manager_ |
| 31 | Opportunity-custom_pg_release_date | Opportunity | custom_pg_release_date | Date |  | 0 | custom_pg_validity |
| 32 | Opportunity-custom_pg_remarks | Opportunity | custom_pg_remarks | Small Text |  | 0 | custom_pg_release_date |
| 33 | Opportunity-custom_pg_status | Opportunity | custom_pg_status | Select | Not Required
Pending
Submitted
Released | 0 | custom_pg_po_no |
| 34 | Opportunity-custom_pg_submission_date | Opportunity | custom_pg_submission_date | Date |  | 0 | custom_pg_amount |
| 35 | Opportunity-custom_pg_submitted_by__person | Opportunity | custom_pg_submitted_by__person | Data |  | 0 | custom_pg_submitted_by_entity_ |
| 36 | Opportunity-custom_pg_submitted_by_entity_ | Opportunity | custom_pg_submitted_by_entity_ | Link | Company Bidder | 0 | custom_pg_bidder_name |
| 37 | Opportunity-custom_pg_validity | Opportunity | custom_pg_validity | Date |  | 0 | custom_pg_submission_date |
| 38 | Opportunity-custom_po_no | Opportunity | custom_po_no | Data |  | 0 | custom_account_manager |
| 39 | Opportunity-custom_project_name | Opportunity | custom_project_name | Data |  | 1 | party_name |
| 40 | Opportunity-custom_release_date | Opportunity | custom_release_date | Date |  | 0 | custom_valid_till |
| 41 | Opportunity-custom_remarks | Opportunity | custom_remarks | Small Text |  | 0 | custom_release_date |
| 42 | Opportunity-custom_status_pendingreleased | Opportunity | custom_status_pendingreleased | Select | Not Required
Pending
Submitted
Released | 0 | custom_po_no |
| 43 | Opportunity-custom_submission_date | Opportunity | custom_submission_date | Date |  | 0 | expected_closing |
| 44 | Opportunity-custom_submitted_by__person | Opportunity | custom_submitted_by__person | Data |  | 0 | custom_submitted_by_entity |
| 45 | Opportunity-custom_submitted_by_entity | Opportunity | custom_submitted_by_entity | Link | Company Bidder | 0 | custom_em__pg_details |
| 46 | Opportunity-custom_valid_till | Opportunity | custom_valid_till | Date |  | 0 | custom_em_submission_date |

### 1a. Deliberately EXCLUDED — needs your decision

These are non-system Custom Fields on Lead/Opportunity that are **native ERPNext v15
fields**, restored here as Custom Fields only because the v16 reference bench dropped
them. Shipping them in the app would add a duplicate column on v15.

| name | dt | fieldname | type | why excluded |
|---|---|---|---|---|
| Lead-campaign_name | Lead | campaign_name | Link | native in ERPNext v15 |
| Lead-source | Lead | source | Link | native in ERPNext v15 |
| Opportunity-campaign | Opportunity | campaign | Link | native in ERPNext v15 |
| Opportunity-source | Opportunity | source | Link | native in ERPNext v15 |

**Ask:** confirm these stay out. If production genuinely has them as Custom Fields,
they must come back in — but then they need a name collision guard on v15.

### 1b. Non-system Custom Fields on other doctypes

**None.** Every other Custom Field on this bench is `is_system_generated = 1`
(ERPNext / HRMS own), and is not exported.

---

## 2. Property Setters

`202` total · `199` are ERPNext's own (`is_system_generated = 1`) ·
**3 non-system rows**, all shown below.

### 2a. Ours — export (2)

| doc_type | field_name | property | value | owner |
|---|---|---|---|---|
| Lead | (doctype) | track_changes | 1 | Administrator |
| Opportunity | (doctype) | track_changes | 1 | Administrator |

### 2b. Not ours / unsure — not exported (1)

| doc_type | field_name | property | value | owner | verdict |
|---|---|---|---|---|---|
| Contact | (doctype) | search_fields | email_id | Administrator | **ask** |

**Ask:** `Contact.search_fields = "email_id"` is the only ambiguous row. It matches none
of the documented setup steps. Keep it out unless you know it is intentional.

---

## 3. Custom DocPerm — parents Lead, Opportunity, Communication, ToDo

**8 rows in scope** (out of 492 on the whole bench — the rest
belong to HRMS/ERPNext and are none of our business).

> Frappe ignores a doctype's standard permissions as soon as it has a single Custom
> DocPerm row, so **every** row of each parent below must be exported. Never filter
> by role.

### Lead (3)

| role | permlevel | read | write | create | delete | share | if_owner |
|---|---|---|---|---|---|---|---|
| System Manager | 0 | 1 | 1 | 1 | 1 | 1 | 0 |
| Sales User | 0 | 1 | 1 | 1 | 0 | 0 | 1 |
| Sales Manager | 0 | 1 | 1 | 1 | 1 | 1 | 0 |

### Opportunity (3)

| role | permlevel | read | write | create | delete | share | if_owner |
|---|---|---|---|---|---|---|---|
| Sales Manager | 0 | 1 | 1 | 1 | 1 | 1 | 0 |
| System Manager | 0 | 1 | 1 | 1 | 1 | 1 | 0 |
| Sales User | 0 | 1 | 1 | 1 | 0 | 0 | 1 |

### Communication (1)

| role | permlevel | read | write | create | delete | share | if_owner |
|---|---|---|---|---|---|---|---|
| Sales User | 0 | 1 | 1 | 1 | 0 | 0 | 1 |

### ToDo (1)

| role | permlevel | read | write | create | delete | share | if_owner |
|---|---|---|---|---|---|---|---|
| Sales User | 0 | 1 | 1 | 0 | 0 | 0 | 0 |

---

## 4. Automation

### Server Scripts (5) — expected 6, found 5

| name | type | doctype | event | disabled |
|---|---|---|---|---|
| CRM Share Lead on Owner Set | DocType Event | Lead | After Save | 0 |
| CRM Share Lead-Opp on Assignment | DocType Event | ToDo | After Insert | 0 |
| CRM Share Opportunity on Owner Set | DocType Event | Opportunity | After Save | 0 |
| CRM Unshare Lead-Opp on Cancel | DocType Event | ToDo | After Save | 0 |
| CRM Unshare Lead-Opp on Delete | DocType Event | ToDo | Before Delete | 0 |

The plan lists a sixth — **`CRM Default Assignment Email Off`** (Notification Settings,
Before Insert) — which does **not** exist on this bench. Its behaviour is already
shipped as a `before_insert` doc event in `flowire/crm/notification_settings.py`, so a
fresh site gets it either way; the disable-patch simply skips a row that is absent.

### Notifications (0 of ours, 11 total)

**None of the 4 CRM notifications exist here.** All 11 Notifications are ERPNext/HRMS stock (Leave Application, Material Request, …).

### Email Templates (0 of ours, 5 total)

**Neither CRM template exists here.** All 5 are stock HR templates.

**Consequence:** `flowire.setup.notifications.capture` will produce empty data files on
this bench, so `sync()` will log a warning and change nothing. That is correct
behaviour, not a failure — there is nothing here to port. On production, capture will
pick up the real 4 + 2 and the same code will replay them.

### Client Scripts / Workflows

- Client Scripts: **0**
- Workflows: **0**

Matches the plan's expectation (none).

### Business data (never exported)

| doctype | records |
|---|---|
| Company Bidder | 0 |
| EM Banks | 0 |

---

## 5. Decisions needed before the fixture export

1. Confirm the **46** Custom Fields in §1.
2. Confirm the **4** exclusions in §1a (native v15 fields).
3. Confirm **2** Property Setters in §2a, and rule on `Contact.search_fields` in §2b.
4. Confirm the Custom DocPerm parent list in §3.
5. Accept that this bench has **no CRM Notifications / Email Templates** to port.

"""Tag Flowire's own schema customizations with ``module = "Flowire"``.

The fixture filters in ``hooks.py`` key off this:

    {"dt": "Custom Field",    "filters": [["module", "=", "Flowire"]]}
    {"dt": "Property Setter", "filters": [["module", "=", "Flowire"]]}

Without this patch those filters match nothing, so no customization would ever be
exported as a fixture or reapplied to a new tenant site.

Deliberately an explicit allow-list rather than "every ``custom_*`` field on Lead
and Opportunity". A tenant can add their own columns to Lead from the UI
(``AddCustomFieldDialog`` / ``useCreateCustomField``), and relabelling those as
ours would export them into this app and then push them into every *other*
tenant. That is the one bug this whole file exists to prevent.

GENERATED from ``docs/audit-before.json`` (see ``docs/inventory.md``), not typed
by hand: 46 Custom Fields and 2 Property Setters were approved
on the reference site. Re-run the audit and update both lists if the reference
site changes.

Runs on every site that installs or migrates this app, so it is idempotent and
never aborts a migration because one record is missing.
"""

import frappe

MODULE = "Flowire"

# Exact list from the audit: every non-system ``custom_*`` Custom Field on Lead and
# Opportunity. Excluded on purpose: ``source``, ``campaign`` and ``campaign_name`` —
# those are NATIVE ERPNext v15 fields that the v16 reference bench had to restore
# as Custom Fields, so exporting them would add a duplicate column on v15.
OUR_CUSTOM_FIELDS = (
	"Lead-custom_currency_name",
	"Lead-custom_estimated_value",
	"Lead-custom_expected_close_date",
	"Lead-custom_lead_status",
	"Lead-custom_probability",
	"Lead-custom_project_name",
	"Lead-custom_stage_1",
	"Lead-custom_submission_date",
	"Lead-custom_whatsapp_no",
	"Opportunity-custom_account_manager",
	"Opportunity-custom_bid_security",
	"Opportunity-custom_bidder_name",
	"Opportunity-custom_company_name",
	"Opportunity-custom_em__pg_details",
	"Opportunity-custom_em_pg_account_manager",
	"Opportunity-custom_em_pg_amount",
	"Opportunity-custom_em_pg_bank",
	"Opportunity-custom_em_pg_status",
	"Opportunity-custom_em_pg_submission_date",
	"Opportunity-custom_em_pg_submitted_by_entity",
	"Opportunity-custom_em_pg_submitted_by_person",
	"Opportunity-custom_em_pg_type",
	"Opportunity-custom_em_pg_valid_till",
	"Opportunity-custom_em_submission_date",
	"Opportunity-custom_opportunity_status",
	"Opportunity-custom_performance_gaurantee",
	"Opportunity-custom_pg_account_manager_",
	"Opportunity-custom_pg_amount",
	"Opportunity-custom_pg_bidder_name",
	"Opportunity-custom_pg_po_no",
	"Opportunity-custom_pg_release_date",
	"Opportunity-custom_pg_remarks",
	"Opportunity-custom_pg_status",
	"Opportunity-custom_pg_submission_date",
	"Opportunity-custom_pg_submitted_by__person",
	"Opportunity-custom_pg_submitted_by_entity_",
	"Opportunity-custom_pg_validity",
	"Opportunity-custom_po_no",
	"Opportunity-custom_project_name",
	"Opportunity-custom_release_date",
	"Opportunity-custom_remarks",
	"Opportunity-custom_status_pendingreleased",
	"Opportunity-custom_submission_date",
	"Opportunity-custom_submitted_by__person",
	"Opportunity-custom_submitted_by_entity",
	"Opportunity-custom_valid_till",
)

# Property Setters we create: Track Changes ON for the audit trail, from
# scripts/setup-erpnext.mjs (TRACK_CHANGES_DOCTYPES).
# Matched on (doc_type, property) because Frappe enforces uniqueness on
# (doc_type, field_name, property, value) — so the matching row is necessarily
# the one we created. Note: do NOT tag "every Property Setter on Lead" — an app
# or a tenant could have added their own.
OUR_PROPERTY_SETTERS = (
	("Lead", "track_changes"),
	("Opportunity", "track_changes"),
)


def execute():
	tag_custom_fields()
	tag_property_setters()


def tag_custom_fields() -> int:
	return _tag("Custom Field", OUR_CUSTOM_FIELDS)


def tag_property_setters() -> int:
	updated = 0
	for doc_type, prop in OUR_PROPERTY_SETTERS:
		names = frappe.get_all(
			"Property Setter",
			filters={"doc_type": doc_type, "property": prop},
			pluck="name",
			limit_page_length=0,
		)
		updated += _tag("Property Setter", names)
	return updated


def _tag(doctype: str, names) -> int:
	"""Set ``module = MODULE`` on each named record that is not already tagged.

	Missing records are skipped: a tenant site may legitimately not have a field
	if it was renamed or dropped, and that must not fail the migration.
	"""
	updated = 0
	for name in names:
		if not frappe.db.exists(doctype, name):
			continue
		if frappe.db.get_value(doctype, name, "module") == MODULE:
			continue
		frappe.db.set_value(doctype, name, "module", MODULE, update_modified=False)
		updated += 1

	frappe.logger().info(f"[flowire] tagged {updated} {doctype} record(s) with module={MODULE}")
	return updated

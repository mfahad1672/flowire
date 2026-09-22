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

Runs on every site that installs or migrates this app, so it is idempotent and
never aborts a migration because one record is missing.
"""

import frappe

MODULE = "Flowire"

# Exact list from scripts/setup-erpnext.mjs (CUSTOM_FIELDS). 9 on Lead, 15 on
# Opportunity, and custom fields exist on no other doctype.
# Do not widen this without re-running scripts/multitenancy_audit.py (§1) on a
# reference site first.
OUR_CUSTOM_FIELDS = (
	"Lead-custom_project_name",
	"Lead-custom_lead_status",
	"Lead-custom_stage_1",
	"Lead-custom_submission_date",
	"Lead-custom_expected_close_date",
	"Lead-custom_estimated_value",
	"Lead-custom_probability",
	"Lead-custom_currency_name",
	"Lead-custom_whatsapp_no",
	"Opportunity-custom_opportunity_status",
	"Opportunity-custom_project_name",
	"Opportunity-custom_company_name",
	"Opportunity-custom_submission_date",
	"Opportunity-custom_bid_security",
	"Opportunity-custom_bidder_name",
	"Opportunity-custom_em_pg_type",
	"Opportunity-custom_em_pg_status",
	"Opportunity-custom_em_pg_submission_date",
	"Opportunity-custom_em_pg_amount",
	"Opportunity-custom_em_pg_valid_till",
	"Opportunity-custom_em_pg_submitted_by_entity",
	"Opportunity-custom_em_pg_bank",
	"Opportunity-custom_em_pg_submitted_by_person",
	"Opportunity-custom_em_pg_account_manager",
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

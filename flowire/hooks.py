"""Flowire CRM — Frappe hooks.

This app is installed on EVERY tenant site. Anything a tenant site needs in order
to be identical to the reference CRM must be declared here (as fixtures) or
shipped as code under this package. Nothing is created by hand through Desk.

Phase map (see docs/multitenancy-plan.md in the flowire-crm repo):
    Phase 1  fixtures + doc_events        <- this file
    Phase 6  before_request / plan limits <- not added yet
"""

app_name = "flowire"
app_title = "Flowire"
app_publisher = "Flowire"
app_description = "Flowire CRM — installed on every tenant site"
app_email = "dev@flowire.app"
app_license = "mit"

# ─── Fixtures ─────────────────────────────────────────────────────────────────
#
# Fixtures are re-imported on every `bench migrate` AND on `install-app`. Two
# rules matter more than anything else in this file:
#
#   1. Filter Custom Field / Property Setter by `module` — NEVER by `dt` alone.
#      A `dt`-only filter would capture custom fields that a *tenant* created
#      from the UI (see AddCustomFieldDialog / useCreateCustomField) and then
#      push them into every other tenant.
#
#   2. Filter Custom DocPerm by `parent` — NEVER by `role`. Frappe ignores a
#      doctype's standard permissions as soon as it has a single Custom DocPerm
#      row, so a role-filtered export revokes access from every role it omits.
#
# The exact lists come from `scripts/multitenancy_audit.py` in the flowire-crm
# repo — copy them from its §1 / §2 / §4 / §5 output before enabling each entry.
fixtures = [
	# Ours, tagged by flowire.patches.v1_0.tag_module_flowire. Safe as written.
	{"dt": "Custom Field", "filters": [["module", "=", "Flowire"]]},
	{"dt": "Property Setter", "filters": [["module", "=", "Flowire"]]},

	# TODO(Phase 1): fill the parent list from audit §4, then uncomment. Every
	# doctype that has ANY Custom DocPerm row must be listed, with ALL of its
	# rows for each. Known today from scripts/setup-erpnext.mjs: Communication,
	# ToDo, Lead, Opportunity — but confirm against the DB before trusting it.
	# {"dt": "Custom DocPerm", "filters": [["parent", "in", [
	# 	"Communication",
	# 	"ToDo",
	# 	"Lead",
	# 	"Opportunity",
	# ]]]},

	# TODO(Phase 1): custom roles only, by name, from audit §5.
	# {"dt": "Role", "filters": [["name", "in", []]]},

	# TODO(Phase 1): as reported by audit §6 / §7.
	# {"dt": "Role Profile", "filters": [["name", "in", []]]},
	# {"dt": "Workflow", "filters": [["document_type", "in", []]]},
	# {"dt": "Client Script", "filters": [["dt", "in", []]]},
	# {"dt": "Report", "filters": [["is_standard", "=", "No"]]},
]

# ─── Doc events ───────────────────────────────────────────────────────────────
#
# Ported from the Server Scripts that scripts/setup-erpnext.mjs created over the
# REST API. Server Scripts are database rows: they cannot ship from an app, so
# without this port a fresh tenant site would have no assignment sharing at all.
#
# Event-name mapping used:
#   Server Script "After Insert"  -> after_insert
#   Server Script "After Save"    -> on_update
#   Server Script "Before Delete" -> on_trash
#
# WHEN THIS GOES LIVE, DISABLE THE MATCHING SERVER SCRIPTS IN THE SAME CHANGE.
# Both sides are idempotent (each checks DocShare first), so a brief overlap is
# survivable, but it does double work and pollutes the error log.
doc_events = {
	"ToDo": {
		"after_insert": "flowire.assignment.share_with_assignee",
		"on_update": "flowire.assignment.revoke_if_cancelled",
		"on_trash": "flowire.assignment.revoke_on_delete",
	},
	"Lead": {"on_update": "flowire.assignment.share_with_owner_field"},
	"Opportunity": {"on_update": "flowire.assignment.share_with_owner_field"},
}

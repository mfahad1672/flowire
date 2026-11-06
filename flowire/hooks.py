"""Flowire CRM — Frappe hooks.

This app is installed on EVERY Flowire site. Anything a site needs in order to be
identical to the reference CRM must be declared here (as fixtures) or shipped as
code under this package. Nothing is created by hand through Desk and nothing is
created at runtime by the frontend.

Plan: ``docs/flowire-app-separation-plan.md`` in the flowire-crm repo (Track A).
"""

app_name = "flowire"
app_title = "Flowire"
app_publisher = "Netlogg"
app_description = "Flowire CRM customizations for ERPNext"
app_email = "dev@flowire.app"
app_license = "proprietary"

# The customizations extend ERPNext doctypes (Lead, Opportunity, Communication,
# ToDo), so erpnext must be installed first.
required_apps = ["erpnext"]

# ─── Fixtures ─────────────────────────────────────────────────────────────────
#
# Two rules matter more than anything else in this file:
#
#   1. Filter Custom Field / Property Setter by `module` — NEVER by `dt` alone.
#      A `dt`-only filter would capture a customization a *site* created from the
#      UI (see AddCustomFieldDialog / useCreateCustomField) and then push it into
#      every other site.
#
#   2. Filter Custom DocPerm by `parent` — NEVER by `role`. Frappe ignores a
#      doctype's standard permissions as soon as it has a single Custom DocPerm
#      row, so a role-filtered export revokes access from every role it omits.
#
# The parent list below is the set from scripts/setup-erpnext.mjs (§1 #6 of the
# plan). Confirm it against the audit output before the first
# `bench export-fixtures`, and extend it if the audit finds another parent.
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Flowire"]]},
	{"dt": "Property Setter", "filters": [["module", "=", "Flowire"]]},
	{
		"dt": "Custom DocPerm",
		"filters": [["parent", "in", ["Lead", "Opportunity", "Communication", "ToDo"]]],
	},
]

# ─── Doc events ───────────────────────────────────────────────────────────────
#
# Ported from the Server Scripts that scripts/setup-erpnext.mjs created over the
# REST API. Server Scripts are database rows: they cannot ship from an app, so
# without this port a fresh site would have no assignment sharing at all.
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
	"Lead": {"on_update": "flowire.crm.sharing.share_with_owner"},
	"Opportunity": {"on_update": "flowire.crm.sharing.share_with_owner"},
	"ToDo": {
		"after_insert": "flowire.crm.sharing.share_on_assignment",
		"on_update": "flowire.crm.sharing.unshare_on_cancel",
		"on_trash": "flowire.crm.sharing.unshare_on_delete",
	},
	"Notification Settings": {
		"before_insert": "flowire.crm.notification_settings.default_assignment_email_off",
	},
}

# ─── Install / migrate ────────────────────────────────────────────────────────
#
# after_install / after_migrate will point at flowire.setup.install once
# flowire/setup/notifications.py lands: that module generates the Notifications
# and Email Templates from the reference database, so it is written after the
# audit rather than guessed at here. Leaving the hooks unwired until then keeps
# `install-app flowire` from importing a module that does not exist yet.

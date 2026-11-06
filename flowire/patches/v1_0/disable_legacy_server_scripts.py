"""Disable the Server Scripts whose behaviour moved into Python.

The five share/unshare scripts plus the Notification Settings default are now
``doc_events`` handlers in ``flowire.crm``. Leaving the old database rows enabled
would run both implementations on every save.

Deliberately ``disabled = 1``, never a delete: re-ticking the checkbox in Desk is
the rollback path if the Python port misbehaves, and the script body is preserved
for comparison against ``docs/legacy-server-scripts/``.

This runs in ``[post_model_sync]``, i.e. in the same ``migrate`` that activates
the ``doc_events`` — so there is no window where both sides are live.
"""

import frappe

LEGACY_SERVER_SCRIPTS = (
	"CRM Share Lead on Owner Set",
	"CRM Share Opportunity on Owner Set",
	"CRM Share Lead-Opp on Assignment",
	"CRM Unshare Lead-Opp on Cancel",
	"CRM Unshare Lead-Opp on Delete",
	"CRM Default Assignment Email Off",
)


def execute():
	if not frappe.db.exists("DocType", "Server Script"):
		return

	disabled = 0
	for name in LEGACY_SERVER_SCRIPTS:
		if not frappe.db.exists("Server Script", name):
			# A site that never ran the old setup script simply has none of these.
			continue
		if frappe.db.get_value("Server Script", name, "disabled"):
			continue
		frappe.db.set_value("Server Script", name, "disabled", 1)
		disabled += 1

	frappe.logger().info(f"[flowire] disabled {disabled} legacy Server Script(s)")

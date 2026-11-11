"""Convert the script-created ``Lead Source`` DocType into one this app owns.

The setup script created Lead Source through the REST API, so on every existing site
it is a **custom** DocType (``custom=1``, ``module=CRM``): a row in ``tabDocType``
rather than a file in an app. Two consequences:

  * it does not exist on a fresh tenant site, so every ``Lead.source`` /
    ``Opportunity.source`` link there points at nothing;
  * ``module=CRM`` claims an app a Flowire site must not need — the ownership probe
    (``tools/v16-probe.py``) fails on exactly that.

The fix is to ship the definition as a file in this app
(``flowire/flowire/doctype/lead_source/``) and let this patch hand an existing site
over to it. What it deliberately does NOT do is delete the DocType: deleting a
DocType drops its table, which would take the 14 source rows — and every stored
``source`` value pointing at them — with it. Instead it flips the two flags and
reloads the definition from the shipped file, so the table, its columns
(``source_name``, ``details``) and its rows are left exactly as they are.

Runs in ``[pre_model_sync]`` so the definition is already app-owned in the same
migrate that adds the file, which also keeps ``remove_orphan_doctypes()`` from ever
seeing a ``custom=0`` DocType whose file is not there yet.

Idempotent, and a no-op on a fresh site (the app file created it as its own).
"""

import frappe

DOCTYPE = "Lead Source"
MODULE = "Flowire"


def execute():
	_own_doctype()


def _own_doctype() -> bool:
	"""Flip ``custom``/``module`` and reload from the app file. True when it changed."""
	if not frappe.db.exists("DocType", DOCTYPE):
		# Fresh site: sync_all will create it from flowire/flowire/doctype/lead_source/.
		return False

	current = frappe.db.get_value("DocType", DOCTYPE, ["custom", "module"], as_dict=True)
	if not current.custom and current.module == MODULE:
		return False

	rows = frappe.db.count(DOCTYPE) or 0

	frappe.db.set_value("DocType", DOCTYPE, {"custom": 0, "module": MODULE}, update_modified=False)
	frappe.clear_cache(doctype=DOCTYPE)

	# Make the shipped definition the authority now, in this same migrate.
	frappe.reload_doctype(DOCTYPE, force=True)

	# Reloading must never be able to empty the option list. If it did, this raise
	# stops the migration with the site intact instead of filling it with broken links.
	remaining = frappe.db.count(DOCTYPE) or 0
	if remaining < rows:
		frappe.throw(
			f"{DOCTYPE}: {rows - remaining} row(s) disappeared while taking ownership "
			f"({rows} before, {remaining} after). The migration was stopped."
		)

	frappe.logger().info(f"[flowire] {DOCTYPE} is now owned by {MODULE} ({remaining} row(s) intact)")
	return True

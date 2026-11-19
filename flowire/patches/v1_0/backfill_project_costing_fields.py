"""Populate the Flowire cost fields on every Project once, and repair project attribution.

``refresh_project_fields`` normally runs from the transaction hooks, which means a
project that has not been touched since the fields were introduced would keep its
zeros until the next timesheet, invoice or claim is submitted against it. This
backfill closes that gap so reports are correct on the first page load after
deploy.

It repairs two things that make ERPNext's own cost aggregates under-report:

* a document whose project sits only on its rows gets that project in its header, so
  ``Project.total_sales_amount`` — the one aggregate ERPNext reads per document — sees it;
* every project's native aggregates are recomputed, because ERPNext only refreshes them
  when a linked transaction is submitted, which leaves documents attached earlier stale.

Deliberately not run from ``after_migrate``: it reads every project's transactions,
which is fine once but wasteful on every migrate.
"""

import frappe
from frappe.utils import create_batch

from flowire.flowire.project_costing import refresh_project_fields
from flowire.setup import project_fields

# Document -> its row table. Both carry a `project`; only the header feeds document totals.
PROJECT_ATTRIBUTED = {
	"Sales Order": "Sales Order Item",
	"Sales Invoice": "Sales Invoice Item",
	"Purchase Order": "Purchase Order Item",
	"Purchase Invoice": "Purchase Invoice Item",
}


def execute():
	# post_model_sync patches run before the after_migrate hook that normally creates
	# these fields, so create them here first. Idempotent.
	project_fields.sync()

	if not frappe.db.has_column("Project", "custom_flowire_profit"):
		return

	stamped = _stamp_header_projects()
	recomputed = _recompute_native_aggregates()

	projects = frappe.get_all("Project", pluck="name", limit_page_length=0)
	refreshed = 0
	for project in projects:
		try:
			refresh_project_fields(project)
			refreshed += 1
		except Exception:
			# One bad project must not abort the deploy; the hooks will retry it.
			frappe.log_error(
				title=f"Project costing backfill failed for {project}",
				message=frappe.get_traceback(),
			)

	frappe.db.commit()
	frappe.logger().info(
		f"[flowire] backfilled costing fields for {refreshed}/{len(projects)} project(s), "
		f"stamped {stamped} header project(s), recomputed {recomputed} native aggregate(s)"
	)


def _stamp_header_projects() -> int:
	"""Copy a document's single row project into its blank header."""
	stamped = 0
	for doctype, item_doctype in PROJECT_ATTRIBUTED.items():
		rows = frappe.db.sql(
			f"""
			SELECT parent, MIN(project) AS project
			FROM `tab{item_doctype}`
			WHERE COALESCE(project, '') != ''
			GROUP BY parent
			HAVING COUNT(DISTINCT project) = 1
			""",
			as_dict=True,
		)
		for batch in create_batch(rows, 200):
			headers = _header_projects(doctype, [row["parent"] for row in batch])
			for row in batch:
				if headers.get(row["parent"]):
					continue
				frappe.db.set_value(
					doctype, row["parent"], "project", row["project"], update_modified=False
				)
				stamped += 1
	return stamped


def _header_projects(doctype: str, names: list[str]) -> dict[str, str | None]:
	return {
		row["name"]: row["project"]
		for row in frappe.get_all(doctype, filters={"name": ("in", names)}, fields=["name", "project"])
	}


def _recompute_native_aggregates() -> int:
	"""Re-run ERPNext's own cost and billing totals for every project."""
	recomputed = 0
	for project in frappe.get_all("Project", pluck="name", limit_page_length=0):
		try:
			doc = frappe.get_doc("Project", project)
			doc.update_costing()
			doc.db_update()
			recomputed += 1
		except Exception:
			frappe.log_error(
				title=f"Native project aggregate refresh failed for {project}",
				message=frappe.get_traceback(),
			)
	return recomputed

"""Share pre-existing assignments with their assignee.

Port of ``scripts/backfill-assignment-shares.mjs``. Before the ``ToDo`` doc events
existed, an assignment created a share only because a Server Script did it on
insert — so any assignment made while those scripts were disabled has no
DocShare, and its assignee cannot see the record even though it is "assigned to"
them.

Only open assignments are considered: a Cancelled ToDo is not entitlement.

Idempotent — ``sharing._share`` skips rows that already exist — and safe to
re-run. Batched so a large site does not hold one long transaction.
"""

import frappe

from flowire.crm import sharing

BATCH_SIZE = 500


def execute():
	if not frappe.db.exists("DocType", "ToDo"):
		return

	start = 0
	shared = 0

	while True:
		todos = frappe.get_all(
			"ToDo",
			filters={
				"reference_type": ["in", list(sharing.TRACKED)],
				"allocated_to": ["is", "set"],
				"status": ["!=", "Cancelled"],
			},
			fields=["name", "reference_type", "reference_name", "allocated_to"],
			limit_start=start,
			limit_page_length=BATCH_SIZE,
			order_by="name asc",
		)
		if not todos:
			break

		for todo in todos:
			if not frappe.db.exists(todo.reference_type, todo.reference_name):
				continue
			sharing._share(todo.reference_type, todo.reference_name, todo.allocated_to)
			shared += 1

		frappe.db.commit()
		start += BATCH_SIZE

	frappe.logger().info(f"[flowire] backfilled assignment shares for {shared} open ToDo(s)")

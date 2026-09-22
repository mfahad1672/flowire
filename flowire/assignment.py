"""Assignment / ownership sharing for Lead and Opportunity.

Faithful port of the Server Scripts created by ``scripts/setup-erpnext.mjs``
(``SHARE_ON_ASSIGN_SCRIPT``, ``UNSHARE_BODY`` and ``ownerShareScript``). Those
only ever existed as database rows, so they cannot ship from an app and would be
absent on a fresh tenant site.

Why this exists at all: the Sales User Custom DocPerm rows use ``if_owner``,
which scopes access to Frappe's core ``owner`` field (the record's creator) — NOT
the business-level ``lead_owner`` / ``opportunity_owner`` field. A
``has_permission`` hook can only restrict access, never grant it, so per-document
access is granted by creating DocShare rows.

Do not change the behaviour here without changing it in
``scripts/setup-erpnext.mjs`` too — the two are meant to be the same logic.
"""

import frappe

# Doctypes whose assignment / ownership creates a share.
TRACKED = ("Lead", "Opportunity")

# The business-level owner field on each tracked doctype.
OWNER_FIELD = {
	"Lead": "lead_owner",
	"Opportunity": "opportunity_owner",
}


def _share(doctype: str, name: str, user: str) -> None:
	"""Create a read+write DocShare for ``user`` if one does not already exist."""
	if not user:
		return

	if frappe.db.exists(
		"DocShare",
		{"share_doctype": doctype, "share_name": name, "user": user},
	):
		return

	frappe.get_doc(
		{
			"doctype": "DocShare",
			"user": user,
			"share_doctype": doctype,
			"share_name": name,
			"read": 1,
			"write": 1,
		}
	).insert(ignore_permissions=True)


def _revoke(doctype: str, name: str, user: str) -> None:
	"""Delete the DocShare row for ``user``, if any."""
	if not user:
		return

	share = frappe.db.get_value(
		"DocShare",
		{"share_doctype": doctype, "share_name": name, "user": user},
	)
	if share:
		frappe.delete_doc("DocShare", share, ignore_permissions=True)


def _has_other_live_assignment(doc) -> bool:
	"""True when another non-cancelled ToDo still assigns this record to the same user."""
	return bool(
		frappe.db.exists(
			"ToDo",
			{
				"reference_type": doc.reference_type,
				"reference_name": doc.reference_name,
				"allocated_to": doc.allocated_to,
				"status": ["!=", "Cancelled"],
				"name": ["!=", doc.name],
			},
		)
	)


def share_with_assignee(doc, method=None):
	"""ToDo ``after_insert`` — share the assigned Lead/Opportunity with the assignee."""
	if doc.reference_type not in TRACKED or not doc.allocated_to:
		return
	_share(doc.reference_type, doc.reference_name, doc.allocated_to)


def revoke_if_cancelled(doc, method=None):
	"""ToDo ``on_update`` — revoke the share when the assignment is cancelled."""
	if doc.status != "Cancelled":
		return
	_revoke_current(doc)


def revoke_on_delete(doc, method=None):
	"""ToDo ``on_trash`` — revoke the share when the assignment ToDo is deleted."""
	_revoke_current(doc)


def _revoke_current(doc) -> None:
	"""Shared tail of the two revoke hooks — skips when the user is still assigned."""
	if doc.reference_type not in TRACKED or not doc.allocated_to:
		return
	if _has_other_live_assignment(doc):
		return
	_revoke(doc.reference_type, doc.reference_name, doc.allocated_to)


def share_with_owner_field(doc, method=None):
	"""Lead/Opportunity ``on_update`` — share with ``lead_owner`` / ``opportunity_owner``.

	Fires when a manager creates a record "on behalf of" someone else, so the
	designated owner receives the same access an explicit assignment would grant.
	"""
	owner_user = doc.get(OWNER_FIELD.get(doc.doctype, ""))
	if not owner_user or owner_user == doc.owner:
		return
	_share(doc.doctype, doc.name, owner_user)

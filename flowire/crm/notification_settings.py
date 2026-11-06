"""Notification Settings defaults.

Port of the ``CRM Default Assignment Email Off`` Server Script created by
``scripts/setup-crm-notifications.mjs``. Frappe's built-in assignment email is
replaced by Flowire's own Notification, so it must stay off for every new
Notification Settings row.

The existing rows are covered by
``flowire/patches/v1_0/disable_builtin_assignment_emails.py``.
"""

import frappe


def default_assignment_email_off(doc, method=None):
	"""Notification Settings ``before_insert`` — keep the built-in assignment email off."""
	doc.enable_email_assignment = 0

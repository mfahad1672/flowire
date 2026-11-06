"""Turn off Frappe's built-in assignment email for every existing user.

Port of ``disableBuiltinAssignmentEmails`` in
``scripts/setup-crm-notifications.mjs``. Flowire sends its own assignment mail
through a Notification, so leaving the built-in one enabled means every assignee
receives two.

New rows are handled forever after by the ``before_insert`` doc event in
``flowire.crm.notification_settings``; this patch covers the users who already
existed when the app was installed.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Notification Settings"):
		return

	count = frappe.db.count("Notification Settings", {"enable_email_assignment": 1})
	if not count:
		return

	frappe.db.sql(
		"""
		UPDATE `tabNotification Settings`
		SET enable_email_assignment = 0
		WHERE enable_email_assignment = 1
		"""
	)
	frappe.logger().info(f"[flowire] disabled built-in assignment email for {count} user(s)")

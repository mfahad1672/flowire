"""Install / migrate entry points.

Both hooks do the same thing on purpose: every ``sync()`` below is idempotent, so
running it again on every migrate is how a site that was created *before* a
notification or a field was added still converges to the reference state.

Registered in ``hooks.py`` as:

    after_install = "flowire.setup.install.after_install"
    after_migrate = "flowire.setup.install.after_migrate"
"""

from flowire.setup import notifications, schema


def after_install():
	"""Fresh site: create the Notifications, Email Templates and fields we ship."""
	schema.sync()
	notifications.sync()


def after_migrate():
	"""Every migrate: re-assert them, so an edit made in Desk does not drift."""
	schema.sync()
	notifications.sync()

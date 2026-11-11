"""Lead Source — the option list behind ``Lead.source`` / ``Opportunity.source``.

This DocType used to be created at runtime by ``docker/frappe/setup/attach-frontend.mjs``
as a *custom* DocType (``custom=1``, ``module=CRM``) with its rows copied out of the
standalone ``crm`` app. Both halves of that are fatal on a fresh site:

  * a custom DocType is a row in the database, not a file in an app, so it does not
    exist on a new tenant site at all — and ``Lead.source`` is a Link field, so every
    lead saved there would have a dangling option list;
  * the rows came from the ``crm`` app, which a Flowire site must not need.

Shipping it here fixes both: the definition travels as a file in this app, the 14
rows travel as a fixture (``flowire/fixtures/lead_source.json``), and the name stays
``Lead Source`` so every existing ``source`` link, report filter and stored value
keeps working. ``flowire/patches/v1_0/own_lead_source.py`` converts a site that
already has the custom row, without dropping the table or its data.
"""

from frappe.model.document import Document


class LeadSource(Document):
	pass

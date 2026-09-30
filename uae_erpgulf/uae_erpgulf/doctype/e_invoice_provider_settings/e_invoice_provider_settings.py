# """Controller for E-Invoice Provider Settings.

# You didn't have a real .py controller file for this doctype yet - the
# before-save behaviour (check_duplicate, set_webhook_url) was living in a
# Server Script instead, from back when this was built browser-only. This
# file is my best reconstruction of that same logic based on what we built
# it to do, PLUS the new enforce_single_active_provider fix. I haven't seen
# your live Server Script's exact wording, so before you delete that script:
# open it side by side with this file and confirm check_duplicate and
# set_webhook_url do the same thing here as they do there. If anything
# differs, tell me and I'll adjust this file rather than the other way
# around - your live script is the source of truth for what those two
# already do, this file is only meant to add the new fix cleanly.

# Once you've confirmed they match, disable or delete the Server Script -
# having both a .py controller AND a Server Script doing the same
# before_save/validate work means it would run twice, which is exactly the
# kind of duplicate-side-effect bug this file is meant to avoid, not add.
# """

# import frappe
# from frappe import _
# from frappe.model.document import Document


# class EInvoiceProviderSettings(Document):
# 	def validate(self):
# 		self.check_duplicate()
# 		self.enforce_single_active_provider()
# 		self.set_webhook_url()

# 	def check_duplicate(self):
# 		"""Blocks a second row for the same company + provider combo -
# 		reconstructed from what check_duplicate was described as doing.
# 		Compare against your live Server Script's version of this."""
# 		if not self.provider:
# 			return

# 		existing = frappe.db.exists(
# 			"E-Invoice Provider Settings",
# 			{
# 				"company": self.company,
# 				"provider": self.provider,
# 				"name": ["!=", self.name or ""],
# 			},
# 		)
# 		if existing:
# 			frappe.throw(
# 				_(
# 					"An E-Invoice Provider Settings row already exists for {0} + {1} ({2})."
# 				).format(self.company, self.provider, existing)
# 			)

# 	def enforce_single_active_provider(self):
# 		"""NEW - this is the fix from the Flick/Marmin mix-up. Only one row
# 		can be the active one for a given company at a time - enabling this
# 		row automatically disables any other enabled row for the same
# 		company, regardless of provider. Without this, two enabled rows for
# 		one company means get_active_provider_settings can pick either one
# 		non-deterministically."""
# 		if not self.enabled:
# 			return

# 		frappe.db.set_value(
# 			"E-Invoice Provider Settings",
# 			{"company": self.company, "enabled": 1, "name": ["!=", self.name or ""]},
# 			"enabled",
# 			0,
# 		)

# 	def set_webhook_url(self):
# 		"""Fills Webhook URL with whichever provider this row actually is'
# 		own listener endpoint - asks that adapter for it (get_webhook_
# 		listener_url(), providers/base.py) rather than hardcoding Flick's
# 		URL here unconditionally, which is what this used to do even for a
# 		Marmin row. An ASP with no webhook API at all (Marmin today, base
# 		class default) just leaves this field blank instead of showing a
# 		URL for a listener that doesn't exist for it."""
# 		from uae_erpgulf.uae_erpgulf.providers import get_adapter

# 		try:
# 			url = get_adapter(self).get_webhook_listener_url()
# 		except Exception:
# 			url = None
# 		self.webhook_url = url or ""

# 	def on_update(self):
# 		"""Reconstructed - keeps Company's own Enabled + Accredited Service
# 		Providers fields in sync whenever this row is the active
# 		(enabled=1) one, same as before. Compare against your live Server
# 		Script's version."""
# 		if self.enabled:
# 			frappe.db.set_value(
# 				"Company",
# 				self.company,
# 				{
# 					"custom_accredited_service_providers": self.provider,
# 					"custom_uae_einvoice_enabled": 1,
# 				},
# 			)


"""Controller for E-Invoice Provider Settings.

You didn't have a real .py controller file for this doctype yet - the
before-save behaviour (check_duplicate, set_webhook_url) was living in a
Server Script instead, from back when this was built browser-only. This
file is my best reconstruction of that same logic based on what we built
it to do, PLUS the new enforce_single_active_provider fix. I haven't seen
your live Server Script's exact wording, so before you delete that script:
open it side by side with this file and confirm check_duplicate and
set_webhook_url do the same thing here as they do there. If anything
differs, tell me and I'll adjust this file rather than the other way
around - your live script is the source of truth for what those two
already do, this file is only meant to add the new fix cleanly.

Once you've confirmed they match, disable or delete the Server Script -
having both a .py controller AND a Server Script doing the same
before_save/validate work means it would run twice, which is exactly the
kind of duplicate-side-effect bug this file is meant to avoid, not add.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class EInvoiceProviderSettings(Document):
	def validate(self):
		self.check_duplicate()
		self.set_webhook_url()

	def check_duplicate(self):
		"""Blocks a second row for the same company + provider combo -
		reconstructed from what check_duplicate was described as doing.
		Compare against your live Server Script's version of this."""
		if not self.provider:
			return

		existing = frappe.db.exists(
			"E-Invoice Provider Settings",
			{
				"company": self.company,
				"provider": self.provider,
				"name": ["!=", self.name or ""],
			},
		)
		if existing:
			frappe.throw(
				_(
					"An E-Invoice Provider Settings row already exists for {0} + {1} ({2})."
				).format(self.company, self.provider, existing)
			)

	def set_webhook_url(self):
		"""Fills Webhook URL with whichever provider this row actually is'
		own listener endpoint - asks that adapter for it (get_webhook_
		listener_url(), providers/base.py) rather than hardcoding Flick's
		URL here unconditionally, which is what this used to do even for a
		Marmin row. An ASP with no webhook API at all (Marmin today, base
		class default) just leaves this field blank instead of showing a
		URL for a listener that doesn't exist for it."""
		from uae_erpgulf.uae_erpgulf.providers import get_adapter

		try:
			url = get_adapter(self).get_webhook_listener_url()
		except Exception:
			url = None
		self.webhook_url = url or ""

	def on_update(self):
		"""More than one row can be enabled for the same company now (see
		validate() above - enforce_single_active_provider is gone), so this
		no longer pushes THIS row's own provider onto Company's Accredited
		Service Providers select field - doing that whenever any row's
		Enabled checkbox is ticked would silently overwrite whichever
		provider the company deliberately chose, every time a second or
		third row gets enabled for testing/history/comparison. Which
		provider is actually used for submission is Company's own
		Accredited Service Providers field, picked there directly (see
		get_active_provider_settings in provider_settings.py) - this file
		doesn't touch it any more.

		Still turns UAE e-invoicing on for the company the first time any
		row here gets enabled, purely as a convenience default - it only
		gates whether e-invoicing is attempted at all
		(validate_accredited_service_provider in validation.py), not which
		provider handles it, so it's safe to leave on once set even while
		multiple rows are enabled."""
		if self.enabled:
			frappe.db.set_value("Company", self.company, "custom_uae_einvoice_enabled", 1)
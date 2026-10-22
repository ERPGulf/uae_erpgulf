"""Shared PINT-AE / UBL helpers used by every ASP adapter.

Everything in this module is UAE e-invoicing law or Peppol/UBL convention,
not anything a particular Accredited Service Provider decided. Adapters
import from here and keep only what is theirs: the JSON shape, the
endpoints, auth and webhook handling.

Rule of thumb for what belongs here: if two adapters would have to agree on
it for the FTA to accept both invoices, it goes here. If only one ASP's
API cares, it stays in that adapter.

The same module is the starting point for any other Peppol-based market
(Oman, Malaysia, Singapore, EU PINT profiles): keep the UAE-specific tables
clearly named so a second profile can sit beside them.
"""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _

from uae_erpgulf.uae_erpgulf.country_code import country_code_mapping

# ---------------------------------------------------------------- numbers
TWO = Decimal("0.01")
SIX = Decimal("0.000001")


def dec(value):
	"""Decimal from anything ERPNext hands us (float, int, str, None)."""
	return Decimal(str(value or 0))


def money(value):
	"""Amount as a 2-dp string, half-up: 12.345 -> '12.35'."""
	return str(dec(value).quantize(TWO, ROUND_HALF_UP))


def qty(value):
	"""Quantity as a 6-dp string, half-up."""
	return str(dec(value).quantize(SIX, ROUND_HALF_UP))


def num(value):
	"""Plain number string without trailing zeros: 1000.000 -> '1000'."""
	d = dec(value).normalize()
	return format(d, "f")


# ---------------------------------------------------------------- Peppol / PINT-AE identifiers
# Peppol participant scheme for UAE (TIN-based). Used when a stored Peppol ID
# carries no scheme prefix of its own.
DEFAULT_ENDPOINT_SCHEME = "0235"

# PINT-AE process identifiers (customization / profile IDs)
PROCESS_BILLING = {
	"profile_id": "urn:peppol:bis:billing",
	"customization_id": "urn:peppol:pint:billing-1@ae-1",
}
PROCESS_SELF_BILLING = {
	"profile_id": "urn:peppol:bis:selfbilling",
	"customization_id": "urn:peppol:pint:selfbilling-1@ae-1",
}

# UNCL1001 invoice type codes used by PINT-AE
INVOICE_TYPE_TAX_INVOICE = "380"
INVOICE_TYPE_CREDIT_NOTE = "381"
INVOICE_TYPE_SELF_BILLED_INVOICE = "389"
INVOICE_TYPE_SELF_BILLED_CREDIT_NOTE = "396"


def endpoint(peppol_id, default_scheme=DEFAULT_ENDPOINT_SCHEME):
	"""'0235:1234567890' -> ('1234567890', '0235'); '1234567890' -> (id, default scheme)."""
	peppol_id = (peppol_id or "").strip()
	if ":" in peppol_id:
		scheme, value = peppol_id.split(":", 1)
		return value.strip(), scheme.strip()
	return peppol_id, default_scheme


def tin_from_trn(trn):
	"""The Peppol endpoint (scheme 0235) uses the 10-digit TIN, which is the
	first 10 digits of the 15-digit TRN."""
	digits = "".join(c for c in (trn or "") if c.isdigit())
	return digits[:10]


# ---------------------------------------------------------------- code tables
# Emirate name (as on Address.emirate) -> Peppol country subdivision code
EMIRATE_CODES = {
	"abu dhabi": "AUH",
	"dubai": "DXB",
	"sharjah": "SHJ",
	"ajman": "AJM",
	"umm al quwain": "UAQ",
	"ras al khaimah": "RAK",
	"fujairah": "FUJ",
}
EMIRATE_NAMES_TEXT = "Abu Dhabi, Dubai, Sharjah, Ajman, Umm Al Quwain, Ras Al Khaimah or Fujairah"


def emirate_code(emirate_name):
	"""'Dubai' -> 'DXB'; unknown or empty -> None."""
	if not emirate_name:
		return None
	return EMIRATE_CODES.get(emirate_name.strip().lower())


# UNCL5305 VAT category codes allowed by PINT-AE
VAT_CODES = ("S", "Z", "E", "AE", "O", "N")

# Full labels (lower-cased) accepted on custom_vat_category and Item Tax Template
VAT_CATEGORY_LABELS = {
	"s - standard rated": "S",
	"standard rated": "S",
	"s": "S",
	"z - zero rated": "Z",
	"zero rated": "Z",
	"z": "Z",
	"e - exempt from tax": "E",
	"exempt from tax": "E",
	"e": "E",
	"ae - vat reverse charge": "AE",
	"vat reverse charge": "AE",
	"reverse charge": "AE",
	"ae": "AE",
	"o - not subject to vat": "O",
	"not subject to vat": "O",
	"o": "O",
	"n - margin scheme": "N",
	"margin scheme": "N",
	"n": "N",
}


def vat_category_code(label):
	"""'S - Standard rated' -> 'S'. Accepts the full label, the plain text or
	the bare code; anything else throws."""
	if not label:
		return None
	key = label.strip().lower()
	code = VAT_CATEGORY_LABELS.get(key)
	if not code:
		code = label.split(" - ")[0].strip().upper()
	if code not in VAT_CODES:
		frappe.throw(_("Invalid VAT Category: {0}. Must be one of S, Z, E, AE, O, N.").format(label))
	return code


# custom_legal_registration_identifier_type option -> BTAE-15/16 type code
LEGAL_REGISTRATION_TYPES = {
	"Commercial/Trade license": "TL",
	"Emirates ID": "EID",
	"Passport": "PAS",
	"Cabinet decision": "CD",
}

# Credit-note / debit-note reason codes (BTAE-19 discrepancy codes)
DISCREPANCY_CODES = {"DL8.61.1.A", "DL8.61.1.B", "DL8.61.1.C", "DL8.61.1.D", "DL8.61.1.E", "VD"}

# ERPNext UOM (lower-cased) -> UNECE Rec 20 code. "piece" style units map to
# `piece_code`, because ASPs differ on EA vs H87.
_PIECE_UOMS = ("nos", "unit", "each", "pcs", "piece")
_UOM_TO_UNECE_BASE = {
	"kg": "KGM",
	"kilogram": "KGM",
	"gram": "GRM",
	"gm": "GRM",
	"litre": "LTR",
	"liter": "LTR",
	"ltr": "LTR",
	"meter": "MTR",
	"metre": "MTR",
	"mtr": "MTR",
	"box": "BX",
	"pair": "PR",
	"dozen": "DZN",
	"hour": "HUR",
	"day": "DAY",
}


def uom_to_unece_table(piece_code="EA"):
	"""The UOM -> UNECE table with the chosen code for piece-type units."""
	table = {u: piece_code for u in _PIECE_UOMS}
	table.update(_UOM_TO_UNECE_BASE)
	return table


UOM_TO_UNECE = uom_to_unece_table("EA")


def uom_to_unece(uom, table=None, default="EA"):
	"""'Nos' -> 'EA'; unknown UOM -> its upper-cased name, empty -> default."""
	table = table or UOM_TO_UNECE
	if not uom:
		return default
	return table.get(uom.strip().lower(), uom.strip().upper() or default)


# ---------------------------------------------------------------- label parsing
def split_code(label):
	"""'DL8.61.1.A-Cancellation' / '30 - Credit transfer' -> (code, text).
	A label with no separator returns (label, label)."""
	raw = (label or "").strip()
	for sep in (" - ", "-"):
		if sep in raw:
			code, text = raw.split(sep, 1)
			return code.strip(), text.strip()
	return raw, raw


def transaction_type_pattern(doc):
	"""custom_invoice_transaction_type_code ('1XXXXXX : Free trade zone
	transaction') -> the 7-character X/1 pattern, or None when unset."""
	raw = (
		doc.get("custom_invoice_transaction_type_code")
		if hasattr(doc, "get")
		else getattr(doc, "custom_invoice_transaction_type_code", None)
	)
	if not raw:
		return None
	return raw.split(":")[0].strip()


def transaction_type_flags(doc):
	"""custom_invoice_transaction_type_code -> the 8-character 0/1 flag
	string BTAE-02 needs ('1XXXXXX' -> '10000000')."""
	raw = transaction_type_pattern(doc) or ""
	bits = "".join("1" if c == "1" else "0" for c in raw)
	return (bits + "00000000")[:8]


# ---------------------------------------------------------------- country / address
def country_code(country_name):
	"""'United Arab Emirates' -> 'AE'; unknown or empty -> None."""
	if not country_name:
		return None
	return country_code_mapping().get(country_name.strip().lower())


def resolve_address_codes(address):
	"""ISO country code and Peppol subdivision for an Address doc.

	Throws when the country is not recognised, or when a UAE address has no
	recognised emirate (PINT-AE IBR-144-ae). Outside the UAE the subdivision
	falls back to state, then city. Returns (country_code, subdivision).
	"""
	code = country_code(address.get("country"))
	if not code:
		frappe.throw(_("Address {0} has no recognised Country.").format(address.name))

	subdivision = emirate_code(address.get("emirate"))
	if not subdivision:
		if code == "AE":
			frappe.throw(
				_("Address {0} needs a recognised UAE emirate ({1}).").format(
					address.name, EMIRATE_NAMES_TEXT
				)
			)
		subdivision = address.get("state") or address.get("city")
	return code, subdivision

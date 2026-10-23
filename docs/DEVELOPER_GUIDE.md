# Multi-ASP Developer Guide

**Intended for:** ERPGulf developers and partner developers working on the `uae_erpgulf` app — adding a new ASP adapter, maintaining an existing one (Flick, Marmin, Suntech), or debugging webhook and status-sync issues. The same adapter pattern applies to any country with a provider-based e-invoicing model, such as Oman or the European countries using Peppol access points, so partners building for those markets can use this guide as the reference design. It assumes you are comfortable with Frappe/ERPNext development in Python.

Source code: [github.com/ERPGulf/uae_erpgulf](https://github.com/ERPGulf/uae_erpgulf). This guide matches the code that introduced the shared `providers/pint.py` layer (branch `version-3-pint-refractor`, October 2026). The [End User Guide](USER_GUIDE.md) describes what the accountant sees; the [Testing Guide](TESTING_GUIDE.md) has the UI test script, including section 9 for a newly added ASP.

## Overview

Every ASP gets its own adapter class, and the rest of the app only ever talks to that adapter. `uae_erpgulf` supports several Accredited Service Providers (ASPs) for UAE e-invoicing: today Flick, Marmin and Suntech, with a Fynamics adapter in the tree that is not yet registered. Each ASP has its own API, auth, JSON format and webhook style, but ERPNext does the same jobs for all of them: submit an invoice, check its status, fetch the XML/PDF, receive webhooks and import incoming invoices.

So the common code (buttons, scheduler, attachments, webhook logs, incoming-invoice import) never knows which ASP it is talking to. It asks for "the adapter for this company" and calls the same method names. Adding a new ASP means one new adapter plus one line in `hooks.py`; the common code is never touched.

## Folder structure

ASP-specific code lives under `providers/<asp>/`. Everything outside `providers/` is shared by all ASPs.

```
uae_erpgulf/uae_erpgulf/
├── providers/
│   ├── __init__.py        # get_adapter(), registered_providers(), assert_provider_registered()
│   ├── base.py            # BaseAdapter: the contract every ASP follows
│   ├── pint.py            # shared PINT-AE / UBL helpers and code tables (see next section)
│   ├── flick/
│   │   ├── adapter.py     # FlickAdapter
│   │   ├── sales_json.py  # Flick's sales invoice JSON builder
│   │   └── purchase_json.py
│   ├── marmin/
│   │   └── adapter.py     # MarminAdapter
│   ├── suntech/
│   │   └── adapter.py     # SuntechAdapter + its webhook listener
│   └── fynamics/
│       └── adapter.py     # FynamicsAdapter (in the tree, not yet registered in hooks.py)
│
├── provider_settings.py   # common: the active Provider Settings row for a company
├── submit_sales.py        # common: Sales Invoice on_submit hook, buttons, bulk submit
├── send_purchase.py       # common: the same for Purchase Invoice
├── status_sync.py         # common: 5-minute scheduler poll, runs for every ASP
├── attach.py              # common: buttons for status / XML / PDF, attaching files
├── webhook.py             # common: webhook buttons + logs
├── get_purchase_inv.py    # common: "Get FTA Incoming Invoices" import
├── verify_token.py        # common: test auth button
└── validation.py          # common: checks before submit (incl. provider is registered)
```

The rule has three parts. If the code mentions an ASP's URL, field name or JSON key, it goes inside that ASP's folder. If two adapters would have to agree on it for the FTA to accept both invoices (a code table, a rounding rule, how a TRN becomes a Peppol ID), it goes in `providers/pint.py`. If it works the same for every ASP and is about ERPNext rather than the invoice format (buttons, scheduler, attachments, logs), it stays outside `providers/`.

## The shared PINT-AE layer

`providers/pint.py` holds everything that is UAE e-invoicing law or Peppol/UBL convention rather than one ASP's choice. Adapters import from it and never re-declare it. What it provides today:

| Group | Names | Notes |
| --- | --- | --- |
| Numbers | `dec`, `money`, `qty`, `num`, `TWO`, `SIX` | `Decimal(str(x))` based; `money` is 2 dp half-up, `qty` 6 dp, `num` strips trailing zeros |
| Peppol identifiers | `DEFAULT_ENDPOINT_SCHEME` (0235), `endpoint(peppol_id)`, `tin_from_trn(trn)` | `endpoint` returns `(id, scheme)`; the TIN is the first 10 digits of the 15-digit TRN |
| Process IDs | `PROCESS_BILLING`, `PROCESS_SELF_BILLING`, `INVOICE_TYPE_*` | PINT-AE customization / profile IDs and UNCL1001 codes 380, 381, 389, 396 |
| Code tables | `EMIRATE_CODES` + `emirate_code()`, `VAT_CODES` + `vat_category_code()`, `LEGAL_REGISTRATION_TYPES`, `DISCREPANCY_CODES`, `UOM_TO_UNECE` + `uom_to_unece()` / `uom_to_unece_table(piece_code)` | `vat_category_code` accepts the full label, the plain text or the bare code and throws on anything else; `uom_to_unece_table("H87")` for ASPs that want H87 instead of EA for pieces |
| Label parsing | `split_code(label)`, `transaction_type_pattern(doc)`, `transaction_type_flags(doc)` | `'30 - Credit transfer'` to `('30', 'Credit transfer')`; `'1XXXXXX : ...'` to `'1XXXXXX'` or the 8-bit `'10000000'` |
| Address | `country_code(name)`, `resolve_address_codes(address)` | returns `(ISO country, subdivision)` and throws the standard messages when the country is unknown or a UAE address has no emirate |

An adapter imports what it needs, usually under the short names it already used:

```python
from uae_erpgulf.uae_erpgulf.providers.pint import (
    PROCESS_BILLING, PROCESS_SELF_BILLING, UOM_TO_UNECE,
    dec as _dec, money as _money, endpoint as _endpoint,
    resolve_address_codes, split_code as _split_code,
    vat_category_code as _vat_category_code,
)
```

When you need a helper that is not there, add it to `pint.py` if a second ASP would need the same thing; keep it in the adapter if only that ASP's API cares. For a market outside the UAE (Oman, Malaysia, EU PINT profiles) add that profile's tables beside the UAE ones rather than editing them; the UAE-specific names are kept explicit for that reason.

## How it works

The Company's selected ASP decides which adapter runs, and everything else stays the same.

1. The Company field `custom_accredited_service_providers` picks the ASP.
2. `get_adapter(settings)` reads the class path from `uae_einvoice_providers` in `hooks.py`.
3. It returns that adapter, already bound to the E-Invoice Provider Settings row.
4. Common code calls the same method names on whichever adapter comes back.
5. Results come back by webhook or by the scheduler poll.

## The adapter contract

Every adapter subclasses `BaseAdapter` in `providers/base.py` and fills in the methods below. `self.settings` is the E-Invoice Provider Settings row, so credentials and URLs always come from there and are never hardcoded. If an ASP doesn't support a feature, leave the base method alone; it throws a clear "<feature> is not supported by <provider>" message.

| Method | What it must do | Required? |
| --- | --- | --- |
| `_fetch_token()` | Call the ASP's auth API, return a token (the base class caches it) | Yes |
| `verify_auth()` | Test the credentials (used by the Test Auth button) | Yes |
| `submit_invoice(doctype, doc)` | Build the ASP's JSON from the invoice and POST it | Yes |
| `parse_submit_response(status_code, data)` | Turn the ASP reply into document_id + status | Yes |
| `get_document_status(doctype, doc)` | Fetch the latest status for an invoice | Yes |
| `get_status_from_document_status(body)` | Map the ASP's status to our Reporting Status | Yes |
| `get_document_xml` / `get_document_pdf` | Download the XML / PDF | If the ASP offers it |
| `get_participant_details()` | Read our own company profile from the ASP | Optional |
| `lookup_peppol_id(peppol_id)` / `update_participant(company_doc)` | Look up a Peppol participant / update our own registration at the ASP | Optional |
| `register_webhook` / `get_subscription` / `get_webhook_deliveries` | Webhook management via API | Only if the ASP has a webhook API |
| `parse_incoming_invoice(json)` | Convert the ASP's received-invoice format into one common dict | If importing purchases |
| `get_webhook_listener_url()` | The URL to give the ASP for webhooks | If using webhooks |

Adapters can also set class flags that the common code reads: `AUTO_FETCH_DOCUMENTS_ON_SUBMIT = False` when the XML/PDF isn't ready right after submit, `ATTACH_DOCUMENTS_IN_SYNC = False` when `get_document_status` attaches the files itself, `STATUS_SYNC_ENABLED = False` to keep an ASP out of the scheduler poll, and `FINAL_REPORTING_STATUSES` if the ASP's final states differ from reported / rejected / failed.

## Adding a new ASP

Adding an ASP takes seven steps, and only steps 2 and 3 are real code. The key you register in `hooks.py` (step 4) is the name users will see in the dropdowns; `validate_accredited_service_provider` and the Provider Settings form both refuse a name that has no entry in `hooks.py`, so a mismatch shows up on the first save rather than at submit time.

1. **Read the ASP's API docs.** Note the base URL, auth type, submit endpoint, status values, XML/PDF download and webhook format.
2. **Create the folder** `providers/<asp>/` with an empty `__init__.py` and an `adapter.py`.
3. **Write the adapter class.** Subclass `BaseAdapter`, import the code tables and helpers from `providers/pint.py`, and implement the required methods from the table above. Start with auth, then submit, then status. Do not re-declare emirate, VAT, UOM or Peppol-ID logic in the adapter.
4. **Register it in hooks.py.** Add one line to `uae_einvoice_providers`. The key is the provider name as it will appear in the dropdowns.
5. **Run `bench --site <site> migrate`.** `sync_provider_options` (hooked on `after_migrate` and `after_install`) appends the new name to the Provider dropdown on E-Invoice Provider Settings and to *Accredited Service Providers* on Company. Nothing to edit by hand; the existing FTA list is kept.
6. **Add any ASP-only custom fields** (like `custom_marmin_profile_id`). Use Depends On so they show only for that ASP, and export them to fixtures.
7. **Test in sandbox.** Save a Provider Settings row (this already checks the registry), run Test Auth, then a sales invoice, credit note, purchase invoice and debit note. Check status, XML/PDF and webhooks. The [Testing Guide](TESTING_GUIDE.md), section 9, is the checklist.

A minimal adapter skeleton:

```python
import frappe
import requests
from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter
from uae_erpgulf.uae_erpgulf.providers.pint import (
    PROCESS_BILLING, PROCESS_SELF_BILLING,
    dec as _dec, money as _money, endpoint as _endpoint,
    resolve_address_codes, vat_category_code as _vat_category_code,
)

TIMEOUT = 60


class NewAspAdapter(BaseAdapter):
    AUTO_FETCH_DOCUMENTS_ON_SUBMIT = False

    def _fetch_token(self):
        r = requests.post(f"{self.get_base_url()}/auth/token", data={
            "client_id": self.settings.client_id,
            "client_secret": self.settings.get_password("client_secret"),
        }, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()["access_token"]

    def verify_auth(self):
        return {"ok": bool(self.get_valid_token())}

    def submit_invoice(self, doctype, doc, json_data=None):
        payload = json_data or self._build_payload(doctype, doc)
        self.save_outgoing_payload(doc, payload)
        r = requests.post(f"{self.get_base_url()}/invoices", json=payload,
                          headers=self.get_auth_headers(), timeout=TIMEOUT)
        return self.parse_submit_response(r.status_code, r.json())

    def get_document_status(self, doctype, doc):
        ...

    def _build_payload(self, doctype, doc):
        # read everything from doc / company / customer fields, never hardcode;
        # codes and rounding come from pint, only the JSON shape is yours
        endpoint_id, scheme = _endpoint(self.settings.participant_id)
        process = PROCESS_SELF_BILLING if doctype == "Purchase Invoice" else PROCESS_BILLING
        lines = [{
            "amount": _money(item.net_amount),
            "vat_category": _vat_category_code(doc.custom_vat_category),
        } for item in doc.items]
        ...
```

Then in `hooks.py`:

```python
uae_einvoice_providers = {
    ...
    "New ASP Name LLC": "uae_erpgulf.uae_erpgulf.providers.newasp.adapter.NewAspAdapter",
}
```

Use `providers/suntech/adapter.py` as the reference. It is the newest and the most complete.

## Webhooks and status sync

Each ASP sends webhooks differently, so the listener lives inside that ASP's adapter file. Every listener ends the same way:

1. A whitelisted guest method receives the POST, e.g. `providers.suntech.adapter.suntech_webhook_listener`.
2. It verifies the request with the ASP's method (JWT, HMAC signature, UUID) using `webhook_secret` from Provider Settings.
3. It writes a row to UAE E-Invoice Webhook Logs.
4. It finds the invoice by `custom_document_id`, updates `custom_reporting_status` and attaches the XML/PDF when ready.
5. For a received invoice, it creates a UAE Incoming Invoices record.

There are two kinds of webhook setup:

- **Subscription via API (Flick):** the Subscribe Webhook button calls `register_webhook()`.
- **Portal only (Marmin, Suntech):** the URL and secret are entered in the ASP's portal. The settings row shows the URL to paste.

Webhooks can be missed, especially when the ASP doesn't retry. The common job `status_sync.sync_pending_invoices` (scheduled every 5 minutes in `hooks.py`) already covers every ASP: it picks submitted invoices from the last 7 days that are not final yet or still miss their XML/PDF, and calls the company's adapter. A new ASP needs no scheduler entry of its own; it only needs a working `get_document_status`, plus the class flags above if its behaviour differs.

## Rules and gotchas

These are the issues already hit while building Flick, Marmin and Suntech.

- **No hardcoded values.** Take amounts, codes, TRN and party details from invoice, Company, Customer or Supplier fields, and credentials from Provider Settings.
- **Purchase invoices flip the parties.** On a purchase (self-billing), the supplier is the seller and our company is the buyer. Check every party block.
- **Returns differ per ASP.** A purchase return links to a Purchase Invoice, not a Sales Invoice. Some ASPs use a separate endpoint or document type for debit and credit notes.
- **Don't break tested flows.** When fixing one document type, change only that branch of the adapter.
- **No `_()` at module or class level.** Semgrep blocks it (frappe-breaks-multitenancy). Wrap messages in a method instead.
- **Never use the `Authorization: Bearer` header for webhooks.** Frappe intercepts it and returns 401 before your guest method runs. Ask the ASP to send the token in a custom header (e.g. `X-TCA-Token`).
- **The webhook URL must be reachable from the internet**, not just from the office. Test from mobile data.
- **Every `requests` call needs `timeout=`.** Without it a stalled ASP hangs a web or scheduler worker indefinitely.
- **TIN vs TRN.** The Peppol endpoint (scheme 0235) uses the 10-digit TIN, which is the first 10 digits of the 15-digit TRN (`pint.tin_from_trn`).
- **Strip credentials.** A trailing space in `client_id` or secret gives a 401 with an empty body.
- **ASP-only fields** get Depends On for that provider and must be added to fixtures.

# UAE E-Invoicing for ERPNext (uae_erpgulf)

A Frappe / ERPNext app that submits Sales Invoices and Purchase Invoices to the UAE Federal Tax Authority (FTA) through an Accredited Service Provider (ASP), tracks their reporting status, stores the FTA-returned XML and PDF against the invoice, receives webhooks, and imports incoming supplier invoices.

The UAE model is Peppol-based (the five-corner "DCTCE" model, PINT-AE invoice profile). Every ASP is a Peppol access point with its own API, so the app has one **adapter per ASP** behind a common interface. Switching ASP is a dropdown on Company; nothing else changes.

| | |
| --- | --- |
| Supported ASPs | Flick Network L.L.C, Marmin AI Software Design LLC, Suntech Business Solutions DMCC |
| Documents | Sales Invoice (tax invoice 380, credit note 381), Purchase Invoice (self-billed 389, self-billed credit note 396), incoming supplier invoices |
| Frappe / ERPNext | Version 15 and 16 |
| Licence | MIT (see `license.txt`) |
| Maintainer | [ERPGulf](https://www.erpgulf.com) · support@erpgulf.com |

## Documentation

| Document | For whom | What it covers |
| --- | --- | --- |
| [End User Guide](docs/USER_GUIDE.md) | Accountants and admins | Setting up Company, Provider Settings and master data; submitting invoices; reading statuses and badges; credit notes; purchase invoices; importing incoming invoices; dashboard, reports, logs; error messages |
| [Testing Guide](docs/TESTING_GUIDE.md) | Implementers and QA | Step-by-step UI test script with test data and expected results for every screen and button, per ASP, plus the procedure for testing a newly added ASP |
| [Multi-ASP Developer Guide](docs/DEVELOPER_GUIDE.md) | ERPGulf developers and partners | Architecture, the adapter contract, the shared PINT-AE layer, how to add a new ASP, webhooks and status sync, rules and gotchas. Also the reference design for other Peppol markets (Oman, Malaysia, EU PINT profiles) |

## How it works

```
Sales / Purchase Invoice  ──submit──▶  validation.py  ──▶  submit_sales.py / send_purchase.py
                                                                     │
                                            providers/__init__.py: get_adapter(settings)
                                                                     │
                       ┌───────────────────────┬─────────────────────┴──────────────────────┐
                 FlickAdapter            MarminAdapter                            SuntechAdapter
                 (flick/)                (marmin/)                                (suntech/)
                       └───────────────────────┴────────────────────────────────────────────┘
                                                 providers/pint.py  (shared PINT-AE helpers)
                                                 providers/base.py  (BaseAdapter contract)
```

1. On Company, **UAE E-invoice Enabled** is ticked and an **Accredited Service Provider** is chosen.
2. One **E-Invoice Provider Settings** row per company holds that ASP's credentials, URLs and webhook secret.
3. When a Sales or Purchase Invoice is submitted, the app checks the setup, builds the ASP's payload from the invoice, Company, Customer/Supplier and Address fields, and POSTs it. The response, document ID and status are stored on the invoice.
4. Status moves to *reported* / *rejected* / *failed* either by **webhook** from the ASP or by the **scheduler** (`status_sync.sync_pending_invoices`, every 5 minutes), which also attaches the XML and PDF once ready.
5. Incoming supplier invoices arrive by webhook into **UAE Incoming Invoices** and can be turned into draft Purchase Invoices from the Purchase Invoice form.

## Installation

```bash
cd frappe-bench
bench get-app https://github.com/ERPGulf/uae_erpgulf.git
bench --site <site> install-app uae_erpgulf
bench --site <site> migrate
bench build --app uae_erpgulf
```

`migrate` installs the custom fields (fixtures) on Company, Customer, Supplier, Address, Item, Item Tax Template, Sales Invoice, Purchase Invoice and their item tables. Updating later:

```bash
bench get-app https://github.com/ERPGulf/uae_erpgulf.git --branch main --overwrite   # or: cd apps/uae_erpgulf && git pull
bench --site <site> migrate
bench --site <site> clear-cache
```

No Python packages beyond what Frappe already ships (`requests`, `PyJWT`). The site must be reachable from the internet on HTTPS for webhooks, and the scheduler must be enabled.

## Quick start (five minutes to a first submission)

1. **Company** → tick *UAE E-invoice Enabled*, pick the ASP under *Accredited Service Providers*, make sure *Tax ID* holds the 15-digit TRN.
2. **E-Invoice Provider Settings** → New: Company, Provider (same name as on Company), *Enabled*, credentials from the ASP's sandbox, *Base URL*, *Participant ID* (Peppol ID). Save, then **E-Invoicing → Verify Token**.
3. **Customer / Supplier** → *Peppol ID*, *Legal Registration Identifier Type* and *Trade License Number*; their **Address** needs *Country* and, for UAE addresses, *Emirate*.
4. **Sales Invoice** → fill *VAT Category* (and the dependent code fields), submit. The *E-Invoice Response* dialog shows the ASP's reply; *UAE E-Invoice Status*, *Reporting Status* and *Document ID* are filled in. Within five minutes the status badge turns to *Reported* and the XML/PDF appear as attachments.

Everything above is covered step by step, with screenshots-level detail, in the [End User Guide](docs/USER_GUIDE.md).

## Folder structure

```
uae_erpgulf/uae_erpgulf/
├── providers/                 # one folder per ASP + the shared layer (see Developer Guide)
│   ├── __init__.py            # get_adapter(), registered_providers(), assert_provider_registered()
│   ├── base.py                # BaseAdapter contract
│   ├── pint.py                # shared PINT-AE / UBL code tables and helpers
│   ├── flick/  marmin/  suntech/  fynamics/
├── submit_sales.py            # Sales Invoice on_submit, "Send Invoice" button, bulk submit
├── send_purchase.py           # the same for Purchase Invoice
├── status_sync.py             # 5-minute scheduler poll for every ASP
├── attach.py                  # XML / PDF fetch-and-attach
├── webhook.py                 # webhook subscribe / logs buttons
├── get_purchase_inv.py        # "Get FTA Incoming Invoices" import
├── verify_token.py            # Test Auth, participant details, access token, document status
├── validation.py              # before-submit checks (ASP selected, settings exist, adapter registered)
├── provider_settings.py       # resolves the active Provider Settings row for a company
├── doctype/                   # E-Invoice Provider Settings, UAE E-Invoice Webhook Logs,
│                              # UAE E-invoicing success log, UAE Incoming Invoices
├── page/uae_e_invoice_dashbo  # UAE E-Invoice Dashboard
├── report/                    # UAE E-Invoice Sales / Purchase Status Report
└── workspace/                 # "UAE E-Invoice Integration" workspace
uae_erpgulf/public/js/         # form scripts: buttons, badges, tooltips, bulk submit
uae_erpgulf/fixtures/          # custom fields
```

## Scheduled jobs

| Job | Schedule | What it does |
| --- | --- | --- |
| `status_sync.sync_pending_invoices` | every 5 min | For submitted invoices of the last 7 days with a Document ID that are not yet final, or still missing XML/PDF: ask the ASP for status, update *Reporting Status*, attach documents |
| `webhook.update_webhook_logs` | every minute | Refresh *Last Webhook Logs Response* on every enabled Provider Settings row that has a webhook UUID |

Both need the scheduler enabled on the site (`bench --site <site> scheduler enable`).

## Webhooks

Each ASP has its own listener, registered as a guest-accessible endpoint:

| ASP | Listener URL (append to your site URL) | Verification |
| --- | --- | --- |
| Flick | `/api/method/uae_erpgulf.uae_erpgulf.providers.flick.adapter.flick_webhook_listener` | subscription via API (*Subscribe Webhook* button) |
| Marmin | `/api/method/uae_erpgulf.uae_erpgulf.providers.marmin.adapter.marmin_webhook_listener` | HMAC signature with *Webhook Secret*; URL and secret are entered in Marmin's Developer Dashboard |
| Suntech | `/api/method/uae_erpgulf.uae_erpgulf.providers.suntech.adapter.suntech_webhook_listener` | JWT in header `X-TCA-Token`, signed with *Webhook Secret*; URL and secret are entered in the Suntech portal |

Every delivery is logged in **UAE E-Invoice Webhook Logs**. Missed webhooks are covered by the 5-minute scheduler.

## Development

```bash
cd apps/uae_erpgulf
pre-commit install          # ruff + ruff-format + prettier, as configured in .pre-commit-config.yaml
pre-commit run --all-files
```

Adding an ASP is one new folder under `providers/` plus one line in `hooks.py`; the [Developer Guide](docs/DEVELOPER_GUIDE.md) walks through it with a skeleton adapter. Issues and pull requests on [GitHub](https://github.com/ERPGulf/uae_erpgulf). Security reports to support@erpgulf.com, please not as public issues.

## Other ERPGulf e-invoicing apps

[ZATCA (Saudi Arabia)](https://github.com/ERPGulf/zatca_erpgulf) · Malaysia (MyInvois) · more at [www.erpgulf.com](https://www.erpgulf.com)

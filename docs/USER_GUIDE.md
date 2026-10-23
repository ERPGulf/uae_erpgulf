# UAE E-Invoicing for ERPNext — End User Guide

This guide is for the accountant or administrator who sets up and uses UAE e-invoicing inside ERPNext. It assumes a working ERPNext site with the `uae_erpgulf` app installed (see the [README](../README.md) for installation) and an account with your chosen Accredited Service Provider (ASP).

Terms used throughout: **ASP** is the provider that carries your invoice to the FTA (Flick, Marmin or Suntech today). **TRN** is your 15-digit VAT registration number. **Peppol ID / Participant ID** is your identity on the Peppol network, derived from the TRN (scheme `0235`). **Reporting Status** is what the FTA said about the invoice; **UAE E-Invoice Status** is whether the ASP accepted the submission.

---

## 1. One-time setup

### 1.1 Company

Open **Company** → your company → tab *UAE E-invoicing* (or scroll to the custom fields).

| Field | Set it to |
| --- | --- |
| UAE E-invoice Enabled | Tick. Until this is ticked the app does nothing for this company. |
| Accredited Service Providers | Your ASP, e.g. *Flick Network L.L.C*. Only providers that have an adapter in the app can be used; the Provider Settings form refuses the rest. |
| Allow credit-note without original invoice in the system | Tick only if you issue credit notes against invoices that were never in ERPNext (migration cases). |
| Tax ID | Your 15-digit TRN. The Peppol ID (first 10 digits) is derived from it. |
| Address | The company's default address must have *Country* and, for the UAE, *Emirate* filled. |

### 1.2 E-Invoice Provider Settings

**E-Invoice Provider Settings → New**. One row per company and provider; only one row per company may be *Enabled*.

| Field | Notes |
| --- | --- |
| Company, Provider | Provider must be exactly the name chosen on Company. |
| Enabled | Tick. Submissions use the enabled row for the company. |
| Auth Type | As your ASP's onboarding notes say (`oauth2` for the three current ASPs). |
| Client ID / Client Secret | From the ASP's portal. Copy without trailing spaces; a trailing space produces a 401 with an empty body. |
| Participant ID | Your Peppol ID as registered with the ASP (`0235:` + 10-digit TIN, or the TIN alone). |
| Base URL | The ASP's sandbox or production API root. *Base URL Override* is only for support cases. |
| Webhook Secret | Marmin and Suntech: the secret used to verify incoming webhooks. |

Save, then use the **E-Invoicing** button group:

- **Verify Token** — checks the credentials. *Last Test Status* becomes *Passed* or *Failed* and *Last Test Response* shows the ASP's reply. Do this first after every credential change.
- **Get Participant Details** — shows how the ASP has you registered (name, TRN, Peppol ID). Use it to confirm the Participant ID.
- **Get Access Token** — forces a fresh OAuth token; rarely needed.
- **Subscribe Webhook** (Flick) — registers the site's listener URL with the ASP so status updates arrive automatically. *Webhook UUID* is filled on success.
- **Get Subscription** / **Webhook Logs** (Flick) — show the current subscription and recent deliveries as reported by the ASP.
- Marmin and Suntech have no webhook API. Copy the *Webhook URL* that the settings row fills in after saving into the ASP's portal (Marmin: Developer Dashboard → Webhooks; Suntech: Settings → Webhooks, header name `X-TCA-Token`, no scheme) and paste the signing secret the portal shows into *Webhook Secret*. Pressing the webhook buttons for these ASPs shows a "not supported" message.

The site must be reachable from the internet on HTTPS for webhooks. If it isn't, statuses still update, but only through the 5-minute scheduler.

### 1.3 Customers and Suppliers

On every **Customer** and **Supplier** you invoice electronically:

| Field | Notes |
| --- | --- |
| Tax ID | Their TRN. |
| Peppol ID | Their Peppol participant ID. Required by Marmin for every party; recommended everywhere. |
| Legal Registration Identifier Type | *Commercial/Trade license*, *Emirates ID*, *Passport* or *Cabinet decision*. |
| Trade License Number, Legal Registration Authority | Shown when the type is *Commercial/Trade license*. |
| FZ Beneficiary ID | Free-zone beneficiary ID where applicable. |
| Is B2C Customer | (Customer only) tick for consumers without a TRN. |

Their **Address** needs *Country*, and *Emirate* for UAE addresses. Submissions fail with a clear message when either is missing.

### 1.4 Items and tax templates

On **Item**: *Item Type Codes* (Goods / Services / Both) and the matching *HS Code* or *SAC code*. The same fields exist on the invoice item rows and can be set per line.

On **Item Tax Template**: *VAT Category* and, when relevant, *VAT Exemption Reason Code* or *RCM Nature Code*. A template assigned to an invoice line overrides the invoice-level VAT category for that line.

### 1.5 Mode of Payment

On each **Mode of Payment** used for POS or payment entries, fill *Payment Means Codes* (e.g. `10` cash, `30` credit transfer, `48` bank card) so the invoice carries the right UNCL4461 code.

---

## 2. Sales Invoices

### 2.1 Fields to fill

| Field | When | Values |
| --- | --- | --- |
| VAT Category | Always | S Standard rated · Z Zero rated · E Exempt · AE Reverse charge · O Not subject to VAT · N Margin scheme |
| VAT Exemption Reason Code | VAT Category = E | DL8.46.1 – DL8.46.4 |
| RCM Nature Code | VAT Category = AE | DL8.48.x codes |
| Invoice Transaction Type Code | When the supply is special | Free trade zone, Deemed supply, Margin scheme, Summary, Continuous, Disclosed agent, E-commerce, Export |
| Frequency Billing Code List, Invoice Note | Periodic / summary invoices | DLY, WKY, MTH … or OTH + note |
| Credit Note Reason Code | Credit notes (Is Return) | DL8.61.1.A Cancellation … VD Void |
| Skip Validation for Credit Note | Credit notes without an original invoice in ERPNext | Lets ERPNext accept a return whose items were never invoiced here |

Hover the small info icon next to each field for a one-line explanation; clicking it opens the field reference.

### 2.2 What happens on Submit

1. Before submit, the app checks that the Company has *UAE E-invoice Enabled*, a provider selected, and an enabled Provider Settings row. Otherwise submit is blocked with a message naming what is missing.
2. On submit, the invoice is sent to the ASP. A dialog **E-Invoice Response** shows the HTTP status and the ASP's reply. Close it; the invoice is submitted either way.
3. The invoice now shows, in the *UAE E-Invoicing* section:
   - **UAE E-Invoice Status**: *Success* (ASP accepted) or *Not Submitted* (ASP rejected or unreachable).
   - **Reporting Status**: *pending* right after submit, then *reported*, *rejected* or *failed* from the FTA.
   - **Document ID**: the ASP's reference; needed for every later status check.
   - **Submit Response** / **Document Status Response**: raw replies, for support.
   - A status badge image: *Pending*, *Reported*, *Not Reported* or *Failed*.
4. The XML and PDF returned by the FTA are attached to the invoice, immediately for Flick and Marmin, and within five minutes for Suntech (whose documents are generated after reporting).
5. A row is written to **UAE E-invoicing success log** for every accepted submission.

### 2.3 Buttons on a submitted invoice

| Button | Where | Shown when | What it does |
| --- | --- | --- | --- |
| Send Invoice | *UAE E-Invoice* menu | Status is *Not Submitted*, or Reporting Status is *failed* | Resubmits the invoice to the ASP after you fixed the data |
| Get Document Status | Toolbar | Submitted and not yet *reported* | Asks the ASP for the latest FTA status and shows a **Document Status** dialog (green = reported, orange = pending, red = error) |
| Get Document → XML / PDF | *Get Document* menu | Submitted; hidden once the file is attached | Fetches the FTA XML or PDF and attaches it |

You rarely need these: the scheduler performs the status check and attachment for every pending invoice every five minutes, and webhooks update the status as soon as the ASP sends them.

### 2.4 Credit notes

Create the return from the original Sales Invoice (*Create → Return / Credit Note*) so *Return Against* is filled, choose a *Credit Note Reason Code*, and submit. It is sent as a credit note (type 381) referencing the original.

For a credit note against an invoice that is not in ERPNext: tick *Allow credit-note without original invoice in the system* on Company, create a new Sales Invoice with *Is Return* ticked, fill *Return Against For UAE E-invoice* with the original invoice number, tick *Skip Validation for Credit Note*, and submit.

### 2.5 Sending many invoices at once

In the **Sales Invoice list**, select two or more invoices → *Actions → Send Invoices to FTA Submission*. Draft invoices are submitted (which sends them); already-submitted ones are resent; invoices with status *Success* are skipped. The result dialog lists *Submitted Successfully*, *Skipped (Already Submitted)* and *Failed* with the reason for each failure. The action needs at least two selected invoices.

---

## 3. Purchase Invoices

Purchase Invoices are **self-billed** documents: your company is the buyer, the supplier is the seller, and the FTA receives them from you. The fields, buttons and statuses mirror the Sales Invoice (section 2), with these differences:

- *Payment Means Codes* is on the invoice itself (header level).
- A purchase return (debit note) is sent as a self-billed credit note (type 396).
- Every Purchase Invoice for an enabled company is sent on submit. With Flick, *Submit To FTA* must be ticked on the invoice or the submission is refused with "Submit to FTA not Enabled"; Marmin and Suntech ignore the checkbox.

### 3.1 Importing invoices your suppliers sent you

When a supplier's ASP delivers an invoice to your Peppol ID, your ASP pushes it to ERPNext by webhook and it appears in **UAE Incoming Invoices** with status *Not Submitted* and the original JSON attached.

To turn them into Purchase Invoices: open **Purchase Invoice → New**, *Get Items From → Get FTA Incoming Invoices*. The dialog **FTA Incoming Invoices – Not Submitted** lists each document ID; tick the ones to import and click **Import Selected**. For every selected record a *draft* Purchase Invoice is created with the supplier (matched by Tax ID, then by name; the import fails with "Supplier not found" if neither matches, so create the supplier first), the lines and the VAT, and the incoming record moves to *Submitted*. The **Import Complete** dialog links to the new drafts. Review each draft, especially the expense accounts and tax template, before submitting it.

**Match & Approve** on a Purchase Invoice looks up the invoice's *Document ID* in UAE Incoming Invoices and shows a green headline when the record exists. It is a convenience check that the invoice came through the FTA channel, not an FTA approval.

---

## 4. Dashboard and reports

**UAE E-Invoice Integration** workspace (under ERPNext Settings) gives the entry points.

**UAE E-Invoice Dashboard** (*Detailed Dashboard* shortcut) shows, for Sales and Purchase separately, the counts of *Reported From FTA*, *Success From ASP*, *Failed*, *Not Submitted* and *Cancelled* invoices, a Reported-vs-Failed chart, and the last 20 invoices of each type with their statuses.

**UAE E-Invoice Sales Status Report** and **UAE E-Invoice Purchase Status Report** list invoices with *Reporting Status* and *UAE Status* for a date range. The *Status* filter takes `reported`, `failed`, `Not Submitted` or `Cancelled`; leave it blank for all. The reports are available to Accounts Manager / Accounts User (and Purchase User, Auditor for purchases).

---

## 5. Logs (System Manager)

| DocType | What it holds |
| --- | --- |
| UAE E-invoicing success log | One row per accepted submission: document ID, invoice, statuses, raw response |
| UAE E-Invoice Webhook Logs | One row per webhook delivery: event, document ID, status, raw body |
| UAE Incoming Invoices | Supplier invoices received through the FTA channel, with the original JSON and import status |
| Error Log (Frappe) | Every failed call, with the full traceback. Titles start with *E-Invoice …* or the ASP name |

For support, send the invoice name, its *Submit Response* or *Document Status Response*, and the matching Error Log entry.

---

## 6. Messages you may see, and what to do

| Message | Cause | Fix |
| --- | --- | --- |
| Select an Accredited Service Provider on {company} before submitting e-invoices | Company has e-invoicing enabled but no provider | Company → Accredited Service Providers |
| No adapter is registered for provider '…' | A provider name without an integration was chosen | Choose Flick, Marmin or Suntech, or ask ERPGulf about the provider you need |
| No enabled E-Invoice Provider Settings found for {provider} under {company} | No settings row, or it is not Enabled, or Provider differs from Company | Create / enable the row; provider names must match exactly |
| 401 with an empty body on Verify Token | Credentials wrong or with trailing spaces | Re-paste Client ID and secret |
| Address {0} has no recognised Country / needs a recognised UAE emirate | Party or company address incomplete | Fill Country and Emirate on the Address |
| Invalid VAT Category: … | VAT Category left blank or an unexpected value | Pick one of S, Z, E, AE, O, N |
| Customer/Supplier … has no PEPPOL ID | Marmin requires a Peppol ID on every party | Fill Peppol ID on the Customer/Supplier |
| E-Invoice processing failed: … | The ASP call raised an error after the invoice was submitted | Read the message; fix the data; use *Send Invoice* to resend |
| … is not supported by {provider} | The button you pressed is not offered by this ASP (e.g. PDF download) | Nothing to fix; use the ASP portal for that document |
| Failed to fetch document XML/PDF: XML not generated for document … | Documents are produced after reporting; not ready yet | Wait for the scheduler or try again later |

If a status seems stuck at *pending* for more than an hour: open the invoice and press *Get Document Status*. If the dialog shows an error, check Error Log and the ASP portal, and confirm that the webhook URL is reachable from the internet (test from a phone on mobile data, not from the office network).

# UAE E-Invoicing for ERPNext — UI Testing Guide

A step-by-step test script for implementers, QA and partners. Every test is done through the ERPNext UI (no console), with the data to enter and the result to expect. Run the whole script once per ASP you go live with, on the ASP's **sandbox**, and again after every app update. Section 9 covers testing an ASP you have just added.

Record results in a copy of the table in section 10. Where a test says "see Error Log", open *Error Log* in the awesome bar and look at the newest entry.

Test data used below (adjust to what your ASP sandbox accepts):

| Item | Value |
| --- | --- |
| Company | `Test Trading LLC`, TRN `100123456700003`, address in Dubai |
| Customer (B2B) | `Al Noor General Trading`, TRN `100987654300003`, Peppol ID `0235:1009876543`, Trade licence `CN-1234567`, address in Abu Dhabi |
| Customer (B2C) | `Walk-in Customer`, *Is B2C Customer* ticked, no TRN |
| Supplier | `Gulf Supplies FZE`, TRN `100555666700003`, Peppol ID `0235:1005556667`, address in Sharjah |
| Items | `Laptop` (Goods, HS 8471.30, AED 3,000) · `Installation Service` (Services, SAC 9987, AED 500) |
| Tax template | `UAE VAT 5%` (Sales Taxes and Charges Template, 5% on net total) |

---

## 1. Installation and setup

| # | Test | Steps | Expected |
| --- | --- | --- | --- |
| 1.1 | App installed | Awesome bar → type *UAE E-Invoice Integration* | The workspace opens with the *Detailed Dashboard* shortcut and the two status reports |
| 1.2 | Custom fields present | Open any Sales Invoice | A *UAE E-Invoicing* section exists with *UAE E-Invoice Status*, *Reporting Status*, *Document ID*, *VAT Category*, *Invoice Transaction Type Code*, *Credit Note Reason Code* |
| 1.3 | Scheduler on | *System Settings* or `bench --site <site> scheduler status` | Scheduler is enabled (needed for 5-minute status sync) |
| 1.4 | Company without provider is blocked | Company: tick *UAE E-invoice Enabled*, leave *Accredited Service Providers* empty. Create and submit a Sales Invoice | Submit blocked: "Select an Accredited Service Provider on Test Trading LLC before submitting e-invoices" |
| 1.5 | Unsupported provider is refused | Company: choose a provider that has no adapter (e.g. *BDO Digital Solutions FZ-LLC*). E-Invoice Provider Settings → New with that provider → Save | Save refused: "No adapter is registered for provider 'BDO Digital Solutions FZ-LLC'. Providers with an adapter: Flick Network L.L.C, Marmin AI Software Design LLC, Suntech Business Solutions DMCC" |
| 1.6 | Settings missing is blocked | Company: choose your real ASP; no Provider Settings yet. Submit a Sales Invoice | Submit blocked: "No enabled E-Invoice Provider Settings found for … under Test Trading LLC" |
| 1.7 | Create Provider Settings | E-Invoice Provider Settings → New: Company, Provider (same as Company), Enabled, credentials, Base URL (sandbox), Participant ID → Save | Row saves; *Webhook URL* is filled automatically; *Last Test Status* = Never |
| 1.8 | Duplicate row refused | Create a second row for the same Company + Provider | Save refused: "An E-Invoice Provider Settings row already exists for …" |
| 1.9 | Verify Token (good) | On the settings row: *E-Invoicing → Verify Token* | *Verify Result* dialog with the ASP's response; *Last Test Status* = Passed, *Last Test On* = now (Marmin only fills *Last Test Response*) |
| 1.10 | Verify Token (bad) | Change *Client Secret* to a wrong value, Save, *Verify Token* | *Last Test Status* = Failed; *Last Test Response* shows the ASP's 401/403 body. Restore the secret afterwards |
| 1.11 | Trailing space | Append a space to *Client ID*, Save, *Verify Token* | Fails with an empty 401 body (documented gotcha). Remove the space |
| 1.12 | Get Participant Details | *E-Invoicing → Get Participant Details* | *Participant Details* dialog shows your company as registered at the ASP; *Last Participant Response* filled |
| 1.13 | Get Access Token | *E-Invoicing → Get Access Token* | Green message "Access token fetched…"; *Token Expires At* is about 55 minutes ahead |
| 1.14 | Subscribe Webhook (Flick) | *E-Invoicing → Subscribe Webhook* | *Webhook Subscribed* dialog; *Webhook UUID* filled; *Get Subscription* shows the listener URL |
| 1.15 | Webhook buttons (Marmin, Suntech) | *E-Invoicing → Subscribe Webhook* | "Webhook subscription is not supported by …" message, no error trace |
| 1.16 | Webhook configured in portal (Marmin, Suntech) | Paste *Webhook URL* and secret into the ASP portal; use the portal's "send test" if offered | A row appears in *UAE E-Invoice Webhook Logs* |
| 1.17 | Webhook reachable from outside | From a phone on mobile data, open the *Webhook URL* in a browser | A Frappe JSON response (an error about method/POST is fine); not a timeout |

## 2. Master data validation

| # | Test | Steps | Expected |
| --- | --- | --- | --- |
| 2.1 | Address without country | Customer address with *Country* empty; submit a Sales Invoice for that customer | "Address … has no recognised Country." Invoice stays submitted in ERPNext with status *Not Submitted*; fix the address and use *Send Invoice* |
| 2.2 | UAE address without emirate | *Country* = United Arab Emirates, *Emirate* empty | "Address … needs a recognised UAE emirate (Abu Dhabi, Dubai, …)" |
| 2.3 | Foreign address | *Country* = India, *Emirate* empty, *State* = Kerala | Submission goes through; subdivision = Kerala |
| 2.4 | Missing Peppol ID (Marmin) | Customer with *Peppol ID* empty | "Customer … has no PEPPOL ID (Participant ID) set" |
| 2.5 | Trade licence fields | Customer: *Legal Registration Identifier Type* = Commercial/Trade license | *Trade License Number* (and *Legal Registration Authority* on Supplier) appear; blank them and submit (Marmin) → clear message naming the missing field |
| 2.6 | VAT Category empty | Sales Invoice with *VAT Category* blank | Submission refused with "Invalid VAT Category" or the ASP's validation error, never a Python traceback |
| 2.7 | Item type codes | Item *Laptop*: Item Type Codes = Goods | *HS Code* appears, *SAC code* hidden; Services shows the opposite; Both shows both |

## 3. Sales Invoice — standard flow

| # | Test | Steps | Expected |
| --- | --- | --- | --- |
| 3.1 | Tooltips | Open a new Sales Invoice; hover the info icon next to *VAT Category* | Tooltip text appears with "Click to learn more →"; clicking opens the field reference page |
| 3.2 | Standard-rated B2B invoice | Customer Al Noor, item Laptop ×2, taxes UAE VAT 5%, VAT Category *S - Standard rated* → Submit | *E-Invoice Response* dialog with HTTP 200/201. After closing: UAE E-Invoice Status = Success, Reporting Status = pending (or reported), Document ID filled, badge *Pending* or *Reported* |
| 3.3 | Success log | Open *UAE E-invoicing success log* list | Newest row has this invoice number and document ID |
| 3.4 | Attachments | Look at the invoice's attachments (Flick, Marmin: immediately; Suntech: within 5 min) | `Submitted-XML-file <name>.xml` and `Submitted-PDF-file <name>.pdf`; *Document Xml* / *Document PDF* fields filled |
| 3.5 | Get Document Status | On the invoice: *Get Document Status* | *Document Status* dialog with HTTP 200, Document ID, Status; indicator green when reported |
| 3.6 | Status sync by scheduler | Submit an invoice; do not press any button; wait 6 minutes; reload | Reporting Status moved from pending to reported; XML/PDF attached (Suntech) |
| 3.7 | Status by webhook | With webhooks configured, submit an invoice and watch *UAE E-Invoice Webhook Logs* | A log row with the invoice's Document ID arrives within a minute; Reporting Status updates without waiting for the scheduler |
| 3.8 | Get Document buttons hidden | After 3.4 | *Get Document → XML* and *PDF* no longer shown (files already attached) |
| 3.9 | Zero-rated | VAT Category *Z - Zero rated*, tax template 0% | Accepted; XML shows category Z |
| 3.10 | Exempt | VAT Category *E - Exempt from tax* → *VAT Exemption Reason Code* appears; pick DL8.46.2 | Accepted; reason code in XML |
| 3.11 | Reverse charge | VAT Category *AE* → *RCM Nature Code* appears; pick DL8.48.8.2 | Accepted |
| 3.12 | Per-line override | Item Tax Template with VAT Category *Z* on one line of an otherwise *S* invoice | Accepted; that line is Z, the others S (check the XML) |
| 3.13 | B2C customer | Customer Walk-in (Is B2C Customer) | Accepted without a buyer TRN |
| 3.14 | Transaction type | *Invoice Transaction Type Code* = `XXXXXXX1 : Export transaction`, foreign customer | Accepted; export flag set |
| 3.15 | Summary invoice | *Frequency Billing Code List* = MTH | Accepted with invoice period |
| 3.16 | Foreign currency | Invoice in USD with exchange rate | Accepted; totals and AED tax amount present (check XML) |
| 3.17 | Discount | Invoice-level discount 10% | Accepted; totals in the ASP portal equal ERPNext's grand total |
| 3.18 | Multiple tax rows | Add a non-VAT charge row (e.g. shipping, Actual) | Accepted; VAT amount equals ERPNext's VAT, not the sum of all charges |
| 3.19 | Resend after failure | Force a failure (2.1), fix the address, *UAE E-Invoice → Send Invoice* | Success; status fields update; a new success log row |
| 3.20 | Cancel | Cancel a reported invoice | ERPNext cancels; dashboard *Cancelled* count +1 (cancellation is not transmitted to the FTA — issue a credit note instead) |

## 4. Credit notes

| # | Test | Steps | Expected |
| --- | --- | --- | --- |
| 4.1 | Return from invoice | On a reported invoice: *Create → Return / Credit Note*; *Credit Note Reason Code* = DL8.61.1.B-Amendment → Submit | Accepted as type 381 with billing reference to the original; positive amounts in the ASP portal |
| 4.2 | Reason code required | Return without a reason code | Clear message from the app or ASP, no traceback |
| 4.3 | Partial return | Return 1 of 2 laptops | Accepted; amounts half of the original |
| 4.4 | Credit note without original | Company: tick *Allow credit-note without original invoice in the system*. New Sales Invoice, *Is Return*, *Return Against For UAE E-invoice* = `INV-OLD-001`, *Skip Validation for Credit Note* ticked, negative qty | ERPNext accepts the return (no "returned items" validation error); ASP accepts with the external reference |

## 5. Bulk submission

| # | Test | Steps | Expected |
| --- | --- | --- | --- |
| 5.1 | Nothing selected | Sales Invoice list → *Actions → Send Invoices to FTA Submission* | "Please select at least one Sales Invoice." |
| 5.2 | One selected | Select one invoice | "Please select more than one invoice." |
| 5.3 | Mixed selection | Select 3: one draft, one already *Success*, one *Not Submitted* | Draft is submitted and sent; *Success* one listed under *Skipped (Already Submitted)*; the third under *Submitted Successfully* or *Failed* with its reason |
| 5.4 | Purchase list | Same on the Purchase Invoice list | Same behaviour (result dialog shows Skipped / Failed sections) |

## 6. Purchase Invoices and incoming invoices

| # | Test | Steps | Expected |
| --- | --- | --- | --- |
| 6.1 | Self-billed invoice | Supplier Gulf Supplies, item Laptop, VAT Category S, *Payment Means Codes* = 30, (Flick: tick *Submit To FTA*) → Submit | *E-Invoice Response* 200/201; statuses and Document ID filled; type 389 in the ASP portal |
| 6.2 | Flick without Submit To FTA | Flick only: leave *Submit To FTA* unticked | "Submit to FTA not Enabled" message; invoice status *Not Submitted* |
| 6.3 | Debit note | *Create → Return / Debit Note* on 6.1 → Submit | Accepted as self-billed credit note (396) |
| 6.4 | Incoming invoice arrives | Ask the ASP sandbox (or a partner sandbox) to send an invoice to your Peppol ID | A row in *UAE Incoming Invoices* with status *Not Submitted* and the JSON attached; a webhook log row |
| 6.5 | Import dialog, none | Purchase Invoice → New → *Get Items From → Get FTA Incoming Invoices* when there are no *Not Submitted* rows | "No FTA Incoming Invoices with status "Not Submitted" found." |
| 6.6 | Import, nothing ticked | Same with rows present; click *Import Selected* without ticking | "Please select at least one invoice." |
| 6.7 | Import one | Tick one row → *Import Selected* | *Import Complete* dialog with a link; the new draft Purchase Invoice opens with supplier, lines, VAT; incoming row status = Submitted |
| 6.8 | Import, unknown supplier | Incoming invoice from a supplier not in ERPNext | Listed under *Failed* with "Supplier not found: …"; create the supplier (Tax ID = the VAT number) and import again |
| 6.9 | Match & Approve | On the imported draft: *Match & Approve* | Green headline "✅ Matched & Approved by FTA — Document ID: …" |
| 6.10 | Match & Approve, no ID | On a manual Purchase Invoice without Document ID | "This Purchase Invoice has no FTA Document ID to match against." |

## 7. Dashboard, reports, logs

| # | Test | Steps | Expected |
| --- | --- | --- | --- |
| 7.1 | Dashboard counts | Open *UAE E-Invoice Dashboard* after sections 3–6 | Counts under Reported, Success, Failed, Not Submitted, Cancelled match the invoices you created; chart shows Reported vs Failed; last-20 tables list them |
| 7.2 | Sales status report | *UAE E-Invoice Sales Status Report*, date range covering today, Status blank | All test invoices with Reporting Status and UAE Status columns |
| 7.3 | Report filter | Status = `reported` / `failed` / `Not Submitted` / `Cancelled` | Only matching rows |
| 7.4 | Purchase status report | Same for purchases | Same |
| 7.5 | Webhook logs | *UAE E-Invoice Webhook Logs* list | One row per delivery with Event Type, Document ID, Reporting Status, raw body |
| 7.6 | Scheduler log refresh (Flick) | Wait 2 minutes after a webhook; open the settings row | *Last Webhook Logs Response* updated |
| 7.7 | Permissions | Log in as an Accounts User (not System Manager) | Can submit invoices and run the reports; cannot open E-Invoice Provider Settings; the logs doctypes are hidden |

## 8. Negative and resilience tests

| # | Test | Steps | Expected |
| --- | --- | --- | --- |
| 8.1 | ASP unreachable | Set *Base URL Override* to `https://10.255.255.1` (non-routable), submit an invoice | Submit completes in ERPNext after the timeout; "E-Invoice processing failed: …"; status *Not Submitted*; Error Log entry *E-Invoice Submit Error*. Clear the override |
| 8.2 | Wrong credentials mid-flight | Break the secret, submit | ASP 401 in *E-Invoice Response*; status *Not Submitted*; *Send Invoice* available after fixing |
| 8.3 | Disabled row | Untick *Enabled* on the settings row, submit | Blocked: "No enabled E-Invoice Provider Settings found…" |
| 8.4 | Provider switch | Change Company to another ASP that has its own enabled settings row; submit | Goes to the new ASP (check *Submit Response* for its format); old invoices keep their statuses |
| 8.5 | Unsupported button | On an ASP without PDF download (if any), *Get Document → PDF* | "PDF download is not supported by …", no traceback |
| 8.6 | Webhook with bad signature (Marmin, Suntech) | POST a dummy body to the listener URL with no signature header (e.g. from a REST client) | 401 "signature verification failed"; Error Log *… Webhook Signature Mismatch* / *Suntech Webhook Auth Failed*; no invoice changed |
| 8.7 | Scheduler catch-up | Disable webhooks temporarily (remove the portal entry); submit; wait 6 minutes | Status still reaches *reported* via the scheduler |

## 9. Testing a newly added ASP

Run this after a developer has added `providers/<asp>/adapter.py` and the `hooks.py` line (see the [Developer Guide](DEVELOPER_GUIDE.md)).

| # | Test | Steps | Expected |
| --- | --- | --- | --- |
| 9.1 | Registry | Company: choose the new provider. E-Invoice Provider Settings → New for it → Save | Saves (if it refuses with "No adapter is registered", the `hooks.py` key does not match the dropdown text character for character) |
| 9.2 | Option present in both lists | Check the Provider dropdown on the settings row and *Accredited Service Providers* on Company | The new name appears, spelled identically, in both |
| 9.3 | Verify Token | 1.9–1.11 | Same behaviour |
| 9.4 | Unimplemented optional methods | Press every *E-Invoicing* button and *Get Document → XML/PDF* | Either works or shows "… is not supported by <provider>"; never a traceback |
| 9.5 | Four document types | 3.2, 4.1, 6.1, 6.3 | All four accepted by the ASP sandbox; Document ID stored each time |
| 9.6 | Status | 3.5, 3.6 | *Get Document Status* and the scheduler both move the status; `FINAL_REPORTING_STATUSES` honoured if the ASP uses other words |
| 9.7 | Documents | 3.4 | XML and PDF attach (or the adapter sets `AUTO_FETCH_DOCUMENTS_ON_SUBMIT = False` and they attach after reporting) |
| 9.8 | Webhook | 3.7, 8.6 | Listener verifies the ASP's signature; a bad signature is rejected; logs written; status updated |
| 9.9 | Incoming import | 6.4–6.7 | `parse_incoming_invoice` produces a draft Purchase Invoice with correct supplier, lines, VAT |
| 9.10 | Shared layer | Developer review: `grep -n "abu dhabi\|AUH\|split(\" - \")" providers/<asp>/adapter.py` | No re-declared emirate / VAT / UOM tables; the adapter imports them from `providers/pint.py` |
| 9.11 | Timeouts | Developer review: `grep -c "timeout=" providers/<asp>/adapter.py` vs number of `requests.` calls | Every HTTP call has a timeout |
| 9.12 | Regression on other ASPs | Repeat 3.2 on an existing ASP | Unchanged |

## 10. Result sheet

Copy into a spreadsheet or the project tracker; one sheet per ASP and app version.

| Test # | ASP | App commit | Tester | Date | Result (Pass / Fail / N/A) | Notes / Error Log title |
| --- | --- | --- | --- | --- | --- | --- |
| 1.1 | | | | | | |
| … | | | | | | |

## Known behaviour to be aware of while testing

These are current behaviours of the app, not test failures. They are tracked for change:

- The bulk *Send Invoices to FTA Submission* action requires at least two selected invoices; for one, use the *Send Invoice* button on the form.
- The dashboard cards *Reported From FTA* and *Success From ASP* open the status report without a usable pre-set filter; set the Status filter by hand.
- The status reports' *Status* filter defaults to a value that returns nothing; clear it or pick a value.
- *Match & Approve* confirms that an incoming record with the same Document ID exists; it does not query the FTA.
- Cancelling an invoice in ERPNext does not send anything to the FTA; issue a credit note.
- *Submit To FTA* on Purchase Invoice is only enforced by the Flick adapter.

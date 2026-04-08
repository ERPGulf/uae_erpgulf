## UAE E‑Invoicing Integration

This repository provides an ERPNext / Frappe-based implementation for UAE E‑Invoicing, aligned with the upcoming UAE Federal Tax Authority (FTA) e‑invoicing framework and UBL 2.1 standards.

The solution focuses on:

Generating UAE‑compliant invoice data (UBL XML‑ready)

Enforcing VAT, HS/SAC, and legal validation rules

Preparing invoices for future FTA clearance & reporting workflows

⚠️ Note: As of now, UAE e‑invoicing is in a phased rollout. This implementation is designed to be future‑proof, configurable, and aligned with published FTA and PEPPOL‑style standards.

---

### ✨ Features

✅ Sales Invoice & Credit Note support

✅ VAT category & tax breakdown handling

✅ HS Code (Goods) & SAC Code (Services) validation

✅ Invoice Transaction Type Codes (Standard, Credit, Debit, Deemed Supply, etc.)

✅ Payment Means Codes (Cash, Card, Bank Transfer, etc.)

✅ Legal Entity & Registration Identifier handling

✅ Customer & Supplier identification blocks

✅ Structured JSON → XML mapping (UBL 2.1 compatible)

✅ Designed for ERPNext v16+

---

## 📂 Supported Document Types

### Sales (Accounts Receivable)

* **380** – Commercial Invoice
* **480** – Out of Scope Invoice
* **381** – Credit Note (Taxable)
* **81** – Credit Note (Out of Scope)

### Purchase (Accounts Payable)

* **389** – Self-Billed Invoice
* **361** – Self-Billed Credit Note

---


#### 🧪 Validation Highlights

✔ Quantity must be greater than zero

✔ Mandatory tax category present

✔ Correct invoice reference for Credit Notes

✔ Legal identifiers validated before submission

✔ Decimal precision handled using ROUND_HALF_UP

---


### 📦 Installation
bench get-app uae_erpgulf https://github.com/your-org/uae_erpgulf.git
bench --site yoursite.local install-app uae_erpgulf

---


## ⚙️ Configuration

### 1. Enable E-Invoicing

Go to:

Company → UAE E-Invoicing

Enable:
☑ UAE E-Invoice Enabled


### 2. API Setup

Provide the following:

* Base URL
* Participant ID
* X-Flick-Auth-Key

---

### 3. Authentication

* Verify Token
* Generate OAuth2 Access Token
* Store and reuse token until expiry

---

### 4. Fetch Participant Details

* Retrieves VAT/TRN and business details
* Ensures proper registration

---

## 🔄 Invoice Flow

1. User creates Sales Invoice
2. System validates configuration
3. Invoice payload is generated
4. Authentication using OAuth2
5. Invoice sent to API (Flick)
6. Forwarded to FTA
7. Response stored in ERPNext

---

## 🔔 Webhooks (Real-Time Updates)

The system listens for:

* Invoice Submitted
* Invoice Validated
* Invoice Accepted
* Invoice Rejected
* Invoice Delivered

---

## 🛠️ Tech Stack

* ERPNext / Frappe
* REST APIs
* OAuth2 Authentication
* Webhooks


---

### 📤 Output Formats

✅ Structured Invoice JSON

⚠️ Note: Only the JSON generation layer is currently implemented.  FTA submission are not yet completed and will be added in future phases.

---

## 📌 Notes

* Ensure VAT and TRN details are correct
* Follow structured format strictly
* Keep API credentials secure

---

## 📈 Benefits

* Improved VAT compliance
* Reduced manual work
* Faster invoice processing
* Better accuracy & transparency

---

### 🧠 References

UAE Federal Tax Authority (FTA)

UBL 2.1 Specification

PEPPOL BIS Billing 3.0


---




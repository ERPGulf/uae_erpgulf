## UAE E‑Invoicing Integration

This repository provides an ERPNext / Frappe-based implementation for UAE E‑Invoicing, aligned with the upcoming UAE Federal Tax Authority (FTA) e‑invoicing framework and UBL 2.1 standards.

The solution focuses on:

Generating UAE‑compliant invoice data (UBL XML‑ready)

Enforcing VAT, HS/SAC, and legal validation rules

Preparing invoices for future FTA clearance & reporting workflows

⚠️ Note: As of now, UAE e‑invoicing is in a phased rollout. This implementation is designed to be future‑proof, configurable, and aligned with published FTA and PEPPOL‑style standards.

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


#### 🧪 Validation Highlights

✔ Quantity must be greater than zero

✔ Mandatory tax category present

✔ Correct invoice reference for Credit Notes

✔ Legal identifiers validated before submission

✔ Decimal precision handled using ROUND_HALF_UP

### 📦 Installation
bench get-app uae_erpgulf https://github.com/your-org/uae_erpgulf.git
bench --site yoursite.local install-app uae_erpgulf

### ⚙️ Configuration

Enable UAE E‑Invoicing in Company Settings

Configure:

VAT Registration Number (TRN)

Legal Entity Name & Address

Default VAT Category

Set Item‑level:

HS Code / SAC Code

Item Tax Templates (recommended)

### 📤 Output Formats

✅ Structured Invoice JSON

⚠️ Note: Only the JSON generation layer is currently implemented.  FTA submission are not yet completed and will be added in future phases.




### 🧠 References

UAE Federal Tax Authority (FTA)

UBL 2.1 Specification

PEPPOL BIS Billing 3.0
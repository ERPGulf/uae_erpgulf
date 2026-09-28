"""Backward-compatibility shim."""
from uae_erpgulf.uae_erpgulf.providers.flick.purchase_json import *  # noqa: F401,F403
from uae_erpgulf.uae_erpgulf.providers.flick.purchase_json import (  # noqa: F401
    build_uae_invoice_json,
    save_and_attach_invoice_json,
    send_invoice_json,
)

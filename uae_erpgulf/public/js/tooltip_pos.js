frappe.ui.form.on('Purchase Invoice', {
    refresh(frm) {
        const fieldDescriptions = {
            'custom_vat_category': {
                text: 'Defines the VAT treatment for the supply. Select the category that matches the nature of the goods or service being invoiced.',
                url: 'https://docs.claudion.com/Claudion-Docs/Field%20Reference'
            },
            'custom_frequency_billing_code_list': {
                text: 'Sets the billing cycle for recurring or continuous supply invoices. If none of the standard codes apply, select OTH and fill in the Invoice Note field. When OTH is selected, the Invoice Note field is mandatory.',
                url: 'https://docs.claudion.com/Claudion-Docs/Field%20Reference'
            },
            'custom_invoice_transaction_type_code': {
                text: "A flag-based code where each position activates a special transaction type. Set a position to '1' to enable it; leave as 'X' if not applicable. Multiple flags can be combined.",
                url: 'https://docs.claudion.com/Claudion-Docs/Field%20Reference'
            },
            'custom_payment_means_codes': {
                text: 'Defines the payment method used for the transaction.',
                url: 'https://docs.claudion.com/Claudion-Docs/Field%20Reference'
            },
            'custom_credit_note_reason_code': {
                text: 'Specifies the reason for issuing the credit note. Select the appropriate code that reflects the purpose of the credit note (e.g., cancellation, discount, return of goods).',
                url: 'https://docs.claudion.com/Claudion-Docs/Field%20Reference'
            }
        };

        setTimeout(() => {
            Object.entries(fieldDescriptions).forEach(([fieldname, { text, url }]) => {
                if (!frm.fields_dict[fieldname]) return;

                const field = frm.fields_dict[fieldname];

                frm.set_df_property(fieldname, 'description', '');
                frm.refresh_field(fieldname);

                const $wrapper = $(field.wrapper);
                $wrapper.find('.custom-info-icon').remove();

                let $label = $wrapper.find('label.control-label');
                if (!$label.length) $label = $wrapper.find('.control-label');
                if (!$label.length) $label = $wrapper.find('label');

                if ($label.length) {
                    const $icon = $(`
                        <span class="custom-info-icon"
                              style="margin-left:6px; 
                                     color:#8d99a6; 
                                     cursor:pointer; 
                                     display:inline-flex; 
                                     vertical-align:middle;">
                            <svg xmlns="http://www.w3.org/2000/svg" 
                                 width="14" height="14" 
                                 viewBox="0 0 24 24" 
                                 fill="none" 
                                 stroke="currentColor" 
                                 stroke-width="2"
                                 stroke-linecap="round"
                                 stroke-linejoin="round">
                                <circle cx="12" cy="12" r="10"/>
                                <line x1="12" y1="16" x2="12" y2="12"/>
                                <line x1="12" y1="8" x2="12.01" y2="8"/>
                            </svg>
                        </span>
                    `);

                    $label.append($icon);

                    // Method 1: Bootstrap tooltip (primary)
                    let tooltipWorking = false;
                    try {
                        $icon.tooltip({
                            title: `${text}<br><br><u>Click to learn more →</u>`,
                            placement: 'top',
                            trigger: 'hover',
                            container: 'body',
                            html: true
                        });
                        tooltipWorking = true;
                    } catch (e) {
                        console.log('Bootstrap tooltip failed, using Frappe alert fallback');
                    }

                    // COMBINED mouseenter — color highlight + Frappe alert fallback together
                    $icon.on('mouseenter', function () {
                        $(this).css('color', '#1a73e8');

                        // Method 2: Frappe alert fallback (only if Bootstrap tooltip not working)
                        if (!tooltipWorking) {
                            frappe.show_alert({
                                message: `<b>Info:</b> ${text}<br><a href="${url}" target="_blank" 
                                    style="color:#1a73e8;">
                                    Learn more →
                                </a>`,
                                indicator: 'blue'
                            }, 8);
                        }

                    }).on('mouseleave', function () {
                        $(this).css('color', '#8d99a6');
                    });

                    // Click opens the documentation URL
                    $icon.on('click', function (e) {
                        e.stopPropagation();
                        window.open(url, '_blank');
                    });
                }
            });
        }, 500);
    }
});
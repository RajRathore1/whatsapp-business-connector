{
    'name': 'WhatsApp Business Connector',
    'version': '19.0.1.0.0',
    'category': 'Marketing/WhatsApp',
    'summary': 'Send CRM leads and Sales quotations via WhatsApp Business Cloud API',
    'description': """
WhatsApp Business Connector for Odoo 19
========================================

Integrate WhatsApp Business Cloud API directly into your CRM and Sales workflows.

Features:
---------
- Send quotations via WhatsApp from CRM leads and Sales orders
- Attach quotation PDF and/or portal link in the message
- WhatsApp message template management with Meta sync and approval tracking
- Real-time delivery and read status tracking in the chatter
- Webhook support for incoming status updates from Meta
- Works with Odoo Community and Enterprise v19
    """,
    'author': 'DigiMonk Technologies',
    'website': 'https://digimonk.in',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'sale_management', 'crm'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/whatsapp_template_views.xml',
        'views/whatsapp_message_views.xml',
        'wizard/whatsapp_composer_views.xml',
        'views/sale_order_views.xml',
        'views/crm_lead_views.xml',
        'views/menus.xml',
    ],
    'images': ['static/description/banner.png', 'static/description/icon.png'],
    'price': 0,
    'currency': 'USD',
    'installable': True,
    'application': True,
    'auto_install': False,
}

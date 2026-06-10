from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    whatsapp_access_token = fields.Char(
        string='Meta Access Token',
        config_parameter='tripfactory_whatsapp.access_token',
    )
    whatsapp_phone_number_id = fields.Char(
        string='Phone Number ID',
        config_parameter='tripfactory_whatsapp.phone_number_id',
    )
    whatsapp_waba_id = fields.Char(
        string='WhatsApp Business Account ID',
        config_parameter='tripfactory_whatsapp.waba_id',
    )
    whatsapp_app_id = fields.Char(
        string='App ID',
        config_parameter='tripfactory_whatsapp.app_id',
    )
    whatsapp_app_secret = fields.Char(
        string='App Secret',
        config_parameter='tripfactory_whatsapp.app_secret',
    )
    whatsapp_webhook_verify_token = fields.Char(
        string='Webhook Verify Token',
        config_parameter='tripfactory_whatsapp.webhook_verify_token',
    )
    whatsapp_default_template_id = fields.Many2one(
        comodel_name='whatsapp.template',
        string='Default Quotation Template',
        domain=[('status', '=', 'approved')],
    )

    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        tmpl_id = ICP.get_param('tripfactory_whatsapp.default_template_id', '')
        try:
            res['whatsapp_default_template_id'] = int(tmpl_id) if tmpl_id else False
        except (ValueError, TypeError):
            res['whatsapp_default_template_id'] = False
        return res

    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(
            'tripfactory_whatsapp.default_template_id',
            str(self.whatsapp_default_template_id.id) if self.whatsapp_default_template_id else '',
        )

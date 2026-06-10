from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    whatsapp_message_ids = fields.One2many('whatsapp.message', 'invoice_id', string='WhatsApp Messages')
    whatsapp_message_count = fields.Integer(compute='_compute_whatsapp_count')

    @api.depends('whatsapp_message_ids')
    def _compute_whatsapp_count(self):
        for rec in self:
            rec.whatsapp_message_count = len(rec.whatsapp_message_ids)

    def action_send_whatsapp(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send via WhatsApp',
            'res_model': 'whatsapp.composer',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_res_model': self._name, 'default_res_id': self.id},
        }

    def action_view_whatsapp_messages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'WhatsApp Messages',
            'res_model': 'whatsapp.message',
            'view_mode': 'list,form',
            'domain': [('invoice_id', '=', self.id)],
        }


class WhatsAppMessageAccount(models.Model):
    _inherit = 'whatsapp.message'

    invoice_id = fields.Many2one('account.move', string='Invoice/Bill', index=True)


class WhatsAppComposerAccount(models.TransientModel):
    _inherit = 'whatsapp.composer'

    def _prefill_account_move(self, res, record):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        partner = record.partner_id
        res['partner_id'] = partner.id if partner else False
        res['var_customer_name'] = partner.name if partner else ''
        res['var_quotation_number'] = record.name or ''
        amount = getattr(record, 'amount_residual', record.amount_total)
        res['var_amount'] = self._format_amount(amount, record.currency_id)
        due = record.invoice_date_due
        res['var_due_date'] = due.strftime('%d %b %Y') if due else ''
        res['var_quotation_url'] = self._get_portal_url(record, base_url)
        phone = getattr(partner, 'mobile', None) or (partner.phone if partner else '') or ''
        res['phone'] = self._normalize_phone(phone)

    def _get_relation_field_vals(self):
        vals = super()._get_relation_field_vals()
        vals['account.move'] = 'invoice_id'
        return vals

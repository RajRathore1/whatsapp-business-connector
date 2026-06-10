from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    whatsapp_message_ids = fields.One2many('whatsapp.message', 'purchase_order_id', string='WhatsApp Messages')
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
            'domain': [('purchase_order_id', '=', self.id)],
        }


class WhatsAppMessagePurchase(models.Model):
    _inherit = 'whatsapp.message'

    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', index=True)


class WhatsAppComposerPurchase(models.TransientModel):
    _inherit = 'whatsapp.composer'

    def _prefill_purchase_order(self, res, record):
        partner = record.partner_id
        res['partner_id'] = partner.id if partner else False
        res['var_customer_name'] = partner.name if partner else ''
        res['var_quotation_number'] = record.name or ''
        res['var_ref'] = record.name or ''
        res['var_amount'] = self._format_amount(record.amount_total, record.currency_id)
        date_order = record.date_order
        res['var_due_date'] = date_order.strftime('%d %b %Y') if date_order else ''
        phone = getattr(partner, 'mobile', None) or (partner.phone if partner else '') or ''
        res['phone'] = self._normalize_phone(phone)

    def _get_relation_field_vals(self):
        vals = super()._get_relation_field_vals()
        vals['purchase.order'] = 'purchase_order_id'
        return vals

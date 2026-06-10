from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    whatsapp_message_ids = fields.One2many(
        comodel_name='whatsapp.message',
        inverse_name='invoice_id',
        string='WhatsApp Messages',
    )
    whatsapp_message_count = fields.Integer(
        string='WhatsApp Messages',
        compute='_compute_whatsapp_count',
    )

    @api.depends('whatsapp_message_ids')
    def _compute_whatsapp_count(self):
        for move in self:
            move.whatsapp_message_count = len(move.whatsapp_message_ids)

    def action_send_whatsapp(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send via WhatsApp',
            'res_model': 'whatsapp.composer',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
            },
        }

    def action_view_whatsapp_messages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'WhatsApp Messages',
            'res_model': 'whatsapp.message',
            'view_mode': 'list,form',
            'domain': [('invoice_id', '=', self.id)],
            'context': {'default_invoice_id': self.id},
        }

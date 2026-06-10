from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    whatsapp_message_ids = fields.One2many(
        comodel_name='whatsapp.message',
        inverse_name='lead_id',
        string='WhatsApp Messages',
    )
    whatsapp_message_count = fields.Integer(
        string='WhatsApp Messages',
        compute='_compute_whatsapp_count',
    )

    @api.depends('whatsapp_message_ids')
    def _compute_whatsapp_count(self):
        for lead in self:
            lead.whatsapp_message_count = len(lead.whatsapp_message_ids)

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
            'domain': [('lead_id', '=', self.id)],
            'context': {'default_lead_id': self.id},
        }

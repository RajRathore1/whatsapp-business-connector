from odoo import api, fields, models


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    whatsapp_message_ids = fields.One2many(
        comodel_name='whatsapp.message',
        inverse_name='calendar_event_id',
        string='WhatsApp Messages',
    )
    whatsapp_message_count = fields.Integer(
        string='WhatsApp Messages',
        compute='_compute_whatsapp_count',
    )

    @api.depends('whatsapp_message_ids')
    def _compute_whatsapp_count(self):
        for event in self:
            event.whatsapp_message_count = len(event.whatsapp_message_ids)

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
            'domain': [('calendar_event_id', '=', self.id)],
            'context': {'default_calendar_event_id': self.id},
        }

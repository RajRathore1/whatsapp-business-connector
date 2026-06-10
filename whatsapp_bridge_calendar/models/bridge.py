from odoo import api, fields, models


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    whatsapp_message_ids = fields.One2many('whatsapp.message', 'calendar_event_id', string='WhatsApp Messages')
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
            'domain': [('calendar_event_id', '=', self.id)],
        }


class WhatsAppMessageCalendar(models.Model):
    _inherit = 'whatsapp.message'

    calendar_event_id = fields.Many2one('calendar.event', string='Appointment', index=True)


class WhatsAppComposerCalendar(models.TransientModel):
    _inherit = 'whatsapp.composer'

    def _prefill_calendar_event(self, res, record):
        organizer = getattr(record, 'user_id', False)
        attendees = getattr(record, 'attendee_ids', False)
        partner = False
        if attendees:
            first = attendees[:1]
            partner = first.partner_id if first else False
        if not partner and organizer:
            partner = organizer.partner_id
        res['partner_id'] = partner.id if partner else False
        res['var_customer_name'] = partner.name if partner else ''
        res['var_destination'] = getattr(record, 'location', '') or ''
        start = record.start
        res['var_travel_date'] = start.strftime('%d %b %Y %H:%M') if start else ''
        res['var_due_date'] = res['var_travel_date']
        res['var_quotation_number'] = record.name or ''
        phone = getattr(partner, 'mobile', None) or (partner.phone if partner else '') or '' if partner else ''
        res['phone'] = self._normalize_phone(phone)

    def _get_relation_field_vals(self):
        vals = super()._get_relation_field_vals()
        vals['calendar.event'] = 'calendar_event_id'
        return vals

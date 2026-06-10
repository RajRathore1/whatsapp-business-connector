import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WhatsAppMessage(models.Model):
    _name = 'whatsapp.message'
    _description = 'WhatsApp Message Log'
    _order = 'sent_at desc, id desc'
    _rec_name = 'phone'

    partner_id = fields.Many2one(comodel_name='res.partner', string='Customer', index=True)
    phone = fields.Char(string='Phone Number', required=True)
    template_id = fields.Many2one(comodel_name='whatsapp.template', string='Template')
    message_body = fields.Text(string='Message Body')

    status = fields.Selection(
        selection=[
            ('queued', 'Queued'),
            ('sent', 'Sent'),
            ('delivered', 'Delivered'),
            ('read', 'Read'),
            ('failed', 'Failed'),
        ],
        string='Status',
        default='queued',
        index=True,
    )
    meta_message_id = fields.Char(string='Meta Message ID', readonly=True, index=True)
    error_message = fields.Text(string='Error Details')

    sent_at = fields.Datetime(string='Sent At')
    delivered_at = fields.Datetime(string='Delivered At')
    read_at = fields.Datetime(string='Read At')

    res_model = fields.Char(string='Related Model', index=True)
    res_id = fields.Integer(string='Related Record ID', index=True)

    sale_order_id = fields.Many2one(comodel_name='sale.order', string='Sale Order', index=True)
    lead_id = fields.Many2one(comodel_name='crm.lead', string='CRM Lead/Opportunity', index=True)
    pdf_attachment_id = fields.Many2one(comodel_name='ir.attachment', string='PDF Attachment')

    status_badge = fields.Char(
        string='Badge',
        compute='_compute_status_badge',
        store=False,
    )

    @api.depends('status')
    def _compute_status_badge(self):
        labels = {
            'queued': '⏳ Queued',
            'sent': '✓ Sent',
            'delivered': '✓✓ Delivered',
            'read': '👁 Read',
            'failed': '✗ Failed',
        }
        for rec in self:
            rec.status_badge = labels.get(rec.status, rec.status)

    def action_view_record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
        }

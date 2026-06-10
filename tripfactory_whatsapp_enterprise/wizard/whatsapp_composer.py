import base64
import json
import logging
import re
import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WhatsAppComposer(models.TransientModel):
    _name = 'whatsapp.composer'
    _description = 'WhatsApp Message Composer'

    res_model = fields.Char(string='Related Model', required=True)
    res_id = fields.Integer(string='Related Record ID', required=True)

    partner_id = fields.Many2one(comodel_name='res.partner', string='Customer')
    phone = fields.Char(string='WhatsApp Number', required=True)

    template_id = fields.Many2one(
        comodel_name='whatsapp.template',
        string='Template',
        domain=[('status', '=', 'approved')],
        required=True,
    )

    @api.onchange('template_id')
    def _onchange_template_id(self):
        """When template changes, try to resolve phone from its phone_field_id config."""
        if not self.template_id or not self.res_model or not self.res_id:
            return
        tmpl = self.template_id
        if tmpl.phone_field_id and tmpl.applies_to == self.res_model:
            try:
                record = self.env[self.res_model].browse(self.res_id)
                phone_val = record[tmpl.phone_field_id.name]
                if phone_val:
                    self.phone = self._normalize_phone(phone_val)
            except Exception:
                pass

    body_preview = fields.Text(
        string='Message Preview',
        compute='_compute_body_preview',
    )

    # Variable fields mapping to template placeholders
    var_customer_name = fields.Char(string='Customer / Vendor Name  {{customer_name}}')
    var_quotation_number = fields.Char(string='Quotation / Invoice / PO Number  {{quotation_number}}')
    var_destination = fields.Char(string='Destination / Location  {{destination}}')
    var_travel_date = fields.Char(string='Travel Date / Event Date  {{travel_date}}')
    var_travellers = fields.Char(string='Travellers  {{travellers}}')
    var_amount = fields.Char(string='Amount  {{amount}}')
    var_quotation_url = fields.Char(string='Portal / Tracking URL  {{quotation_url}}')
    var_due_date = fields.Char(string='Due Date / Delivery Date  {{due_date}}')
    var_ref = fields.Char(string='Reference / Delivery Ref  {{ref}}')

    send_pdf = fields.Boolean(string='Attach Quotation PDF', default=True)
    send_link = fields.Boolean(string='Include Portal Link', default=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        res_model = self._context.get('default_res_model') or res.get('res_model')
        res_id = self._context.get('default_res_id') or res.get('res_id')

        if res_model and res_id:
            try:
                record = self.env[res_model].browse(res_id)
                self._prefill_from_record(res, record, res_model, res_id)
            except Exception as e:
                _logger.warning('Failed to prefill WhatsApp composer: %s', e)

        ICP = self.env['ir.config_parameter'].sudo()
        default_tmpl = ICP.get_param('tripfactory_whatsapp.default_template_id', '')
        if default_tmpl:
            try:
                tmpl = self.env['whatsapp.template'].browse(int(default_tmpl))
                if tmpl.exists() and tmpl.status == 'approved':
                    res.setdefault('template_id', tmpl.id)
            except (ValueError, TypeError):
                pass

        return res

    def _prefill_from_record(self, res, record, res_model, res_id):
        # Dispatch to per-model handler — bridge modules add their own handlers
        handler = getattr(self, '_prefill_' + res_model.replace('.', '_'), None)
        if handler:
            try:
                handler(res, record)
            except Exception as e:
                _logger.warning('WhatsApp prefill failed for %s: %s', res_model, e)

    def _prefill_sale_order(self, res, record):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        partner = record.partner_id
        res['partner_id'] = partner.id if partner else False
        res['var_customer_name'] = partner.name if partner else ''
        res['var_quotation_number'] = record.name or ''
        res['var_amount'] = self._format_amount(record.amount_total, record.currency_id)
        res['phone'] = self._normalize_phone(
            getattr(partner, 'mobile', None) or partner.phone or '' if partner else ''
        )
        res['var_quotation_url'] = self._get_portal_url(record, base_url)

    def _prefill_crm_lead(self, res, record):
        partner = record.partner_id
        res['partner_id'] = partner.id if partner else False
        res['var_customer_name'] = (
            record.partner_name or (partner.name if partner else '') or ''
        )
        phone = (
            getattr(record, 'mobile', None)
            or record.phone
            or (getattr(partner, 'mobile', None) if partner else '')
            or (partner.phone if partner else '')
            or ''
        )
        res['phone'] = self._normalize_phone(phone)

    def _get_relation_field_vals(self):
        # Bridge modules extend this to register their relation fields
        return {
            'sale.order': 'sale_order_id',
            'crm.lead': 'lead_id',
        }

    def _format_amount(self, amount, currency):
        try:
            return f'{amount:,.0f}'
        except Exception:
            return str(amount)

    def _normalize_phone(self, phone):
        if not phone:
            return ''
        cleaned = ''.join(c for c in phone if c.isdigit() or c == '+')
        if cleaned and not cleaned.startswith('+'):
            cleaned = '+91' + cleaned
        return cleaned

    def _get_portal_url(self, record, base_url):
        try:
            if hasattr(record, '_get_share_url'):
                return base_url + record._get_share_url(redirect=False)
        except Exception:
            pass
        try:
            if record.access_token:
                return f'{base_url}/my/orders/{record.id}?access_token={record.access_token}'
        except Exception:
            pass
        return f'{base_url}/web#id={record.id}&model=sale.order'

    @api.depends(
        'template_id',
        'var_customer_name', 'var_quotation_number', 'var_destination',
        'var_travel_date', 'var_travellers', 'var_amount', 'var_quotation_url',
        'var_due_date', 'var_ref',
    )
    def _compute_body_preview(self):
        for rec in self:
            if not rec.template_id:
                rec.body_preview = ''
                continue
            rec.body_preview = rec._render_template_body(rec.template_id.body or '')

    def _render_template_body(self, body):
        var_map = {
            'customer_name': self.var_customer_name or '',   # {{1}}
            'quotation_number': self.var_quotation_number or '',  # {{2}}
            'amount': self.var_amount or '',                 # {{3}}
            'destination': self.var_destination or '',       # {{4}}
            'travel_date': self.var_travel_date or '',       # {{5}}
            'travellers': self.var_travellers or '',         # {{6}}
            'quotation_url': self.var_quotation_url or '',   # {{7}}
            'due_date': self.var_due_date or '',             # {{8}}
            'ref': self.var_ref or '',                       # {{9}}
        }
        ordered = list(var_map.values())

        def replace_named(m):
            return var_map.get(m.group(1), m.group(0))

        def replace_numbered(m):
            idx = int(m.group(1)) - 1
            return ordered[idx] if 0 <= idx < len(ordered) else m.group(0)

        body = re.sub(r'\{\{([a-z_]+)\}\}', replace_named, body)
        body = re.sub(r'\{\{(\d+)\}\}', replace_numbered, body)
        return body

    def _get_api_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param('tripfactory_whatsapp.access_token', '')
        phone_number_id = ICP.get_param('tripfactory_whatsapp.phone_number_id', '')
        if not token or not phone_number_id:
            raise UserError(_(
                'WhatsApp API credentials are not configured. '
                'Please go to Settings → WhatsApp Configuration.'
            ))
        return token, phone_number_id

    def action_send_whatsapp(self):
        self.ensure_one()
        if not self.phone:
            raise UserError(_('Please enter a WhatsApp number for the customer.'))
        if not self.template_id:
            raise UserError(_('Please select an approved WhatsApp template.'))

        token, phone_number_id = self._get_api_config()
        phone = re.sub(r'\D', '', self.phone)  # digits only for Meta API

        # Generate PDF and upload to Meta BEFORE sending the template,
        # so we can embed it as a document header (guaranteed delivery).
        pdf_attachment = False
        pdf_media_id = False
        pdf_warning = False

        if self.send_pdf and self.res_model == 'sale.order':
            pdf_attachment = self._generate_quotation_pdf()
            if pdf_attachment:
                if self.template_id.header_type == 'DOCUMENT':
                    pdf_media_id = self._upload_media_to_meta(pdf_attachment, token, phone_number_id)
                    if not pdf_media_id:
                        pdf_warning = _('PDF upload to Meta failed. The message will be sent without the PDF.')
                else:
                    pdf_warning = _(
                        'PDF not sent: your selected template does not have a Document header. '
                        'To send PDFs with WhatsApp templates, create a new template in Meta Business '
                        'Manager with Header Type = Document, then sync templates here.'
                    )

        components = self._build_api_components(pdf_media_id=pdf_media_id)
        payload = {
            'messaging_product': 'whatsapp',
            'to': phone,
            'type': 'template',
            'template': {
                'name': self.template_id.template_name or self.template_id.name,
                'language': {'code': self.template_id.language},
                'components': components,
            },
        }

        url = f'https://graph.facebook.com/v19.0/{phone_number_id}/messages'
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }

        meta_message_id = False
        error_msg = False
        status = 'failed'

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            msgs = data.get('messages', [])
            if msgs:
                meta_message_id = msgs[0].get('id')
                status = 'sent'
        except requests.HTTPError as e:
            try:
                err_data = e.response.json()
                error_msg = err_data.get('error', {}).get('message', str(e))
            except Exception:
                error_msg = str(e)
        except requests.RequestException as e:
            error_msg = str(e)

        # Log the message
        msg_vals = {
            'partner_id': self.partner_id.id if self.partner_id else False,
            'phone': self.phone,
            'template_id': self.template_id.id,
            'message_body': self.body_preview,
            'status': status,
            'meta_message_id': meta_message_id,
            'error_message': error_msg,
            'sent_at': fields.Datetime.now(),
            'res_model': self.res_model,
            'res_id': self.res_id,
            'pdf_attachment_id': pdf_attachment.id if pdf_attachment else False,
        }
        # Dynamically set the relation field — works for core + bridge modules
        msg_model_fields = self.env['whatsapp.message']._fields
        relation_fields = self._get_relation_field_vals()
        if self.res_model in relation_fields:
            field_name = relation_fields[self.res_model]
            if field_name in msg_model_fields:
                msg_vals[field_name] = self.res_id
        msg_log = self.env['whatsapp.message'].create(msg_vals)

        # Post chatter note on the originating record
        try:
            record = self.env[self.res_model].browse(self.res_id)
            self._post_chatter_note(record, status, error_msg, pdf_warning=pdf_warning, pdf_sent=bool(pdf_media_id))
        except Exception as e:
            _logger.warning('Chatter post failed: %s', e)

        if status == 'failed':
            raise UserError(_('WhatsApp message failed to send: %s') % error_msg)

        if pdf_warning:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Message Sent (PDF Issue)'),
                    'message': _('WhatsApp message sent to %s.\n\n%s') % (self.phone, pdf_warning),
                    'type': 'warning',
                    'sticky': True,
                },
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Message Sent'),
                'message': _('WhatsApp message sent to %s%s.') % (
                    self.phone,
                    _(' with PDF') if pdf_media_id else '',
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def _build_api_components(self, pdf_media_id=None):
        """Build Meta API template components with variable substitutions."""
        body = self.template_id.body or ''
        var_map = {
            'customer_name': self.var_customer_name or '',   # {{1}}
            'quotation_number': self.var_quotation_number or '',  # {{2}}
            'amount': self.var_amount or '',                 # {{3}}
            'destination': self.var_destination or '',       # {{4}}
            'travel_date': self.var_travel_date or '',       # {{5}}
            'travellers': self.var_travellers or '',         # {{6}}
            'quotation_url': self.var_quotation_url or '',   # {{7}}
            'due_date': self.var_due_date or '',             # {{8}}
            'ref': self.var_ref or '',                       # {{9}}
        }
        ordered_vals = list(var_map.values())

        # Detect which variable style is used (named or numbered)
        numbered = sorted(set(re.findall(r'\{\{(\d+)\}\}', body)), key=int)
        named = re.findall(r'\{\{([a-z_]+)\}\}', body)

        body_params = []
        if numbered:
            for n in numbered:
                idx = int(n) - 1
                val = ordered_vals[idx] if idx < len(ordered_vals) else ''
                body_params.append({'type': 'text', 'text': val})
        elif named:
            for name in named:
                body_params.append({'type': 'text', 'text': var_map.get(name, '')})

        components = []

        # Header component
        if pdf_media_id and self.template_id.header_type == 'DOCUMENT':
            # Embed PDF as document header — this is the only reliable way to
            # send a PDF to a customer who hasn't messaged us in the last 24 hours.
            filename = f'Quotation_{self.var_quotation_number or self.res_id}.pdf'
            components.append({
                'type': 'header',
                'parameters': [{'type': 'document', 'document': {'id': pdf_media_id, 'filename': filename}}],
            })
        elif self.template_id.header_type == 'TEXT' and self.template_id.header_text:
            header_vars = re.findall(r'\{\{(\d+)\}\}', self.template_id.header_text)
            if header_vars:
                header_params = [{'type': 'text', 'text': ordered_vals[0] if ordered_vals else ''}]
                components.append({'type': 'header', 'parameters': header_params})

        if body_params:
            components.append({'type': 'body', 'parameters': body_params})

        return components

    def _generate_quotation_pdf(self):
        """Generate the sale order quotation as a PDF attachment."""
        try:
            report = self.env.ref('sale.action_report_saleorder')
            # Odoo 19: _render_qweb_pdf(report_ref, res_ids) — pass report.id as first arg
            if hasattr(report, '_render_qweb_pdf'):
                pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(
                    'sale.action_report_saleorder', [self.res_id]
                )
            elif hasattr(report, '_render'):
                pdf_content, _ = report._render([self.res_id])
            else:
                return False

            name = f'Quotation_{self.var_quotation_number or self.res_id}.pdf'
            return self.env['ir.attachment'].create({
                'name': name,
                'type': 'binary',
                'datas': base64.b64encode(pdf_content).decode('utf-8'),
                'res_model': 'sale.order',
                'res_id': self.res_id,
                'mimetype': 'application/pdf',
            })
        except Exception as e:
            _logger.warning('PDF generation failed: %s', e)
            return False

    def _upload_media_to_meta(self, attachment, token, phone_number_id):
        """Upload a PDF attachment to Meta Media API and return its media_id."""
        try:
            pdf_bytes = base64.b64decode(attachment.datas)
            upload_url = f'https://graph.facebook.com/v19.0/{phone_number_id}/media'
            headers = {'Authorization': f'Bearer {token}'}
            files = {
                'file': (attachment.name, pdf_bytes, 'application/pdf'),
                'type': (None, 'application/pdf'),
                'messaging_product': (None, 'whatsapp'),
            }
            resp = requests.post(upload_url, headers=headers, files=files, timeout=60)
            resp.raise_for_status()
            media_id = resp.json().get('id')
            if media_id:
                _logger.info('PDF uploaded to Meta for template header, media_id=%s', media_id)
                return media_id
            _logger.warning('PDF upload: no media_id in response: %s', resp.text)
            return False
        except requests.HTTPError as e:
            try:
                err_detail = e.response.json().get('error', {}).get('message', str(e))
            except Exception:
                err_detail = str(e)
            _logger.warning('PDF upload to Meta failed: %s', err_detail)
            return False
        except Exception as e:
            _logger.warning('PDF upload to Meta failed: %s', e)
            return False

    def _post_chatter_note(self, record, status, error_msg, pdf_warning=False, pdf_sent=False):
        if not hasattr(record, 'message_post'):
            return
        color = '#25D366' if status == 'sent' else '#dc3545'
        label = '✓ Sent' if status == 'sent' else '✗ Failed'
        lines = [
            f'<div style="border-left:4px solid {color};padding:8px 12px;margin:4px 0;">',
            f'<strong>📱 WhatsApp Message — {label}</strong><br/>',
            f'<small>To: <b>{self.phone}</b></small><br/>',
            f'<small>Template: <b>{self.template_id.name}</b></small>',
        ]
        if pdf_sent:
            lines.append('<br/><small style="color:#25D366;">📎 PDF attached in message header</small>')
        elif pdf_warning:
            lines.append(f'<br/><small style="color:#e67e22;">⚠ {pdf_warning}</small>')
        if self.body_preview:
            preview = self.body_preview.replace('\n', '<br/>')
            lines.append(f'<hr/><small>{preview}</small>')
        if error_msg:
            lines.append(f'<br/><span style="color:#dc3545;">Error: {error_msg}</span>')
        lines.append('</div>')
        record.message_post(
            body=''.join(lines),
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )

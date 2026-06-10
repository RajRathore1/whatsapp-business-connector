import json
import logging
from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsAppWebhookController(http.Controller):

    @http.route('/whatsapp/webhook', type='http', auth='public', methods=['GET'], csrf=False)
    def verify_webhook(self, **kwargs):
        """Handle Meta webhook subscription verification challenge."""
        mode = kwargs.get('hub.mode')
        token = kwargs.get('hub.verify_token')
        challenge = kwargs.get('hub.challenge')

        ICP = request.env['ir.config_parameter'].sudo()
        verify_token = ICP.get_param('tripfactory_whatsapp.webhook_verify_token', '')

        if mode == 'subscribe' and token and token == verify_token:
            _logger.info('WhatsApp webhook verified successfully.')
            return http.Response(challenge, status=200, content_type='text/plain')

        _logger.warning('WhatsApp webhook verification failed. token=%s', token)
        return http.Response('Forbidden', status=403)

    @http.route('/whatsapp/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def receive_webhook(self, **kwargs):
        """Receive and process Meta WhatsApp status/message events."""
        try:
            raw = request.httprequest.get_data(as_text=True)
            data = json.loads(raw)
            _logger.debug('WhatsApp webhook payload: %s', json.dumps(data))
            self._dispatch_events(data)
        except Exception:
            _logger.exception('Error processing WhatsApp webhook payload.')
        return http.Response('OK', status=200)

    def _dispatch_events(self, payload):
        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                contacts = value.get('contacts', [])

                for status_obj in value.get('statuses', []):
                    self._handle_status_update(status_obj)

                for msg_obj in value.get('messages', []):
                    self._handle_incoming_message(msg_obj, contacts)

    def _handle_status_update(self, status_data):
        """Update whatsapp.message record and post chatter note on delivery/read."""
        meta_id = status_data.get('id')
        new_status = status_data.get('status', '').lower()

        if not meta_id or new_status not in ('sent', 'delivered', 'read', 'failed'):
            return

        Message = request.env['whatsapp.message'].sudo()
        msg = Message.search([('meta_message_id', '=', meta_id)], limit=1)
        if not msg:
            _logger.debug('No message found for Meta ID %s', meta_id)
            return

        update_vals = {}
        now = fields.Datetime.now()

        if new_status == 'delivered' and msg.status not in ('delivered', 'read'):
            update_vals = {'status': 'delivered', 'delivered_at': now}
        elif new_status == 'read' and msg.status != 'read':
            update_vals = {'status': 'read', 'read_at': now}
        elif new_status == 'failed' and msg.status not in ('delivered', 'read'):
            errors = status_data.get('errors', [])
            err_text = '; '.join(e.get('message', '') for e in errors)
            update_vals = {'status': 'failed', 'error_message': err_text}

        if update_vals:
            msg.write(update_vals)
            self._post_status_to_chatter(msg, new_status, update_vals.get('error_message'))

    def _post_status_to_chatter(self, msg, status, error_text=None):
        """Post delivery/read receipt to the originating Odoo record chatter."""
        if not msg.res_model or not msg.res_id:
            return
        try:
            record = request.env[msg.res_model].sudo().browse(msg.res_id)
            if not record.exists() or not hasattr(record, 'message_post'):
                return

            labels = {
                'delivered': ('✓✓ Delivered', '#25D366'),
                'read': ('👁 Read', '#007bff'),
                'failed': ('✗ Failed', '#dc3545'),
            }
            label, color = labels.get(status, (status.capitalize(), '#6c757d'))

            body = (
                f'<div style="border-left:4px solid {color};padding:6px 10px;margin:4px 0;">'
                f'<strong>📱 WhatsApp — {label}</strong><br/>'
                f'<small>To: {msg.phone}</small>'
            )
            if error_text:
                body += f'<br/><span style="color:#dc3545;">{error_text}</span>'
            body += '</div>'

            record.message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
        except Exception as e:
            _logger.error('Chatter update failed for msg %s: %s', msg.id, e)

    def _handle_incoming_message(self, msg_data, contacts):
        """Log incoming WhatsApp messages for reference."""
        from_phone = msg_data.get('from', '')
        msg_type = msg_data.get('type', '')
        contact_name = next(
            (c.get('profile', {}).get('name', '') for c in contacts if c.get('wa_id') == from_phone),
            '',
        )
        body = ''
        if msg_type == 'text':
            body = msg_data.get('text', {}).get('body', '')

        _logger.info(
            'Incoming WhatsApp from +%s (%s) [%s]: %s',
            from_phone, contact_name, msg_type, body[:200],
        )

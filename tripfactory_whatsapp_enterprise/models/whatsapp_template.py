import json
import logging
import re
import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

LANGUAGE_SELECTION = [
    ('en', 'English'),
    ('en_US', 'English (US)'),
    ('hi', 'Hindi'),
    ('ar', 'Arabic'),
    ('fr', 'French'),
    ('de', 'German'),
    ('es', 'Spanish'),
    ('pt_BR', 'Portuguese (Brazil)'),
    ('ru', 'Russian'),
    ('zh_CN', 'Chinese (Simplified)'),
    ('ja', 'Japanese'),
    ('ko', 'Korean'),
    ('it', 'Italian'),
    ('nl', 'Dutch'),
    ('tr', 'Turkish'),
]


class WhatsAppTemplateVariable(models.Model):
    _name = 'whatsapp.template.variable'
    _description = 'WhatsApp Template Variable Mapping'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    template_id = fields.Many2one(
        comodel_name='whatsapp.template',
        string='Template',
        required=True,
        ondelete='cascade',
    )
    name = fields.Char(
        string='Variable',
        required=True,
        help='Variable placeholder used in the template, e.g. {{1}}, {{2}}',
    )
    line_type = fields.Selection(
        selection=[
            ('body', 'Body'),
            ('header', 'Header'),
            ('button', 'Button'),
        ],
        string='Used In',
        default='body',
        required=True,
    )
    field_name = fields.Char(
        string='Field Path',
        help='Dot-notation Odoo field path on the applied model, e.g. partner_id.name',
    )
    field_id = fields.Many2one(
        comodel_name='ir.model.fields',
        string='Odoo Field',
        domain="[('model_id.model', '=', template_id.applies_to)]",
    )
    demo_value = fields.Char(
        string='Demo / Example Value',
        required=True,
        default='Sample Value',
        help='Used as sample text when submitting this template to Meta for approval',
    )

    @api.onchange('field_id')
    def _onchange_field_id(self):
        if self.field_id:
            self.field_name = self.field_id.name
            if not self.demo_value or self.demo_value == 'Sample Value':
                self.demo_value = f'Sample {self.field_id.field_description}'


class WhatsAppTemplate(models.Model):
    _name = 'whatsapp.template'
    _description = 'WhatsApp Message Template'
    _rec_name = 'name'
    _order = 'name'

    # ── Basic info ──────────────────────────────────────────────────────────
    name = fields.Char(
        string='Template Name',
        required=True,
        help='User-friendly display name (will be normalized to lowercase for Meta)',
    )
    template_name = fields.Char(
        string='Meta Template Name',
        help='Auto-generated normalized name sent to Meta API (lowercase, underscores only). '
             'Leave blank to auto-generate from the display name.',
    )
    language = fields.Selection(
        selection=LANGUAGE_SELECTION,
        string='Language',
        default='en_US',
        required=True,
    )
    category = fields.Selection(
        selection=[
            ('MARKETING', 'Marketing'),
            ('UTILITY', 'Utility'),
            ('AUTHENTICATION', 'Authentication'),
        ],
        string='Category',
        default='UTILITY',
        required=True,
    )

    # ── Model / phone mapping (Enterprise-like) ──────────────────────────────
    applies_to_id = fields.Many2one(
        comodel_name='ir.model',
        string='Applies To',
        help='The Odoo model this template is designed for, e.g. Sale Order or CRM Lead',
    )
    applies_to = fields.Char(
        related='applies_to_id.model',
        string='Model Technical Name',
        store=True,
        readonly=True,
    )
    phone_field_id = fields.Many2one(
        comodel_name='ir.model.fields',
        string='Phone Field',
        domain="[('model_id', '=', applies_to_id), ('ttype', 'in', ['char', 'phone'])]",
        help='Which field on the model holds the customer WhatsApp number',
    )

    # ── Header ──────────────────────────────────────────────────────────────
    header_type = fields.Selection(
        selection=[
            ('NONE', 'None'),
            ('TEXT', 'Text'),
            ('IMAGE', 'Image'),
            ('DOCUMENT', 'Document'),
            ('VIDEO', 'Video'),
        ],
        string='Header Type',
        default='NONE',
    )
    header_text = fields.Char(string='Header Text')

    # Attachment — standard Odoo many2many_binary widget for file picking
    header_attachment_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='whatsapp_template_header_attachment_rel',
        column1='template_id',
        column2='attachment_id',
        string='Header File',
        help='Select one file (PDF/JPG/PNG/MP4). Then click Upload to Meta.',
    )
    header_handle = fields.Char(
        string='Meta Media Handle',
        help='Auto-filled after clicking "Upload to Meta". You can also paste it manually.',
    )
    report_id = fields.Many2one(
        comodel_name='ir.actions.report',
        string='Report',
        help='Odoo PDF report to auto-attach as document when sending this template',
    )

    # ── Body / Footer ────────────────────────────────────────────────────────
    body = fields.Text(string='Body', required=True)
    footer_text = fields.Char(string='Footer Message')

    # ── Buttons ─────────────────────────────────────────────────────────────
    buttons_json = fields.Text(string='Buttons (JSON)', default='[]')

    # ── Variables ────────────────────────────────────────────────────────────
    variable_ids = fields.One2many(
        comodel_name='whatsapp.template.variable',
        inverse_name='template_id',
        string='Variables',
    )

    # ── Meta sync fields ─────────────────────────────────────────────────────
    meta_template_id = fields.Char(string='Meta Template ID', readonly=True)
    status = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('paused', 'Paused'),
            ('disabled', 'Disabled'),
        ],
        string='Status',
        default='draft',
    )
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True)

    # ── Computed preview ──────────────────────────────────────────────────────
    body_preview = fields.Text(
        string='Preview',
        compute='_compute_body_preview',
        store=False,
    )
    whatsapp_account_info = fields.Char(
        string='Account',
        compute='_compute_account_info',
        store=False,
    )

    @api.depends('body', 'header_type', 'header_text', 'footer_text')
    def _compute_body_preview(self):
        for rec in self:
            parts = []
            if rec.header_type == 'TEXT' and rec.header_text:
                parts.append(f'*{rec.header_text}*')
            if rec.body:
                parts.append(rec.body)
            if rec.footer_text:
                parts.append(f'_{rec.footer_text}_')
            rec.body_preview = '\n\n'.join(parts)

    def _compute_account_info(self):
        ICP = self.env['ir.config_parameter'].sudo()
        waba_id = ICP.get_param('tripfactory_whatsapp.waba_id', '')
        for rec in self:
            rec.whatsapp_account_info = waba_id or 'Not configured'

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _get_api_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param('tripfactory_whatsapp.access_token', '')
        waba_id = ICP.get_param('tripfactory_whatsapp.waba_id', '')
        if not token or not waba_id:
            raise UserError(_(
                'WhatsApp API credentials are not configured. '
                'Please go to Settings → WhatsApp Configuration.'
            ))
        return token, waba_id

    def _normalized_meta_name(self):
        """Return a Meta-valid template name (lowercase, underscores only)."""
        source = self.template_name or self.name
        return re.sub(r'[^a-z0-9]+', '_', source.lower()).strip('_')

    # ── Header media upload to Meta ──────────────────────────────────────────
    def action_upload_header_to_meta(self):
        """Upload the selected header file to Meta and store the returned handle."""
        self.ensure_one()
        if not self.header_attachment_ids:
            raise UserError(_('Please select a file first using the "Header File" field.'))

        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param('tripfactory_whatsapp.access_token', '')
        app_id = ICP.get_param('tripfactory_whatsapp.app_id', '')
        if not token:
            raise UserError(_('WhatsApp Access Token is not configured. Go to Settings → WhatsApp Configuration.'))
        if not app_id:
            raise UserError(_('WhatsApp App ID is not configured. Go to Settings → WhatsApp Configuration.'))

        import base64
        attachment = self.header_attachment_ids[0]
        file_data = base64.b64decode(attachment.datas)
        file_size = len(file_data)
        file_name = attachment.name or 'document'

        # Use attachment's stored mimetype, fall back to extension detection
        mime_type = attachment.mimetype or ''
        if not mime_type:
            ext = (file_name.rsplit('.', 1)[-1] if '.' in file_name else '').lower()
            mime_map = {
                'pdf': 'application/pdf',
                'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                'png': 'image/png',
                'mp4': 'video/mp4',
                '3gp': 'video/3gpp', '3gpp': 'video/3gpp',
            }
            mime_type = mime_map.get(ext, 'application/octet-stream')

        # Step 1: Create upload session using App ID (not WABA ID)
        session_url = f'https://graph.facebook.com/v19.0/{app_id}/uploads'
        session_headers = {'Authorization': f'Bearer {token}'}
        session_params = {
            'file_length': file_size,
            'file_type': mime_type,
            'file_name': file_name,
            'messaging_product': 'whatsapp',
        }
        try:
            resp = requests.post(session_url, headers=session_headers, params=session_params, timeout=30)
            resp.raise_for_status()
            upload_session_id = resp.json().get('id', '')
        except requests.HTTPError as e:
            err = str(e)
            try:
                err = e.response.json().get('error', {}).get('message', str(e))
            except Exception:
                pass
            raise UserError(_('Failed to create Meta upload session:\n%s') % err)
        except requests.RequestException as e:
            raise UserError(_('Connection error: %s') % str(e))

        if not upload_session_id:
            raise UserError(_('Meta did not return an upload session ID.'))

        # Step 2: Upload file bytes
        upload_url = f'https://graph.facebook.com/v19.0/{upload_session_id}'
        upload_headers = {
            'Authorization': f'OAuth {token}',
            'file_offset': '0',
            'Content-Type': mime_type,
        }
        try:
            resp = requests.post(upload_url, headers=upload_headers, data=file_data, timeout=120)
            resp.raise_for_status()
            handle = resp.json().get('h', '')
        except requests.HTTPError as e:
            err = str(e)
            try:
                err = e.response.json().get('error', {}).get('message', str(e))
            except Exception:
                pass
            raise UserError(_('Failed to upload file to Meta:\n%s') % err)
        except requests.RequestException as e:
            raise UserError(_('Connection error during upload: %s') % str(e))

        if not handle:
            raise UserError(_('Upload succeeded but Meta did not return a media handle. Check the file format.'))

        self.write({'header_handle': handle})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Upload Successful ✓'),
                'message': _('"%s" uploaded to Meta. Handle saved — ready to Submit for Approval.') % file_name,
                'type': 'success',
                'sticky': True,
            },
        }

    # ── + Variable button ────────────────────────────────────────────────────
    def action_add_variable(self):
        """Append the next {{N}} to the body and create a variable mapping line."""
        self.ensure_one()
        existing_nums = [int(n) for n in re.findall(r'\{\{(\d+)\}\}', self.body or '')]
        next_num = max(existing_nums, default=0) + 1
        placeholder = f'{{{{{next_num}}}}}'

        self.write({'body': (self.body or '').rstrip() + f' {placeholder}'})

        already = self.variable_ids.filtered(lambda v: v.name == placeholder and v.line_type == 'body')
        if not already:
            self.env['whatsapp.template.variable'].create({
                'template_id': self.id,
                'name': placeholder,
                'line_type': 'body',
                'sequence': next_num * 10,
                'demo_value': f'Sample {next_num}',
            })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'whatsapp.template',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Meta: Sync all ────────────────────────────────────────────────────────
    def action_sync_from_meta(self):
        """Pull all templates from Meta and create/update local records."""
        token, waba_id = self._get_api_config()
        url = f'https://graph.facebook.com/v19.0/{waba_id}/message_templates'
        headers = {'Authorization': f'Bearer {token}'}
        params = {
            'limit': 200,
            'fields': 'id,name,language,category,status,components,rejected_reason',
        }
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            raise UserError(_('Failed to fetch templates from Meta: %s') % str(e))

        created = updated = 0
        for tmpl in data.get('data', []):
            vals = self._parse_meta_template(tmpl)
            existing = self.search([('meta_template_id', '=', tmpl.get('id'))], limit=1)
            if existing:
                existing.write(vals)
                updated += 1
            else:
                self.create(vals)
                created += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': _('%d templates created, %d updated from Meta.') % (created, updated),
                'type': 'success',
                'sticky': False,
            },
        }

    def _parse_meta_template(self, tmpl):
        header_type = 'NONE'
        header_text = False
        header_handle = False
        body_text = ''
        footer_text = False
        buttons = []

        for comp in tmpl.get('components', []):
            ctype = comp.get('type', '').upper()
            if ctype == 'HEADER':
                fmt = comp.get('format', 'TEXT').upper()
                header_type = fmt
                if fmt == 'TEXT':
                    header_text = comp.get('text', '')
                else:
                    handles = comp.get('example', {}).get('header_handle', [])
                    header_handle = handles[0] if handles else False
            elif ctype == 'BODY':
                body_text = comp.get('text', '')
            elif ctype == 'FOOTER':
                footer_text = comp.get('text', '')
            elif ctype == 'BUTTONS':
                buttons = comp.get('buttons', [])

        status_map = {
            'approved': 'approved', 'pending': 'pending',
            'rejected': 'rejected', 'paused': 'paused', 'disabled': 'disabled',
        }
        status = status_map.get(tmpl.get('status', 'DRAFT').lower(), 'draft')

        return {
            'name': tmpl.get('name', ''),
            'template_name': tmpl.get('name', ''),
            'language': tmpl.get('language', 'en_US'),
            'category': tmpl.get('category', 'UTILITY'),
            'header_type': header_type,
            'header_text': header_text,
            'header_handle': header_handle,
            'body': body_text,
            'footer_text': footer_text,
            'buttons_json': json.dumps(buttons),
            'meta_template_id': tmpl.get('id'),
            'status': status,
            'rejection_reason': tmpl.get('rejected_reason', False),
        }

    # ── Meta: Submit for approval ─────────────────────────────────────────────
    def action_submit_for_approval(self):
        """Submit this template to Meta for approval."""
        self.ensure_one()
        token, waba_id = self._get_api_config()

        meta_name = self._normalized_meta_name()
        if not meta_name:
            raise UserError(_('Template name is invalid. Use only letters, numbers, and underscores.'))

        components = self._build_components()
        if not components:
            raise UserError(_('Template must have at least a Body component.'))

        url = f'https://graph.facebook.com/v19.0/{waba_id}/message_templates'
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        payload = {
            'name': meta_name,
            'language': self.language,
            'category': self.category,
            'components': components,
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.HTTPError as e:
            err_detail = str(e)
            try:
                err_obj = e.response.json().get('error', {})
                err_detail = err_obj.get('error_user_msg') or err_obj.get('message') or str(e)
            except Exception:
                pass
            raise UserError(_('Meta API rejected the template:\n%s') % err_detail)
        except requests.RequestException as e:
            raise UserError(_('Connection error: %s') % str(e))

        self.write({
            'template_name': meta_name,
            'meta_template_id': data.get('id', self.meta_template_id),
            'status': 'pending',
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Submitted'),
                'message': _('Template "%s" submitted to Meta for approval.') % meta_name,
                'type': 'success',
                'sticky': False,
            },
        }

    def _build_components(self):
        """Build Meta API component list with example values for all variables."""
        components = []

        # Header — only include if we have enough data for Meta
        if self.header_type == 'TEXT' and self.header_text:
            header = {'type': 'HEADER', 'format': 'TEXT', 'text': self.header_text}
            if re.search(r'\{\{\d+\}\}', self.header_text):
                hdr_vars = self.variable_ids.filtered(lambda v: v.line_type == 'header')
                sample = hdr_vars[0].demo_value if hdr_vars else 'Sample Header'
                header['example'] = {'header_text': [sample]}
            components.append(header)
        elif self.header_type in ('DOCUMENT', 'IMAGE', 'VIDEO') and self.header_handle:
            # Only include media header if handle is available (requires prior Upload to Meta)
            components.append({
                'type': 'HEADER',
                'format': self.header_type,
                'example': {'header_handle': [self.header_handle]},
            })

        # Body
        if self.body:
            body_comp = {'type': 'BODY', 'text': self.body}
            numbered = sorted(set(re.findall(r'\{\{(\d+)\}\}', self.body)), key=int)
            if numbered:
                body_vars = self.variable_ids.filtered(
                    lambda v: v.line_type == 'body' and v.name in [f'{{{{{n}}}}}' for n in numbered]
                )
                # Build ordered demo values matching {{1}}, {{2}}, etc.
                var_by_name = {v.name: v.demo_value for v in body_vars}
                sample_row = [var_by_name.get(f'{{{{{n}}}}}', f'Sample {n}') for n in numbered]
                body_comp['example'] = {'body_text': [sample_row]}
            components.append(body_comp)

        # Footer
        if self.footer_text:
            components.append({'type': 'FOOTER', 'text': self.footer_text})

        # Buttons
        try:
            buttons = json.loads(self.buttons_json or '[]')
            if buttons:
                components.append({'type': 'BUTTONS', 'buttons': buttons})
        except (json.JSONDecodeError, TypeError):
            pass

        return components

    # ── Meta: Delete ──────────────────────────────────────────────────────────
    def action_delete_from_meta(self):
        self.ensure_one()
        if not self.meta_template_id:
            raise UserError(_('This template has not been submitted to Meta yet.'))
        token, waba_id = self._get_api_config()
        url = f'https://graph.facebook.com/v19.0/{waba_id}/message_templates'
        headers = {'Authorization': f'Bearer {token}'}
        try:
            response = requests.delete(
                url, headers=headers,
                params={'name': self.template_name or self.name},
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            raise UserError(_('Failed to delete template from Meta: %s') % str(e))
        self.write({'status': 'draft', 'meta_template_id': False})

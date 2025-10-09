"""
Slack Bot integration module
"""

import os
import logging
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from datetime import datetime
import json
import re

DEFAULT_COLUMN_ALIASES = {
    'title': ['title', 'issue', 'task'],
    'link': ['thread link', 'link', 'permalink', 'slack thread'],
    'status': ['status', 'state'],
    'attachment': ['attachments', 'files', 'evidence', 'screenshots'],
    'description': ['description', 'details', 'summary'],
    'product': ['product', 'app'],
    'label': ['label', 'type label'],
    'feature': ['feature', 'module'],
    'category': ['category', 'type'],
    'date_of_incident': ['date of incident', 'incident date', 'date'],
    'severity': ['severity', 'impact'],
    'urgency': ['urgency', 'priority'],
    'reporter': ['reporter', 'requester', 'submitter', 'submitted by', 'submitted_by'],
    'responder': ['responder', 'owner', 'assignee'],
    'assignee': ['assignee', 'assigne', 'assigned to'],
    'sheet_name': ['sheet', 'sheet name', 'source sheet'],
    'quarter': ['quarter'],
    'week': ['week', 'week number'],
    'from_value': ['from', 'source'],
    'reporting_date_time': ['reported at', 'reported time', 'reported', 'date submitted', 'submitted date', 'submitted on'],
    'response_time': ['responded at', 'response time', 'responded'],
    'channel': ['channel'],
}

RICH_TEXT_COLUMN_KEYS = [
    'description',
    'product',
    'label',
    'feature',
    'category',
    'date_of_incident',
    'severity',
    'urgency',
    'reporter',
    'responder',
    'sheet_name',
    'quarter',
    'week',
    'from_value',
    'reporting_date_time',
    'response_time',
    'channel',
]

logger = logging.getLogger(__name__)

class SlackBot:
    def __init__(self):
        """Initialize Slack bot"""
        self.token = os.getenv('SLACK_BOT_TOKEN')
        self.client = WebClient(token=self.token)
        
        if not self.token:
            raise ValueError("SLACK_BOT_TOKEN environment variable is required")

        # Slack List configuration (optional)
        self.slack_list_id = os.getenv('SLACK_LIST_ID')
        self.slack_list_link_display_name = os.getenv('SLACK_LIST_LINK_DISPLAY_NAME', 'Slack Thread')
        self.slack_list_default_status_key = os.getenv('SLACK_LIST_DEFAULT_STATUS_NAME') or os.getenv('SLACK_LIST_DEFAULT_STATUS_KEY', 'New')

        self.slack_list_column_names = {}
        self.slack_list_columns_by_id = {}
        self.slack_list_columns_by_name = {}
        self.slack_list_title_column_id = None
        self.slack_list_link_column_id = None
        self.slack_list_status_column_id = None
        self.slack_list_attachment_column_id = None
        self.slack_list_rich_text_columns = {}
        self.slack_list_status_options = {}
        self.legacy_status_options = self._parse_status_options(os.getenv('SLACK_LIST_STATUS_OPTIONS', ''))

        self._initialize_slack_list_configuration()
        for legacy_key, legacy_value in self.legacy_status_options.items():
            self.slack_list_status_options.setdefault(legacy_key, legacy_value)

        self.slack_list_enabled = bool(self.slack_list_id and self.slack_list_title_column_id)

    def _initialize_slack_list_configuration(self):
        if not self.slack_list_id:
            logger.debug("Slack List ID not configured; skipping list auto-configuration.")
            return

        self.slack_list_column_names = self._load_column_name_overrides()
        columns = self._fetch_list_columns(self.slack_list_id)
        if columns:
            self.slack_list_columns_by_id = {
                column.get('id'): column for column in columns if column.get('id')
            }
            self.slack_list_columns_by_name = {
                self._normalize_column_name(column.get('name')): column
                for column in columns
                if column.get('name')
            }
            logger.debug("Discovered %d columns for Slack List %s", len(columns), self.slack_list_id)
        else:
            self.slack_list_columns_by_id = {}
            self.slack_list_columns_by_name = {}
            if self.slack_list_id:
                logger.debug("Could not auto-discover Slack List columns; relying on explicit configuration.")

        self.slack_list_title_column_id = self._resolve_column_id('title', DEFAULT_COLUMN_ALIASES.get('title', []))
        self.slack_list_link_column_id = self._resolve_column_id('link', DEFAULT_COLUMN_ALIASES.get('link', []))
        self.slack_list_attachment_column_id = self._resolve_column_id('attachment', DEFAULT_COLUMN_ALIASES.get('attachment', []))
        self.slack_list_status_column_id = self._resolve_column_id('status', DEFAULT_COLUMN_ALIASES.get('status', []))

        rich_text_mapping = {}
        for key in RICH_TEXT_COLUMN_KEYS:
            column_id = self._resolve_column_id(key, DEFAULT_COLUMN_ALIASES.get(key, []))
            if column_id:
                rich_text_mapping[key] = column_id
        self.slack_list_rich_text_columns = rich_text_mapping

        discovered_status_options = self._build_status_options(self.slack_list_status_column_id)
        if discovered_status_options:
            self.slack_list_status_options.update(discovered_status_options)

    def _fetch_list_columns(self, list_id):
        try:
            response = self.client.api_call('slackLists.lists.info', json={'list_id': list_id})
            if response.get('ok'):
                return response.get('list', {}).get('columns', []) or []
            if response.get('error'):
                logger.debug("Slack Lists API returned error when fetching schema: %s", response.get('error'))
        except SlackApiError as exc:
            logger.debug("Slack API rejected list schema lookup: %s", exc.response.get('error', str(exc)))
        except Exception as exc:
            logger.debug("Unexpected error fetching Slack List schema: %s", str(exc))
        return []

    def _load_column_name_overrides(self):
        overrides = {}
        file_path = os.getenv('SLACK_LIST_COLUMN_NAMES_FILE')
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as handle:
                    data = json.load(handle)
                    if isinstance(data, dict):
                        overrides.update(data)
            except Exception as exc:
                logger.warning("Failed to load Slack List column names file %s: %s", file_path, str(exc))
        raw = os.getenv('SLACK_LIST_COLUMN_NAMES')
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    overrides.update(data)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in SLACK_LIST_COLUMN_NAMES; ignoring value.")
        return overrides

    def _normalize_column_name(self, name):
        if not name:
            return ''
        return re.sub(r'[^a-z0-9]+', '_', str(name).lower()).strip('_')

    def _looks_like_identifier(self, candidate):
        if not candidate or not isinstance(candidate, str):
            return False
        if len(candidate) < 6:
            return False
        if any(ch.isspace() for ch in candidate):
            return False
        if not any(ch.isdigit() for ch in candidate):
            return False
        return bool(re.match(r'^[A-Za-z0-9]+$', candidate))

    def _resolve_column_id(self, key, default_aliases):
        legacy_env_name = f'SLACK_LIST_{key.upper()}_COLUMN_ID'
        legacy_value = os.getenv(legacy_env_name)
        if legacy_value:
            return legacy_value

        override = self.slack_list_column_names.get(key)
        candidate_names = []

        if isinstance(override, dict):
            override_id = override.get('id')
            if override_id:
                return override_id
            name_candidate = override.get('name') or override.get('label')
            if name_candidate:
                candidate_names.append(name_candidate)
            aliases = override.get('aliases') or override.get('alias') or []
            if isinstance(aliases, (list, tuple)):
                candidate_names.extend(aliases)
        elif isinstance(override, (list, tuple)):
            candidate_names.extend(override)
        elif isinstance(override, str):
            if override in self.slack_list_columns_by_id:
                return override
            if self._looks_like_identifier(override):
                return override
            candidate_names.append(override)

        if not candidate_names:
            if isinstance(default_aliases, (list, tuple)):
                candidate_names = [alias for alias in default_aliases if isinstance(alias, str) and alias.strip()]
            elif isinstance(default_aliases, str) and default_aliases.strip():
                candidate_names = [default_aliases]

        for name in candidate_names:
            normalized = self._normalize_column_name(name)
            column = self.slack_list_columns_by_name.get(normalized)
            if column:
                return column.get('id')

        if isinstance(override, str) and self._looks_like_identifier(override):
            return override

        return None

    def _build_status_options(self, status_column_id):
        options = {}
        if not status_column_id:
            return options
        column = self.slack_list_columns_by_id.get(status_column_id)
        if not column:
            return options
        potential_containers = [
            column.get('select_options'),
            column.get('options'),
            column.get('choices'),
        ]
        for container in potential_containers:
            if isinstance(container, list) and container:
                for option in container:
                    option_id = option.get('id')
                    name = option.get('name') or option.get('label') or option.get('value')
                    if not option_id or not name:
                        continue
                    normalized = self._normalize_status_key(name)
                    options[normalized] = option_id
                    options[name] = option_id
                break
        return options

    def _normalize_status_key(self, key):
        if not key:
            return ''
        return re.sub(r'[^a-z0-9]+', '_', str(key).lower()).strip('_')
    
    def send_message(self, channel, text, thread_ts=None):
        """Send message to Slack channel"""
        try:
            response = self.client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts
            )
            return response
        except SlackApiError as e:
            logger.error(f"Error sending message: {e.response['error']}")
            return None
    
    def get_thread_data(self, channel, ts, max_retries=3):
        """Get thread data from Slack, with rate limit handling and exponential backoff"""
        import time
        logger.info(f"[get_thread_data] Called with channel={channel}, ts={ts}")
        try:
            # Dapatkan thread_ts dari event (bisa parent atau reply)
            thread_ts = ts
            wait = 5
            for attempt in range(max_retries):
                try:
                    response = self.client.conversations_replies(channel=channel, ts=ts)
                    break
                except SlackApiError as e:
                    if e.response['error'] == 'ratelimited':
                        retry_after = int(e.response.headers.get('Retry-After', wait))
                        logger.warning(f"Rate limited on conversations_replies. Waiting {retry_after} seconds (attempt {attempt+1}/{max_retries})...")
                        time.sleep(retry_after)
                        wait = min(retry_after * 2, 600)  # Exponential backoff, max 10 menit
                        continue
                    else:
                        logger.error(f"Error getting thread data: {e.response['error']}")
                        return None
            else:
                logger.error("Max retries exceeded for conversations_replies")
                return None
            messages_first = response.get('messages') or []
            if response.get('ok') and messages_first:
                thread_ts = messages_first[0].get('thread_ts', ts)

            # Ambil semua pesan di thread (paginasi jika perlu)
            all_messages = []
            cursor = None
            while True:
                wait = 5
                for attempt in range(max_retries):
                    try:
                        resp = self.client.conversations_replies(channel=channel, ts=thread_ts, cursor=cursor)
                        break
                    except SlackApiError as e:
                        if e.response['error'] == 'ratelimited':
                            retry_after = int(e.response.headers.get('Retry-After', wait))
                            logger.warning(f"Rate limited on conversations_replies (pagination). Waiting {retry_after} seconds (attempt {attempt+1}/{max_retries})...")
                            time.sleep(retry_after)
                            wait = min(retry_after * 2, 600)
                            continue
                        else:
                            logger.error(f"Error getting thread data: {e.response['error']}")
                            return None
                else:
                    logger.error("Max retries exceeded for conversations_replies (pagination)")
                    return None
                if not resp.get('ok'):
                    logger.error(f"Error getting thread data: {resp.get('error')}")
                    return None
                messages = resp.get('messages') or []
                all_messages.extend(messages)
                if not resp.get('has_more'):
                    break
                cursor = resp.get('response_metadata', {}).get('next_cursor')

            # Parent = pesan dengan ts == thread_ts
            parent_message = next((m for m in all_messages if m['ts'] == thread_ts), all_messages[0])
            replies = [m for m in all_messages if m['ts'] != thread_ts]

            # Get permalink
            wait = 5
            for attempt in range(max_retries):
                try:
                    permalink_response = self.client.chat_getPermalink(channel=channel, message_ts=thread_ts)
                    break
                except SlackApiError as e:
                    if e.response['error'] == 'ratelimited':
                        retry_after = int(e.response.headers.get('Retry-After', wait))
                        logger.warning(f"Rate limited on chat_getPermalink. Waiting {retry_after} seconds (attempt {attempt+1}/{max_retries})...")
                        time.sleep(retry_after)
                        wait = min(retry_after * 2, 600)
                        continue
                    else:
                        logger.error(f"Error getting permalink: {e.response['error']}")
                        return None
            else:
                logger.error("Max retries exceeded for chat_getPermalink")
                return None
            permalink = permalink_response.get('permalink', '') if permalink_response.get('ok') else ''

            # Compile thread data
            thread_data = {
                'timestamp': datetime.fromtimestamp(float(thread_ts)).isoformat(),
                'channel': channel,
                'parent_message': {
                    'text': parent_message.get('text', ''),
                    'user': parent_message.get('user', ''),
                    'ts': parent_message.get('ts', '')
                },
                'replies': [
                    {
                        'text': r.get('text', ''),
                        'user': r.get('user', ''),
                        'ts': r.get('ts', ''),
                        'files': r.get('files', [])
                    } for r in replies
                ],
                'permalink': permalink,
                'message_count': len(all_messages)
            }
            # Get user info for parent message
            if parent_message.get('user'):
                user_info = self.get_user_info(parent_message['user'])
                thread_data['user'] = user_info.get('real_name', user_info.get('name', '')) if user_info else parent_message['user']
                thread_data['parent_message']['files'] = parent_message.get('files', [])
            return thread_data
        except SlackApiError as e:
            logger.error(f"Error getting thread data: {e.response['error']}")
            return None
    
    def create_list_item(self, *, title, rich_text_fields=None, link=None, status_key=None, attachments=None, custom_fields=None):
        """Create an item in the configured Slack List (if enabled)."""
        if not self.slack_list_enabled:
            logger.debug("Slack List integration is not configured; skipping item creation.")
            return None

        if not title:
            logger.warning("Slack List item requires a non-empty title. Skipping creation.")
            return None

        initial_fields = []

        title_field = self._create_rich_text_field(self.slack_list_title_column_id, title)
        if not title_field:
            logger.warning("Failed to prepare title field for Slack List item; skipping creation.")
            return None
        initial_fields.append(title_field)

        for key, text_value in (rich_text_fields or {}).items():
            column_id = self.slack_list_rich_text_columns.get(key)
            field = self._create_rich_text_field(column_id, text_value)
            if field:
                initial_fields.append(field)

        if link:
            link_field = None
            if isinstance(link, dict):
                link_field = self._create_link_field(
                    self.slack_list_link_column_id,
                    link.get('url'),
                    link.get('display_name', self.slack_list_link_display_name),
                    link.get('display_as_url', False)
                )
            elif isinstance(link, str):
                link_field = self._create_link_field(
                    self.slack_list_link_column_id,
                    link,
                    self.slack_list_link_display_name,
                    False
                )
            if link_field:
                initial_fields.append(link_field)

        if attachments and self.slack_list_attachment_column_id:
            attachment_field = self._create_attachment_field(self.slack_list_attachment_column_id, attachments)
            if attachment_field:
                initial_fields.append(attachment_field)

        if self.slack_list_status_column_id:
            resolved_key = status_key or self.slack_list_default_status_key
            option_id = self._resolve_status_option_id(resolved_key)
            if option_id:
                initial_fields.append({
                    'column_id': self.slack_list_status_column_id,
                    'select': [option_id]
                })
            elif resolved_key:
                logger.warning(f"Slack List status option for key '{resolved_key}' not found; skipping status field.")

        for field in custom_fields or []:
            if isinstance(field, dict):
                initial_fields.append(field)

        if not initial_fields:
            logger.warning("No fields generated for Slack List item creation; aborting request.")
            return None

        payload = {
            'list_id': self.slack_list_id,
            'initial_fields': initial_fields
        }

        try:
            response = self.client.api_call('slackLists.items.create', json=payload)
            logger.info("Successfully created Slack List item for list %s", self.slack_list_id)
            return response
        except SlackApiError as e:
            logger.error("Failed to create Slack List item: %s", e.response.get('error', str(e)))
        except Exception as e:
            logger.error("Unexpected error when creating Slack List item: %s", str(e))
        return None

    def _parse_status_options(self, raw_options):
        if not raw_options:
            return {}
        try:
            parsed = json.loads(raw_options)
            if isinstance(parsed, dict):
                options = {}
                for key, value in parsed.items():
                    if not value:
                        continue
                    key_str = str(key)
                    value_str = str(value)
                    options[key_str] = value_str
                    options[self._normalize_status_key(key_str)] = value_str
                return options
        except json.JSONDecodeError:
            pass

        options = {}
        for fragment in raw_options.split(','):
            if ':' in fragment:
                key, value = fragment.split(':', 1)
                key = key.strip()
                value = value.strip()
                if key and value:
                    options[key] = value
                    options[self._normalize_status_key(key)] = value
        return options

    def _resolve_status_option_id(self, status_key):
        if not status_key:
            return None
        if status_key in self.slack_list_status_options:
            return self.slack_list_status_options[status_key]
        normalized = self._normalize_status_key(status_key)
        option_id = self.slack_list_status_options.get(normalized)
        if option_id:
            return option_id
        if self._looks_like_identifier(status_key):
            return status_key
        return None

    def _create_rich_text_field(self, column_id, text):
        if not column_id or text is None:
            return None
        text = str(text).strip()
        if not text:
            return None
        return {
            'column_id': column_id,
            'rich_text': [
                {
                    'type': 'rich_text',
                    'elements': [
                        {
                            'type': 'rich_text_section',
                            'elements': [
                                {
                                    'type': 'text',
                                    'text': text
                                }
                            ]
                        }
                    ]
                }
            ]
        }

    def _create_link_field(self, column_id, url, display_name=None, display_as_url=False):
        if not column_id or not url:
            return None
        link_payload = {
            'original_url': url,
            'display_as_url': bool(display_as_url)
        }
        if display_name:
            link_payload['display_name'] = display_name
        return {
            'column_id': column_id,
            'link': [link_payload]
        }

    def _create_attachment_field(self, column_id, file_ids):
        if not column_id or not file_ids:
            return None
        valid_ids = [fid for fid in file_ids if fid]
        if not valid_ids:
            return None
        return {
            'column_id': column_id,
            'attachment': valid_ids
        }
    def get_user_info(self, user_id):
        """Get user information"""
        try:
            response = self.client.users_info(user=user_id)
            if response['ok']:
                return response['user']
            return None
        except SlackApiError as e:
            logger.error(f"Error getting user info: {e.response['error']}")
            return None
    
    def get_channel_info(self, channel_id):
        """Get channel information"""
        try:
            response = self.client.conversations_info(channel=channel_id)
            if response['ok']:
                return response['channel']
            return None
        except SlackApiError as e:
            logger.error(f"Error getting channel info: {e.response['error']}")
            return None
import os
import logging
import json
import base64
import binascii
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import certifi
import ssl
from typing import Dict, List, Optional

os.environ['SSL_CERT_FILE'] = certifi.where()

logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_column_letter(n):
	result = ''
	while n > 0:
		n, remainder = divmod(n - 1, 26)
		result = chr(65 + remainder) + result
	return result

class SpreadsheetBugManager:
	def __init__(self):
		raw_credentials_json_b64 = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON_B64')
		raw_credentials_json = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')
		self.credentials_file = os.getenv('GOOGLE_SHEETS_CREDENTIALS_FILES')
		self.credentials_info = None
		self.spreadsheet_id = os.getenv('SPREADSHEET_ID_BUG')
		if raw_credentials_json_b64:
			try:
				decoded_json = base64.b64decode(raw_credentials_json_b64).decode('utf-8')
				self.credentials_info = json.loads(decoded_json)
			except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
				raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON_B64 environment variable must be valid Base64-encoded JSON") from exc
		elif raw_credentials_json:
			try:
				self.credentials_info = json.loads(raw_credentials_json)
			except json.JSONDecodeError as exc:
				raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable contains invalid JSON") from exc
		if not self.credentials_info and not self.credentials_file:
			raise ValueError("Either GOOGLE_APPLICATION_CREDENTIALS_JSON or GOOGLE_SHEETS_CREDENTIALS_FILES environment variable is required")
		if not self.spreadsheet_id:
			raise ValueError("SPREADSHEET_ID_BUG environment variable is required")

	def _initialize_service(self):
		try:
			scopes = ['https://www.googleapis.com/auth/spreadsheets']
			if self.credentials_info:
				credentials = Credentials.from_service_account_info(
					self.credentials_info,
					scopes=scopes
				)
			else:
				credentials = Credentials.from_service_account_file(
					self.credentials_file,
					scopes=scopes
				)
			service = build('sheets', 'v4', credentials=credentials, cache_discovery=False)
			return service
		except Exception as e:
			logger.error(f"Error initializing Google Sheets service: {str(e)}")
			raise

	def _ensure_headers(self, sheet_name):
		try:
			service = self._initialize_service()
			headers = [
				'From',
				'Type',
				'Code',
				'Product',
				'Role',
				'Modul/Fitur',
				'Reporter',
				'Reporting Date Time',
				'Deskripsi',
				'Step Reproduce',
				'Severity',
				'Urgency',
				'Assignee',
				'Status',
				'Scheduled Release On',
				'Link Message',
				'Note'
			]
			num_cols = len(headers)
			last_col = get_column_letter(num_cols)
			header_range = f'A1:{last_col}1'
			result = service.spreadsheets().values().get(
				spreadsheetId=self.spreadsheet_id,
				range=f'{sheet_name}!{header_range}'
			).execute()
			values = result.get('values', [])
			if not values or len(values[0]) < len(headers):
				service.spreadsheets().values().update(
					spreadsheetId=self.spreadsheet_id,
					range=f'{sheet_name}!{header_range}',
					valueInputOption='RAW',
					body={'values': [headers]}
				).execute()
				logger.info(f"Headers added/updated in spreadsheet {sheet_name}")
		except HttpError as e:
			logger.error(f"Error ensuring headers: {str(e)}")
			raise

	def prepend_row_bug(self, data: Dict, sheet_name: str) -> bool:
		"""Prepend a new bug row below header, skip if duplicate by permalink."""
		link = data.get('link', '')
		clean_link = link.split('&cid=')[0] if link else link
		existing_links = [l.split('&cid=')[0] if l else l for l in self.get_all_links(sheet_name)]
		if clean_link in existing_links:
			logger.info(f"Duplicate bug detected, not prepending row for link: {link}")
			return False
		try:
			self._ensure_headers(sheet_name)
			service = self._initialize_service()
			requests = [{
				"insertDimension": {
					"range": {
						"sheetId": self._get_sheet_id(sheet_name),
						"dimension": "ROWS",
						"startIndex": 1,
						"endIndex": 2
					},
					"inheritFromBefore": False
				}
			}]
			service.spreadsheets().batchUpdate(
				spreadsheetId=self.spreadsheet_id,
				body={"requests": requests}
			).execute()
			headers = [
				'From',
				'Type',
				'Code',
				'Product',
				'Role',
				'Modul/Fitur',
				'Reporter',
				'Reporting Date Time',
				'Deskripsi',
				'Step Reproduce',
				'Severity',
				'Urgency',
				'Assignee',
				'Status',
				'Scheduled Release On',
				'Link Message',
				'Note'
			]
			num_cols = len(headers)
			last_col = get_column_letter(num_cols)
			row2_range = f'A2:{last_col}2'
			row_data = [
				data.get('from', ''),
				data.get('type', ''),
				data.get('code', ''),
				data.get('product', ''),
                data.get('role', ''),
				data.get('fitur', ''),
				data.get('reporter', ''),
				data.get('reporting_date_time', ''),
				data.get('deskripsi', ''),
				'',
				data.get('severity', ''),
				data.get('urgency', ''),
				'',
				'',
				'',
				data.get('link', ''),
				''
			]
			service.spreadsheets().values().update(
				spreadsheetId=self.spreadsheet_id,
				range=f'{sheet_name}!{row2_range}',
				valueInputOption="USER_ENTERED",
				body={"values": [row_data]}
			).execute()
			logger.info(f"[prepend_row_bug] Sukses menulis ke sheet '{sheet_name}' dengan data: {data}")
			return True
		except Exception as e:
			logger.error(f"Error prepending bug row: {str(e)}")
			return False

	def get_all_bugs(self, sheet_name: str) -> Optional[List[List]]:
		"""Get all bug data from the spreadsheet"""
		try:
			service = self._initialize_service()
			headers = [
				'From',
				'Type',
				'Code',
				'Product',
				'Role',
				'Modul/Fitur',
				'Reporter',
				'Reporting Date Time',
				'Deskripsi',
				'Step Reproduce',
				'Severity',
				'Urgency',
				'Assignee',
				'Status',
				'Scheduled Release On',
				'Link Message',
				'Note'
			]
			num_cols = len(headers)
			last_col = get_column_letter(num_cols)
			data_range = f'A1:{last_col}'
			result = service.spreadsheets().values().get(
				spreadsheetId=self.spreadsheet_id,
				range=f'{sheet_name}!{data_range}'
			).execute()
			return result.get('values', [])
		except HttpError as e:
			logger.error(f"Error getting bug data from spreadsheet: {str(e)}")
			return None

	def _get_sheet_id(self, sheet_name: str):
		service = self._initialize_service()
		spreadsheet = service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
		for sheet in spreadsheet['sheets']:
			if sheet['properties']['title'] == sheet_name:
				return sheet['properties']['sheetId']
		logger.error(f"Sheet '{sheet_name}' not found.")
		raise ValueError(f"Sheet name '{sheet_name}' not found.")

	def get_all_links(self, sheet_name: str) -> list:
		all_data = self.get_all_bugs(sheet_name)
		if not all_data or len(all_data) < 2:
			return []
		header = all_data[0]
		try:
			link_idx = header.index('Link Message')
		except ValueError:
			return []
		links = []
		for row in all_data[1:]:
			if len(row) > link_idx:
				links.append(row[link_idx])
		return links

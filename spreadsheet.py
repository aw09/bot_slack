"""
Google Sheets integration module
"""

import os
import logging
import json
import base64
import binascii
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime
from typing import Dict, List, Optional
import string
import ssl
import certifi
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

class SpreadsheetManager:
    def _set_data_validation_dropdowns(self, sheet_name):
        """Set data validation (dropdown) for From, Severity, and Urgency columns."""
        try:
            service = self._initialize_service()
            sheet_id = self._get_sheet_id(sheet_name)
            # Kolom: From (A), Severity (R), Urgency (S)
            requests = [
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,  # Mulai dari baris 2 (0-based)
                            "endRowIndex": 2,  # Atur sesuai kebutuhan
                            "startColumnIndex": 4,  # Kolom A (From)
                            "endColumnIndex": 5
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [
                                    {"userEnteredValue": "Backend"},
                                    {"userEnteredValue": "Frontend"}
                                ]
                            },
                            "showCustomUi": True,
                            "strict": True
                        }
                    }
                },
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,  # Mulai dari baris 2 (0-based)
                            "endRowIndex": 2,  # Atur sesuai kebutuhan
                            "startColumnIndex": 1,  # Kolom A (From)
                            "endColumnIndex": 2
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [
                                    {"userEnteredValue": "Ask"},
                                    {"userEnteredValue": "Bug"},
                                    {"userEnteredValue": "Feedback"},
                                    {"userEnteredValue": "Invalid"}
                                ]
                            },
                            "showCustomUi": True,
                            "strict": True
                        }
                    }
                },
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,  # Mulai dari baris 2 (0-based)
                            "endRowIndex": 2,  # Atur sesuai kebutuhan
                            "startColumnIndex": 0,  # Kolom A (From)
                            "endColumnIndex": 1
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [
                                    {"userEnteredValue": "internal"},
                                    {"userEnteredValue": "external"}
                                ]
                            },
                            "showCustomUi": True,
                            "strict": True
                        }
                    }
                },
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 2,
                            "startColumnIndex": 18,  # Kolom R (Severity)
                            "endColumnIndex": 19
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [
                                    {"userEnteredValue": "Hotfix"},
                                    {"userEnteredValue": "Bugfix"},
                                    {"userEnteredValue": "Features"},
                                    {"userEnteredValue": "Other(Ask)"}
                                ]
                            },
                            "showCustomUi": True,
                            "strict": True
                        }
                    }
                },
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 2,
                            "startColumnIndex": 19,  # Kolom S (Urgency)
                            "endColumnIndex": 20
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [
                                    {"userEnteredValue": "High"},
                                    {"userEnteredValue": "Medium"},
                                    {"userEnteredValue": "Low"}
                                ]
                            },
                            "showCustomUi": True,
                            "strict": True
                        }
                    }
                }
            ]
            service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": requests}
            ).execute()
            logger.info(f"Data validation (dropdown) set for From, Severity, and Urgency columns in '{sheet_name}'")
        except Exception as e:
            logger.error(f"Error setting data validation: {str(e)}")

    def __init__(self):
        """Initialize Google Sheets manager"""
        raw_credentials_json_b64 = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON_B64')
        raw_credentials_json = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')
        self.credentials_file = os.getenv('GOOGLE_SHEETS_CREDENTIALS_FILES')
        self.credentials_info = None
        self.spreadsheet_id = os.getenv('SPREADSHEET_ID')

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
            raise ValueError("SPREADSHEET_ID environment variable is required")
        # Removed self.service initialization
        # Don't ensure headers on init - will be done dynamically per sheet
    
    def _initialize_service(self):
        """Initialize Google Sheets service"""
        try:
            # Define scopes
            scopes = ['https://www.googleapis.com/auth/spreadsheets']
            # Load credentials
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
            
            # Build service
            service = build('sheets', 'v4', credentials=credentials, cache_discovery=False)
            
            return service
        except Exception as e:
            logger.error(f"Error initializing Google Sheets service: {str(e)}")
            raise
    
    def _ensure_headers(self, sheet_name):
        """Ensure spreadsheet has proper headers"""
        try:
            service = self._initialize_service()
            headers = [
                'From',
                'Type',
                'Number of Feedback',
                'Product',
                'Role',
                'Modul/Fitur',
                'Reporter',
                'Reporting Date Time',
                'Response Time',
                'Resolution Time',
                'Deployment Time',
                'Response Time (Days) SLA',
                'Resolution Time (Days) SLA',
                'Resolve Time (Days) SLA',
                'SLA Status Record',
                'Responder',
                'Deskripsi',
                'Step Reproduce',
                'Severity',
                'Urgency',
                'SLA',
                'Assignee',
                'Status',
                'Scheduled Release On',
                'Link Message',
                'Related Ticket'
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
    
    def prepend_row(self, data: Dict, sheet_name: str) -> bool:
        """Prepend a new row right below the header (row 2), skip if duplicate by permalink using get_all_links."""
        link = data.get('link', '')
        # Clean the link for comparison
        clean_link = link.split('&cid=')[0] if link else link
        # Get all existing links and clean them
        existing_links = [l.split('&cid=')[0] if l else l for l in self.get_all_links(sheet_name)]
        if clean_link in existing_links:
            logger.info(f"Duplicate thread detected, not prepending row for link: {link}")
            return False
        try:
            self._ensure_headers(sheet_name)
            # Set dropdowns (data validation) jika belum ada
            self._set_data_validation_dropdowns(sheet_name)
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
                'Number of Feedback',
                'Product',
                'Role',
                'Modul/Fitur',
                'Reporter',
                'Reporting Date Time',
                'Response Time',
                'Resolution Time',
                'Deployment Time',
                'Response Time (Days) SLA',
                'Resolution Time (Days) SLA',
                'Resolve Time (Days) SLA',
                'SLA Status Record',
                'Responder',
                'Deskripsi',
                'Step Reproduce',
                'Severity',
                'Urgency',
                'SLA',
                'Assignee',
                'Status',
                'Scheduled Release On',
                'Link Message',
                'Related Ticket'
            ]
            num_cols = len(headers)
            last_col = get_column_letter(num_cols)
            row2_range = f'A2:{last_col}2'
            row_num = 2
            response_time_sla_formula = f'=IF(ISBLANK(I{row_num}), "Waiting Response", IF(H{row_num} = I{row_num}, 1, NETWORKDAYS(H{row_num}, I{row_num}) - 1))'
            resolution_time_sla_formula = f'=IF(ISBLANK(J{row_num}), "Waiting Solution", IF(H{row_num} = J{row_num}, 1, NETWORKDAYS(H{row_num}, J{row_num}) - 1))'
            resolve_time_sla_formula = f'=IF(AND(ISBLANK(J{row_num}), ISBLANK(K{row_num})), "Waiting Solution", IF(ISBLANK(K{row_num}), "Feedback on progress", IF(H{row_num} = K{row_num}, 1, NETWORKDAYS(H{row_num}, K{row_num}) - 1)))'
            sla_status_record_formula = f'=IFS(AND(ISBLANK(J{row_num}), ISBLANK(K{row_num})), "Waiting Solution", ISBLANK(K{row_num}), "Feedback on progress", N{row_num} <= U{row_num}, "MEET SLA", N{row_num} > U{row_num}, "OVER SLA")'
            sla = f'=IF(T{row_num}="High",3,IF(T{row_num}="Medium",13,IF(T{row_num}="Low",30,"FALSE")))'
            row_data = [
                data.get('from', ''),                    # From
                data.get('type', ''),                    # Type
                '',                                       # Number of Feedback
                data.get('product', ''),                 # Product
                data.get('role', ''),                    # Role
                data.get('fitur', ''),                   # Modul/Fitur
                data.get('reporter', ''),
                data.get('reporting_date_time', ''),        #Reporting time
                data.get('response_time', ''),         # Response time
                '',                                       # Resolution Time
                '',                                       # Deployment Time
                response_time_sla_formula,                # Response Time (Days) SLA (kolom K)
                resolution_time_sla_formula,              # Resolution Time (Days) SLA (kolom L)
                resolve_time_sla_formula,
                sla_status_record_formula,                # SLA Status Record
                data.get('responder', ''),               # Responder
                data.get('description', ''),             # Deskripsi
                '',                                       # Step Reproduce
                data.get('severity', ''),                # Severity
                data.get('urgency', ''),                 # Urgency
                sla,                                       # SLA
                '',                                       # Assignee
                '',                                       # Status
                '',                                       # Scheduled Release On
                data.get('link', ''),                    # Link Message
                ''                                        # Note
            ]
            # Tambahan log sebelum dan sesudah proses penting
            logger.info(f"[prepend_row] Akan menulis ke sheet '{sheet_name}' dengan data: {data}")
            try:
                service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range=f'{sheet_name}!{row2_range}',
                    valueInputOption="USER_ENTERED",
                    body={"values": [row_data]}
                ).execute()
            except Exception as e:
                logger.error(f"[prepend_row] Error: {str(e)} | Sheet: {sheet_name} | Data: {data}")
                import traceback
                logger.error(traceback.format_exc())
                return False
            # Tambahan log setelah sukses
            logger.info(f"[prepend_row] Sukses menulis ke sheet '{sheet_name}' dengan data: {data}")
            return True
        except Exception as e:
            logger.error(f"Error prepending row: {str(e)}")
            return False

    def update_column_by_link(self, sheet_name, link, column_name, value):
        """Update a specific column for the row where 'Link Message' matches link."""
        try:
            service = self._initialize_service()
            all_data = self.get_all_data(sheet_name)
            if not all_data or len(all_data) < 2:
                return False
            header = all_data[0]
            try:
                link_idx = header.index('Link Message')
                col_idx = header.index(column_name)
            except ValueError:
                return False
            for i, row in enumerate(all_data[1:], start=2):  # start=2 for 1-based row number
                if len(row) > link_idx and row[link_idx] and row[link_idx].split('&cid=')[0] == link:
                    cell = f"{get_column_letter(col_idx+1)}{i}"
                    service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"{sheet_name}!{cell}",
                        valueInputOption="USER_ENTERED",
                        body={"values": [[value]]}
                    ).execute()
                    return True
            return False
        except Exception as e:
            logger.error(f"Error updating column: {str(e)}")
            return False

    def _get_sheet_id(self, sheet_name: str):
        """Get the sheetId for the current sheet_name"""
        service = self._initialize_service()
        spreadsheet = service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        available_sheets = []
        for sheet in spreadsheet['sheets']:
            available_sheets.append(sheet['properties']['title'])
            if sheet['properties']['title'] == sheet_name:
                return sheet['properties']['sheetId']
        
        # If sheet not found, log available sheets for debugging
        logger.error(f"Sheet '{sheet_name}' not found. Available sheets: {available_sheets}")
        raise ValueError(f"Sheet name '{sheet_name}' not found. Available sheets: {available_sheets}")
    
    def get_all_data(self, sheet_name: str) -> Optional[List[List]]:
        """Get all data from the spreadsheet"""
        try:
            service = self._initialize_service()
            headers = [
                'From',
                'Type',
                'Number of Feedback',
                'Product',
                'Role',
                'Modul/Fitur',
                'Reporter',
                'Reporting Date Time',
                'Response Time',
                'Resolution Time',
                'Deployment Time',
                'Response Time (Days) SLA',
                'Resolution Time (Days) SLA',
                'Resolve Time (Days) SLA',
                'SLA Status Record',
                'Responder',
                'Deskripsi',
                'Step Reproduce',
                'Severity',
                'Urgency',
                'SLA',
                'Assignee',
                'Status',
                'Scheduled Release On',
                'Link Message',
                'Related Ticket'
            ]
            num_cols = len(headers)
            last_col = get_column_letter(num_cols)
            data_range = f'A:{last_col}'
            result = service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f'{sheet_name}!{data_range}'
            ).execute()
            
            return result.get('values', [])
            
        except HttpError as e:
            logger.error(f"Error getting data from spreadsheet: {str(e)}")
            return None
    
    def clear_sheet(self, sheet_name: str) -> bool:
        """Clear all data from the sheet (except headers)"""
        try:
            service = self._initialize_service()
            # Clear data (keep headers)
            result = service.spreadsheets().values().clear(
                spreadsheetId=self.spreadsheet_id,
                range=f'{sheet_name}!A2:Z'
            ).execute()
            
            logger.info(f"Sheet {sheet_name} cleared successfully")
            return True
            
        except HttpError as e:
            logger.error(f"Error clearing sheet {sheet_name}: {str(e)}")
            return False
    
    def create_sheet_if_not_exists(self, sheet_name: str) -> bool:
        """Create sheet if it doesn't exist"""
        try:
            service = self._initialize_service()
            # Get spreadsheet metadata
            spreadsheet = service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            
            sheets = spreadsheet.get('sheets', [])
            sheet_names = [sheet['properties']['title'] for sheet in sheets]
            
            if sheet_name not in sheet_names:
                # Create new sheet
                requests = [{
                    'addSheet': {
                        'properties': {
                            'title': sheet_name
                        }
                    }
                }]
                
                service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={'requests': requests}
                ).execute()
                
                logger.info(f"Sheet '{sheet_name}' created successfully")
                
                # Add headers
                self._ensure_headers(sheet_name)
                
                return True
            
            return True
            
        except HttpError as e:
            logger.error(f"Error creating sheet: {str(e)}")
            return False
    
    def get_available_sheets(self) -> List[str]:
        """Get list of available sheet names"""
        try:
            service = self._initialize_service()
            spreadsheet = service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            sheets = spreadsheet.get('sheets', [])
            return [sheet['properties']['title'] for sheet in sheets]
        except Exception as e:
            logger.error(f"Error getting available sheets: {str(e)}")
            return []

    def get_all_links(self, sheet_name: str) -> list:
        """Get all values from the 'Link Message' column, skipping the header row."""
        all_data = self.get_all_data(sheet_name)
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

print(ssl.OPENSSL_VERSION)

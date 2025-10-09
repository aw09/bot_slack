"""
Gemini AI integration module for thread analysis
"""

import os
import logging
import google.generativeai as genai
import json
from typing import Dict, Optional

logging.basicConfig(
    level=logging.DEBUG,  # Ubah ke DEBUG
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

class GeminiAnalyzer:
    def __init__(self):
        """Initialize Gemini AI analyzer"""
        self.api_key = os.getenv('GEMINI_API_KEY')
        
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        
        # Configure Gemini
        genai.configure(api_key=self.api_key)
        
        # Initialize model
        self.model = genai.GenerativeModel('gemini-2.0-flash')
    
    def analyze_thread(self, thread_data: Dict) -> Optional[Dict]:
        """Analyze thread data using Gemini AI"""
        try:
            # Prepare thread content for analysis
            thread_content = self._prepare_thread_content(thread_data)
            
            # Create analysis prompt
            prompt = self._create_analysis_prompt(thread_content)
            
            # Generate analysis
            response = self.model.generate_content(prompt)
            
            if response.text:
                # Parse the response
                analysis = self._parse_analysis_response(response.text)
                return analysis
            
            return None
            
        except Exception as e:
            logger.error(f"Error analyzing thread with Gemini: {str(e)}")
            return None
    
    def _prepare_thread_content(self, thread_data: Dict) -> str:
        """Prepare thread content for analysis"""
        content = []
        
        # Add parent message
        parent = thread_data.get('parent_message', {})
        content.append(f"PARENT MESSAGE:")
        content.append(f"User ID: {parent.get('user', 'Unknown')}")
        content.append(f"Text: {parent.get('text', '')}")
        content.append("")
        
        # Add replies
        replies = thread_data.get('replies', [])
        if replies:
            content.append("REPLIES:")
            for i, reply in enumerate(replies, 1):
                content.append(f"{i}. User ID: {reply.get('user', 'Unknown')}")
                content.append(f"   Text: {reply.get('text', '')}")
                content.append("")
        
        # Add metadata
        content.append("METADATA:")
        content.append(f"Total messages: {thread_data.get('message_count', 0)}")
        content.append(f"Timestamp: {thread_data.get('timestamp', '')}")
        
        return "\n".join(content)
    
    def _create_analysis_prompt(self, thread_content: str) -> str:
        """Create analysis prompt for Gemini"""
        prompt = f"""
        Kamu adalah asisten QA profesional. Analisa thread berikut dan berikan hasil dalam format JSON valid seperti contoh di bawah.

THREAD:
{thread_content}

Kembalikan hanya JSON berikut (tanpa penjelasan tambahan):

{{
  "type": "menganalisis deskripsi issue atau thread diskusi di bawah ini, kemudian tentukan Type issue ke dalam salah satu kategori berikut:
                Ask → Pertanyaan, permintaan klarifikasi, atau permintaan informasi,
                Bug → Ditemukan bug, error, defect, atau malfungsi pada sistem yang harus diperbaiki,
                Feedback → Masukan untuk peningkatan, saran perbaikan UX, usability, atau usulan perubahan non-critical,
                Other → Lainnya (jika tidak ada yang sesuai)",
  "product": "Nama produk (misal: AgentLabs, LLM, Intent Base, Shopee, Email, Dialogflow, App Center, Qiscus Survey, Email Broadcast, Tiktok, Tokopedia, QCRM, CSAT, Agent Copilot atau Unknown jika tidak ada)",
  "fitur" : "Fitur yang di ambil dari hasil analisis thread merupakan fitur yang terkena bug, error, ask ,ataupun feedback",
  "description": "Ringkasan diskusi (maksimal 600 karakter, dalam bahasa Indonesia)",
  "role": "menganalisis deskripsi issue atau thread diskusi di bawah ini, lalu tentukan Role yang paling tepat untuk menangani issue tersebut:
                Backend → Backend Developer Jika issue berkaitan dengan server, API, database, logic backend,
                Frontend → Frontend Developer Jika issue berkaitan dengan tampilan UI, interaksi user, behavior di sisi klien,
                Design → UI/UX Designer Jika issue berkaitan dengan desain visual, elemen grafis, layout, UX/UI improvement,
                Other → Lainnya (jika tidak ada yang sesuai)"
  "reporter": "User ID dari user yang melaporkan/membuat thread (ambil dari PARENT MESSAGE User, contoh: U092H3HB2D7)",
  "responder": "User ID dari user yang menjawab thread (ambil dari REPLIES User, contoh: U091UAMQCF8, jika tidak ada pilih Unknown)",
  "severity": "Menganalisis deskripsi issue atau thread diskusi di bawah ini. Kemudian klasifikasikan issue tersebut ke SATU tipe berikut:
                Hotfix → Masalah kritis yang harus segera diperbaiki di produksi,
                Bugfix → Bug atau defect yang perlu diperbaiki tetapi tidak mendesak untuk langsung deploy ke produksi,
                Feature → Permintaan penambahan fitur baru atau peningkatan signifikan,
                Other (Ask) → Hal di luar ketiganya, seperti dokumentasi, tes, refactoring, atau pertanyaan",
  "urgency": " Menganalisis deskripsi issue atau diskusi thread. Kemudian tentukan prioritas/urgensi issue ke dalam salah satu tingkat berikut:
                High → Issue yang memiliki dampak besar, harus segera ditangani,
                Medium → Issue yang memiliki dampak sedang, tidak mendesak tapi perlu ditangani dalam waktu dekat,
                Low → Issue yang memiliki dampak kecil, tidak mendesak dan dapat ditangani nanti"
}}

Contoh output:
{{
  "type": "Ask",
  "product": "LLM",
  "fitur": "Export Import",
  "description": "User melaporkan error pada fitur LLM dan meminta solusi.",
  "role": "Backend",
  "reporter": "U092H3HB2D7",
  "responder": "U091UAMQCF8",
  "severity": "Bugfix",
  "urgency": "High"
}}

PENTING: 
1. Baca isi thread dengan teliti.
2. Analisis dampak & risiko issue.
3. Untuk reporter, ambil User ID dari PARENT MESSAGE. Untuk responder, ambil User ID dari REPLIES. Jangan ubah format User ID, gunakan persis seperti yang ada di data.
4. Jika hanya ada 1 pesan, tetap lakukan klasifikasi sebaik mungkin berdasarkan isi pesan.
        """
        
        return prompt
    
    def _parse_analysis_response(self, response_text: str) -> Dict:
        """Parse Gemini AI response"""
        try:
            # Clean the response text
            response_text = response_text.strip()
            
            # Try to extract JSON from the response
            if response_text.startswith('```json'):
                response_text = response_text[7:-3]
            elif response_text.startswith('```'):
                response_text = response_text[3:-3]
            
            # Parse JSON
            analysis = json.loads(response_text)
            
            # Validate required fields
            required_fields = ['type', 'product', 'fitur', 'description', 'role', 'reporter', 'responder', 'severity', 'urgency']
            for field in required_fields:
                if field not in analysis:
                    if field == 'severity':
                        analysis[field] = 'Others (Ask)'
                    elif field == 'urgency':
                        analysis[field] = 'Low'
                    else:
                        analysis[field] = 'Unknown'
            
            return analysis
            
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing Gemini response as JSON: {str(e)}")
            
            # Fallback: try to extract basic info from text
            return {
                'type': 'Other',
                'product': 'Unknown',
                'fitur': 'Unknown',
                'description': 'Gagal menganalisis thread',
                'role': 'Other',
                'reporter': 'Unknown',
                'responder': 'Unknown',
                'severity': 'Others (Ask)',
                'urgency': 'Low'
            }
        
        except Exception as e:
            logger.error(f"Error parsing analysis response: {str(e)}")
            return {
                'type': 'Other',
                'product': 'Unknown',
                'fitur': 'Unknown',
                'description': 'Error dalam analisis',
                'role': 'Other',
                'reporter': 'Unknown',
                'responder': 'Unknown',
                'severity': 'Others (Ask)',
                'urgency': 'Low'
            }

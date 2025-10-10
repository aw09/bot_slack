import os
import logging
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from bot.executor import get_executor
from bot.services.app_mention import SlackAppMentionHandler

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress DEBUG logs from slack_sdk
logging.getLogger("slack_sdk").setLevel(logging.WARNING)

# Initialize Flask app
app = Flask(__name__)

# Instantiate handlers
_app_mention_handler = SlackAppMentionHandler()
_executor = get_executor()

@app.route('/slack/events', methods=['POST'])
def slack_events():
    # Cek header retry dari Slack
    if request.headers.get('X-Slack-Retry-Num'):
        return jsonify({'status': 'ignored retry'}), 200
    try:
        data = request.get_json()
        # Handle URL verification challenge
        if data.get('type') == 'url_verification':
            return jsonify({'challenge': data.get('challenge')})
        # Handle app mention events
        if data.get('type') == 'event_callback':
            event = data.get('event', {})
            if event.get('type') == 'app_mention':
                _executor.submit(_app_mention_handler.handle_event, event)
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"Error handling Slack event: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'slack-thread-analyzer'})

def run_flask_app(port):
    """Run Flask app"""
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    # Untuk expose ke publik, jalankan: ngrok http 3000 di terminal lain
    run_flask_app(port)

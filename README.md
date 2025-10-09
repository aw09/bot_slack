# Slack Thread Analyzer Bot

Bot Slack yang menganalisis thread dan menyimpan data ke Google Spreadsheet menggunakan Gemini AI.

## Fitur

- 🤖 Analisis otomatis thread Slack menggunakan Gemini AI
- 📊 Menyimpan data ke Google Spreadsheet secara otomatis
- 🔍 Mengekstrak type, description, sentiment, dan urgency dari thread
- 📝 Mendukung perintah sederhana dalam Bahasa Indonesia
- 🔗 Menyimpan permalink thread untuk referensi
- ✅ Membuat task otomatis di Slack List untuk tindak lanjut PQF/Bug

## Setup

### 1. Persiapan Environment

```bash
# Clone atau download project
# Install dependencies
pip install -r requirements.txt
```

### 2. Konfigurasi Slack App

1. Buat aplikasi Slack di [https://api.slack.com/apps](https://api.slack.com/apps)
2. Aktifkan **Event Subscriptions** dan subscribe ke event `app_mention`
3. Tambahkan **Bot Token Scopes**:
   - `app_mentions:read`
   - `chat:write`
   - `channels:history`
   - `groups:history`
   - `groups:read`
   - `im:history`
   - `mpim:history`
   - `users:read`
   - `users:read.email`
   - `channels:join`
   - `channels:read`
   - `slacklists:write` *(untuk membuat item Lists)*
4. Install aplikasi ke workspace Slack Anda

### 3. Konfigurasi Google Sheets

1. Buat project di [Google Cloud Console](https://console.cloud.google.com/)
2. Aktifkan Google Sheets API
3. Buat Service Account dan download file JSON credentials
4. Buat Google Spreadsheet baru
5. Share spreadsheet dengan email service account (berikan akses Edit)

### 4. Konfigurasi Gemini AI

1. Dapatkan API key dari [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Simpan API key untuk konfigurasi

### 5. Environment Variables

Buat file `.env` dengan konfigurasi berikut:

```env
# Slack Bot Configuration
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_SIGNING_SECRET=your-signing-secret-here
SLACK_APP_TOKEN=xapp-your-app-token-here

# Worker Concurrency (optional)
#   - Defaults to 5 * CPU cores (min 2, max 32)
#   - Override when hosting platform limits parallel threads
THREAD_POOL_MAX_WORKERS=8

# Google Sheets Configuration
# Option A (recommended for managed hosting): inline JSON credentials
#   - For .env files, wrap in single quotes or escape quotes
#   - Alternatively, use the Base64 variant below to avoid quoting entirely
GOOGLE_APPLICATION_CREDENTIALS_JSON='{"type":"service_account","project_id":"..."}'

# Option A2 (quote-safe): Base64-encoded JSON
#   echo -n '{"type":"service_account",...}' | base64
GOOGLE_APPLICATION_CREDENTIALS_JSON_B64=eyJ0eXBlIjoic2VydmljZV9hY2NvdW50IiwiLi4u

# Option B (legacy): absolute path to a mounted credentials file
GOOGLE_SHEETS_CREDENTIALS_FILES=/path/to/your/credentials.json

SPREADSHEET_ID=your-spreadsheet-id-here
SHEET_NAME=Thread Analysis

> **Tips:** Platform seperti Railway mendukung nilai environment multiline. Gunakan menu *Bulk Edit* atau tempel langsung JSON service account ke `GOOGLE_APPLICATION_CREDENTIALS_JSON`, atau pakai `GOOGLE_APPLICATION_CREDENTIALS_JSON_B64` jika ingin paste satu baris Base64.

# Gemini AI Configuration
GEMINI_API_KEY=your-gemini-api-key-here

# Slack List Integration (Optional)
SLACK_LIST_ID=F1234ABCD
SLACK_LIST_COLUMN_NAMES={"title":"Title","link":"Thread Link","status":"Status","description":"Description","product":"Product","reporter":"Reporter"}
# Atau simpan mapping di file JSON dan tunjukkan lokasinya
# SLACK_LIST_COLUMN_NAMES_FILE=./config/slack_list_columns.json

# Status default berdasarkan label yang muncul di Slack List
SLACK_LIST_DEFAULT_STATUS_NAME=New
SLACK_LIST_PQF_STATUS_NAME=New
SLACK_LIST_LINK_DISPLAY_NAME=Slack Thread

# (Opsional) Fallback legacy jika ingin menyetel ID kolom secara manual
# SLACK_LIST_TITLE_COLUMN_ID=ColTitle123
# SLACK_LIST_DESCRIPTION_COLUMN_ID=ColDesc123
# ... dan seterusnya
# SLACK_LIST_STATUS_OPTIONS={"New":"OptNew123","In Progress":"OptInProgress123"}

Bot akan mencoba mendeteksi kolom Slack List secara otomatis berdasarkan nama kolom (`Title`, `Status`, `Product`, dll). Bila nama kolom workspace berbeda, set `SLACK_LIST_COLUMN_NAMES` (atau file JSON) dengan `key -> display name` agar mappingnya tepat. Legacy environment variables masih didukung untuk kompatibilitas dan menjadi fallback jika auto-detect gagal (misalnya tidak mempunyai izin membaca schema List).

### 6. Konfigurasi ngrok (Opsional untuk Development)

Untuk development lokal, bot akan otomatis menggunakan ngrok:

1. Download dan install [ngrok](https://ngrok.com/download)
2. Daftar akun ngrok dan dapatkan auth token
3. Tambahkan `NGROK_AUTH_TOKEN` ke file `.env`
4. Set `USE_NGROK=true` di file `.env`

## Cara Menjalankan

### Development
```bash
# Bot akan otomatis start ngrok tunnel dan menampilkan URL
python apps.py

# Output akan menampilkan:
# 🌐 ngrok tunnel started: https://abc123.ngrok.io
# 📝 Update your Slack app Request URL to: https://abc123.ngrok.io/slack/events
```

**Catatan:** Saat running development, copy URL ngrok yang ditampilkan dan update di Slack App settings > Event Subscriptions > Request URL

### Production
```bash
gunicorn -w 4 -b 0.0.0.0:3000 apps:app
```

## Cara Menggunakan

### Perintah Bot

1. **Analisis Thread:**
   ```
   @botSpread masukkan ke pqf
   ```
   atau
   ```
   @botSpread masukkan ke spreadsheet
   ```

2. **Help:**
   ```
   @botSpread help
   ```

### Contoh Penggunaan

1. Panggil bot dalam sebuah thread Slack
2. Gunakan perintah `@botSpread masukkan ke pqf`
3. Bot akan menganalisis thread dan menyimpan data ke spreadsheet

## Data yang Disimpan

Bot akan menyimpan data berikut ke Google Spreadsheet:

- **Timestamp**: Waktu thread dibuat
- **Type**: Kategori thread (Question, Discussion, Bug Report, dll.)
- **Description**: Deskripsi singkat thread
- **Link**: Permalink ke thread Slack
- **User**: Pembuat thread
- **Channel**: Channel tempat thread berada
- **Sentiment**: Sentiment keseluruhan (Positive, Negative, Neutral)
- **Urgency**: Level urgensi (Low, Medium, High)
- **Participants**: Jumlah peserta dalam thread
- **Summary**: Ringkasan detail diskusi
- **Created At**: Waktu data disimpan

## Struktur File

```
├── apps.py              # Aplikasi utama Flask
├── slack_bot.py         # Integrasi Slack API
├── gemini_hook.py       # Integrasi Gemini AI
├── spreadsheet.py       # Integrasi Google Sheets
├── requirements.txt     # Dependencies Python
├── .env                 # Environment variables
└── README.md           # Dokumentasi
```

## Troubleshooting

### Error "SLACK_BOT_TOKEN not found"
- Pastikan file `.env` ada dan berisi token yang benar
- Verifikasi token di Slack App settings

### Error "Permission denied" untuk Google Sheets
- Pastikan service account memiliki akses Edit ke spreadsheet
- Verifikasi file credentials JSON sudah benar

### Error Gemini AI
- Pastikan API key Gemini sudah benar
- Periksa quota API key di Google AI Studio

### Bot tidak merespon
- Periksa Event Subscriptions di Slack App
- Pastikan bot sudah diinvite ke channel
- Verifikasi webhook URL sudah benar

## Deployment

### Menggunakan Railway/Heroku

1. Deploy aplikasi ke platform pilihan
2. Set environment variables
   - Tempel seluruh isi file service account ke variabel `GOOGLE_APPLICATION_CREDENTIALS_JSON` (gunakan single quotes saat di `.env` lokal)
   - Atau encode ke Base64 dan set `GOOGLE_APPLICATION_CREDENTIALS_JSON_B64`
   - (Opsional) Jika tetap memakai file, upload ke storage/volume dan set `GOOGLE_SHEETS_CREDENTIALS_FILES`
3. Update Request URL di Slack App settings
4. Pastikan webhook endpoint dapat diakses publik

### Menggunakan ngrok (Development)

```bash
# Ngrok akan otomatis start saat menjalankan apps.py
python apps.py

# Copy URL yang ditampilkan dan update di Slack App settings
# Contoh: https://abc123.ngrok.io/slack/events
```

## Kontribusi

Silakan buat issue atau pull request untuk perbaikan dan penambahan fitur.

## Lisensi

MIT License

"""High-level workflows for handling Slack app mentions."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from slack_sdk.errors import SlackApiError

from ..config import Settings, get_settings
from ..container import ServiceContainer, container
from ..executor import get_executor

logger = logging.getLogger(__name__)


@dataclass
class ThreadContext:
    channel: str
    ts: str
    thread_ts: Optional[str]
    user: Optional[str]
    text: str

    @property
    def is_parent_message(self) -> bool:
        return not self.thread_ts or self.thread_ts == self.ts


class SlackAppMentionHandler:
    """Encapsulates the branching logic for app mentions."""

    def __init__(
        self,
        services: ServiceContainer = container,
        settings: Settings | None = None,
    ):
        self._services = services
        self._settings = settings or get_settings()
        self._executor = get_executor()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def handle_event(self, event: Dict) -> None:
        context = ThreadContext(
            channel=event.get("channel", ""),
            ts=event.get("ts", ""),
            thread_ts=event.get("thread_ts"),
            user=event.get("user"),
            text=event.get("text", ""),
        )
        if not self._is_allowed_channel(context.channel):
            logger.info("Ignored event from channel %s (not allowed)", context.channel)
            return

        if context.is_parent_message:
            self._handle_parent_thread(context)
            return

        lowered_text = context.text.lower()
        if "pqf" in lowered_text:
            self._handle_pqf_command(context)
        elif "resolution" in lowered_text or "resolve" in lowered_text:
            self._executor.submit(self._handle_resolution_command, context, lowered_text)
        elif "ticket" in lowered_text:
            self._handle_ticket_command(context)
        elif "confirm bug" in lowered_text or "feedback" in lowered_text:
            self._handle_feedback_confirmation(context)
        else:
            self._send_help_message(context.channel, context.thread_ts or context.ts)

    # ------------------------------------------------------------------
    # Parent thread handling
    # ------------------------------------------------------------------
    def _handle_parent_thread(self, context: ThreadContext) -> None:
        slack_client = self._services.slack_bot
        slack_client.send_message(
            context.channel,
            "Mohon maaf atas ketidaknyamanan yang terjadi 🙏. Terima kasih atas laporanya! "
            "Laporanmu sudah masuk ke antrian dan akan segera kami proses. Harap menunggu ya, QFolks!",
            thread_ts=context.ts,
        )

        thread_data = slack_client.get_thread_data(context.channel, context.ts)
        if not thread_data:
            logger.warning("Cannot retrieve thread data for channel=%s ts=%s", context.channel, context.ts)
            return

        parent_ts = thread_data.get("parent_message", {}).get("ts")
        if not parent_ts:
            logger.info("Thread data missing parent timestamp; skipping spreadsheet write")
            return

        dt_parent = datetime.fromtimestamp(float(parent_ts))
        quarter = self._derive_quarter(dt_parent)
        product_sheet = self._resolve_product_sheet(thread_data)
        if product_sheet is None:
            self._notify_unknown_product(thread_data, dt_parent)
            return

        sheet_name = f"{quarter} {dt_parent.year} {product_sheet}"
        spreadsheet_manager = self._services.spreadsheet_manager
        spreadsheet_manager.create_sheet_if_not_exists(sheet_name)

        permalink = self._clean_permalink(thread_data.get("permalink", ""))
        if permalink in self._sanitize_links(spreadsheet_manager.get_all_links(sheet_name)):
            logger.info("Thread %s already exists in sheet %s", permalink, sheet_name)
            return

        analysis = self._services.gemini_analyzer.analyze_thread(thread_data)
        if not analysis:
            logger.warning("Gemini analysis failed for thread %s", permalink)
            return

        row_data = self._build_parent_row(thread_data, analysis, dt_parent, permalink)
        if spreadsheet_manager.prepend_row(row_data, sheet_name):
            self._announce_recording(thread_data, dt_parent, quarter)
        else:
            logger.error("Failed to prepend row into sheet %s", sheet_name)

    # ------------------------------------------------------------------
    # PQF command handling
    # ------------------------------------------------------------------
    def _handle_pqf_command(self, context: ThreadContext) -> None:
        if context.channel not in self._settings.forward_channel_ids:
            self._send_help_message(context.channel, context.thread_ts or context.ts)
            return

        from_value, product, error = self._validate_pqf_command(context.text)
        if error:
            self._send_help_message(context.channel, context.thread_ts or context.ts)
            return
        if not from_value or not product:
            logger.info("PQF command missing required sections: %s", context.text)
            return

        thread_data = self._get_original_thread_data(context)
        if not thread_data:
            self._services.slack_bot.send_message(
                context.channel,
                f"<@{context.user}> Tidak dapat mengambil data thread. Pastikan bot dipanggil dalam sebuah thread.",
                thread_ts=context.thread_ts or context.ts,
            )
            return

        permalink = self._clean_permalink(thread_data.get("permalink", ""))
        spreadsheet_manager = self._services.spreadsheet_manager
        parent_ts = thread_data.get("parent_message", {}).get("ts")
        sheet_name = self._derive_sheet_name(product, parent_ts)
        if permalink in self._sanitize_links(spreadsheet_manager.get_all_links(sheet_name)):
            self._services.slack_bot.send_message(
                context.channel,
                f"<@{context.user}> Thread ini sudah pernah dianalisis dan dicatat di spreadsheet.",
                thread_ts=context.thread_ts or context.ts,
            )
            return

        self._services.slack_bot.send_message(
            context.channel,
            "✅ Sudah masuk ke List PQF",
            thread_ts=context.thread_ts or context.ts,
        )
        self._executor.submit(
            self._process_thread_data,
            thread_data,
            context.channel,
            context.user,
            context.thread_ts or context.ts,
            from_value,
            sheet_name,
        )

    # ------------------------------------------------------------------
    # Resolution / resolve handling
    # ------------------------------------------------------------------
    def _handle_resolution_command(self, context: ThreadContext, lowered_text: str) -> None:
        thread_data = self._services.slack_bot.get_thread_data(context.channel, context.thread_ts or context.ts)
        if not thread_data:
            self._services.slack_bot.send_message(
                context.channel,
                f"<@{context.user}> Tidak dapat mengambil data thread.",
                thread_ts=context.ts,
            )
            return

        permalink = self._clean_permalink(thread_data.get("permalink", ""))
        spreadsheet_manager = self._services.spreadsheet_manager
        updated = False
        updated_sheet = None
        column_name = "Resolution Time" if "resolution" in lowered_text else "Deployment Time"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        for sheet in spreadsheet_manager.get_available_sheets():
            links = self._sanitize_links(spreadsheet_manager.get_all_links(sheet))
            if permalink in links:
                updated = spreadsheet_manager.update_column_by_link(sheet, permalink, column_name, now)
                updated_sheet = sheet
                break

        if not updated:
            self._services.slack_bot.send_message(
                context.channel,
                f"<@{context.user}>Saat ini bot tidak dapat menindaklanjuti issue melalui kolom komentar."
                "Kami sudah mencatat informasi ini dan akan menindaklanjutinya secara manual. Terima kasih atas kesabarannya!",
                thread_ts=context.ts,
            )
            return

        reporter_mention = self._resolve_reporter_mention(thread_data)
        message = self._build_resolution_message(lowered_text, reporter_mention)
        self._services.slack_bot.send_message(context.channel, message, thread_ts=context.ts)
        logger.info("Updated %s for permalink %s in sheet %s", column_name, permalink, updated_sheet)

    # ------------------------------------------------------------------
    # Ticket command handling
    # ------------------------------------------------------------------
    def _handle_ticket_command(self, context: ThreadContext) -> None:
        thread_data_forward = self._services.slack_bot.get_thread_data(context.channel, context.thread_ts or context.ts)
        if not thread_data_forward:
            logger.error("Ticket command: cannot fetch forward thread data")
            return

        channel_real, thread_ts_real, permalink = self._resolve_original_thread(thread_data_forward)
        if not channel_real or not thread_ts_real:
            logger.error("Ticket command: unable to resolve original thread for context %s", context)
            return

        original_thread = self._services.slack_bot.get_thread_data(channel_real, thread_ts_real)
        if not original_thread:
            logger.error("Ticket command: unable to fetch original thread data")
            return

        bug_manager = self._services.spreadsheet_bug_manager
        sheet_name = self._settings.bug_sheet_name
        parent = original_thread.get("parent_message", {})
        parent_ts = parent.get("ts")
        dt_parent = datetime.fromtimestamp(float(parent_ts)) if parent_ts else None
        reporting_date_time = dt_parent.strftime("%Y-%m-%d %H:%M") if dt_parent else ""
        analysis = self._services.gemini_analyzer.analyze_thread(original_thread) or {}
        reporter_name = self._lookup_user_name(parent.get("user"), analysis)

        code_value = self._generate_bug_code(bug_manager, sheet_name)
        row_data = {
            "from": "Eksternal",
            "type": analysis.get("type", ""),
            "code": code_value,
            "product": analysis.get("product", ""),
            "role": analysis.get("role", ""),
            "fitur": analysis.get("fitur", ""),
            "reporter": reporter_name,
            "reporting_date_time": reporting_date_time,
            "deskripsi": analysis.get("description", ""),
            "step reproduce": "",
            "severity": analysis.get("severity", ""),
            "urgency": analysis.get("urgency", ""),
            "assignee": "",
            "status": "",
            "scheduled release on": "",
            "link": permalink,
            "note": "",
        }

        try:
            is_new = bug_manager.prepend_row_bug(row_data, sheet_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to prepend bug row: %s", exc)
            self._services.slack_bot.send_message(context.channel, f"Gagal mencatat bug: {exc}", thread_ts=context.thread_ts or context.ts)
            return

        if not is_new:
            logger.info("Duplicate bug detected for permalink %s", permalink)
            return

        self._update_related_ticket(permalink, code_value)
        self._services.slack_bot.send_message(
            context.channel,
            f"✅ Ticketmu sudah tercatat di bug tracking dengan kode: {code_value}",
            thread_ts=context.thread_ts or context.ts,
        )

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
    def _handle_feedback_confirmation(self, context: ThreadContext) -> None:
        from_value, sheet_name, _ = self._validate_pqf_command(context.text)
        sheet_name = sheet_name or "Thread Analysis"
        self._services.slack_bot.send_message(
            context.channel,
            f"Laporanmu sudah masuk ke list PQF di sheet {sheet_name} untuk proses tindak lanjut, ya QFolks!",
            thread_ts=context.thread_ts or context.ts,
        )

    def _send_help_message(self, channel: str, thread_ts: str) -> None:
        help_message = (
            "Saat ini bot tidak dapat menindaklanjuti issue melalui kolom komentar. Informasi terkait bug/issue/feedback "
            "tersebut sudah kami terima dan sedang diproses oleh tim kami. Pembaruan dan respon akan disampaikan oleh tim kami "
            "setelah ada perkembangan lebih lanjut. Terimakasih."
        )
        self._services.slack_bot.send_message(channel, help_message, thread_ts=thread_ts)

    def _validate_pqf_command(self, text: str):
        cleaned = re.sub(r"<@[^>]+>", "", text).strip().lower()
        valid_froms = {"internal", "eksternal"}
        valid_products = {"agentlabs", "appcenter"}
        from_match = re.search(r"(internal|eksternal)", cleaned)
        product_match = re.search(r"(agentlabs|appcenter)", cleaned)

        if not from_match or "pqf" not in cleaned or not product_match:
            return None, None, "Format perintah tidak valid"

        from_value = from_match.group(1).capitalize()
        product = product_match.group(1).capitalize()
        if from_value.lower() not in valid_froms:
            return None, None, f"From harus 'internal' atau 'eksternal', bukan '{from_value}'"
        if product.lower() not in valid_products:
            return None, None, f"Product harus 'agentlabs' atau 'appcenter', bukan '{product}'"
        return from_value, product, None

    def _is_allowed_channel(self, channel: str) -> bool:
        return not self._settings.allowed_channels or channel in self._settings.allowed_channels

    @staticmethod
    def _derive_quarter(moment: datetime) -> str:
        month = moment.month
        if 1 <= month <= 3:
            return "Q1"
        if 4 <= month <= 6:
            return "Q2"
        if 7 <= month <= 9:
            return "Q3"
        return "Q4"

    @staticmethod
    def _clean_permalink(permalink: str) -> str:
        if "&cid=" in permalink:
            return permalink.split("&cid=")[0]
        return permalink

    @staticmethod
    def _sanitize_links(links: list[str]) -> set[str]:
        sanitized = set()
        for link in links or []:
            sanitized.add(SlackAppMentionHandler._clean_permalink(link or ""))
        return sanitized

    def _notify_unknown_product(self, thread_data: Dict, dt_parent: datetime) -> None:
        forward_channel = next(iter(self._settings.forward_channel_ids), None)
        if not forward_channel:
            return
        slack_bot = self._services.slack_bot
        try:
            bot_user_id = self._settings.user_id_slack_bot or slack_bot.client.auth_test()["user_id"]
        except SlackApiError as exc:  # pragma: no cover - defensive
            logger.error("auth_test failed: %s", exc)
            bot_user_id = ""

        info_text = (
            f"[{self._derive_quarter(dt_parent)}] [{dt_parent.year}] [Week {((dt_parent.day - 1) // 7) + 1}] "
            f"[Date {dt_parent.day} - {dt_parent.strftime('%B')}] [Tidak Tercatat] [{f'<@{bot_user_id}>' if bot_user_id else ''}]"
        )
        permalink = self._clean_permalink(thread_data.get("permalink", ""))
        slack_bot.client.chat_postMessage(channel=forward_channel, text=info_text + "\n" + permalink)

    def _resolve_product_sheet(self, thread_data: Dict) -> Optional[str]:
        analysis = self._services.gemini_analyzer.analyze_thread(thread_data)
        if not analysis:
            return None
        product_raw = (analysis.get("product") or "").strip().lower()
        agentlabs_keywords = ["agentlabs", "llm", "intent base", "dialogflow"]
        appcenter_keywords = [
            "shopee",
            "email",
            "qcrm",
            "appcenter",
            "survey",
            "tokopedia",
            "email broadcast",
            "tiktok",
            "csat",
            "agent copilot",
        ]
        if any(keyword in product_raw for keyword in agentlabs_keywords):
            return "Agentlabs"
        if any(keyword in product_raw for keyword in appcenter_keywords):
            return "Appcenter"
        return None

    def _build_parent_row(self, thread_data: Dict, analysis: Dict, dt_parent: datetime, permalink: str) -> Dict:
        slack_bot = self._services.slack_bot
        bot_user_id = slack_bot.client.auth_test()["user_id"]
        bot_info = slack_bot.get_user_info(bot_user_id)
        bot_name = bot_info.get("real_name", bot_info.get("name", "Bot")) if bot_info else "Bot"

        response_time = "Unknown"
        responder_name = "Unknown"
        for reply in thread_data.get("replies", []):
            if reply.get("user") == bot_user_id:
                responder_name = bot_name
                ts_reply = reply.get("ts")
                if ts_reply:
                    response_time = datetime.fromtimestamp(float(ts_reply)).strftime("%Y-%m-%d %H:%M")
                break

        reporter = analysis.get("reporter", "Unknown")
        reporter_name = self._resolve_user_name(reporter)

        return {
            "from": "Eksternal",
            "type": analysis.get("type", "Unknown"),
            "product": analysis.get("product", "Unknown"),
            "role": "",
            "fitur": analysis.get("fitur", "Unknown"),
            "reporter": reporter_name,
            "reporting_date_time": dt_parent.strftime("%Y-%m-%d %H:%M"),
            "responder": responder_name,
            "description": analysis.get("description", "No description"),
            "link": permalink,
            "response_time": response_time,
            "severity": "",
            "urgency": "",
        }

    def _announce_recording(self, thread_data: Dict, dt_parent: datetime, quarter: str) -> None:
        forward_channel = next(iter(self._settings.forward_channel_ids), None)
        if not forward_channel:
            return
        permalink = self._clean_permalink(thread_data.get("permalink", ""))
        info_text = (
            f"[{quarter}] [{dt_parent.year}] [Week {((dt_parent.day - 1) // 7) + 1}] "
            f"[Date {dt_parent.day} - {dt_parent.strftime('%B')}] [Tercatat]"
        )
        self._services.slack_bot.client.chat_postMessage(channel=forward_channel, text=info_text + "\n" + permalink)

    def _process_thread_data(
        self,
        thread_data,
        channel,
        user,
        thread_ts,
        from_value,
        sheet_name,
    ) -> None:
        permalink = self._clean_permalink(thread_data.get("permalink", ""))
        spreadsheet_manager = self._services.spreadsheet_manager
        if permalink in self._sanitize_links(spreadsheet_manager.get_all_links(sheet_name)):
            self._services.slack_bot.send_message(
                channel,
                f"<@{user}> Thread ini sudah pernah dianalisis dan dicatat di spreadsheet.",
                thread_ts=thread_ts,
            )
            return

        analysis = self._services.gemini_analyzer.analyze_thread(thread_data)
        if not analysis:
            self._services.slack_bot.send_message(
                channel,
                f"<@{user}> ❌ Gagal menganalisis thread dengan Gemini AI.",
                thread_ts=thread_ts,
            )
            return

        row_data = {
            "from": from_value,
            "type": analysis.get("type", "Unknown"),
            "product": analysis.get("product", "Unknown"),
            "role": analysis.get("role", "Unknown"),
            "fitur": analysis.get("fitur", "Unknown"),
            "reporter": self._resolve_user_name(analysis.get("reporter", "Unknown")),
            "reporting_date_time": self._timestamp_to_string(thread_data.get("parent_message", {}).get("ts")),
            "responder": self._collect_responder_names(thread_data),
            "description": analysis.get("description", "No description"),
            "link": permalink,
            "response_time": self._first_response_time(thread_data),
            "severity": analysis.get("severity", "Others (Ask)"),
            "urgency": analysis.get("urgency", "Medium"),
        }
        if not spreadsheet_manager.prepend_row(row_data, sheet_name):
            self._services.slack_bot.send_message(
                channel,
                f"<@{user}> ❌ Analisis berhasil, tetapi gagal menyimpan ke spreadsheet {sheet_name}.",
                thread_ts=thread_ts,
            )

    def _get_original_thread_data(self, context: ThreadContext):
        slack_bot = self._services.slack_bot
        thread_data = slack_bot.get_thread_data(context.channel, context.thread_ts or context.ts)
        if not thread_data:
            return None
        parent = thread_data.get("parent_message", {})
        permalink = parent.get("permalink")
        if permalink and parent.get("ts"):
            channel_real, thread_ts_real = self._parse_slack_permalink(permalink.split("?")[0])
        else:
            channel_real, thread_ts_real = None, None
            text_parent = parent.get("text", "")
            match = re.search(r"<(https://[^>]+)>", text_parent)
            if match:
                channel_real, thread_ts_real = self._parse_slack_permalink(match.group(1).split("?")[0])

        if channel_real and thread_ts_real:
            return slack_bot.get_thread_data(channel_real, thread_ts_real)
        return thread_data

    @staticmethod
    def _parse_slack_permalink(permalink: str):
        match = re.search(r"/archives/([A-Z0-9]+)/p(\d+)", permalink)
        channel_id = None
        thread_ts = None
        if match:
            channel_id = match.group(1)
            ts_str = match.group(2)
            if len(ts_str) > 6:
                thread_ts = ts_str[:10] + "." + ts_str[10:]
        query_match = re.search(r"thread_ts=(\d+\.\d+)", permalink)
        if query_match:
            thread_ts = query_match.group(1)
        return channel_id, thread_ts

    def _derive_sheet_name(self, product: str, parent_ts: Optional[str]) -> str:
        if not parent_ts:
            return "Thread Analysis"
        dt_parent = datetime.fromtimestamp(float(parent_ts))
        quarter = self._derive_quarter(dt_parent)
        return f"{quarter} {dt_parent.year} {product}"

    def _resolve_reporter_mention(self, thread_data: Dict) -> str:
        reporter_id = thread_data.get("reporter")
        if reporter_id:
            return f"<@{reporter_id}>"
        analysis = self._services.gemini_analyzer.analyze_thread(thread_data) or {}
        reporter_id = analysis.get("reporter")
        if reporter_id:
            return f"<@{reporter_id}>"
        return "Reporter"

    def _build_resolution_message(self, lowered_text: str, reporter_name: str) -> str:
        if "resolution" in lowered_text:
            return (
                f"Halo {reporter_name} 👋\n\n"
                "Laporan yang anda sampaikan sudah selesai direproduksi dan dianalisis.\n"
                "Solusinya juga sudah ditemukan dan saat ini sedang dalam tahap pengerjaan.\n"
                "STATUS: 🚧 On Progress - Dev Team.\n"
                "Kami akan memberikan informasi selanjutnya setelah proses pengerjaan selesai."
                "Terima kasih atas kesabarannya! 🙏\n\nSalam,\nTim Profeat"
            )
        return (
            f"Halo {reporter_name} 👋\n\n"
            "Laporan telah terselesaikan dan perbaikan sudah diimplementasikan serta aktif di sistem! 🚀\n"
            "Apabila masih ditemukan kendala setelah implementasi, silakan informasikan kembali.\n"
            "Terima kasih atas laporan serta kolaborasinya 🙏.\n\nSalam,\nTim Profeat"
        )

    def _resolve_original_thread(self, thread_data_forward: Dict):
        parent = thread_data_forward.get("parent_message", {})
        permalink = parent.get("permalink")
        if permalink and parent.get("ts"):
            channel_real, thread_ts_real = self._parse_slack_permalink(permalink.split("?")[0])
            return channel_real, thread_ts_real, self._clean_permalink(permalink)
        text = parent.get("text", "")
        match = re.search(r"<(https://[^>]+)>", text)
        if match:
            permalink = match.group(1)
            channel_real, thread_ts_real = self._parse_slack_permalink(permalink.split("?")[0])
            return channel_real, thread_ts_real, self._clean_permalink(permalink)
        fallback_permalink = thread_data_forward.get("permalink")
        if fallback_permalink:
            channel_real, thread_ts_real = self._parse_slack_permalink(fallback_permalink.split("?")[0])
            return channel_real, thread_ts_real, self._clean_permalink(fallback_permalink)
        return None, None, ""

    def _lookup_user_name(self, user_id: Optional[str], analysis: Dict) -> str:
        if user_id:
            info = self._services.slack_bot.get_user_info(user_id)
            if info:
                return info.get("real_name", info.get("name", user_id))
            return user_id
        return analysis.get("reporter", "Unknown")

    def _generate_bug_code(self, bug_manager, sheet_name: str) -> str:
        all_codes = []
        try:
            rows = bug_manager.get_all_bugs(sheet_name)
        except Exception:
            rows = None
        if rows and len(rows) > 1:
            header = rows[0]
            try:
                code_idx = header.index("Code")
            except ValueError:
                code_idx = None
            if code_idx is not None:
                for row in rows[1:]:
                    if len(row) > code_idx:
                        code_val = row[code_idx]
                        if isinstance(code_val, str) and code_val.startswith("QR-"):
                            try:
                                num = int(code_val.replace("QR-", "").lstrip("0") or "0")
                                all_codes.append(num)
                            except ValueError:
                                continue
        next_code = (max(all_codes) if all_codes else 0) + 1
        return f"QR-{next_code:03d}"

    def _update_related_ticket(self, permalink: str, code_value: str) -> None:
        spreadsheet_manager = self._services.spreadsheet_manager
        for sheet in spreadsheet_manager.get_available_sheets():
            links = self._sanitize_links(spreadsheet_manager.get_all_links(sheet))
            if permalink in links:
                spreadsheet_manager.update_column_by_link(sheet, permalink, "Related Ticket", code_value)
                return
        logger.info("No sheet contains permalink %s for related ticket update", permalink)

    def _resolve_user_name(self, user_id: Optional[str]) -> str:
        if not user_id or user_id == "Unknown":
            return "Unknown"
        info = self._services.slack_bot.get_user_info(user_id)
        if info:
            return info.get("real_name", info.get("name", user_id))
        return user_id

    def _timestamp_to_string(self, ts: Optional[str]) -> str:
        if not ts:
            return ""
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")

    def _collect_responder_names(self, thread_data: Dict) -> str:
        responders = set()
        for reply in thread_data.get("replies", []):
            user_id = reply.get("user")
            if not user_id:
                continue
            info = self._services.slack_bot.get_user_info(user_id)
            if info:
                name = info.get("real_name", info.get("name", user_id))
                responders.add(name)
        return ", ".join(sorted(responders)) or "Unknown"

    def _first_response_time(self, thread_data: Dict) -> str:
        first_ts = None
        for reply in thread_data.get("replies", []):
            ts = reply.get("ts")
            if ts and (first_ts is None or float(ts) < float(first_ts)):
                first_ts = ts
        if first_ts:
            return datetime.fromtimestamp(float(first_ts)).strftime("%Y-%m-%d %H:%M")
        parent_ts = thread_data.get("parent_message", {}).get("ts")
        return self._timestamp_to_string(parent_ts)

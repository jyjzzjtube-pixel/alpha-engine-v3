"""
AI Command Center - Master Bot
===============================
Telegram bot with Gemini AI integration for automated task management.

Architecture:
  [Telegram] --> [Auth Gate] --> [Command Router] --> [Gemini AI / File Handler / Reporter]
                                                            |
                                                     [Screenshot + Report back to Telegram]
"""

import os
import sys
import json
import logging
import asyncio
import traceback
import subprocess
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# ─── Load .env from parent franchise-db directory ───
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

# ─── Configuration ───
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ─── Paths ───
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
DOWNLOADS_DIR = BASE_DIR / "downloads"
LOG_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)

# ─── Logging ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "master_bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("MasterBot")


# ══════════════════════════════════════════════════════════
#  1. SECURITY GATE - Only accept messages from owner
# ══════════════════════════════════════════════════════════
def is_authorized(chat_id: int) -> bool:
    """Check if the incoming chat_id matches the allowed owner."""
    if ALLOWED_CHAT_ID == 0:
        logger.warning("TELEGRAM_CHAT_ID not set - rejecting all messages")
        return False
    return chat_id == ALLOWED_CHAT_ID


# ══════════════════════════════════════════════════════════
#  2. GEMINI AI ENGINE
# ══════════════════════════════════════════════════════════
class GeminiEngine:
    """Wrapper for Google Gemini API calls."""

    def __init__(self):
        self.model = None
        self._init_model()

    def _init_model(self):
        if not GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set - AI features disabled")
            return
        try:
            from google import genai
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            self.model_name = "gemini-2.0-flash"
            self.model = True  # flag for availability check
            logger.info(f"Gemini client initialized: {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini: {e}")

    async def generate_text(self, prompt: str) -> str:
        """Generate text response from Gemini."""
        if not self.model:
            return "[Gemini unavailable] AI 모델이 초기화되지 않았습니다."
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=prompt,
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini generation error: {e}")
            return f"[Gemini Error] {str(e)}"

    async def summarize(self, text: str) -> str:
        """Summarize text using Gemini."""
        prompt = f"""다음 텍스트를 핵심 포인트 위주로 한국어로 간결하게 요약해줘:

{text}"""
        return await self.generate_text(prompt)

    async def analyze_image_from_bytes(self, image_bytes: bytes, question: str = "") -> str:
        """Analyze an image using Gemini Vision."""
        if not self.model:
            return "[Gemini unavailable]"
        try:
            from PIL import Image
            from google.genai import types
            import io
            img = Image.open(io.BytesIO(image_bytes))
            prompt = question if question else "이 이미지를 분석하고 한국어로 설명해줘."
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model_name,
                contents=[prompt, img],
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini vision error: {e}")
            return f"[Vision Error] {str(e)}"


# ══════════════════════════════════════════════════════════
#  3. SCREENSHOT UTILITY
# ══════════════════════════════════════════════════════════
async def take_screenshot() -> Optional[bytes]:
    """Capture the current screen and return as PNG bytes."""
    try:
        from PIL import ImageGrab
        screenshot = await asyncio.to_thread(ImageGrab.grab)
        buffer = BytesIO()
        screenshot.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception as e:
        logger.error(f"Screenshot failed: {e}")
        return None


# ══════════════════════════════════════════════════════════
#  4. FILE DOWNLOAD HANDLER
# ══════════════════════════════════════════════════════════
async def download_file(url: str, filename: str = "") -> Path:
    """Download a file from URL to the downloads directory."""
    import requests
    if not filename:
        filename = url.split("/")[-1].split("?")[0] or "download"
    filepath = DOWNLOADS_DIR / filename
    logger.info(f"Downloading: {url} -> {filepath}")
    response = await asyncio.to_thread(
        lambda: requests.get(url, stream=True, timeout=60)
    )
    response.raise_for_status()
    with open(filepath, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"Downloaded: {filepath} ({filepath.stat().st_size:,} bytes)")
    return filepath


# ══════════════════════════════════════════════════════════
#  5. COMMAND EXECUTOR (shell commands)
# ══════════════════════════════════════════════════════════
async def execute_command(cmd: str) -> str:
    """Execute a shell command and return output (max 4000 chars for Telegram)."""
    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30,
                cwd=str(BASE_DIR)
            )
        )
        output = result.stdout + result.stderr
        if len(output) > 4000:
            output = output[:2000] + "\n...[truncated]...\n" + output[-1500:]
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "[Timeout] 명령어가 30초 초과"
    except Exception as e:
        return f"[Error] {str(e)}"


# ══════════════════════════════════════════════════════════
#  6. TELEGRAM BOT HANDLERS
# ══════════════════════════════════════════════════════════
def build_bot():
    """Build and configure the Telegram bot application."""
    from telegram import Update, BotCommand
    from telegram.ext import (
        ApplicationBuilder, CommandHandler, MessageHandler,
        filters, ContextTypes,
    )

    gemini = GeminiEngine()

    # ── Auth wrapper ──
    def auth_required(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not is_authorized(update.effective_chat.id):
                logger.warning(f"Unauthorized access attempt: {update.effective_chat.id}")
                await update.message.reply_text("Unauthorized. Access denied.")
                return
            return await func(update, context)
        return wrapper

    # ── /start ──
    @auth_required
    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        welcome = (
            "AI Command Center Online\n\n"
            "Available Commands:\n"
            "/ai <prompt> - Gemini AI query\n"
            "/summary <text> - Text summarization\n"
            "/screenshot - Capture current screen\n"
            "/download <url> - Download a file\n"
            "/exec <cmd> - Execute shell command\n"
            "/cost [detail] - API cost report (KRW/USD)\n"
            "/status - System status check\n"
            "/help - Show this message"
        )
        await update.message.reply_text(welcome)

    # ── /ai ──
    @auth_required
    async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
        prompt = " ".join(context.args) if context.args else ""
        if not prompt:
            await update.message.reply_text("Usage: /ai <your question>")
            return
        await update.message.reply_text("Thinking...")
        result = await gemini.generate_text(prompt)
        # Split long messages (Telegram 4096 char limit)
        for i in range(0, len(result), 4000):
            await update.message.reply_text(result[i:i+4000])

    # ── /summary ──
    @auth_required
    async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = " ".join(context.args) if context.args else ""
        if not text:
            await update.message.reply_text("Usage: /summary <text to summarize>")
            return
        await update.message.reply_text("Summarizing...")
        result = await gemini.summarize(text)
        await update.message.reply_text(result[:4000])

    # ── /screenshot ──
    @auth_required
    async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Capturing screen...")
        img_bytes = await take_screenshot()
        if img_bytes:
            await update.message.reply_photo(
                photo=BytesIO(img_bytes),
                caption=f"Screenshot: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        else:
            await update.message.reply_text("Screenshot failed.")

    # ── /download ──
    @auth_required
    async def cmd_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /download <url> [filename]")
            return
        url = context.args[0]
        filename = context.args[1] if len(context.args) > 1 else ""
        try:
            await update.message.reply_text(f"Downloading: {url}")
            filepath = await download_file(url, filename)
            size_mb = filepath.stat().st_size / (1024 * 1024)
            await update.message.reply_text(
                f"Download complete\nFile: {filepath.name}\nSize: {size_mb:.2f} MB\nPath: {filepath}"
            )
            # Send small files directly
            if filepath.stat().st_size < 50 * 1024 * 1024:  # < 50MB
                await update.message.reply_document(
                    document=open(filepath, "rb"),
                    filename=filepath.name
                )
        except Exception as e:
            await update.message.reply_text(f"Download failed: {str(e)}")

    # ── /exec ──
    @auth_required
    async def cmd_exec(update: Update, context: ContextTypes.DEFAULT_TYPE):
        cmd = " ".join(context.args) if context.args else ""
        if not cmd:
            await update.message.reply_text("Usage: /exec <shell command>")
            return
        # Safety: block dangerous commands
        dangerous = ["rm -rf /", "format c:", "del /s /q c:", "shutdown", "rmdir /s"]
        if any(d in cmd.lower() for d in dangerous):
            await update.message.reply_text("Blocked: dangerous command detected")
            return
        await update.message.reply_text(f"Executing: {cmd}")
        output = await execute_command(cmd)
        await update.message.reply_text(f"```\n{output}\n```", parse_mode="Markdown")

    # ── /status ──
    @auth_required
    async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
        import platform
        status_lines = [
            "System Status",
            f"OS: {platform.system()} {platform.release()}",
            f"Python: {platform.python_version()}",
            f"Bot uptime: Running",
            f"Gemini: {'Connected' if gemini.model else 'Disconnected'}",
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Base: {BASE_DIR}",
            f"Downloads: {len(list(DOWNLOADS_DIR.iterdir()))} files",
        ]
        await update.message.reply_text("\n".join(status_lines))

    # ── Handle plain text messages (auto-route to Gemini) ──
    @auth_required
    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if not text:
            return

        # Auto-detect intent and route
        if text.startswith("http://") or text.startswith("https://"):
            # URL detected - offer to download
            await update.message.reply_text(
                f"URL detected. Reply /download {text} to download,\n"
                "or I'll analyze it with AI."
            )
            result = await gemini.generate_text(
                f"이 URL이 무엇인지 분석해줘: {text}"
            )
            await update.message.reply_text(result[:4000])
        else:
            # Default: send to Gemini
            result = await gemini.generate_text(text)
            for i in range(0, len(result), 4000):
                await update.message.reply_text(result[i:i+4000])

    # ── Handle photo messages (Gemini Vision) ──
    @auth_required
    async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        photo = update.message.photo[-1]  # highest resolution
        caption = update.message.caption or "이 이미지를 분석하고 한국어로 설명해줘."
        await update.message.reply_text("Analyzing image...")
        file = await photo.get_file()
        img_bytes = await file.download_as_bytearray()
        result = await gemini.analyze_image_from_bytes(bytes(img_bytes), caption)
        for i in range(0, len(result), 4000):
            await update.message.reply_text(result[i:i+4000])

    # ── Handle document messages ──
    @auth_required
    async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
        doc = update.message.document
        await update.message.reply_text(f"Saving: {doc.file_name} ({doc.file_size:,} bytes)")
        file = await doc.get_file()
        filepath = DOWNLOADS_DIR / doc.file_name
        await file.download_to_drive(str(filepath))
        await update.message.reply_text(f"Saved to: {filepath}")

    # ── /cost ──
    @auth_required
    async def cmd_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
        period = context.args[0] if context.args else "summary"
        try:
            sys.path.insert(0, str(BASE_DIR.parent))
            from api_cost_tracker import CostTracker, BUDGET_LIMIT_KRW
            tracker = CostTracker(
                db_path=str(BASE_DIR.parent / "api_usage.db"),
                project_name="telegram_bot"
            )
            rate = tracker.get_exchange_rate()
            today_usd = tracker.get_today_total()
            monthly_usd = tracker.get_monthly_total()
            alltime_usd = tracker.get_all_time_total()

            today_krw = today_usd * rate
            monthly_krw = monthly_usd * rate
            alltime_krw = alltime_usd * rate
            budget_pct = (monthly_krw / BUDGET_LIMIT_KRW * 100) if BUDGET_LIMIT_KRW > 0 else 0

            # 예산 상태 이모지
            if budget_pct >= 100:
                budget_emoji = "\U0001F6A8"  # 🚨
            elif budget_pct >= 80:
                budget_emoji = "\u26A0\uFE0F"  # ⚠️
            else:
                budget_emoji = "\u2705"  # ✅

            lines = [
                "API \uBE44\uC6A9 \uB9AC\uD3EC\uD2B8",  # API 비용 리포트
                "",
                f"\uC624\uB298: \u20A9{today_krw:,.0f} (${today_usd:.4f})",  # 오늘
                f"\uC774\uBC88\uB2EC: \u20A9{monthly_krw:,.0f} (${monthly_usd:.4f})",  # 이번달
                f"\uC804\uCCB4 \uB204\uC801: \u20A9{alltime_krw:,.0f} (${alltime_usd:.4f})",  # 전체 누적
                "",
                f"{budget_emoji} \uC608\uC0B0: {budget_pct:.1f}% (\u20A9{BUDGET_LIMIT_KRW:,} \uD55C\uB3C4)",  # 예산
                f"\uD658\uC728: 1 USD = \u20A9{rate:,.2f}",  # 환율
            ]

            # 모델별 상세 (summary 모드)
            if period == "detail":
                models = tracker.get_model_breakdown()
                if models:
                    lines.append("")
                    lines.append("[\uBAA8\uB378\uBCC4 \uBE44\uC6A9]")  # [모델별 비용]
                    for model, in_tok, out_tok, cost in models[:8]:
                        name = model[:20] + ".." if len(model) > 20 else model
                        lines.append(f"  {name}: \u20A9{cost*rate:,.0f}")

            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"Cost report error: {str(e)}")

    # ── Build application ──
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("ai", cmd_ai))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("screenshot", cmd_screenshot))
    app.add_handler(CommandHandler("download", cmd_download))
    app.add_handler(CommandHandler("exec", cmd_exec))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cost", cmd_cost))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    return app


# ══════════════════════════════════════════════════════════
#  7. MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════
def main():
    logger.info("=" * 60)
    logger.info("  AI COMMAND CENTER - Starting Up")
    logger.info("=" * 60)

    # Validate config
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in .env")
        logger.error("Get one from @BotFather on Telegram")
        sys.exit(1)

    if ALLOWED_CHAT_ID == 0:
        logger.warning("TELEGRAM_CHAT_ID not set - bot will reject all messages")
        logger.warning("Send /start to your bot, then check logs for your Chat ID")

    logger.info(f"Authorized Chat ID: {ALLOWED_CHAT_ID}")
    logger.info(f"Gemini API: {'Configured' if GEMINI_API_KEY else 'Not set'}")
    logger.info(f"Base directory: {BASE_DIR}")

    app = build_bot()
    logger.info("Bot is now polling for messages...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

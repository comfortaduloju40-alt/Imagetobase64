import os
import io
import base64
import logging
from PIL import Image
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
bot = telebot.TeleBot(BOT_TOKEN)

MAX_BYTES = 10 * 1024 * 1024

FORMATS = {
    "Raw Base64":          "raw",
    "Data URL (PNG)":      "data_png",
    "Data URL (JPEG)":     "data_jpeg",
    "Data URL (WEBP)":     "data_webp",
    "CSS background":      "css",
    "HTML <img> tag":      "html",
    "JSON field":          "json",
    "Markdown code block": "markdown",
}

user_sessions = {}


def format_size(n):
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    else:
        return f"{n / (1024 * 1024):.1f} MB"


def to_base64(img_bytes, fmt):
    def encode(b):
        return base64.b64encode(b).decode("utf-8")

    def as_png(b):
        img = Image.open(io.BytesIO(b))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    if fmt == "raw":
        return encode(img_bytes), "txt"

    elif fmt == "data_png":
        png = as_png(img_bytes)
        return f"data:image/png;base64,{encode(png)}", "txt"

    elif fmt == "data_jpeg":
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88, optimize=True)
        return f"data:image/jpeg;base64,{encode(buf.getvalue())}", "txt"

    elif fmt == "data_webp":
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=88)
        return f"data:image/webp;base64,{encode(buf.getvalue())}", "txt"

    elif fmt == "css":
        png = as_png(img_bytes)
        return f"background-image: url('data:image/png;base64,{encode(png)}');", "css"

    elif fmt == "html":
        img = Image.open(io.BytesIO(img_bytes))
        png = as_png(img_bytes)
        w, h = img.size
        return (
            f'<img src="data:image/png;base64,{encode(png)}" '
            f'width="{w}" height="{h}" alt="image" />',
            "html"
        )

    elif fmt == "json":
        png = as_png(img_bytes)
        return f'{{"image": "data:image/png;base64,{encode(png)}"}}', "json"

    elif fmt == "markdown":
        png = as_png(img_bytes)
        data_url = f"data:image/png;base64,{encode(png)}"
        return f"```\n{data_url}\n```", "txt"

    return encode(img_bytes), "txt"


def send_format_picker(cid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton(name, callback_data=f"fmt:{key}")
        for name, key in FORMATS.items()
    ]
    markup.add(*buttons)
    bot.send_message(
        cid,
        "📦 *Step 2 — Choose output format:*",
        parse_mode="Markdown",
        reply_markup=markup,
    )


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    cid = message.chat.id
    bot.send_message(
        cid,
        "👋 *Image to Base64 Bot*\n\n"
        "Convert any image to Base64 instantly!\n\n"
        "📤 Output formats:\n"
        "• Raw Base64\n"
        "• Data URL — PNG / JPEG / WEBP\n"
        "• CSS background-image\n"
        "• HTML \\<img\\> tag\n"
        "• JSON field\n"
        "• Markdown code block\n\n"
        "Send /convert to start\n"
        "Send /decode to go Base64 → image",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["convert"])
def cmd_convert(message):
    cid = message.chat.id
    user_sessions[cid] = {"step": "photo"}
    bot.send_message(
        cid,
        "📸 *Step 1 — Send your image:*\n"
        "_(send as a file for best quality)_\n\n"
        f"Max size: {format_size(MAX_BYTES)}",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["decode"])
def cmd_decode(message):
    cid = message.chat.id
    user_sessions[cid] = {"step": "decode"}
    bot.send_message(
        cid,
        "🔄 *Base64 → Image*\n\n"
        "Paste your Base64 string or Data URL:\n"
        "_(supports raw base64 or data:image/...;base64,...)_",
        parse_mode="Markdown",
    )


@bot.message_handler(
    content_types=["photo", "document"],
    func=lambda m: user_sessions.get(m.chat.id, {}).get("step") == "photo",
)
def handle_photo(message):
    cid = message.chat.id
    session = user_sessions.get(cid, {})
    try:
        if message.content_type == "photo":
            file_id = message.photo[-1].file_id
        else:
            if not message.document.mime_type.startswith("image/"):
                bot.send_message(cid, "⚠️ Please send an image file.")
                return
            if message.document.file_size > MAX_BYTES:
                bot.send_message(
                    cid,
                    f"❌ File too large. Max is {format_size(MAX_BYTES)}."
                )
                return
            file_id = message.document.file_id

        file_info = bot.get_file(file_id)
        img_bytes = bot.download_file(file_info.file_path)

        if len(img_bytes) > MAX_BYTES:
            bot.send_message(cid, f"❌ Image too large. Max {format_size(MAX_BYTES)}.")
            return

        session["img_bytes"] = img_bytes
        session["step"] = "format"

        img = Image.open(io.BytesIO(img_bytes))
        w, h = img.size
        fmt = img.format or "Unknown"
        raw_b64_len = len(base64.b64encode(img_bytes))

        bot.send_message(
            cid,
            f"✅ *Image received!*\n\n"
            f"Dimensions: `{w} × {h}`\n"
            f"Format: `{fmt}`\n"
            f"File size: `{format_size(len(img_bytes))}`\n"
            f"Base64 length: `{raw_b64_len:,} chars`",
            parse_mode="Markdown",
        )
        send_format_picker(cid)

    except Exception as e:
        logger.exception("Photo error")
        bot.send_message(cid, f"❌ Error reading image: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("fmt:"))
def handle_format(call):
    cid = call.message.chat.id
    fmt_key = call.data.split(":", 1)[1]
    session = user_sessions.get(cid, {})

    if not session.get("img_bytes"):
        bot.answer_callback_query(call.id, "Session expired. Send /convert again.")
        return

    fmt_name = next((k for k, v in FORMATS.items() if v == fmt_key), fmt_key)
    bot.answer_callback_query(call.id, f"Converting…")
    bot.edit_message_text(
        f"✅ Format: *{fmt_name}*\n⏳ Converting…",
        cid, call.message.message_id, parse_mode="Markdown",
    )

    try:
        output, ext = to_base64(session["img_bytes"], fmt_key)
        output_bytes = output.encode("utf-8")
        output_size = len(output_bytes)

        file_buf = io.BytesIO(output_bytes)
        file_buf.name = f"base64_output.{ext}"

        bot.send_document(
            cid,
            file_buf,
            caption=(
                f"✅ *Done!*\n\n"
                f"Format: `{fmt_name}`\n"
                f"Output size: `{format_size(output_size)}`\n"
                f"Characters: `{len(output):,}`\n\n"
                f"/convert to encode another\n"
                f"/decode to decode Base64 → image"
            ),
            parse_mode="Markdown",
        )

        # Inline preview for small outputs
        if output_size < 3000 and fmt_key == "raw":
            preview = output[:500] + ("…" if len(output) > 500 else "")
            bot.send_message(
                cid,
                f"📋 *Preview:*\n```\n{preview}\n```",
                parse_mode="Markdown",
            )
        elif output_size < 2000 and fmt_key in ("html", "css", "json"):
            bot.send_message(
                cid,
                f"📋 *Preview:*\n```\n{output[:800]}\n```",
                parse_mode="Markdown",
            )

    except Exception as e:
        logger.exception("Conversion error")
        bot.send_message(cid, f"❌ Conversion failed: {e}")


@bot.message_handler(
    func=lambda m: user_sessions.get(m.chat.id, {}).get("step") == "decode",
)
def handle_decode(message):
    cid = message.chat.id
    raw = message.text.strip()
    processing_msg = bot.send_message(cid, "⏳ Decoding…")
    try:
        if raw.startswith("data:"):
            header, b64_data = raw.split(",", 1)
            mime = header.split(":")[1].split(";")[0]
            ext = mime.split("/")[1]
        else:
            b64_data = raw
            ext = "png"

        b64_data = b64_data.replace("\n", "").replace("\r", "").replace(" ", "")
        img_bytes = base64.b64decode(b64_data)
        img = Image.open(io.BytesIO(img_bytes))
        w, h = img.size

        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG")
        out.seek(0)

        bot.send_photo(
            cid,
            out,
            caption=(
                f"✅ *Decoded!*\n\n"
                f"Dimensions: `{w} × {h}`\n"
                f"Format: `{img.format or ext.upper()}`\n\n"
                f"/decode to decode another\n"
                f"/convert to encode an image"
            ),
            parse_mode="Markdown",
        )
        bot.delete_message(cid, processing_msg.message_id)
        user_sessions[cid]["step"] = "done"

    except Exception as e:
        logger.exception("Decode error")
        bot.edit_message_text(
            f"❌ Failed to decode. Make sure you sent a valid Base64 string.\n\nError: `{e}`",
            cid,
            processing_msg.message_id,
            parse_mode="Markdown",
        )


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    cid = message.chat.id
    user_sessions.pop(cid, None)
    bot.send_message(cid, "❌ Cancelled. Send /convert to start over.")


if __name__ == "__main__":
    logger.info("Image to Base64 bot starting…")
    bot.infinity_polling()

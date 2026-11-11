"""Bounded local Windows OCR; no document images are sent to a cloud OCR service."""
from __future__ import annotations

import asyncio
import io
from contextlib import closing


async def _recognize(png: bytes) -> str:
    import winrt.windows.foundation
    import winrt.windows.foundation.collections
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise ValueError("Install a Windows OCR language pack for your preferred language.")
    with InMemoryRandomAccessStream() as stream:
        writer = DataWriter(stream)
        writer.write_bytes(png)
        await writer.store_async()
        writer.detach_stream()
        writer.close()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        with await decoder.get_software_bitmap_async() as bitmap:
            result = await engine.recognize_async(bitmap)
            return "\n".join(line.text for line in result.lines)


def image_text(image) -> str:
    if image.width * image.height > 20_000_000:
        raise ValueError("OCR image exceeds 20 million pixels.")
    with image.convert("RGB") as frame:
        frame.thumbnail((2000, 2000))
        output = io.BytesIO()
        frame.save(output, format="PNG")
        return asyncio.run(_recognize(output.getvalue()))


def pdf_page_text(data: bytes, index: int) -> str:
    import pypdfium2

    with pypdfium2.PdfDocument(data) as pdf:
        with closing(pdf[index]) as page:
            width, height = page.get_size()
            if min(width, height) <= 0:
                raise ValueError("Invalid PDF page size.")
            with closing(page.render(scale=min(2, 2000 / max(width, height)))) as bitmap:
                with bitmap.to_pil() as image:
                    return image_text(image)

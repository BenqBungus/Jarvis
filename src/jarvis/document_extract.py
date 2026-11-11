"""PDF/DOCX text and bounded local OCR in a console-free subprocess."""
from __future__ import annotations

import io
import json
import sys
import zipfile

MAX_INPUT = 20 * 1024 * 1024
MAX_TEXT = 60000
MAX_UNITS = 120
MAX_OCR_IMAGES = 8


def extract_document(data: bytes, extension: str) -> dict:
    if not data or len(data) > MAX_INPUT:
        raise ValueError("Document must be nonempty and at most 20 MiB.")
    blocks, count, partial, empty = [], 0, False, 0
    ocr_attempts, ocr_read, ocr_failed = 0, 0, 0

    def recognize(read):
        nonlocal ocr_attempts, ocr_read, ocr_failed, partial
        if ocr_attempts >= MAX_OCR_IMAGES:
            partial = True
            return ""
        ocr_attempts += 1
        try:
            text = read().strip()
        except Exception:
            ocr_failed += 1
            partial = True
            return ""
        if text:
            ocr_read += 1
        return text

    def append(label, text):
        nonlocal count, partial, empty
        text = text.strip()
        if not text:
            empty += 1
            return True
        available = MAX_TEXT - count - len(label) - 4
        if available <= 0:
            partial = True
            return False
        blocks.append({"label": label, "text": text[:available]})
        count += len(blocks[-1]["text"]) + len(label) + 4
        if len(text) > available:
            partial = True
            return False
        return True

    if extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported. Choose an unencrypted copy you may access.")
        total = len(reader.pages)
        inspected = 0
        for index in range(min(total, MAX_UNITS)):
            inspected += 1
            text = reader.pages[index].extract_text() or ""
            label = f"Page {index + 1}"
            if not text.strip():
                from .ocr import pdf_page_text
                text = recognize(lambda: pdf_page_text(data, index))
                label += " (OCR)"
            if not append(label, text):
                break
        partial = partial or inspected < total or bool(empty)
        coverage = f"Text extracted from {inspected}/{total} PDF pages; {empty} inspected pages had no readable text. OCR is attempted on image-only pages. Charts and mixed text/image page illustrations are not interpreted."
    elif extension == ".docx":
        from docx import Document
        from docx.table import Table

        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 2000 or sum(item.file_size for item in members) > 40 * 1024 * 1024:
                raise ValueError("DOCX archive exceeds the expanded-size or entry limit.")
            if any(item.flag_bits & 1 or "vbaproject" in item.filename.casefold() for item in members):
                raise ValueError("Encrypted or macro-containing documents are not supported.")
        doc = Document(io.BytesIO(data))
        inspected = 0
        for index, block in enumerate(doc.iter_inner_content(), 1):
            if index > 2000:
                partial = True
                break
            inspected += 1
            if isinstance(block, Table):
                text = "\n".join(" | ".join(cell.text for cell in row.cells) for row in block.rows)
                label = f"Block {index} table"
            else:
                text, label = block.text, f"Block {index}"
            if not append(label, text):
                break
        from PIL import Image
        from .ocr import image_text
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            images = [item for item in members if item.filename.startswith("word/media/")
                      and item.filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff"))]
            for index, item in enumerate(images[:MAX_OCR_IMAGES], 1):
                def read_image():
                    with Image.open(io.BytesIO(archive.read(item))) as image:
                        return image_text(image)
                if not append(f"Embedded image {index} (OCR)", recognize(read_image)):
                    break
        # Word pagination and non-body material require a layout-aware reader.
        partial = True
        coverage = f"Read {inspected} DOCX body blocks including tables. Headers, footnotes, text boxes, comments, revisions and images are not fully covered; block labels are not page numbers. Embedded-image OCR is listed in archive order, not page order."
    else:
        raise ValueError("Only .pdf and .docx are supported, not .doc or .docm.")
    if not blocks:
        raise ValueError("No readable text was found. Local OCR needs the documents extra and a Windows OCR language pack; blank, damaged or unsupported images cannot be read.")
    coverage += f" Local OCR: {ocr_read}/{ocr_attempts} images yielded text, {ocr_failed} failures; limit {MAX_OCR_IMAGES} images. OCR may misread text; verify important quotations against the original."
    if partial:
        coverage += " Coverage is partial. Extraction is capped at 60000 characters, 120 PDF pages or 2000 DOCX body blocks."
    return {"blocks": blocks, "partial": partial, "coverage": coverage, "characters": count,
            "ocr_images": ocr_read, "ocr_attempts": ocr_attempts}


def main():
    try:
        result = extract_document(sys.stdin.buffer.read(MAX_INPUT + 1), sys.argv[1])
        payload = {"ok": True, "document": result}
    except ImportError:
        payload = {"ok": False, "error": "Document dependency missing. Install Jarvis with the documents extra."}
    except ValueError as exc:
        payload = {"ok": False, "error": str(exc)[:500]}
    except Exception:
        payload = {"ok": False, "error": "Document parsing failed. The file may be damaged or unsupported."}
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))


if __name__ == "__main__":
    main()

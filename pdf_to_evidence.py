import sys
import io
from pathlib import Path
import fitz
from PIL import Image

SCRIPT_DIR = Path(__file__).parent
EVIDENCE_DIR = SCRIPT_DIR / "static" / "evidence"
MEDIA_DIR = SCRIPT_DIR / "static" / "assets" / "evidence-files"


def save_image_as_webp(img_data, img_ext, name, idx):
    filename = f"{name}-{idx:03d}.webp"
    dest = MEDIA_DIR / filename
    try:
        with Image.open(io.BytesIO(img_data)) as im:
            if im.mode in ("RGBA", "LA"):
                im.save(dest, "WEBP", quality=90, lossless=False)
            else:
                im.convert("RGB").save(dest, "WEBP", quality=90)
    except Exception as e:
        print(f"  [warn] image {idx}: {e}")
        fallback = f"{name}-{idx:03d}.{img_ext.lower()}"
        (MEDIA_DIR / fallback).write_bytes(img_data)
        return f"/static/assets/evidence-files/{fallback}"
    return f"/static/assets/evidence-files/{filename}"

def is_header(span, body_size):
    size = span.get("size", 0)
    flags = span.get("flags", 0)
    is_bold = bool(flags & 0b10000)
    return size >= body_size * 1.2 or (is_bold and size > body_size)

def estimate_body_font_size(doc):
    sizes = {}
    for page in doc:
        for block in page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]:
            if block["type"] != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    s = round(span.get("size", 0), 1)
                    if s > 0:
                        sizes[s] = sizes.get(s, 0) + len(span.get("text", ""))
    return max(sizes, key=sizes.get) if sizes else 10.0

def build_page_elements(page, doc, pdf_stem, counter, body_size):
    elements = []

    for block in page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]:
        if block["type"] != 0:
            continue
        first_span = next(
            (s for ln in block.get("lines", []) for s in ln.get("spans", []) if s.get("text", "").strip()),
            None,
        )
        if first_span is None:
            continue
        header = is_header(first_span, body_size)

        parts = []
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                raw = span.get("text", "").strip()
                if not raw:
                    continue
                if header:
                    parts.append(raw)
                else:
                    flags = span.get("flags", 0)
                    bold = bool(flags & 0b10000)
                    italic = bool(flags & 0b00010)
                    if bold and italic:
                        parts.append(f"***{raw}***")
                    elif bold:
                        parts.append(f"**{raw}**")
                    elif italic:
                        parts.append(f"*{raw}*")
                    else:
                        parts.append(raw)

        text = " ".join(parts).strip()
        if text:
            elements.append({"type": "text", "y": block["bbox"][1], "text": text, "is_header": header})

    for img_info in page.get_images(full=True):
        xref = img_info[0]
        try:
            base_img = doc.extract_image(xref)
        except Exception:
            continue
        img_data = base_img.get("image")
        if not img_data or len(img_data) < 100:
            continue
        img_rects = page.get_image_rects(xref)
        img_y = img_rects[0].y0 if img_rects else 0.0
        idx = counter[0]
        counter[0] += 1
        web_path = save_image_as_webp(img_data, base_img.get("ext", "png"), pdf_stem, idx)
        elements.append({"type": "image", "y": img_y, "md": f"![{pdf_stem}-{idx:03d}]({web_path})"})

    elements.sort(key=lambda e: e["y"])
    return elements

def build_markdown(all_elements):
    lines = []
    for el in all_elements:
        if el["type"] == "image":
            lines.append(el["md"])
        else:
            lines.append(f"# {el['text']}" if el["is_header"] else el["text"])
        lines.append("")

    out, prev_blank = [], False
    for line in lines:
        blank = line.strip() == ""
        if blank and prev_blank:
            continue
        out.append(line)
        prev_blank = blank

    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()

    return "\n".join(out) + "\n"

def convert(pdf_path):
    pdf_path = Path(pdf_path).resolve()
    pdf_stem = pdf_path.stem
    for f in MEDIA_DIR.glob(f"{pdf_stem}-*.webp"):
        f.unlink()
    doc = fitz.open(str(pdf_path))
    body_size = estimate_body_font_size(doc)
    counter = [1]

    all_elements = []
    for page in doc:
        all_elements.extend(build_page_elements(page, doc, pdf_stem, counter, body_size))
    doc.close()

    md_dest = EVIDENCE_DIR / f"{pdf_stem}.md"
    md_dest.write_text(build_markdown(all_elements), encoding="utf-8")
    print(f"Done")

if __name__ == "__main__":
    convert(sys.argv[1])
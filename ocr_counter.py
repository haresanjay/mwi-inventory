"""
MWI Print – Machine Counter photo ka OCR

Photo (counter screen / counter report) se ye values nikalta hai:
    model, serial, date, counter (jaise 101), total (jaise 2274238)

OCR engine:
  * OCR_SPACE_KEY mila ho  -> OCR.space (free API, mobile photo par zyada sahi)
  * warna                  -> Tesseract (Streamlit Cloud par packages.txt se install hota hai)
"""

import io
import re
import shutil
import subprocess
from datetime import date

import requests
from PIL import Image, ImageFilter, ImageOps

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# ------------------------------------------------------------------ OCR engines
def _prepare(image_bytes: bytes) -> list[Image.Image]:
    """Photo ko OCR ke layak banata hai: seedha, grey, bada, saaf. Andheri screen ho to ulta bhi."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("L")
    w, h = img.size
    longest = max(w, h)
    if longest < 1800:
        f = 1800 / longest
        img = img.resize((int(w * f), int(h * f)), Image.LANCZOS)
    elif longest > 3000:
        img.thumbnail((3000, 3000))
    img = ImageOps.autocontrast(img, cutoff=1).filter(ImageFilter.SHARPEN)
    out = [img]
    mean = sum(i * c for i, c in enumerate(img.histogram())) / max(1, img.width * img.height)
    if mean < 110:                      # kaali screen par safed akshar
        out.insert(0, ImageOps.invert(img))
    return out


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _tesseract(img: Image.Image, psm: int) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    r = subprocess.run(["tesseract", "stdin", "stdout", "--psm", str(psm), "-l", "eng"],
                       input=buf.getvalue(), capture_output=True, timeout=90)
    return r.stdout.decode("utf-8", "ignore")


def ocr_tesseract(image_bytes: bytes) -> str:
    if not tesseract_available():
        raise RuntimeError("Tesseract install nahi hai (Streamlit Cloud ke liye packages.txt chahiye).")
    texts = []
    for img in _prepare(image_bytes):
        for psm in (6, 4):
            texts.append(_tesseract(img, psm))
        if parse_counter("\n".join(texts)).get("total"):
            break
    return "\n".join(texts)


def ocr_space(image_bytes: bytes, api_key: str) -> str:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    img.thumbnail((2000, 2000))
    q, data = 85, b""
    while q >= 40:                      # free plan: file 1 MB se chhoti
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q)
        data = buf.getvalue()
        if len(data) < 950_000:
            break
        q -= 15
    r = requests.post("https://api.ocr.space/parse/image",
                      data={"apikey": api_key, "language": "eng", "OCREngine": "2",
                            "scale": "true", "detectOrientation": "true"},
                      files={"file": ("counter.jpg", data, "image/jpeg")}, timeout=90)
    j = r.json()
    if j.get("IsErroredOnProcessing"):
        raise RuntimeError(f"OCR.space: {j.get('ErrorMessage')}")
    return "\n".join(p.get("ParsedText", "") for p in j.get("ParsedResults") or [])


def read_photo(image_bytes: bytes, ocr_space_key: str = "") -> tuple[dict, str, str]:
    """Photo padhkar (values, poora text, engine ka naam) lautata hai."""
    errors = []
    if ocr_space_key:
        try:
            text = ocr_space(image_bytes, ocr_space_key)
            data = parse_counter(text)
            if data.get("total") or not tesseract_available():
                return data, text, "OCR.space"
        except Exception as e:                       # OCR.space na chale to Tesseract
            errors.append(str(e))
    try:
        text = ocr_tesseract(image_bytes)
        return parse_counter(text), text, "Tesseract"
    except Exception as e:
        errors.append(str(e))
    raise RuntimeError(" | ".join(errors))


# ------------------------------------------------------------------ text se values
NUM = r"(\d{1,3}(?:[,.\s]\d{3})+|\d{4,})"           # 2274238 / 2,274,238 / 2 274 238


def _num(s: str) -> int:
    return int(re.sub(r"\D", "", s))


def _clean_value(v: str) -> str:
    v = re.split(r"\s{3,}|\t|\|", v.strip())[0]      # aage ka doosra column hatao
    return v.strip(" :.-_=|")


def _to_date(d: int, m: int, y: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        dt = date(y, m, d)
    except ValueError:
        return None
    return dt if 2000 <= dt.year <= 2100 else None


def _dates_in(line: str) -> list[date]:
    found = []
    for m in re.finditer(r"\b(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\b", line):
        d = _to_date(int(m[3]), int(m[2]), int(m[1]))
        if d:
            found.append(d)
    for m in re.finditer(r"\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4}|\d{2})\b", line):
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        d = _to_date(a, b, y) if a > 12 or b <= 12 else _to_date(b, a, y)   # India: dd/mm
        if d:
            found.append(d)
    for m in re.finditer(r"\b(\d{1,2})\s*[- ]?\s*([A-Za-z]{3})[a-z]*\.?\s*[- ,]?\s*(\d{4})\b", line):
        mon = MONTHS.get(m[2].lower())
        d = mon and _to_date(int(m[1]), mon, int(m[3]))
        if d:
            found.append(d)
    for m in re.finditer(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", line):
        mon = MONTHS.get(m[1].lower())
        d = mon and _to_date(int(m[2]), mon, int(m[3]))
        if d:
            found.append(d)
    return found


BRAND_MODEL = re.compile(
    r"\b(i[Rr][-\s]?(?:ADV(?:ANCE)?\s*(?:DX\s*)?)?[A-Z]?\s?\d{3,4}[A-Za-z]{0,3}"
    r"|imageRUNNER\s+(?:ADVANCE\s+)?(?:DX\s+)?[A-Z]?\d{3,4}\w*"
    r"|TASKalfa\s*\d{3,4}\w*|ECOSYS\s*[A-Z]{1,2}\d{3,4}\w*|bizhub\s*[A-Z]?\d{3,4}\w*"
    r"|MP\s?C?\d{3,4}\w*|IM\s?C?\d{3,4}\w*|WorkCentre\s*\d{3,4}\w*|AltaLink\s*[A-Z]?\d{4}\w*"
    r"|e-STUDIO\s*\d{3,4}\w*)", re.I)


def parse_counter(text: str) -> dict:
    """OCR text se model, serial, date, counter, total nikalta hai (jo mile)."""
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    out: dict = {}

    # ---- Model
    for l in lines:
        m = re.search(r"(?i)\b(?:model(?:\s*name)?|product(?:\s*name)?|device\s*name|"
                      r"machine\s*(?:model|name)|printer\s*model)\b\s*[:=\-.]?\s*(.+)", l)
        if m:
            v = _clean_value(m[1])
            if len(v) >= 3 and re.search(r"[A-Za-z0-9]", v):
                out["model"] = v[:60]
                break
    if "model" not in out:
        m = BRAND_MODEL.search(text)
        if m:
            out["model"] = re.sub(r"\s+", " ", m[1]).strip()

    # ---- Serial number
    for l in lines:
        m = re.search(r"(?i)(?:serial\s*(?:no\.?|number|num|#)?|s\s*/\s*n|sr\.?\s*no\.?|"
                      r"machine\s*(?:id|no\.?|serial))\s*[:=\-.]?\s*([A-Z0-9][A-Z0-9\-]{3,})", l)
        if m and re.search(r"\d", m[1]):
            out["serial"] = m[1].upper().strip("-")
            break

    # ---- Reading date ("date" wali line ko pehle dekho)
    date_lines = [l for l in lines if re.search(r"(?i)date|time|print|report", l)]
    for l in date_lines + lines:
        ds = _dates_in(l)
        if ds:
            out["date"] = ds[0]
            break

    # ---- Counter no + Total
    cands = []
    for l in lines:
        m = re.search(r"(?i)\b(\d{3})\s*[:;.\-]?\s*tota[l1i|]\b\s*(?:\d{1,2}\b)?\s*[:;.\-]?\s*" + NUM, l)
        if m:
            cands.append((m[1], _num(m[2]), 0))
            continue
        if re.search(r"(?i)tota[l1i|]", l):
            nums = re.findall(NUM, l)
            if nums:
                code = re.match(r"^\W*(\d{3})\b", l)
                cands.append((code[1] if code else None, max(_num(n) for n in nums), 1))
                continue
        m = re.match(r"^\W{0,3}(\d{3})\s*[:;.\-]\D{0,25}?" + NUM + r"\s*$", l)
        if m:
            cands.append((m[1], _num(m[2]), 2))
    if cands:
        cands.sort(key=lambda c: (c[0] != "101", c[2]))   # 101 (Total 1) sabse pehle
        code, total, _ = cands[0]
        out["total"] = total
        if code:
            out["counter"] = code
    return out

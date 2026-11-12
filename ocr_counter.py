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
from PIL import Image, ImageChops, ImageFilter, ImageOps

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# ------------------------------------------------------------------ OCR engines
def _mean(img: Image.Image) -> float:
    return sum(i * c for i, c in enumerate(img.histogram())) / max(1, img.width * img.height)


def _skew_angle(img: Image.Image) -> float:
    """Tirchhi photo ka angle dhoondhta hai (lines ke projection se)."""
    small = img.copy()
    small.thumbnail((700, 700))
    bw = _flatten(small).point(lambda v: 255 if v < 128 else 0)       # akshar = safed
    best, best_score = 0.0, -1.0
    for a10 in range(-120, 121, 5):                                      # -12 se +12 degree
        a = a10 / 10
        r = bw.rotate(a, resample=Image.NEAREST, fillcolor=0)
        w, h = r.size
        px = r.tobytes()
        rows = [px[y * w:(y + 1) * w].count(255) for y in range(h)]
        score = sum((rows[i] - rows[i - 1]) ** 2 for i in range(1, h))
        if score > best_score:
            best, best_score = a, score
    return best


def _flatten(img: Image.Image) -> Image.Image:
    """Chamak (glare) aur asaman roshni hatata hai: har jagah ki background se tulna."""
    bg = img.filter(ImageFilter.BoxBlur(max(15, img.width // 40)))
    diff = ImageChops.subtract(bg, img, scale=1, offset=0)              # akshar background se gehre
    return ImageOps.invert(ImageOps.autocontrast(diff, cutoff=1))


def _prepare(image_bytes: bytes) -> list[Image.Image]:
    """Photo ko OCR ke layak banata hai: seedha, grey, bada, saaf. Kai roop lautata hai."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("L")
    if _mean(img) < 110:                # kaali screen par safed akshar
        img = ImageOps.invert(img)
    w, h = img.size
    longest = max(w, h)
    if longest < 2000:
        f = 2000 / longest
        img = img.resize((int(w * f), int(h * f)), Image.LANCZOS)
    elif longest > 3000:
        img.thumbnail((3000, 3000))
    img = img.filter(ImageFilter.MedianFilter(3))                       # LCD ki dhaariyan kam
    angle = _skew_angle(img)
    if abs(angle) >= 0.5:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255)
    flat = _flatten(img)
    plain = ImageOps.autocontrast(img, cutoff=1).filter(ImageFilter.SHARPEN)
    binar = flat.point(lambda v: 0 if v < 150 else 255)
    return [flat, plain, binar]


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _tesseract(img: Image.Image, psm: int, tsv: bool = False) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    cmd = ["tesseract", "stdin", "stdout", "--psm", str(psm), "-l", "eng"] + (["tsv"] if tsv else [])
    r = subprocess.run(cmd, input=buf.getvalue(), capture_output=True, timeout=90)
    return r.stdout.decode("utf-8", "ignore")


def _rows_from_tsv(tsv: str) -> str:
    """Har shabd ki jagah (x, y) dekh kar ek hi line ke shabd jodta hai,
    chahe label baayein ho aur number door daayein (jaise '101: Total 1 ....... 2274238')."""
    words = []
    for line in tsv.splitlines()[1:]:
        p = line.split("\t")
        if len(p) < 12 or not p[11].strip():
            continue
        try:
            x, y, w, h, conf = int(p[6]), int(p[7]), int(p[8]), int(p[9]), float(p[10])
        except ValueError:
            continue
        if conf < 10 or h < 6:
            continue
        words.append((y + h / 2, x, h, p[11].strip()))
    if not words:
        return ""
    hs = sorted(w[2] for w in words)
    tol = max(8, hs[len(hs) // 2] * 0.7)
    rows = []
    for cy, x, h, t in sorted(words):
        if rows and abs(cy - rows[-1][0]) <= tol:
            rows[-1][1].append((x, t))
            n = len(rows[-1][1])
            rows[-1][0] = (rows[-1][0] * (n - 1) + cy) / n
        else:
            rows.append([cy, [(x, t)]])
    return "\n".join(" ".join(t for _, t in sorted(r[1])) for r in rows)


def ocr_tesseract(image_bytes: bytes) -> str:
    if not tesseract_available():
        raise RuntimeError("Tesseract install nahi hai (Streamlit Cloud ke liye packages.txt chahiye).")
    texts = []
    for img in _prepare(image_bytes):
        texts.append(_rows_from_tsv(_tesseract(img, 11, tsv=True)))
        texts.append(_tesseract(img, 6))
        d = parse_counter("\n".join(texts))
        if d.get("total") and d.get("_prio", 9) <= 1 and d.get("serial"):
            break
    for img in _prepare(image_bytes)[:1]:                     # aakhri koshish: alag layout
        if parse_counter("\n".join(texts)).get("_prio", 9) > 1:
            texts.append(_rows_from_tsv(_tesseract(img, 4, tsv=True)))
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


_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1",
                            "i": "1", "!": "1", "Z": "2", "z": "2", "S": "5", "s": "5", "B": "8",
                            "G": "6", "b": "6", "T": "7", "g": "9", "q": "9"})


def _fix_digits(line: str) -> str:
    """OCR ki aam galti: number ke andar O->0, l->1, S->5 ... (sirf jo shabd zyada-tar ank hon)."""
    def fix(m):
        tok = m.group(0)
        digits = sum(ch.isdigit() for ch in tok)
        if digits >= 3 and digits >= len(re.sub(r"[,.]", "", tok)) * 0.6:
            return tok.translate(_DIGIT_FIX)
        return tok
    return re.sub(r"[0-9OoDQIl|i!ZzSsBGbTgq,.]{4,}", fix, line)


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
    nlines = [_fix_digits(l) for l in lines]
    serial_digits = re.sub(r"\D", "", out.get("serial", ""))
    cands = []
    for i, l in enumerate(nlines):
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
            continue
        # label ek line par, number agli line par
        m = re.search(r"(?i)\b(101)\b|tota[l1i|]\s*1\b", l)
        if m and not re.search(NUM, l):
            for nxt in nlines[i + 1:i + 3]:
                n2 = re.fullmatch(r"\W*" + NUM + r"\W*", nxt)
                if n2:
                    cands.append(("101", _num(n2[1]), 3))
                    break
    if not cands:                                # aakhri upaay: sabse bada counter jaisa number
        nums = []
        for l in nlines:
            if _dates_in(l) or re.search(r"(?i)serial|s/n|\d{1,2}:\d{2}", l):
                continue
            for n in re.findall(NUM, l):
                v = _num(n)
                if 1000 <= v < 10**9 and str(v) != serial_digits and not re.fullmatch(r"20\d{6}", str(v)):
                    nums.append(v)
        if nums:
            cands.append((None, max(nums), 4))
    if cands:
        def rank(c):                             # 101 > bina code wali Total line > baaki code > andaza
            code, _, prio = c
            group = 0 if code == "101" else 1 if (code is None and prio < 4) else 2 if code else 3
            return (group, prio)
        cands.sort(key=rank)
        code, total, prio = cands[0]
        out["total"] = total
        out["counter"] = code or "101"           # Canon: Total 1 = counter 101
        out["_prio"] = prio
    return out

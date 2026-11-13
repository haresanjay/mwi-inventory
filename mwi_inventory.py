"""
MWI Print – Inventory Entry Form (Python + Streamlit + Supabase)

Tables : Machine_Counter, Machine_Parts, PDF_DETAIL, Paper_Table, Toner
Images : Supabase Storage (cloud) ke bucket "parts_images" mein
         Machine_Parts   Old / New photo     -> old_parts/   , new_parts/
         Machine_Counter IN / OUT photo      -> counter_in/  , counter_out/
         Database mein photo ka public link (URL) save hota hai,
         isliye photo kisi bhi computer ya mobile se dikhti hai.

Chalane ke liye:  run_app.bat  par double-click   (ya:  streamlit run mwi_inventory.py)
"""

import hashlib
import io
import json
import re
import time as _time
import uuid
from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")   # India ka samay


def now_ist() -> datetime:
    return datetime.now(IST)


from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from PIL import Image, ImageOps

OCR_ENABLED = False                        # True karne par photo ka OCR (dheema) wapas chalu

try:
    import importlib
    import ocr_counter                     # Machine Counter photo ka OCR
    ocr_counter = importlib.reload(ocr_counter)   # GitHub par nayi file aaye to turant wahi chale
except Exception:                          # file na ho to baaki app chalta rahe
    ocr_counter = None

# ------------------------------------------------------------------ settings
APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "mwi_settings.json"
DEFAULT_URL = "https://bemtbxxbcgvdsjziytmn.supabase.co"

TABLES = {
    "Machine_Counter": "🔢 Machine Counter",
    "Machine_Parts": "⚙️ Machine Parts",
    "PDF_DETAIL": "📑 PDF Detail",
    "Paper_Table": "📄 Paper",
    "Toner": "🖨️ Toner",
}

# Kis table ke kis column mein photo aayegi (column naam chhote/bade akshar se farq nahi padta)
PHOTOS = {
    "Machine_Parts": {
        "heading": "Parts Photo", "item": "Part",
        "fields": [
            {"col": "old_item_pic_path", "label": "Damage Parts Photo", "folder": "old_parts",
             "button": "🔧 Old Parts Image", "title": "Purana Part (Old)"},
            {"col": "new_item_pic_path", "label": "New Parts Photo", "folder": "new_parts",
             "button": "✨ New Parts Image", "title": "Naya Part (New)"},
        ],
    },
    "Machine_Counter": {
        "heading": "Counter Photo", "item": "Entry",
        "fields": [
            {"col": "machine_counter_in_photo_path", "label": "Counter IN Photo",
             "folder": "counter_in", "button": "📥 Counter IN Image", "title": "Counter IN"},
            {"col": "machine_counter_out_photo_path", "label": "Counter OUT Photo",
             "folder": "counter_out", "button": "📤 Counter OUT Image", "title": "Counter OUT"},
        ],
    },
}
BUCKET = "parts_images"

# Form mein fields ka kram (order) aur naam.
# (Dikhne wala naam, database column ke sambhavit naam, naya column ka naam, SQL type)
F = lambda label, aliases, sql_name, sql_type: {
    "label": label, "aliases": aliases, "sql": sql_name, "type": sql_type}
FIELD_ORDER = {
    "Machine_Parts": {
        "first": [
            F("Machine No", ["machine_no", "machine_number", "mc_no", "machine"], "Machine_No", "text"),
            F("Parts Name", ["parts_name", "part_name", "item_name", "name", "parts"], "Parts_Name", "text"),
            F("Qty", ["qty", "quantity"], "Qty", "integer"),
        ],
    },
    "Machine_Counter": {
        "first": [
            F("Machine No", ["machine_no", "machine_number", "mc_no", "machine"], "Machine_No", "text"),
            F("Model (IN)", ["model_in", "in_model"], "Model_in", "text"),
            F("Serial Number (IN)", ["serial_number_in", "serial_no_in", "serial_in"],
              "Serial_Number_in", "text"),
            F("Reading Date (IN)", ["reading_date_in", "date_in"], "Reading_Date_in", "date"),
            F("Counter No (IN)", ["counter_no_in", "counter_in"], "Counter_No_in", "text"),
            F("Total (IN)", ["total_in", "total_count_in", "count_in"], "Total_in", "bigint"),
            F("Reading Date (OUT)", ["reading_date_out", "date_out"], "Reading_Date_out", "date"),
            F("Total (OUT)", ["total_out", "total_count_out", "count_out"], "Total_out", "bigint"),
            F("Net Total", ["net_total", "net_count", "net"], "Net_Total", "bigint"),
        ],
        "last": [
            F("Reason", ["reason", "remark", "remarks"], "Reason", "text"),
        ],
    },
    "PDF_DETAIL": {
        "first": [
            F("District Name", ["district_name", "district", "dist_name", "dist", "zila"],
              "District_Name", "text"),
            F("Ac No", ["ac_no", "ac_number", "acno", "ac", "assembly_no", "assembly_constituency_no",
                        "account_no"], "Ac_No", "text"),
            F("Page Qty", ["page_qty", "pages_qty", "page_quantity", "no_of_pages", "no_of_page",
                           "pages", "page", "total_pages", "page_count"], "Page_Qty", "integer"),
        ],
    },
    "Toner": {
        "first": [
            F("Toner Received Date", ["toner_received_date", "toner_receive_date", "received_date",
                                      "receive_date", "toner_date", "date"], "Toner_Received_Date", "date"),
            F("Invoice No", ["invoice_no", "invoice_number", "invoice", "bill_no"], "Invoice_No", "text"),
            F("Toner Company", ["toner_company", "company", "company_name", "brand", "toner_brand"],
              "Toner_Company", "text"),
            F("Toner Qty", ["toner_qty", "qty", "quantity", "toner_quantity"], "Toner_Qty", "integer"),
            F("Toner Used", ["toner_used", "used", "used_qty", "toner_use"], "Toner_Used", "integer"),
            F("Toner Balance Qty", ["toner_balance_qty", "toner_balance", "balance_qty", "balance"],
              "Toner_Balance_Qty", "integer"),
        ],
    },
    "Paper_Table": {
        "first": [
            F("Paper Received Date", ["paper_received_date", "paper_receive_date", "received_date",
                                      "receive_date", "paper_date", "date"], "Paper_Received_Date", "date"),
            F("Invoice No", ["invoice_no", "invoice_number", "invoice", "bill_no"], "Invoice_No", "text"),
            F("Party Name", ["party_name", "party", "supplier_name", "supplier"], "Party_Name", "text"),
            F("GSM", ["gsm"], "GSM", "integer"),
            F("Paper Company", ["paper_company", "company", "company_name", "brand"], "Paper_Company", "text"),
            F("Qty Rim", ["qty_rim", "qty_rims", "rim_qty", "rim", "rims", "qty_ream", "ream", "reams"],
              "Qty_Rim", "numeric"),
            F("No of Paper", ["no_of_paper", "no_of_papers", "number_of_paper", "no_of_sheets",
                              "total_paper", "paper_qty", "sheets"], "No_of_Paper", "integer"),
            F("Consumption Paper", ["consumption_paper", "paper_consumption", "consumption",
                                    "consumed_paper", "used_paper"], "Consumption_Paper", "integer"),
            F("Balance Paper Qty", ["balance_paper_qty", "balance_paper", "paper_balance",
                                    "paper_balance_qty", "balance_qty", "balance"],
              "Balance_Paper_Qty", "integer"),
        ],
    },
}


# Photo ka OCR karke kaun-sa field bharna hai:  photo column -> {OCR value: field label}
OCR_MAP = {
    "Machine_Counter": {
        "machine_counter_in_photo_path": {
            "model": "Model (IN)", "serial": "Serial Number (IN)", "date": "Reading Date (IN)",
            "counter": "Counter No (IN)", "total": "Total (IN)"},
        "machine_counter_out_photo_path": {
            "date": "Reading Date (OUT)", "total": "Total (OUT)"},
    },
}
OCR_NAMES = {"model": "Model", "serial": "Serial Number", "date": "Reading Date",
             "counter": "Counter No", "total": "Total"}


# Apne-aap hisaab wale fields (form mein bharna nahi padta). Upar se neeche kram mein chalte hain.
def _minus(a, b):
    return a - (b or 0)


def _both_minus(a, b):
    """Dono value hon tabhi  a - b."""
    return None if a is None or b is None else a - b


CALC = {
    "Machine_Counter": [
        {"target": "Net Total", "uses": ["Total (OUT)", "Total (IN)"], "fn": _both_minus,
         "desc": "Total OUT − Total IN", "no_negative": True},
    ],
    "Toner": [
        {"target": "Toner Balance Qty", "uses": ["Toner Qty", "Toner Used"], "fn": _minus,
         "desc": "Toner Qty − Toner Used", "no_negative": True},
    ],
    "Paper_Table": [
        {"target": "No of Paper", "uses": ["Qty Rim"], "fn": lambda rim: rim * 500,
         "desc": "Qty Rim × 500"},
        {"target": "Balance Paper Qty", "uses": ["No of Paper", "Consumption Paper"], "fn": _minus,
         "desc": "No of Paper − Consumption Paper", "no_negative": True},
    ],
}


def calc_rules(table: str, labels: dict) -> list[dict]:
    """CALC ke labels ko asli column naam se jodta hai (sirf wahi niyam jinke column maujood hain)."""
    by_label = {lbl: col for col, lbl in labels.items()}
    out = []
    for r in CALC.get(table, []):
        cols = [by_label.get(x) for x in [r["target"]] + r["uses"]]
        if all(cols):
            out.append({**r, "t_col": cols[0], "u_cols": cols[1:]})
    return out


def run_rule(rule: dict, values: dict, types: dict):
    """Ek niyam ka hisaab. Pehla value khaali ho to None."""
    args = [values.get(c) for c in rule["u_cols"]]
    if args[0] is None:
        return None
    res = rule["fn"](*args)
    if res is None:
        return None
    if types.get(rule["t_col"]) in INT_TYPES:
        res = int(round(res))
    return res


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())
MAX_IMG_SIDE = 1600      # photo isse badi ho to chhoti kar di jaati hai (jagah bachane ke liye)
JPEG_QUALITY = 82

INT_TYPES = {"smallint", "integer", "bigint"}
NUM_TYPES = {"numeric", "real", "double precision", "money"}

# numeric column hone par bhi in naamon wale fields poore ank (bina .00) mein dikhte hain
WHOLE_WORDS = ("total", "counter", "count", "page", "gsm", "noof", "qty", "used", "balance",
               "consumption", "reading")
DECIMAL_WORDS = ("rim", "ream", "rate", "price", "amount", "weight", "kg")


def is_whole(col: dict) -> bool:
    """Ye field poore ank (1, 2, 101, 2274238) wala hai ya nahi."""
    dt = col["data_type"]
    if dt in INT_TYPES:
        return True
    if dt in NUM_TYPES:
        n = norm(col["column_name"])
        return any(w in n for w in WHOLE_WORDS) and not any(w in n for w in DECIMAL_WORDS)
    return False


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data: dict):
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ Supabase REST
class Supabase:
    def __init__(self, url: str, key: str):
        self.root = url.rstrip("/")
        self.base = self.root + "/rest/v1/"
        self.h = {"apikey": key, "Authorization": f"Bearer {key}",
                  "Content-Type": "application/json"}

    # ---- Storage (photos)
    def upload(self, path: str, data: bytes, content_type="image/jpeg") -> str:
        h = {**self.h, "Content-Type": content_type, "x-upsert": "false",
             "cache-control": "max-age=31536000"}
        r = requests.post(f"{self.root}/storage/v1/object/{BUCKET}/{path}",
                          headers=h, data=data, timeout=60)
        if not r.ok:
            try:
                msg = r.json().get("message") or r.text
            except ValueError:
                msg = r.text
            if "bucket" in msg.lower() and "not found" in msg.lower():
                msg += " — setup.sql dobara chalayein (bucket nahi bana)."
            elif "row-level security" in msg.lower() or r.status_code in (401, 403):
                msg += " — Storage ki permission nahi hai, setup.sql chalayein."
            raise RuntimeError("Photo upload nahi hui: " + msg)
        return self.public_url(path)

    def public_url(self, path: str) -> str:
        return f"{self.root}/storage/v1/object/public/{BUCKET}/{path}"

    @staticmethod
    def _check(r: requests.Response):
        if r.ok:
            return r.json() if r.text else []
        try:
            j = r.json()
            msg = j.get("message") or r.text
            if j.get("hint"):
                msg += f" ({j['hint']})"
        except ValueError:
            msg = f"{r.status_code} {r.text[:200]}"
        raise RuntimeError(msg)

    def columns(self, table: str) -> list[dict]:
        r = requests.post(self.base + "rpc/mwi_table_columns", headers=self.h,
                          json={"p_table": table}, timeout=20)
        return self._check(r)

    def select(self, table: str, params: dict):
        return self._check(requests.get(self.base + table, headers=self.h,
                                        params=params, timeout=20))

    def update(self, table: str, id_col: str, id_val, row: dict):
        """Ek entry (id se) badalta hai. Badli hui rows lautata hai ([] = permission nahi/entry nahi)."""
        h = {**self.h, "Prefer": "return=representation"}
        return self._check(requests.patch(self.base + table, headers=h,
                                          params={id_col: f"eq.{id_val}"}, json=row, timeout=20))

    def delete(self, table: str, id_col: str, id_val):
        """Ek entry (id se) mitata hai. Miti hui rows lautata hai ([] = permission nahi/entry nahi)."""
        h = {**self.h, "Prefer": "return=representation"}
        return self._check(requests.delete(self.base + table, headers=h,
                                           params={id_col: f"eq.{id_val}"}, timeout=20))

    def insert(self, table: str, row: dict):
        h = {**self.h, "Prefer": "return=minimal"}
        return self._check(requests.post(self.base + table, headers=h,
                                         json=row, timeout=20))


@st.cache_data(ttl=600, show_spinner=False)
def get_columns(url: str, key: str, table: str) -> list[dict]:
    return Supabase(url, key).columns(table)


# ------------------------------------------------------------------ images
def compress_image(uploaded) -> bytes:
    """Photo ko chhota karke JPG bytes banata hai (cloud ki jagah bachane ke liye)."""
    img = ImageOps.exif_transpose(Image.open(uploaded))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((MAX_IMG_SIDE, MAX_IMG_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def save_image(db: "Supabase", uploaded, folder_name: str) -> str:
    """Photo ko cloud ke folder (old_parts/, counter_in/ ...) mein daalta hai, public URL lautata hai."""
    name = f"{folder_name}_{now_ist():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.jpg"
    return db.upload(f"{folder_name}/{name}", compress_image(uploaded))


def image_src(db: "Supabase", value) -> str | None:
    """DB mein rakhi value se dikhane layak link banata hai."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    v = str(value).strip()
    if not v:
        return None
    if v.startswith("http"):
        return v
    p = Path(v) if Path(v).is_absolute() else APP_DIR / v    # purani local photo
    if p.exists():
        return str(p)
    if "/" in v and not Path(v).is_absolute():               # sirf cloud path save hua ho
        return db.public_url(v.lstrip("/"))
    return None


# ------------------------------------------------------------------ form helpers
def pretty(name: str) -> str:
    return name.replace("_", " ").strip().title()


def input_for(col: dict, key: str, label: str | None = None):
    """Column ke data type ke hisaab se sahi input box banata hai."""
    name, dt = col["column_name"], col["data_type"]
    req = (not col["is_nullable"]) and (not col["has_default"])
    label = (label or pretty(name)) + (" *" if req else "")

    if is_whole(col):
        return st.number_input(label, value=None, step=1, key=key)
    if dt in NUM_TYPES:
        return st.number_input(label, value=None, step=1.0, format="%.2f", key=key)
    if dt == "boolean":
        return st.checkbox(label, key=key)
    if dt == "date":
        dv = {} if key in st.session_state else {"value": now_ist().date()}
        return st.date_input(label, format="DD/MM/YYYY", key=key, **dv)
    if dt.startswith("timestamp"):
        c1, c2 = st.columns(2)
        dv = {} if key + "_d" in st.session_state else {"value": now_ist().date()}
        d = c1.date_input(label, format="DD/MM/YYYY", key=key + "_d", **dv)
        tv = {} if key + "_t" in st.session_state else {
            "value": now_ist().time().replace(second=0, microsecond=0, tzinfo=None)}
        t = c2.time_input("Time", key=key + "_t", **tv)
        return datetime.combine(d, t, tzinfo=IST) if d else None
    if dt.startswith("time"):
        return st.time_input(label, value=None, key=key)
    if dt in ("json", "jsonb"):
        return st.text_area(label, placeholder='{"key": "value"}', key=key)
    if dt == "text" and any(w in name.lower() for w in ("remark", "note", "desc", "detail")):
        return st.text_area(label, height=80, key=key)
    return st.text_input(label, max_chars=col.get("max_length"), key=key)


def to_db_value(col: dict, value):
    dt = col["data_type"]
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        if dt in ("json", "jsonb"):
            return json.loads(value)
        if dt == "ARRAY":
            return [v.strip() for v in value.split(",") if v.strip()]
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if is_whole(col):
        return int(value)
    if dt in NUM_TYPES:
        return float(value)
    return value


def find_col(cols: list[dict], lower_name: str) -> str | None:
    for c in cols:
        if c["column_name"].lower() == lower_name:
            return c["column_name"]
    return None


def arrange_fields(table: str, fields: list[dict]):
    """Fields ko FIELD_ORDER ke kram mein lagata hai.
    Lautata hai: [(column, label)], {column: label}, [missing specs]"""
    conf = FIELD_ORDER.get(table, {})
    by_norm = {norm(c["column_name"]): c["column_name"] for c in fields}
    used, labels, missing = set(), {}, []

    def match(spec):
        for a in [spec["sql"]] + spec["aliases"]:
            col = by_norm.get(norm(a))
            if col and col not in used:
                used.add(col)
                labels[col] = spec["label"]
                return col
        missing.append(spec)
        return None

    first = [c for c in (match(sp) for sp in conf.get("first", [])) if c]
    last = [c for c in (match(sp) for sp in conf.get("last", [])) if c]
    middle = [c["column_name"] for c in fields if c["column_name"] not in used]
    order = first + middle + last
    return [(c, labels.get(c, pretty(c))) for c in order], labels, missing


def missing_sql(table: str, missing: list[dict]) -> str:
    return "\n".join(f'alter table public."{table}" add column if not exists '
                     f'"{m["sql"]}" {m["type"]};' for m in missing)


def photo_fields(table: str, cols: list[dict]) -> list[dict]:
    """Is table ke photo columns (jo database mein sach mein maujood hain)."""
    out = []
    for f in PHOTOS.get(table, {}).get("fields", []):
        real = find_col(cols, f["col"])
        if real:
            out.append({**f, "col": real})
    known = {f["col"] for f in out}
    for c in cols:                       # naya photo column bina config ke bhi chalega
        n = c["column_name"]
        if n not in known and n.lower().endswith(("photo_path", "pic_path")):
            out.append({"col": n, "label": pretty(n.replace("_Path", "").replace("_path", "")),
                        "folder": n.lower().replace("_path", ""), "button": "🖼️ " + pretty(n),
                        "title": pretty(n)})
    return out


# ------------------------------------------------------------------ entry form
IMG_TYPES = ["jpg", "jpeg", "png", "webp", "bmp"]


def photo_picker(label: str, key: str):
    """Gallery se file ya seedhe Camera se photo. Photo aane par preview dikhata hai."""
    st.markdown(f"**{label}**")
    mode = st.radio(label, ["📁 Gallery", "📸 Camera"], horizontal=True,
                    key=key + "_mode", label_visibility="collapsed")
    if mode == "📸 Camera":
        f = st.camera_input(label, key=key + "_cam", label_visibility="collapsed")
    else:
        f = st.file_uploader(label, type=IMG_TYPES, key=key + "_file",
                             label_visibility="collapsed")
    if f is not None:
        st.image(f, width=160)
        st.caption("✔ Photo ready – ab Save dabayein")
    return f


def ocr_key() -> str:
    try:
        return str(st.secrets.get("OCR_SPACE_KEY", "")).strip()
    except Exception:
        return ""


def set_widget(col: dict, key: str, value):
    """OCR se mili value ko form ke box mein daalta hai (box ke type ke hisaab se)."""
    dt = col["data_type"]
    ss = st.session_state
    if isinstance(value, date):
        if dt == "date":
            ss[key] = value
        elif dt.startswith("timestamp"):
            ss[key + "_d"] = value
        else:
            ss[key] = value.strftime("%d-%m-%Y")
        return
    if is_whole(col):
        try:
            ss[key] = int(re.sub(r"\D", "", str(value)))
        except ValueError:
            pass
    elif dt in NUM_TYPES:
        try:
            ss[key] = float(value)
        except ValueError:
            pass
    else:
        ss[key] = str(value)


def prefill_widget(col: dict, key: str, raw):
    """Edit ke liye: database ki purani value ko form ke box mein pehle se bharta hai."""
    dt = col["data_type"]
    ss = st.session_state
    empty = raw is None or (isinstance(raw, str) and raw.strip() == "")
    try:
        if dt == "date":
            ss[key] = None if empty else date.fromisoformat(str(raw)[:10])
        elif dt.startswith("timestamp"):
            if empty:
                ss[key + "_d"], ss[key + "_t"] = None, None
            else:
                d = pd.to_datetime(raw, utc=True).tz_convert(IST)
                ss[key + "_d"], ss[key + "_t"] = d.date(), d.time().replace(second=0, microsecond=0)
        elif dt.startswith("time"):
            ss[key] = None if empty else time.fromisoformat(str(raw)[:8])
        elif dt == "boolean":
            ss[key] = bool(raw) if not empty else False
        elif is_whole(col):
            ss[key] = None if empty else int(round(float(raw)))
        elif dt in NUM_TYPES:
            ss[key] = None if empty else float(raw)
        elif dt in ("json", "jsonb"):
            ss[key] = "" if empty else json.dumps(raw, ensure_ascii=False)
        elif dt == "ARRAY":
            ss[key] = "" if empty else ", ".join(map(str, raw))
        else:
            ss[key] = "" if empty else str(raw)
    except (ValueError, TypeError):
        ss[key] = None if (is_whole(col) or dt in NUM_TYPES or dt == "date") else str(raw or "")


def machine_from_filename(name: str) -> str:
    """Photo ki file ke naam se Machine No:  M1.jpg -> M1,  M12 (2).jpeg -> M12,  Counter_M3.png -> M3"""
    stem = Path(str(name or "")).stem
    m = re.search(r"(?i)(?:^|[^a-z0-9])m\s*[-_ ]?\s*(\d{1,3})(?=$|[^0-9])", stem)
    return f"M{int(m[1])}" if m else ""


_LOOKALIKE = str.maketrans("Z2O0QDI1LS5B8G6", "220000111558866")


def _one_extra(ocr: str, known: str) -> bool:
    """OCR ne ek faltu akshar jod diya ho (KZ2T00864 vs KZT00864).
    Ank badalne wala farq (XRW01235 vs XRW01234) NAHI maana jaata - wo alag machine ho sakti hai."""
    if len(ocr) != len(known) + 1:
        return False
    a, b = ocr.translate(_LOOKALIKE), known.translate(_LOOKALIKE)
    return any(a[:i] + a[i + 1:] == b for i in range(len(a)))


def fix_serial(db, table: str, labels: dict, serial: str) -> str:
    """OCR wale Serial ko pehle se save Serial Numbers se milata hai (K2T00864 -> KZT00864)."""
    by_label = {lbl: col for col, lbl in labels.items()}
    scols = [c for c in (by_label.get("Serial Number (IN)"), by_label.get("Serial Number (OUT)")) if c]
    if not db or not scols or not serial:
        return serial
    try:
        rows = db.select(table, {"select": ",".join(scols), "limit": 2000})
    except Exception:
        return serial
    known = {str(r[c]).strip().upper() for r in rows for c in scols if r.get(c)}
    s0 = serial.upper()
    if s0 in known:
        return s0
    alike = [k for k in known if k.translate(_LOOKALIKE) == s0.translate(_LOOKALIKE)]
    if len(alike) == 1:
        return alike[0]
    near = [k for k in known if len(k) >= 6 and _one_extra(s0, k)]
    return near[0] if len(near) == 1 else serial


def lookup_by_serial(db, table: str, labels: dict, order_col: str, serial: str) -> dict:
    """Isi Serial Number wali pichhli entry se Machine No aur Model nikalta hai."""
    by_label = {lbl: col for col, lbl in labels.items()}
    scols = [c for c in (by_label.get("Serial Number (IN)"), by_label.get("Serial Number (OUT)")) if c]
    mcol = by_label.get("Machine No")
    if not db or not scols or not mcol or not serial:
        return {}
    flt = ",".join(f'{c}.eq."{serial}"' for c in scols)
    try:
        rows = db.select(table, {"select": "*", "or": f"({flt})", "order": f"{order_col}.desc",
                                 "limit": 20})
    except Exception:
        return {}
    out = {}
    for r in rows:
        if not out.get("machine") and r.get(mcol):
            out["machine"] = str(r[mcol])
        for lbl in ("Model (IN)", "Model (OUT)"):
            c = by_label.get(lbl)
            if not out.get("model") and c and r.get(c):
                out["model"] = str(r[c])
    return out


def filename_fill(photo, k: str, pcol: str, labels: dict):
    """Bina OCR: sirf photo ki file ke naam se Machine No (M1.jpeg -> M1). Turant, koi intezaar nahi."""
    sig_key = f"{k}_{pcol}_fnsig"
    sig = (getattr(photo, "file_id", None) or getattr(photo, "name", ""), getattr(photo, "size", 0))
    mno = machine_from_filename(getattr(photo, "name", ""))
    mcol = {lbl: c for c, lbl in labels.items()}.get("Machine No")
    if st.session_state.get(sig_key) != sig:
        st.session_state[sig_key] = sig
        if mno and mcol and st.session_state.get(f"{k}_{mcol}") != mno:
            st.session_state[f"{k}_pending"] = {mcol: mno}   # box pehle ban chuka: agli baar bharenge
            st.rerun()
    if mno and mcol:
        st.caption(f"🏷️ Machine No: **{mno}** (file ke naam se)")


def ocr_fill(photo, targets: dict, by_name: dict, k: str, pcol: str,
             db=None, table: str = "", labels: dict | None = None, order_col: str = "id"):
    """Nayi photo aane par OCR karke us group ke fields bharta hai.
    Machine No: 1) photo ki file ke naam se (M1.jpg -> M1)  2) photo mein likha ho to
                3) warna isi Serial Number ki pichhli entry se."""
    labels = labels or {}
    sig_key, res_key = f"{k}_{pcol}_ocrsig", f"{k}_{pcol}_ocrres"
    sig = (getattr(photo, "file_id", None) or getattr(photo, "name", ""), getattr(photo, "size", 0))
    if st.session_state.get(sig_key) != sig:
        fname_machine = machine_from_filename(getattr(photo, "name", ""))
        if ocr_counter is None:
            st.session_state[res_key] = ({"machine": fname_machine,
                                          "_machine_src": "file ke naam se"} if fname_machine else {},
                                         "", "", "ocr_counter.py file nahi mili")
        else:
            with st.spinner("🔍 Photo padh raha hai (OCR)... Pls Wait"):
                try:
                    data, text, engine = ocr_counter.read_photo(photo.getvalue(), ocr_key())
                    data = dict(data)
                    # Serial ko pehle se save Serials se milao (OCR ki Z/2, O/0 galti)
                    if data.get("serial"):
                        data["serial"] = fix_serial(db, table, labels, data["serial"])
                    # Serial Number se pichhli entry: Machine No (aur Model agar photo mein na ho)
                    past = lookup_by_serial(db, table, labels, order_col, data.get("serial", ""))
                    if "model" not in data and past.get("model"):
                        data["model"] = past["model"]
                    src = ""
                    if fname_machine:
                        data["machine"], src = fname_machine, "file ke naam se"
                    elif data.get("machine"):
                        src = "photo se"
                    elif past.get("machine"):
                        data["machine"], src = past["machine"], "isi Serial ki pichhli entry se"
                    data["_machine_src"] = src
                    for kk, col in targets.items():
                        if kk in data:
                            set_widget(by_name[col], f"{k}_{col}", data[kk])
                    st.session_state[res_key] = (data, text, engine, "")
                except Exception as e:
                    st.session_state[res_key] = ({"machine": fname_machine,
                                                  "_machine_src": "file ke naam se"}
                                                 if fname_machine else {}, "", "", str(e))
        data0 = st.session_state[res_key][0]
        mcol = {lbl: c for c, lbl in labels.items()}.get("Machine No")
        if data0.get("machine") and mcol:
            cur = st.session_state.get(f"{k}_{mcol}")
            # file ke naam wala Machine No hamesha lagao; baaki tabhi jab box khaali ho
            if not cur or (data0.get("_machine_src") == "file ke naam se" and cur != data0["machine"]):
                # Machine No ka box photo se pehle ban chuka hai: agli baar (rerun) bharenge
                st.session_state[f"{k}_pending"] = {mcol: data0["machine"]}
        st.session_state[sig_key] = sig
        if st.session_state.get(f"{k}_pending"):
            st.rerun()

    data, text, engine, err = st.session_state.get(res_key, ({}, "", "", ""))
    if err:
        st.warning(f"OCR nahi ho saka: {err}. Values haath se bharein.")
        if data.get("machine"):
            st.caption(f"🏷️ Machine No: **{data['machine']}** ({data.get('_machine_src', '')})")
        return
    got = [OCR_NAMES[x] for x in targets if x in data]
    miss = [OCR_NAMES[x] for x in targets if x not in data]
    ver = getattr(ocr_counter, "VERSION", "")
    msg = f"🔍 OCR ({engine}, v{ver or '?'}): {len(got)}/{len(targets)} values bhari gayi"
    if not ver:
        st.error("⚠️ ocr_counter.py purani hai – GitHub par nayi ocr_counter.py upload karein.")
    if miss:
        st.warning("Update Value: " + ", ".join(miss) + f"   (OCR v{ver or '?'})")
    elif data.get("_total_src") == "count":
        st.success(f"✔ Total = {data['total']} (Count ke neeche pehli row)   ·   "
                   f"{len(got)}/{len(targets)} values bhari gayi (OCR v{ver})")
    else:
        st.info(msg + ". Save se pehle ek baar jaanch lein.")
    if "total" in data and data.get("_total_src") != "count" and "total" in targets:
        st.warning("⚠️ Count ke neeche pehli row saaf nahi padhi gayi – Total ek baar report se "
                   "mila lein.")
    c1, c2 = st.columns([1, 2])
    if c1.button("🔄 OCR dobara", key=f"{k}_{pcol}_reocr"):
        st.session_state.pop(sig_key, None)
        st.rerun()
    with c2.expander("Photo se padha gaya text"):
        st.text(text.strip() or "(kuch nahi padha gaya)")
    if "Machine No" in labels.values():
        if data.get("machine"):
            st.caption(f"🏷️ Machine No: **{data['machine']}** ({data.get('_machine_src', '')})")
        elif data.get("serial"):
            st.caption(f"🏷️ Serial **{data['serial']}** ki pehli entry hai – Machine No haath se "
                       "bharein, agli baar apne-aap aayega.")


def entry_form(db: Supabase, table: str, cols: list[dict], edit: dict | None = None):
    """Nayi entry ka form.  edit={"id_col", "id", "row"} ho to wahi form purani entry badalne ke liye."""
    pics = photo_fields(table, cols)
    pic_cols = {f["col"] for f in pics}
    fields = [c for c in cols if not c["is_auto"] and c["column_name"] not in pic_cols]

    # Save ke baad form khaali karne ke liye har baar naye widget keys
    ver_key = f"{table}_ever" if edit else f"{table}_ver"
    ver = st.session_state.setdefault(ver_key, 0)
    k = f"{table}_e{edit['id']}_v{ver}" if edit else f"{table}_v{ver}"

    # Edit: purani values form mein pehle se (sirf pehli baar)
    if edit and not st.session_state.get(f"{k}_pref"):
        for c in fields:
            prefill_widget(c, f"{k}_{c['column_name']}", edit["row"].get(c["column_name"]))
        st.session_state[f"{k}_pref"] = True

    # OCR se mila Machine No (box banne se pehle bharna zaroori hai)
    pend = st.session_state.pop(f"{k}_pending", None)
    if pend:
        meta = {c["column_name"]: c for c in cols}
        for col, v in pend.items():
            if col in meta:
                set_widget(meta[col], f"{k}_{col}", v)

    done = None if edit else st.session_state.pop(f"{table}_done", None)
    if done is not None:
        st.success("Entry Saved")
        if done:
            for colx, (t, u) in zip(st.columns(len(done)), done):
                colx.image(u, caption=t, width=200)

    ordered, labels, missing = arrange_fields(table, fields)
    if missing:
        names = ", ".join(m["label"] for m in missing)
        with st.expander(f"⚠️ Ye field table mein nahi mile: {names}"):
            st.write("Supabase ke SQL Editor mein ye chalayein, phir sidebar mein "
                     "**Columns Refresh** dabayein:")
            st.code(missing_sql(table, missing), language="sql")

    by_name = {c["column_name"]: c for c in fields}
    rules = {r["t_col"]: r for r in calc_rules(table, labels)}
    types = {c["column_name"]: c["data_type"] for c in fields}
    values, uploads = {}, {}                       # uploads: photo column -> photo

    # OCR wali photo usi ke fields se theek pehle dikhegi
    by_label = {lbl: col for col, lbl in labels.items()}
    ocr_groups = {}                                # photo col -> {ocr key: field col}
    for f in pics:
        conf = OCR_MAP.get(table, {}).get(f["col"].lower())
        if conf:
            tg = {kk: by_label[lbl] for kk, lbl in conf.items() if lbl in by_label}
            if tg:
                ocr_groups[f["col"]] = tg
    order_names = [n for n, _ in ordered]
    photo_before = {}
    for pc, tg in ocr_groups.items():
        first = min(tg.values(), key=order_names.index)
        photo_before[first] = next(f for f in pics if f["col"] == pc)

    def render_field(name, label):
        if name in rules:                          # apne-aap hisaab, bharna nahi
            r = rules[name]
            res = run_rule(r, values, types)
            st.text_input(label,
                          value="" if res is None else f"{res:g}", disabled=True,
                          key=f"{k}_{name}_auto_{res}")
            if r.get("no_negative") and res is not None and res < 0:
                st.caption(f"⚠️ {r['uses'][1]}, {r['uses'][0]} se zyada hai")
            values[name] = res
        else:
            values[name] = input_for(by_name[name], f"{k}_{name}", label)

    def pick_photo(f):
        if edit:
            cur = image_src(db, edit["row"].get(f["col"]))
            if cur:
                st.image(cur, width=160)
        return photo_picker(f["label"], f"{k}_{f['col']}")

    pending = []

    def flush():
        for i in range(0, len(pending), 2):
            for colx, (n, l) in zip(st.columns(2), pending[i:i + 2]):
                with colx:
                    render_field(n, l)
        pending.clear()

    for name, label in ordered:
        if name in photo_before:
            flush()
            f = photo_before[name]
            st.markdown(f"#### 📷 {f['label']}")
            uploads[f["col"]] = pick_photo(f)
            if uploads[f["col"]] is not None:
                if OCR_ENABLED:
                    ocr_fill(uploads[f["col"]], ocr_groups[f["col"]], by_name, k, f["col"],
                             db, table, labels, cols[0]["column_name"])
                else:
                    filename_fill(uploads[f["col"]], k, f["col"], labels)
        pending.append((name, label))
    flush()

    rest = [f for f in pics if f["col"] not in uploads]
    if rest:
        st.markdown(f"#### 📷 {PHOTOS.get(table, {}).get('heading', 'Photo')}")
        for colx, f in zip(st.columns(len(rest)), rest):
            with colx:
                uploads[f["col"]] = pick_photo(f)

    # ---- Save button: dabate hi band (disabled) ho jata hai, double save nahi hoga
    lock_key = f"{table}_esaving" if edit else f"{table}_saving"
    err_key = f"{table}_eerr" if edit else f"{table}_err"
    saving = st.session_state.get(lock_key, False)

    def _start_save():
        st.session_state[lock_key] = True

    st.button("⏳ Save ho raha hai... Pls Wait" if saving else ("💾 Save Changes" if edit else "💾 Save"),
              type="primary", use_container_width=True, disabled=saving,
              on_click=_start_save, key=f"{k}_save")
    err = st.session_state.pop(err_key, None)
    if err:
        st.error(err)
    if not saving:
        return

    try:
        result = save_entry(db, table, fields, labels, pics, values, uploads, edit=edit)
    finally:
        st.session_state[lock_key] = False

    if isinstance(result, str):                    # galti ka sandesh
        st.session_state[err_key] = result
    elif edit:
        st.session_state[f"{table}_edit_msg"] = f"✔ Entry Updated (id {edit['id']})"
        st.session_state.pop(f"{table}_edit_id", None)     # edit band
        st.session_state[ver_key] = ver + 1
    else:
        st.session_state[f"{table}_done"] = result
        st.session_state[ver_key] = ver + 1        # form khaali
    st.rerun()


def save_entry(db, table, fields, labels, pics, values, uploads, edit=None):
    """Entry save karta hai (edit ho to purani entry badalta hai).
    Safal hone par photo list, warna galti ka sandesh (str) lautata hai."""
    any_photo = any(u is not None for u in uploads.values())
    row, req_missing = {}, []
    for c in fields:
        name = c["column_name"]
        try:
            v = to_db_value(c, values.get(name))
        except (ValueError, json.JSONDecodeError):
            return f"'{labels.get(name, pretty(name))}' ki value sahi nahi hai."
        if v is None and not c["is_nullable"] and not c["has_default"]:
            req_missing.append(labels.get(name, pretty(name)))
        if v is not None or edit:                  # edit: khaali kiya field database mein bhi khaali
            row[name] = v
    if req_missing:
        return "Ye fields bharna zaroori hai: " + ", ".join(req_missing)

    # Khaali form ki jaanch: pehle se bhari tareekh/samay, auto-hisaab wale fields
    # aur bina tick ke checkbox ko "bhara hua" nahi maana jaata
    types = {c["column_name"]: c["data_type"] for c in fields}
    rules = calc_rules(table, labels)
    auto_cols = {r["t_col"] for r in rules}
    filled = [n for n, v in row.items()
              if n not in auto_cols and v is not False and v is not None
              and not types.get(n, "").startswith(("date", "timestamp", "time"))]
    if not filled and not any_photo:
        return "Form is Empty ?"

    # Apne-aap hisaab (Toner Balance, No of Paper, Balance Paper Qty ...)
    for r in rules:
        row.pop(r["t_col"], None)
        res = run_rule(r, row, types)
        if res is None:
            continue
        if r.get("no_negative") and res < 0:
            return f"{r['uses'][1]}, {r['uses'][0]} se zyada nahi ho sakta."
        row[r["t_col"]] = res

    # Duplicate jaanch: bilkul wahi entry 2 minute ke andar dobara save na ho
    photo_sig = sorted((col, getattr(u, "name", ""), getattr(u, "size", 0))
                       for col, u in uploads.items() if u is not None)
    fp = hashlib.md5(json.dumps([table, row, photo_sig], sort_keys=True, default=str)
                     .encode()).hexdigest()
    last = st.session_state.get(f"{table}_last_fp")
    if not edit and last and last[0] == fp and _time.time() - last[1] < 120:
        return "⚠️ Ye entry abhi-abhi save ho chuki hai, isliye dobara save nahi ki gayi."

    try:
        with st.spinner("Save ho raha hai... Pls Wait"):
            for f in pics:
                if uploads.get(f["col"]) is not None:
                    row[f["col"]] = save_image(db, uploads[f["col"]], f["folder"])
            if edit:
                changed = db.update(table, edit["id_col"], edit["id"], row)
                if not changed:
                    return ("❌ Entry update nahi hui – Supabase mein 'edit_permission.sql' "
                            "chalayein (ek baar).")
            else:
                db.insert(table, row)
    except Exception as e:
        return f"❌ Save nahi hua: {e}"

    st.session_state[f"{table}_last_fp"] = (fp, _time.time())
    return [(f["label"], row[f["col"]]) for f in pics if row.get(f["col"])]


# ------------------------------------------------------------------ records + images
def records_view(db: Supabase, table: str, cols: list[dict]):
    first = cols[0]["column_name"]
    limit = st.select_slider("Show Entries", [10, 25, 50, 100, 500], value=25,
                             key=f"{table}_limit")
    try:
        rows = db.select(table, {"select": "*", "order": f"{first}.desc", "limit": limit})
    except RuntimeError:
        rows = db.select(table, {"select": "*", "limit": limit})
    if not rows:
        st.info("Empty Entry ?")
        return
    df = pd.DataFrame(rows)
    sc = summary_cols(table, cols)         # Machine Counter: dates / totals ke columns
    days_col = None
    if sc.get("din") in df.columns and sc.get("dout") in df.columns:
        days = (pd.to_datetime(df[sc["dout"]], errors="coerce")
                - pd.to_datetime(df[sc["din"]], errors="coerce")).dt.days
        days_col = "Net Days"
        df[days_col] = days.astype("Int64")
    for c in cols:                         # poore ank bina .00 ke
        if c["column_name"] in df.columns and is_whole(c):
            df[c["column_name"]] = pd.to_numeric(df[c["column_name"]], errors="coerce").round().astype("Int64")
    for c in cols:                         # UTC -> India ka samay
        if c["data_type"].startswith("timestamp") and c["column_name"] in df.columns:
            t = pd.to_datetime(df[c["column_name"]], utc=True, errors="coerce")
            df[c["column_name"]] = t.dt.tz_convert(IST).dt.strftime("%d-%m-%Y %I:%M %p")
        elif c["data_type"] == "date" and c["column_name"] in df.columns:
            t = pd.to_datetime(df[c["column_name"]], errors="coerce")
            df[c["column_name"]] = t.dt.strftime("%d-%m-%Y")
    pics = [f for f in photo_fields(table, cols) if f["col"] in df.columns]
    pic_cols = [f["col"] for f in pics]

    # columns ka kram: id -> form wale fields -> photos -> created_at
    auto = [c for c in cols if c["is_auto"]]
    inputs = [c for c in cols if not c["is_auto"] and c["column_name"] not in pic_cols]
    ordered, labels, _ = arrange_fields(table, inputs)
    order = ([c["column_name"] for c in auto if not c["data_type"].startswith("timestamp")]
             + [n for n, _ in ordered] + pic_cols
             + [c["column_name"] for c in auto if c["data_type"].startswith("timestamp")])
    if days_col:                           # Net Days: Reading Date (OUT) ke theek baad
        at = order.index(sc["dout"]) + 1 if sc["dout"] in order else len(order)
        order.insert(at, days_col)
    order = [c for c in order if c in df.columns] + [c for c in df.columns if c not in order]
    df = df[order]
    all_labels = {n: lbl for n, lbl in ordered}

    view = df.copy()
    cfg = {n: st.column_config.Column(lbl) for n, lbl in all_labels.items()}
    for f in pics:
        view[f["col"]] = view[f["col"]].map(lambda v: image_src(db, v))
        cfg[f["col"]] = st.column_config.ImageColumn(f["label"], width="small")
    grid_kw = dict(on_select="rerun", selection_mode="single-row",
                   key=f"{table}_grid_{st.session_state.get(f'{table}_gver', 0)}")
    try:
        ev = st.dataframe(view, use_container_width=True, hide_index=True, column_config=cfg, **grid_kw)
    except TypeError:                                  # purana Streamlit: row chunna nahi
        ev = st.dataframe(view, use_container_width=True, hide_index=True, column_config=cfg)
    picked_from_grid = False
    try:
        sel_rows = list(ev.selection.rows)
    except Exception:
        sel_rows = []
    if sel_rows and 0 <= sel_rows[0] < len(df):
        gi = df.index[sel_rows[0]]
        last_key = f"{table}_grid_last"
        if st.session_state.get(last_key) != gi:       # nayi row chuni: neeche wala box bhi wahi
            st.session_state[last_key] = gi
            st.session_state[f"{table}_pick"] = gi
        picked_from_grid = True
    csv = df.rename(columns={**all_labels, **{f["col"]: f["label"] for f in pics}})
    st.download_button("⬇️ Excel (CSV) download", csv.to_csv(index=False).encode("utf-8-sig"),
                       f"{table}.csv", "text/csv", key=f"{table}_csv")
    if sc:
        counter_summary(db, table, sc)

    if edit_section(db, table, cols, df, rows, sel_rows):
        return                                     # edit chal raha hai: neeche ka hissa chhupa

    if not pics:
        return

    conf = PHOTOS.get(table, {})
    st.divider()
    st.subheader(f"🖼️ {conf.get('heading', 'Photo')}")
    show_cols = [c for c in df.columns if c not in pic_cols][:3]
    labels = {i: " | ".join(str(df.at[i, c]) for c in show_cols) for i in df.index}
    idx = st.selectbox(f"{conf.get('item', 'Entry')} Select & Show", list(labels),
                       format_func=labels.get, key=f"{table}_pick")

    state_key = f"{table}_show_img"
    for n, (colx, f) in enumerate(zip(st.columns(len(pics)), pics)):
        if colx.button(f["button"], use_container_width=True, key=f"{table}_b{n}"):
            st.session_state[state_key] = (idx, f["col"])

    photo_update_box(db, table, cols, df, idx, pics, expanded=picked_from_grid)

    chosen = st.session_state.get(state_key)
    if not chosen or chosen[0] != idx:
        return
    f = next((x for x in pics if x["col"] == chosen[1]), None)
    if f is None:
        return
    raw = df.at[idx, f["col"]]
    src = image_src(db, raw)
    title = f["title"]
    if src is None:
        if raw is None or (isinstance(raw, float) and pd.isna(raw)) or not str(raw).strip():
            st.warning(f"Is entry mein {title} ki photo nahi daali gayi thi.")
        else:
            st.error(f"Photo nahi mili: {raw}")
    else:
        st.image(src, caption=title, use_container_width=True)
        if src.startswith("http"):
            st.markdown(f"[🔗 Photo poore size mein kholein]({src})")


def summary_cols(table: str, cols: list[dict]) -> dict:
    """Machine Counter ke Reading Date IN/OUT, Total IN/OUT, Net Total ke asli column naam."""
    if table != "Machine_Counter":
        return {}
    inputs = [c for c in cols if not c["is_auto"]]
    _, labels, _ = arrange_fields(table, inputs)
    by_label = {lbl: col for col, lbl in labels.items()}
    out = {"din": by_label.get("Reading Date (IN)"), "dout": by_label.get("Reading Date (OUT)"),
           "tin": by_label.get("Total (IN)"), "tout": by_label.get("Total (OUT)"),
           "net": by_label.get("Net Total")}
    return {k: v for k, v in out.items() if v}


def counter_summary(db, table: str, sc: dict):
    """CSV download ke neeche: poori Machine_Counter table ka jod."""
    try:
        rows = db.select(table, {"select": ",".join(sorted(set(sc.values()))), "limit": 100000})
    except Exception as e:
        st.caption(f"Total nahi nikal saka: {e}")
        return
    df = pd.DataFrame(rows)
    if df.empty:
        return

    def total(key):
        if sc.get(key) not in df.columns:
            return None
        return int(round(pd.to_numeric(df[sc[key]], errors="coerce").sum()))

    # Start Date = pehli Reading Date (IN), End Date = aakhri Reading Date (OUT)
    # (sirf wo entries jinmein dono date hain);  Total Days = End - Start  (jod nahi)
    days = start = end = None
    if sc.get("din") in df.columns and sc.get("dout") in df.columns:
        din = pd.to_datetime(df[sc["din"]], errors="coerce")
        dout = pd.to_datetime(df[sc["dout"]], errors="coerce")
        both = din.notna() & dout.notna()
        if both.any():
            start, end = din[both].min(), dout[both].max()
            days = int((end - start).days)
    items = [("Total Days", f"{days:,}" if days is not None else "–"),
             ("Start Date", start.strftime("%d-%m-%Y") if start is not None else "–"),
             ("End Date", end.strftime("%d-%m-%Y") if end is not None else "–")]
    out = total("net")                                   # Total Output = sab Net Total ka jod
    if out is not None:
        items.append(("Total Output", f"{out:,}"))
    st.markdown("**Grand Total**")
    cards = "".join(
        f'<div style="flex:1 1 140px;min-width:0;padding:8px 12px;border:1px solid rgba(128,128,128,.35);'
        f'border-radius:8px"><div style="font-size:.85rem;opacity:.75">{name}</div>'
        f'<div style="font-size:1.35rem;font-weight:600;white-space:nowrap">{v}</div></div>'
        for name, v in items)
    st.markdown(f'<div style="display:flex;flex-wrap:wrap;gap:10px">{cards}</div>',
                unsafe_allow_html=True)


def edit_section(db, table: str, cols: list[dict], df, rows: list[dict], sel_rows: list) -> bool:
    """Chuni hui row ke liye ✏️ Edit button aur edit form. Edit chal raha ho to True."""
    id_col = next((c["column_name"] for c in cols if c["column_name"].lower() == "id"), None)
    msg = st.session_state.pop(f"{table}_edit_msg", None)
    if msg:
        (st.error if msg.startswith("❌") else st.success)(msg)
    if not id_col or id_col not in df.columns:
        return False
    edit_key = f"{table}_edit_id"
    if sel_rows and 0 <= sel_rows[0] < len(df):
        gi = df.index[sel_rows[0]]
        rid = int(df.at[gi, id_col])
        summary = " | ".join(str(df.at[gi, c]) for c in list(df.columns)[:3])
        del_key = f"{table}_del_id"
        c1, c2, c3 = st.columns([1, 1, 3])
        if c1.button("✏️ Edit", type="primary", use_container_width=True, key=f"{table}_editbtn"):
            st.session_state[edit_key] = rid
            st.session_state.pop(del_key, None)
        if c2.button("🗑️ Delete", use_container_width=True, key=f"{table}_delbtn"):
            st.session_state[del_key] = rid
            st.session_state.pop(edit_key, None)
        c3.markdown(f"Selected Entry: **{summary}**")

        # Delete se pehle pakka poochho
        if st.session_state.get(del_key) == rid:
            st.warning(f"⚠️ Confirm Delete: **{summary}**")
            d1, d2, _ = st.columns([1, 1, 3])
            if d1.button("✅ Yes", type="primary", use_container_width=True,
                         key=f"{table}_delyes"):
                try:
                    gone = db.delete(table, id_col, rid)
                    st.session_state[f"{table}_edit_msg"] = (
                        f"🗑️ Entry Deleted (id {rid})" if gone else
                        "❌ Entry delete nahi hui – Supabase mein 'delete_permission.sql' chalayein (ek baar).")
                except Exception as e:
                    st.session_state[f"{table}_edit_msg"] = f"❌ Delete nahi hua: {e}"
                st.session_state.pop(del_key, None)
                st.session_state[f"{table}_gver"] = st.session_state.get(f"{table}_gver", 0) + 1
                st.rerun()
            if d2.button("✖ No", use_container_width=True, key=f"{table}_delno"):
                st.session_state.pop(del_key, None)
                st.rerun()

    eid = st.session_state.get(edit_key)
    if eid is None:
        return False
    raw = next((r for r in rows if str(r.get(id_col)) == str(eid)), None)
    if raw is None:
        try:
            got = db.select(table, {"select": "*", id_col: f"eq.{eid}"})
            raw = got[0] if got else None
        except RuntimeError:
            raw = None
    if raw is None:
        st.error(f"Entry id {eid} nahi mili.")
        st.session_state.pop(edit_key, None)
        return False

    st.divider()
    h1, h2 = st.columns([3, 1])
    h1.subheader(f"✏️ Edit Entry – id {eid}")
    if h2.button("✖ Cancel", use_container_width=True, key=f"{table}_editcancel"):
        st.session_state.pop(edit_key, None)
        st.rerun()
    try:
        box = st.container(border=True)
    except TypeError:
        box = st.container()
    with box:
        entry_form(db, table, cols, edit={"id_col": id_col, "id": eid, "row": raw})
    return True


def photo_update_box(db, table: str, cols: list[dict], df, idx, pics: list[dict], expanded=False):
    """Chuni hui entry mein photo jodna / badalna (ek-ek karke)."""
    id_col = next((c["column_name"] for c in cols if c["column_name"].lower() == "id"), None)
    msg_key = f"{table}_photo_upd_msg"
    msg = st.session_state.pop(msg_key, None)
    if msg:
        (st.success if msg[0] == "ok" else st.error)(msg[1])
    if not id_col or id_col not in df.columns:
        return
    row_id = df.at[idx, id_col]
    sel = " | ".join(str(df.at[idx, c]) for c in list(df.columns)[:2])
    with st.expander(f"📷 Photo Update – {sel}", expanded=expanded):
        names = {f["col"]: f["label"] for f in pics}
        # Machine Counter mein OUT photo pehle se chuni rahe
        default = next((i for i, f in enumerate(pics) if "out" in f["col"].lower()), 0)
        pcol = st.radio("Kaun-si photo?", list(names), index=default, format_func=names.get,
                        horizontal=True, key=f"{table}_pu_col")
        f = next(x for x in pics if x["col"] == pcol)
        cur = image_src(db, df.at[idx, pcol]) if pcol in df.columns else None
        if cur:
            st.image(cur, width=200)
        ver = st.session_state.get(f"{table}_pu_ver", 0)
        up = photo_picker(f["label"], f"{table}_pu_{ver}")
        if st.button("💾 Save Photo", type="primary", disabled=up is None,
                     use_container_width=True, key=f"{table}_pu_save_{ver}"):
            try:
                with st.spinner("Photo save ho rahi hai... Pls Wait"):
                    url = save_image(db, up, f["folder"])
                    done = db.update(table, id_col, int(row_id), {pcol: url})
                if done:
                    st.session_state[msg_key] = ("ok", f"✔ Photo Saved – entry id {row_id}")
                    st.session_state[f"{table}_pu_ver"] = ver + 1      # box khaali
                else:
                    st.session_state[msg_key] = ("err", "Photo upload hui par entry update nahi hui – "
                                                 "Supabase mein 'photo_update_permission.sql' chalayein.")
            except Exception as e:
                st.session_state[msg_key] = ("err", f"❌ Photo save nahi hui: {e}")
            st.rerun()


# ------------------------------------------------------------------ app
def cloud_secrets() -> tuple[str, str]:
    """Streamlit Cloud par chal raha ho to Secrets se URL/Key lo."""
    try:
        return st.secrets["SUPABASE_URL"].strip(), st.secrets["SUPABASE_KEY"].strip()
    except Exception:
        return "", ""


def connection_sidebar() -> tuple[str, str]:
    url, key = cloud_secrets()
    if url and key:                       # online version: key chhupi rahegi
        with st.sidebar:
            st.header("🔌 Supabase")
            st.success("Connected ✔")
            if st.button("🔄 Columns Refresh", use_container_width=True):
                get_columns.clear()
                st.rerun()
        return url, key

    s = load_settings()
    with st.sidebar:
        st.header("🔌 Supabase Connection")
        url = st.text_input("Project URL", value=s.get("url", DEFAULT_URL))
        key = st.text_input("Anon / Publishable Key", value=s.get("key", ""), type="password")
        if st.button("💾 Settings Save", use_container_width=True):
            save_settings({"url": url.strip(), "key": key.strip()})
            get_columns.clear()
            st.success("Save ho gaya.")
            st.rerun()
        st.caption(f"☁️ Photos Supabase Storage ke `{BUCKET}` bucket mein save hoti hain.")
        if st.button("🔄 Columns Refresh", use_container_width=True):
            get_columns.clear()
            st.rerun()
    return url.strip(), key.strip()


def main():
    st.set_page_config(page_title="MWI Inventory", page_icon="📦", layout="wide")
    st.title("📦 MWI Print – Inventory")

    url, key = connection_sidebar()
    if not url or not key:
        st.info("👈 Sidebar mein Supabase ki **Anon Key** daalein aur 'Settings Save' dabayein.")
        st.stop()

    db = Supabase(url, key)
    tabs = st.tabs(list(TABLES.values()))
    for tab, table in zip(tabs, TABLES):
        with tab:
            try:
                cols = get_columns(url, key, table)
            except Exception as e:
                msg = str(e)
                if "mwi_table_columns" in msg or "PGRST202" in msg or "404" in msg:
                    st.error("Setup baaki hai: Supabase ke SQL Editor mein **setup.sql** chalayein, "
                             "phir sidebar mein 'Columns Refresh' dabayein.")
                else:
                    st.error(f"Supabase se connect nahi hua: {msg}")
                continue
            if not cols:
                st.error(f"Table '{table}' nahi mila. Naam check karein.")
                continue

            mode = st.radio("Kya karna hai?", ["➕ New Entry", "📋 Entries Show"],
                            horizontal=True, key=f"{table}_mode", label_visibility="collapsed")
            if mode.startswith("➕"):
                entry_form(db, table, cols)
            else:
                try:
                    records_view(db, table, cols)
                except RuntimeError as e:
                    st.error(f"Entries nahi aa sakin: {e}")


if __name__ == "__main__":
    main()

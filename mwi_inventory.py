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
        ],
    },
}


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())
MAX_IMG_SIDE = 1600      # photo isse badi ho to chhoti kar di jaati hai (jagah bachane ke liye)
JPEG_QUALITY = 82

INT_TYPES = {"smallint", "integer", "bigint"}
NUM_TYPES = {"numeric", "real", "double precision", "money"}


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

    if dt in INT_TYPES:
        return st.number_input(label, value=None, step=1, key=key)
    if dt in NUM_TYPES:
        return st.number_input(label, value=None, step=1.0, format="%.2f", key=key)
    if dt == "boolean":
        return st.checkbox(label, key=key)
    if dt == "date":
        return st.date_input(label, value=now_ist().date(), format="DD/MM/YYYY", key=key)
    if dt.startswith("timestamp"):
        c1, c2 = st.columns(2)
        d = c1.date_input(label, value=now_ist().date(), format="DD/MM/YYYY", key=key + "_d")
        t = c2.time_input("Time", value=now_ist().time().replace(second=0, microsecond=0, tzinfo=None),
                          key=key + "_t")
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
    if dt in INT_TYPES:
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


def entry_form(db: Supabase, table: str, cols: list[dict]):
    pics = photo_fields(table, cols)
    pic_cols = {f["col"] for f in pics}
    fields = [c for c in cols if not c["is_auto"] and c["column_name"] not in pic_cols]

    # Save ke baad form khaali karne ke liye har baar naye widget keys
    ver_key = f"{table}_ver"
    ver = st.session_state.setdefault(ver_key, 0)
    k = f"{table}_v{ver}"

    done = st.session_state.pop(f"{table}_done", None)
    if done is not None:
        st.success(f"✅ {TABLES[table]} mein entry save ho gayi!")
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
    values = {}
    grid = st.columns(2)
    for i, (name, label) in enumerate(ordered):
        with grid[i % 2]:
            values[name] = input_for(by_name[name], f"{k}_{name}", label)

    uploads = {}                                   # column -> photo
    if pics:
        st.markdown(f"#### 📷 {PHOTOS.get(table, {}).get('heading', 'Photo')}")
        for colx, f in zip(st.columns(len(pics)), pics):
            with colx:
                uploads[f["col"]] = photo_picker(f["label"], f"{k}_{f['col']}")

    # ---- Save button: dabate hi band (disabled) ho jata hai, double save nahi hoga
    lock_key, err_key = f"{table}_saving", f"{table}_err"
    saving = st.session_state.get(lock_key, False)

    def _start_save():
        st.session_state[lock_key] = True

    st.button("⏳ Save ho raha hai... Pls Wait" if saving else "💾 Save",
              type="primary", use_container_width=True, disabled=saving,
              on_click=_start_save, key=f"{k}_save")
    err = st.session_state.pop(err_key, None)
    if err:
        st.error(err)
    if not saving:
        return

    try:
        result = save_entry(db, table, fields, labels, pics, values, uploads)
    finally:
        st.session_state[lock_key] = False

    if isinstance(result, str):                    # galti ka sandesh
        st.session_state[err_key] = result
    else:
        st.session_state[f"{table}_done"] = result
        st.session_state[ver_key] = ver + 1        # form khaali
    st.rerun()


def save_entry(db, table, fields, labels, pics, values, uploads):
    """Entry save karta hai. Safal hone par photo list, warna galti ka sandesh (str) lautata hai."""
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
        if v is not None:
            row[name] = v
    if req_missing:
        return "Ye fields bharna zaroori hai: " + ", ".join(req_missing)

    # Toner: Balance khaali chhoda ho to apne-aap  Toner Qty - Toner Used
    if table == "Toner":
        by_label = {lbl: col for col, lbl in labels.items()}
        q, u, b = (by_label.get(x) for x in ("Toner Qty", "Toner Used", "Toner Balance Qty"))
        if q and u and b and b not in row and q in row:
            row[b] = row[q] - row.get(u, 0)
            if row[b] < 0:
                return "Toner Used, Toner Qty se zyada nahi ho sakta."
    text_filled = any(isinstance(v, str) for v in row.values())
    if not row and not any_photo:
        return "Form khaali hai. Pehle details bharein, phir Save dabayein."
    if any(c["data_type"] in ("text", "character varying") for c in fields) \
            and not text_filled and not any_photo:
        return "Naam / details bharein, khaali entry save nahi hogi."

    # Duplicate jaanch: bilkul wahi entry 2 minute ke andar dobara save na ho
    photo_sig = sorted((col, getattr(u, "name", ""), getattr(u, "size", 0))
                       for col, u in uploads.items() if u is not None)
    fp = hashlib.md5(json.dumps([table, row, photo_sig], sort_keys=True, default=str)
                     .encode()).hexdigest()
    last = st.session_state.get(f"{table}_last_fp")
    if last and last[0] == fp and _time.time() - last[1] < 120:
        return "⚠️ Ye entry abhi-abhi save ho chuki hai, isliye dobara save nahi ki gayi."

    try:
        with st.spinner("Save ho raha hai... Pls Wait"):
            for f in pics:
                if uploads.get(f["col"]) is not None:
                    row[f["col"]] = save_image(db, uploads[f["col"]], f["folder"])
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
        st.info("Abhi koi entry nahi hai.")
        return
    df = pd.DataFrame(rows)
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
    order = [c for c in order if c in df.columns] + [c for c in df.columns if c not in order]
    df = df[order]
    all_labels = {n: lbl for n, lbl in ordered}

    view = df.copy()
    cfg = {n: st.column_config.Column(lbl) for n, lbl in all_labels.items()}
    for f in pics:
        view[f["col"]] = view[f["col"]].map(lambda v: image_src(db, v))
        cfg[f["col"]] = st.column_config.ImageColumn(f["label"], width="small")
    st.dataframe(view, use_container_width=True, hide_index=True, column_config=cfg)
    csv = df.rename(columns={**all_labels, **{f["col"]: f["label"] for f in pics}})
    st.download_button("⬇️ Excel (CSV) download", csv.to_csv(index=False).encode("utf-8-sig"),
                       f"{table}.csv", "text/csv", key=f"{table}_csv")

    if not pics:
        return

    conf = PHOTOS.get(table, {})
    st.divider()
    st.subheader(f"🖼️ {conf.get('heading', 'Photo')}")
    show_cols = [c for c in df.columns if c not in pic_cols][:3]
    labels = {i: " | ".join(str(df.at[i, c]) for c in show_cols) for i in df.index}
    idx = st.selectbox(f"{conf.get('item', 'Entry')} chunein", list(labels),
                       format_func=labels.get, key=f"{table}_pick")

    state_key = f"{table}_show_img"
    for n, (colx, f) in enumerate(zip(st.columns(len(pics)), pics)):
        if colx.button(f["button"], use_container_width=True, key=f"{table}_b{n}"):
            st.session_state[state_key] = (idx, f["col"])

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

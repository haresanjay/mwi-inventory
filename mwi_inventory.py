"""
MWI Print – Inventory Entry Form (Python + Streamlit + Supabase)

Tables : Machine_Parts, paper, PDF_DETAIL, Toner
Images : Supabase Storage (cloud) ke bucket "parts_images" mein
         Machine_Parts ki purani photo  -> parts_images/old_parts/
         Machine_Parts ki nayi photo    -> parts_images/new_parts/
         Database mein photo ka public link (URL) save hota hai,
         isliye photo kisi bhi computer ya mobile se dikhti hai.

Chalane ke liye:  run_app.bat  par double-click   (ya:  streamlit run mwi_inventory.py)
"""

import io
import json
import uuid
from datetime import date, datetime, time
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
    "Machine_Parts": "⚙️ Machine Parts",
    "paper": "📄 Paper",
    "PDF_DETAIL": "📑 PDF Detail",
    "Toner": "🖨️ Toner",
}
OLD_COL, NEW_COL = "old_item_pic_path", "new_item_pic_path"   # lower-case match
OLD_FOLDER, NEW_FOLDER = "old_parts", "new_parts"
BUCKET = "parts_images"
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
    """Photo ko cloud ke old_parts/ ya new_parts/ folder mein daalta hai, public URL lautata hai."""
    name = f"{folder_name}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.jpg"
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
    if v.startswith((OLD_FOLDER + "/", NEW_FOLDER + "/")):   # sirf path save hua ho
        return db.public_url(v)
    p = Path(v) if Path(v).is_absolute() else APP_DIR / v    # purani local photo
    return str(p) if p.exists() else None


# ------------------------------------------------------------------ form helpers
def pretty(name: str) -> str:
    return name.replace("_", " ").strip().title()


def input_for(col: dict, key: str):
    """Column ke data type ke hisaab se sahi input box banata hai."""
    name, dt = col["column_name"], col["data_type"]
    req = (not col["is_nullable"]) and (not col["has_default"])
    label = pretty(name) + (" *" if req else "")

    if dt in INT_TYPES:
        return st.number_input(label, value=None, step=1, key=key)
    if dt in NUM_TYPES:
        return st.number_input(label, value=None, step=1.0, format="%.2f", key=key)
    if dt == "boolean":
        return st.checkbox(pretty(name), key=key)
    if dt == "date":
        return st.date_input(label, value=date.today(), format="DD/MM/YYYY", key=key)
    if dt.startswith("timestamp"):
        c1, c2 = st.columns(2)
        d = c1.date_input(label, value=date.today(), format="DD/MM/YYYY", key=key + "_d")
        t = c2.time_input("Time", value=datetime.now().time().replace(second=0, microsecond=0),
                          key=key + "_t")
        return datetime.combine(d, t) if d else None
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
    old_col, new_col = find_col(cols, OLD_COL), find_col(cols, NEW_COL)
    pic_cols = {old_col, new_col} - {None}
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

    values = {}
    grid = st.columns(2)
    for i, c in enumerate(fields):
        with grid[i % 2]:
            values[c["column_name"]] = input_for(c, f"{k}_{c['column_name']}")

    old_up = new_up = None
    if pic_cols:
        st.markdown("#### 📷 Parts Photo")
        p1, p2 = st.columns(2)
        if old_col:
            with p1:
                old_up = photo_picker("Damage Parts Photo", f"{k}_old")
        if new_col:
            with p2:
                new_up = photo_picker("New Parts Photo", f"{k}_new")

    submitted = st.button("💾 Save", type="primary", use_container_width=True,
                          key=f"{k}_save")
    if not submitted:
        return

    # check + convert
    row, missing = {}, []
    for c in fields:
        name = c["column_name"]
        try:
            v = to_db_value(c, values.get(name))
        except (ValueError, json.JSONDecodeError):
            st.error(f"'{pretty(name)}' ki value sahi nahi hai.")
            return
        if v is None and not c["is_nullable"] and not c["has_default"]:
            missing.append(pretty(name))
        if v is not None:
            row[name] = v
    if missing:
        st.error("Ye fields bharna zaroori hai: " + ", ".join(missing))
        return
    text_filled = any(isinstance(v, str) for v in row.values())
    if not row and old_up is None and new_up is None:
        st.error("Form khaali hai. Pehle details bharein, phir Save dabayein.")
        return
    if any(c["data_type"] in ("text", "character varying") for c in fields) and not text_filled \
            and old_up is None and new_up is None:
        st.error("Naam / details bharein, khaali entry save nahi hogi.")
        return

    try:
        with st.spinner("Save ho raha hai... (photo upload mein thoda samay lag sakta hai)"):
            if old_up is not None:
                row[old_col] = save_image(db, old_up, OLD_FOLDER)
            if new_up is not None:
                row[new_col] = save_image(db, new_up, NEW_FOLDER)
            db.insert(table, row)
    except Exception as e:
        st.error(f"❌ Save nahi hua: {e}")
        return

    st.session_state[f"{table}_done"] = [
        (t, row[c]) for t, c in (("Damage Parts Photo", old_col), ("New Parts Photo", new_col))
        if c and row.get(c)]
    st.session_state[ver_key] = ver + 1          # form khaali
    st.rerun()


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
    old_col, new_col = find_col(cols, OLD_COL), find_col(cols, NEW_COL)

    view = df.copy()
    cfg = {}
    for c, title in ((old_col, "Old Photo"), (new_col, "New Photo")):
        if c and c in view.columns:
            view[c] = view[c].map(lambda v: image_src(db, v) if str(v).startswith(("http", OLD_FOLDER, NEW_FOLDER)) else None)
            cfg[c] = st.column_config.ImageColumn(title, width="small")
    st.dataframe(view, use_container_width=True, hide_index=True, column_config=cfg)
    st.download_button("⬇️ Excel (CSV) download", df.to_csv(index=False).encode("utf-8-sig"),
                       f"{table}.csv", "text/csv", key=f"{table}_csv")

    if not (old_col or new_col):
        return

    st.divider()
    st.subheader("🖼️ Parts Photo")
    show_cols = [c for c in df.columns if c not in (old_col, new_col)][:3]
    labels = {i: " | ".join(str(df.at[i, c]) for c in show_cols) for i in df.index}
    idx = st.selectbox("Part chunein", list(labels), format_func=labels.get,
                       key=f"{table}_pick")

    state_key = f"{table}_show_img"
    b1, b2 = st.columns(2)
    if old_col and b1.button("🔧 Old Parts Image", use_container_width=True, key=f"{table}_bo"):
        st.session_state[state_key] = (idx, "old")
    if new_col and b2.button("✨ New Parts Image", use_container_width=True, key=f"{table}_bn"):
        st.session_state[state_key] = (idx, "new")

    chosen = st.session_state.get(state_key)
    if not chosen or chosen[0] != idx:
        return
    which = chosen[1]
    col = old_col if which == "old" else new_col
    raw = df.at[idx, col] if col in df.columns else None
    src = image_src(db, raw)
    title = "Purana Part (Old)" if which == "old" else "Naya Part (New)"
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
        st.caption(f"☁️ Photos Supabase Storage mein save hoti hain:\n\n"
                   f"`{BUCKET}/{OLD_FOLDER}/`\n\n`{BUCKET}/{NEW_FOLDER}/`")
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

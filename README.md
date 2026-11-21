# 📦 MWI Print – Inventory App

**Multiwave Innovation (MWI Print)** ke print kaam ka poora hisaab ek jagah. Isme machine counter, parts, paper, toner, PDF/page detail, attendance, stock aur scanning billing sab aate hain.

- **Live app:** https://mwi-inventory.streamlit.app
- **Code:** GitHub – `haresanjay/mwi-inventory`
- **Backend:** Supabase (Postgres database + Storage for photos)
- **Bhasha:** App ki bhasha Hinglish hai (Hindi Roman lipi mein, English field names ke saath)

---

## 1. Project ka dhaancha

```
mwi-inventory/
├── mwi_inventory.py      # Poora Streamlit app (ek hi file)
├── ocr_counter.py        # Counter photo ka OCR (abhi band: OCR_ENABLED = False)
├── requirements.txt      # Python packages
├── packages.txt          # Streamlit Cloud ke liye system packages (tesseract)
├── setup.sql             # Pehli baar Supabase setup
├── secrets_example.toml  # Secrets ka namuna (asli key yahan nahi)
├── run_app.bat           # Windows par local chalane ke liye
└── README.md
```

**requirements.txt:** streamlit, pandas, requests, pillow, openpyxl, xlrd

---

## 2. Tables (tabs)

| Tab | Supabase table | Kya rakhta hai | Grand Total mein |
|---|---|---|---|
| 🔢 Machine Counter | `Machine_Counter` | Model, Serial No, Machine No, Reading Start/End Date, Total Days, Reading Start/End No, Total Print Page, Counter Start/End Photo, Reason | Machine-wise print pages |
| ⚙️ Machine Parts | `Machine_Parts` | Machine No, Sr No, Parts Name, Model Number, Qty, Unit, Price, Total Value, Supplier, Invoice No, Invoice Date, Payment, Damage/New Parts Photo, Invoice Photo | Qty, Total Value |
| 📑 PDF Detail | `PDF_DETAIL` | Roll Type, Publish Date, District Name, Ac Name, Ac No, PDF File Name, Part No, Total Parts, Total Pages, Both Side, Single Side, Set, Total Double, Total Single, Laser, Billing Page, Carton, Photo | Roll + Date → District-wise cards, AC Detail, GRAND TOTAL |
| 📄 Paper | `Paper_Table` | Received Date, Paper Company, Invoice No, Item, Qty Rim, GSM Kg, Rate, Invoice Total (GST), No of Paper, Consumption Paper, Balance Paper Qty, Photo | No of Paper, Consumption (peela), Balance |
| 🖨️ Toner | `Toner` | Received Date, Toner Company, Party Name, Invoice No, Toner Qty, Rate, Amount, Invoice Total (GST), Toner Used, Toner Balance Qty, Photo | Qty, Used (peela), Balance, Amount, Amount with GST |
| 🕘 Attendance | `Attendance` | Employee ID, Card No, Name, Department, Date, In Time, Out Time, Work Hours, Status | Day-wise view + Month-wise Grand Total |
| 📦 Paper Toner Stock | `Paper_Toner_Stock` | Stock Date, Item Type, Item Name, GSM, Qty, Carton, Sheet, Kg, Photo | Paper / Toner / dono ka stock |
| 🖨 Scanning | `Scanning` | Client, Work Order No, Scan Date, A4 Pages, Rate, Amount, Invoice No, Invoice Date, Payment Status, Payment Date, UTR No, Remark | Pages, Days, Bills, Amount, Paid, Pending + Invoice-wise table |
| 📜 Log *(sirf Admin)* | `Activity_Log` | Kisne, kab, kya kiya (insert / update / delete / login) | — |

### Apne aap hone wale hisaab (CALC)

| Table | Field | Formula |
|---|---|---|
| Machine Counter | Total Print Page | Reading End No − Reading Start No |
| Machine Counter | Total Days | Reading End Date − Reading Start Date |
| Machine Parts | Total Value | Qty × Price |
| PDF Detail | Total Double | Both Side × Set |
| PDF Detail | Total Single | Single Side × Set |
| PDF Detail | Billing Page | Total Double + Total Single + Laser |
| PDF Detail | Carton | Billing Page ÷ 5000 |
| Toner | Amount | Toner Qty × Rate |
| Scanning | Amount | A4 Pages × Rate |
| Attendance | Work Hours, Status | In/Out Time se (Present / Out Missing) |
| Paper Toner Stock | Total Qty / Carton / Sheet / Kg | Item ke hisaab se |

---

## 3. Mukhya features

- **Login + Roles.** Login ke users Secrets ke `[users]` se aate hain, aur roles `[roles]` se:

  | Kaam | Admin | Operator |
  |---|---|---|
  | Entry dekhna / nayi entry | ✅ | ✅ |
  | Edit / Delete | ✅ | ❌ |
  | Excel Upload / Backup | ✅ | ❌ |
  | 📜 Log tab | ✅ | ❌ |

  Agar `[roles]` nahi likha to sab Admin maane jaate hain.
- **Created_By / Modify_By / Modify_date** har entry mein apne aap bharte hain.
- **Activity Log.** Insert, update, delete, login, logout aur galat login sab darj hote hain. Log ko koi edit ya delete nahi kar sakta.
- **Sabhi entries dikhti hain.** Koi 25 ki seema nahi. Har tab par entries ki ginti dikhti hai.
- **🔍 Filter / Find.** Date (From – End) aur "Any Item to Find" (Invoice No, Name, Number…) se dhoondh sakte hain. Grand Total bhi filter ke hisaab se banta hai.
- **📷 Photos.** Gallery ya camera se photo le sakte hain. Photo chhoti (max 1600px JPG) karke Supabase Storage ke `parts_images` bucket mein jaati hai. Kisi bhi entry par "📷 Photo Update" bhi kar sakte hain.
- **📥 Excel Upload** (sabhi tables). Ye section 4 mein vistaar se hai.
- **💾 Backup Excel.** Sidebar se ek click mein saari tables ek Excel mein download ho jaati hain.
- **Peela highlight.** Consumption Paper aur Toner Used list mein aur Grand Total mein peele dikhte hain.
- **Stock → Balance sync.** Paper Toner Stock ki ginti se Paper/Toner ki Balance Qty FIFO tareeke se (purana pehle khatam) milayi jaati hai, aur bacha hua Consumption mein jaata hai.
- **Attendance machine report.** Biometric machine ki `AttendanceRecord.xls` seedhe upload ho jaati hai. Usse din-wise entries apne aap banti hain.
- **Attendance Day-wise.** Select Day ya ◀ Prev Day / Next Day ▶ se kisi ek din ki attendance dekh sakte hain. Table mein Date, Employee ID, Name, In Time, Out Time dikhte hain. Absent karmchari ka time khaali rehta hai.
- **➖ Used Entry (Paper / Toner).** Roz ka kharch sirf Date + Qty se daalein (Paper: Carton / Ream / Sheet, Toner: Pkt). App use sabse purani bachi entry se ghata deta hai (FIFO). Consumption Paper / Toner Used badhta hai aur Balance apne aap ghat jaata hai. Har kharch `Paper_Toner_Used` mein save hota hai (📜 Used History, mahine-wise jod, CSV). Admin galat entry hata sakta hai, tab Balance wapas aa jaata hai.
- **Indian number format.** Jaise ₹ 2,62,640. Sr No aur Price bina `.00` ke dikhte hain.

---

## 4. 📥 Excel Upload – kaise kaam karta hai

1. Tab kholein, phir **Excel Upload** mein `.xlsx`, `.xls` ya `.csv` chunein.
2. App Excel ki heading ko table ke field se khud milata hai. Bade/chhote akshar, space aur `_` se farq nahi padta. Jo field Excel mein nahi hain, unme sabhi entries ke liye ek jaisi value daal sakte hain.
3. **📷 Photos:** Excel ke photo column mein photo ka file naam likhein. Phir photos (ya poori **ZIP**) chunein. Ek photo kai entries mein ho to bhi Storage mein ek hi baar jaati hai.
4. **Preview** mein dikhega:
   - 🔑 **Same entry ki pehchaan** – kin fields se purani entry pehchani gayi
   - ⚪ **Pehle wali** (same – kuch nahi badla) · 🟢 **New** (nayi dalegi) · 🟡 **Update** (purani mein badlav)
5. **"📥 Upload: X New + Y Update"** dabayein.
   - Default mein purani entry ke sirf **khaali** field bharte hain.
   - Bhari value bhi badalni ho to "overwrite" checkbox tick karein.
   - Hisaab wale field (Total Value, Amount, Billing Page…) dobara calculate hote hain.

### Same entry ki pehchaan (UPLOAD_KEYS)

Har table ke liye kai pehchaan sets hain. Pehla set na mile to agla set try hota hai. Agla (fallback) set sirf un purani entries se milta hai jinme pehle set ke baaki field khaali hain. Ek purani entry sirf ek Excel line se milti hai.

| Table | Pehchaan (kram se) |
|---|---|
| Paper | Invoice No + Paper Company + Qty Rim → Invoice No + Paper Company → Received Date + Company + Qty Rim |
| Toner | Invoice No + Toner Qty → Invoice No + Toner Company → Received Date + Toner Qty |
| Machine Parts | Supplier + Invoice No + Sr No + Parts Name → Sr No + Parts Name + Qty + Price → Sr No + Parts Name + Model Number |
| Machine Counter | Machine No + Reading Start Date → Serial No + Reading Start Date |
| PDF Detail | Roll Type + Publish Date + AC + Part No |
| Attendance | Employee ID + Date → Name + Date |
| Paper Toner Stock | Stock Date + Item Type + Item Name + GSM (+ …) → Stock Date + Item Name |
| Scanning | Client + Scan Date → Invoice No + Scan Date → Scan Date |

---

## 5. Setup (naya computer / naya Supabase)

### 5.1 Supabase
1. Supabase → **SQL Editor** mein `setup.sql` chalayein.
2. Phir zaroorat ke hisaab se ye SQL files chalayein (sab dobara chalane par safe hain, data delete nahi hota):

| File | Kaam |
|---|---|
| `created_by_modify_by.sql` | Created_By / Modify_By columns |
| `activity_log_setup.sql` | Activity_Log table (update/delete band) |
| `edit_permission.sql`, `delete_permission.sql`, `photo_update_permission.sql` | App se edit / delete / photo update ki permission |
| `paper_toner_photo_columns.sql` | Paper / Toner photo columns |
| `attendance_setup.sql` | Attendance table |
| `stock_setup.sql`, `stock_photo_column.sql`, `stock_rename_paper_toner_stock.sql` | Paper_Toner_Stock table |
| `stock_balance_match.sql` | Stock se Balance Qty milana |
| `scanning_setup.sql` | Scanning table + columns whitelist (8 tables) |
| `pdf_detail_set_billing.sql`, `pdf_detail_roll_date.sql`, `pdf_detail_ac_name.sql`, `pdf_detail_photo_column.sql` | PDF_DETAIL ke naye fields |
| `machine_parts_purchase_columns.sql` | Unit, Supplier, Invoice No/Date, Payment, Invoice Photo |
| `machine_parts_duplicate_fix.sql` | Dobara bani parts entries ko milakar ek karna |
| `machine_counter_rename_columns.sql` | Machine Counter ke naye column naam |
| `paper_toner_used_setup.sql` | ➖ Used Entry ki history table (Paper_Toner_Used) |

3. Storage mein **`parts_images`** naam ka public bucket hona chahiye.
4. Naya column jodne ke baad app mein **"Columns Refresh"** dabayein.

> App sirf `mwi_table_columns()` function mein likhi tables hi padhta hai (whitelist). Nayi table jodne par is function mein uska naam bhi jodein.

### 5.2 Streamlit Secrets
Streamlit Cloud → App → **Settings → Secrets**:

```toml
SUPABASE_URL = "https://<project>.supabase.co"
SUPABASE_KEY = "<anon public key>"

[users]
op1 = "sha256:<password ka sha256 hash>"
op2 = "sha256:<...>"

[roles]
op1 = "admin"
op2 = "operator"
```

⚠️ **Suraksha:**
- Sirf **anon** key daalein, `service_role` / secret key kabhi nahi.
- Password GitHub code mein na likhein, sirf Secrets mein (hash ke roop mein).
- Asli key wali secrets file GitHub par na daalein.

### 5.3 Local (Windows)
`run_app.bat` par double-click karein. Ye packages install karke app browser mein khol deta hai.

### 5.4 Update kaise karein
Naya `mwi_inventory.py` GitHub par purani file ki jagah upload karke commit karein. Streamlit app 1–2 minute mein apne aap update ho jaata hai.

---

## 6. Saath ke tools

- **PDF Page Detail Tool** (`PDF_Page_Detail_Tool.zip`: `pdf_page_detail.py` + `PDF_Page_Detail.bat`)
  - PDF folder chunte hi har PDF ke Ac No, Part No, Pages, Both Side aur Single Side Excel mein nikal deta hai.
  - Tool PDF folder ke bahar rakhein.
  - Python 3.8+ par chalta hai.
- **Upload Excel files.** Har bill, stock aur inventory ki photo se banayi gayi Excel (jaise `Machine_Parts_Upload_Inventory_14-11-2026.xlsx`) seedhe Excel Upload mein daali ja sakti hai.

---

## 7. Aage ke kaam (Roadmap)

1. **Print–Kagaz–Bill milaan:** Billing Page vs Total Print Page vs Consumption Paper. Isse wastage pakda ja sakega.
2. **Machine-wise laagat:** parts + toner + paper ka kharcha ÷ print pages = ₹ per page.
3. **Parts stock:** kitne aaye − kitne lage = bacha hua, aur kam hone par warning.
4. **Machine service history:** kab kaun-sa part badla, counter kitna tha.
5. **Kam stock ki chetavni** (Paper / Toner minimum level).
6. **Dashboard tab** (mahine-wise graphs).
7. **Attendance:** late list, salary sheet, Sunday/chhutti.
8. **Entry ke waqt jaanch:** End No < Start No, duplicate Invoice No, Qty × Price ≠ bill total.
9. **Mahine ki report** ek click mein.

---

## 8. Takneeki notes (developer ke liye)

- **Supabase se baat.** App Supabase se PostgREST (`requests`) se baat karta hai:
  - `select_all` 1000-row paging karta hai.
  - Ginti `Prefer: count=exact` se aati hai.
  - `insert_many` mein `return=minimal,missing=default` lagta hai.
- **Mukhya config** `mwi_inventory.py` ke upar hai:

  | Config | Kaam |
  |---|---|
  | `TABLES` | Tabs |
  | `PHOTOS` | Photo columns, folders |
  | `FIELD_ORDER` | Labels, aliases, kram |
  | `CALC` | Hisaab wale field |
  | `UPLOAD_KEYS` | Same entry ki pehchaan |
  | `UPLOAD_FILL` | Upload ke waqt khaali field bharna |
  | `HIGHLIGHT` | Peele cells |
  | `FILTER_LABELS` | Filter ke labels |

- **Column naam** bade/chhote akshar se farq nahi padta. App asli naam khud dhoondh leta hai.
- **Buttons** ke liye `on_click` flag pattern use hota hai (Streamlit rerun ke saath sahi chalta hai).
- **SQL helper files** ka tareeka:
  - `mwi_xxx(false)` = Preview, `mwi_xxx(true)` = Apply, phir `drop function`.
  - Har helper ko `anon/authenticated` se revoke kiya jaata hai.

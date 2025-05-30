import pdfplumber
import pandas as pd
import re
import os
from pdf2image import convert_from_path
import pytesseract
from PIL import Image

def to_number(val):
    if val is None: return None
    val = str(val).replace('.', '').replace(',', '.')
    try:
        return float(val)
    except:
        return None

def extract_date(text):
    match = re.search(r"Ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", text, re.IGNORECASE)
    if match:
        return f"{int(match.group(1)):02d}/{int(match.group(2)):02d}/{match.group(3)}"
    return ""

def clean_item_name(name):
    import re
    if not name:
        return ''
    name = name.strip()
    name = re.sub(r'^(\d+\s+)?Hàng\s*h[oó]a[,\s\n]*d[iị]ch\s*v[uụ][:,\s\n]*', '', name, flags=re.IGNORECASE)
    return name

def extract_text_with_ocr(pdf_path):
    images = convert_from_path(pdf_path, dpi=300)
    full_text = ""
    for img in images:
        text = pytesseract.image_to_string(img, lang='vie')
        full_text += text + "\n"
    return full_text

def extract_invoice_items(pdf_path, file_name_hint='UNKNOWN'):
    items = []
    known_units = ['Cái', 'Lít', 'm2', 'm', 'Bộ', 'Kg', 'Tấm', 'Ống', 'Phào', 'mét', 'Cặp', 'Chiếc']
    extracted_text = ""
    extracted_tables = []
    is_scan_pdf = False

    # 1. Thử extract bằng pdfplumber như cũ
    try:
        with pdfplumber.open(pdf_path) as pdf:
            extracted_text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
            for page in pdf.pages:
                tables = page.extract_tables()
                if tables:
                    extracted_tables.extend(tables)
    except Exception as e:
        print(f"Lỗi khi mở file PDF bằng pdfplumber: {pdf_path}, {e}")
        extracted_text = ""
        extracted_tables = []

    # 2. Nếu không extract được text hoặc bảng, chuyển qua OCR
    if not extracted_text.strip() or not extracted_tables:
        print(f"==> File {pdf_path} không extract được text hoặc bảng, chuyển sang xử lý OCR")
        is_scan_pdf = True
        try:
            extracted_text = extract_text_with_ocr(pdf_path)
        except Exception as ex:
            print(f"Lỗi OCR: {ex}")
            return []  # Không đọc được gì thì bỏ qua

    # 3. Extract thông tin chung hóa đơn
    serial = re.search(r"Ký hiệu.*?:\s*([A-Z0-9\-]+)", extracted_text)
    number = (
        re.search(r"Số[:：]?\s*(\d{5,})", extracted_text) or
        re.search(r"Số hóa đơn[:：]?\s*(\d+)", extracted_text) or
        re.search(r"Số HĐ[:：]?\s*(\d+)", extracted_text)
    )
    date_str = extract_date(extracted_text)
    seller_match = re.search(r"Tên người bán[:：]?\s*(.*)", extracted_text)
    seller = seller_match.group(1).strip() if seller_match else ''
    tax = re.search(r"Mã số thuế:?\s*([0-9\-\.]+)", extracted_text)

    # 4. Nếu có bảng (text-based), xử lý như cũ
    if extracted_tables:
        for row in sum(extracted_tables, []):
            if not row or len(row) < 6:
                continue
            row = [r.strip() if isinstance(r, str) else '' for r in row]
            unit_idx = -1
            for i in range(len(row)-1, 0, -1):
                if any(row[i].lower() == u.lower() for u in known_units if row[i]):
                    unit_idx = i
                    break
            if unit_idx == -1:
                unit_idx = 2
            numeric_fields = row[unit_idx+1:]
            quantity, unit_price = '', ''
            if len(numeric_fields) >= 2:
                quantity = numeric_fields[0]
                unit_price = numeric_fields[1]

            tax_rate = ''
            for val in reversed(numeric_fields):
                if not val:
                    continue
                stripped = val.strip().replace('%', '')
                if stripped.isdigit():
                    num = int(stripped)
                    if num in [5, 8, 10]:
                        tax_rate = str(num)
                        break
                elif val.strip().upper() == 'KCT':
                    tax_rate = 'KCT'
                    break

            name_parts = row[1:unit_idx]
            name = " ".join([p for p in name_parts if p])

            qty_val = to_number(quantity) if quantity else None
            price_val = to_number(unit_price) if unit_price else None

            value = None
            for v in reversed(row):
                v_num = to_number(v)
                if v_num is not None and v_num > 0:
                    value = v_num
                    break
            if (value is None or value == 0) and (qty_val is not None and price_val is not None):
                value = round(qty_val * price_val, 2)
            if value is None or value == 0:
                value = ''

            try:
                vat_rate_num = int(tax_rate) if tax_rate and tax_rate != 'KCT' else 0
            except:
                vat_rate_num = 0
            vat_tax = round(value * vat_rate_num / 100, 0) if value != '' and vat_rate_num > 0 else ''

            items.append({
                'STT': '',
                'Tên file PDF': file_name_hint,
                'Mẫu số': '01GTKT0/001',
                'Ký hiệu': serial.group(1).strip() if serial else '',
                'Số': number.group(1).strip() if number else file_name_hint,
                'Ngày, tháng, năm': date_str,
                'Tên người bán': seller,
                'Mã số thuế người bán': tax.group(1).strip() if tax else '',
                'Tên hàng hóa, dịch vụ': clean_item_name(name),
                'Đơn vị tính': row[unit_idx] if unit_idx < len(row) else '',
                'Số lượng': quantity if quantity else '',
                'Đơn giá': unit_price if unit_price else '',
                'Giá trị HHDV mua vào chưa có thuế GTGT': value,
                'Thuế suất (%)': tax_rate if tax_rate else '',
                'Tiền thuế GTGT': vat_tax,
                'Ghi chú': ''
            })
    else:
        # 5. Nếu không có bảng (scan), cố gắng extract từng dòng hàng hóa từ text OCR
        # Tìm các dòng có dạng: Tên hàng hóa, đơn vị, số lượng, đơn giá, thành tiền (có thể không đều hàng, nên cần regex khôn khéo)
        # Ví dụ mẫu: "Tên HH | Đơn vị | Số lượng | Đơn giá | Thành tiền"
        # Cách đơn giản: tìm các dòng có số lượng và đơn giá có vẻ hợp lý
        # Tách thành từng dòng
        lines = extracted_text.split('\n')
        for line in lines:
            # Tìm dòng có số lượng và đơn giá (dạng số, cách nhau bởi khoảng trắng/tab)
            match = re.match(r'^(.{5,60}?)[\s|]+([A-Za-zÀ-ỹ]+)[\s|]+([\d.,]+)[\s|]+([\d.,]+)[\s|]+([\d.,]+)', line)
            if match:
                name = match.group(1).strip()
                unit = match.group(2).strip()
                quantity = match.group(3).strip()
                unit_price = match.group(4).strip()
                value = match.group(5).strip()
                qty_val = to_number(quantity)
                price_val = to_number(unit_price)
                value_val = to_number(value)
                items.append({
                    'STT': '',
                    'Tên file PDF': file_name_hint,
                    'Mẫu số': '01GTKT0/001',
                    'Ký hiệu': serial.group(1).strip() if serial else '',
                    'Số': number.group(1).strip() if number else file_name_hint,
                    'Ngày, tháng, năm': date_str,
                    'Tên người bán': seller,
                    'Mã số thuế người bán': tax.group(1).strip() if tax else '',
                    'Tên hàng hóa, dịch vụ': clean_item_name(name),
                    'Đơn vị tính': unit,
                    'Số lượng': quantity,
                    'Đơn giá': unit_price,
                    'Giá trị HHDV mua vào chưa có thuế GTGT': value_val,
                    'Thuế suất (%)': '',
                    'Tiền thuế GTGT': '',
                    'Ghi chú': ''
                })

    return items

def main(pdf_dir, output_file):
    all_data = []
    for file in os.listdir(pdf_dir):
        if file.lower().endswith(".pdf"):
            file_path = os.path.join(pdf_dir, file)
            items = extract_invoice_items(file_path, file_name_hint=file)
            all_data.extend(items)

    df = pd.DataFrame(all_data)
    # Loại các dòng tiêu đề/trống
    df = df[~df['Tên hàng hóa, dịch vụ'].str.lower().str.contains('tên hàng hóa|đơn vị tính', na=False)]
    # Loại dòng mà mọi thông tin chính đều trống
    df = df[~(
        (df['Tên hàng hóa, dịch vụ'].isna() | (df['Tên hàng hóa, dịch vụ'] == '')) &
        (df['Số lượng'].isna() | (df['Số lượng'] == '')) &
        (df['Đơn giá'].isna() | (df['Đơn giá'] == ''))
    )]
    df['STT'] = range(1, len(df) + 1)

    try:
        df.to_excel(output_file, index=False)
    except PermissionError:
        print(f"⚠️ Không thể ghi đè file {output_file}. Đang ghi vào file dự phòng...")
        fallback_file = output_file.replace('.xlsx', '_v2.xlsx')
        df.to_excel(fallback_file, index=False)
        print(f"✅ Đã ghi vào: {fallback_file}")

if __name__ == "__main__":
    main('./pdfs', 'Ket_qua_hoa_don_final.xlsx')
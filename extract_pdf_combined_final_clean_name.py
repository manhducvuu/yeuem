
import pdfplumber
import pandas as pd
import re
import os

def to_number(val):
    if not val: return 0
    val = str(val).replace('.', '').replace(',', '.')
    try:
        return float(val)
    except:
        return 0

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
    if not name:
        return ''
    name = name.strip()
    return name

def extract_invoice_items(pdf_path, file_name_hint='UNKNOWN'):
    items = []
    known_units = ['Cái', 'Lít', 'm2', 'm', 'Bộ', 'Kg', 'Tấm', 'Ống', 'Phào', 'mét', 'Cặp', 'Chiếc']
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
            serial = re.search(r"Ký hiệu.*?:\s*([A-Z0-9]+)", text)
            number = re.search(r"Số:\s*(\d+)", text) or re.search(r"Số hóa đơn:\s*(\d+)", text)
            date_str = extract_date(text)
            seller_match = re.search(r"Tên người bán[:：]?\s*(.*)", text)
            seller = seller_match.group(1).strip() if seller_match else ''
            tax = re.search(r"Mã số thuế:?\s*([0-9\-\.]+)", text)

            for page in pdf.pages:
                tables = page.extract_tables()
                for row in sum(tables, []):
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
                    quantity, unit_price, tax_rate = '', '', ''
                    if len(numeric_fields) >= 2:
                        quantity = numeric_fields[0]
                        unit_price = numeric_fields[1]
                    for val in numeric_fields:
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
                    qty_val = to_number(quantity)
                    price_val = to_number(unit_price)
                    value = next((to_number(v) for v in reversed(row) if to_number(v) > 0), round(qty_val * price_val, 2))
                    try:
                        vat_rate_num = int(tax_rate) if tax_rate and tax_rate != 'KCT' else 0
                    except:
                        vat_rate_num = 0
                    vat_tax = round(value * vat_rate_num / 100, 0)
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
                        'Số lượng': qty_val,
                        'Đơn giá': price_val,
                        'Giá trị HHDV mua vào chưa có thuế GTGT': value,
                        'Thuế suất (%)': tax_rate,
                        'Tiền thuế GTGT': vat_tax,
                        'Ghi chú': ''
                    })
    except Exception as e:
        print(f"Lỗi khi xử lý file {pdf_path}: {e}")
    return items

def main(pdf_dir, output_file):
    all_data = []
    for file in os.listdir(pdf_dir):
        if file.lower().endswith(".pdf"):
            file_path = os.path.join(pdf_dir, file)
            items = extract_invoice_items(file_path, file_name_hint=file)
            all_data.extend(items)

    df = pd.DataFrame(all_data)
    df = df[df['Số lượng'] > 0]
    df = df[df['Tên hàng hóa, dịch vụ'].notna()]
    df = df[~df['Tên hàng hóa, dịch vụ'].str.lower().str.contains('tên hàng hóa|đơn vị tính', na=False)]
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

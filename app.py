import os
import re
import imaplib
import email
from email.header import decode_header
from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

def extract_otp_and_link(subject, body):
    otp_code = "Không thấy OTP"
    verify_link = None
    full_text = f"{subject} {body}"

    # 1. Tìm chuỗi 6 chữ số OTP
    digits = re.findall(r'\b\d{6}\b', full_text)
    if digits:
        otp_code = digits[0]

    # 2. Bắt link TẠI ĐÂY
    try:
        soup = BeautifulSoup(body, 'html.parser')
        for a_tag in soup.find_all('a', href=True):
            text_inside = a_tag.get_text().strip().upper()
            if "TẠI ĐÂY" in text_inside or "TAI DAY" in text_inside:
                verify_link = a_tag['href']
                break
    except Exception:
        pass

    # 3. Kích hoạt link bằng User-Agent Browser
    link_status = "Không có link TẠI ĐÂY"
    if verify_link:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
            resp = requests.get(verify_link, headers=headers, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                link_status = "Đã bấm link (Thành công)"
            else:
                link_status = f"Đã bấm link (HTTP {resp.status_code})"
        except Exception as e:
            link_status = f"Lỗi kích hoạt: {str(e)}"

    return otp_code, verify_link, link_status

def decode_mime_header(header_value):
    if not header_value:
        return ""
    decoded_list = decode_header(header_value)
    header_text = ""
    for decoded_string, charset in decoded_list:
        if isinstance(decoded_string, bytes):
            charset = charset or 'utf-8'
            try:
                header_text += decoded_string.decode(charset, errors='ignore')
            except Exception:
                header_text += decoded_string.decode('latin-1', errors='ignore')
        else:
            header_text += str(decoded_string)
    return header_text

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/verify', methods=['POST'])
def verify_accounts():
    data = request.get_json() or {}
    account_lines = data.get('accounts', [])
    results = []

    for line in account_lines:
        line = line.strip()
        if not line:
            continue
            
        parts = line.split('|')
        email_user = parts[0].strip()
        email_pass = parts[1].strip() if len(parts) > 1 else ""

        if not email_pass:
            results.append({
                "email": email_user,
                "status": "Lỗi",
                "otp": "Thiếu Pass",
                "link": None,
                "link_status": "Lỗi"
            })
            continue

        try:
            domain = email_user.split('@')[-1].lower() if '@' in email_user else ''
            if 'gmail' in domain:
                imap_server = 'imap.gmail.com'
            elif 'outlook' in domain or 'hotmail' in domain or 'live' in domain:
                imap_server = 'outlook.office365.com'
            else:
                imap_server = domain if domain else 'mail.fshare.dpdns.org'

            mail = imaplib.IMAP4_SSL(imap_server, port=993)
            mail.login(email_user, email_pass)
            mail.select("INBOX")

            status, messages = mail.search(None, 'ALL')
            mail_ids = messages[0].split()

            if not mail_ids:
                results.append({
                    "email": email_user,
                    "status": "Thành công",
                    "otp": "Hòm thư trống",
                    "link": None,
                    "link_status": "Không có mail"
                })
                mail.logout()
                continue

            latest_email_id = mail_ids[-1]
            status, msg_data = mail.fetch(latest_email_id, '(RFC822)')

            subject = ""
            body = ""

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject = decode_mime_header(msg.get("Subject", ""))

                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            content_disposition = str(part.get("Content-Disposition"))
                            if content_type in ["text/plain", "text/html"] and "attachment" not in content_disposition:
                                body += part.get_payload(decode=True).decode(errors='ignore')
                    else:
                        body = msg.get_payload(decode=True).decode(errors='ignore')

            mail.logout()

            otp_code, verify_link, link_status = extract_otp_and_link(subject, body)

            results.append({
                "email": email_user,
                "status": "Thành công",
                "otp": otp_code,
                "link": verify_link,
                "link_status": link_status
            })

        except Exception as e:
            results.append({
                "email": email_user,
                "status": "Lỗi",
                "otp": "Lỗi IMAP",
                "link": None,
                "link_status": f"Lỗi: {str(e)}"
            })

    return jsonify({"results": results})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

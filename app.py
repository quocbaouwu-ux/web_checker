import imaplib
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

CHEAPLUXURY_API_URL = "https://cheapluxurymail.xyz/login"
MAX_WORKERS = 8

# ----- iCloud (hộp thư do bạn quản lý, đọc qua IMAP) -----
ICLOUD_IMAP_HOST = "imap.mail.me.com"
ICLOUD_MAX_MINUTES = 10     # chỉ lấy mail iCloud trong số phút này
ICLOUD_MAX_MAILS = 50       # tối đa số mail quét mỗi hộp thư
EMAIL_RE = re.compile(r'^[\w.+-]+@[\w-]+(\.[\w-]+)+$')
SAFE_URL_RE = re.compile(r'^https?://[^\s"\'<>]+$')

def is_within_15_minutes(date_str):
    if not date_str:
        return False
    try:
        try:
            email_time = parsedate_to_datetime(date_str)
        except Exception:
            email_time = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        
        if email_time.tzinfo is None:
            email_time = email_time.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        diff_in_seconds = (now - email_time).total_seconds()
        return 0 <= diff_in_seconds <= 900
    except Exception:
        return True

def extract_otp_and_link(subject, body_text, body_html):
    otp_code = "Không thấy OTP"
    verify_link = None
    
    full_text = f"{subject or ''} {body_text or ''} {body_html or ''}"
    
    digits = re.findall(r'\b\d{6}\b', full_text)
    if digits:
        otp_code = digits[0]

    target_html = body_html if body_html else body_text
    keywords = ["TẠI ĐÂY", "TAI DAY", "XÁC MINH", "XÁC NHẬN", "VERIFY", "CONFIRM", "CLICK", "ACTIVATE", "KÍCH HOẠT"]
    url_keywords = ["verify", "confirm", "activate", "token", "xac-minh", "kich-hoat"]

    if target_html:
        try:
            soup = BeautifulSoup(target_html, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                text_inside = a_tag.get_text().strip().upper()
                href = a_tag['href']
                if any(kw in text_inside for kw in keywords):
                    verify_link = href
                    break
            
            if not verify_link:
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href'].lower()
                    if any(ukw in href for ukw in url_keywords):
                        verify_link = a_tag['href']
                        break
        except Exception:
            pass

    if not verify_link:
        urls = re.findall(r'(https?://[^\s<>"]+)', full_text)
        for url in urls:
            url_lower = url.lower()
            if "cheapluxurymail.xyz" in url_lower and not any(ukw in url_lower for ukw in url_keywords):
                continue
            if any(social in url_lower for social in ["facebook.com", "t.me", "twitter.com", "instagram.com"]):
                continue
            if any(ukw in url_lower for ukw in url_keywords):
                verify_link = url
                break

    link_status = "Có link" if verify_link else "Chưa thấy yêu cầu đăng nhập"
    return otp_code, verify_link, link_status

def check_single_account(line):
    line = line.strip()
    if not line or '|' not in line:
        return {
            "email": line,
            "status": "Thất bại",
            "otp": "N/A",
            "link": None,
            "link_status": "Sai định dạng email|password"
        }

    parts = line.split('|')
    email = parts[0].strip()
    password = parts[1].strip()

    payload = {'email': email, 'password': password}
    headers = {'Content-Type': 'application/json'}
    
    max_retries = 2
    response = None

    for attempt in range(max_retries):
        try:
            response = requests.post(CHEAPLUXURY_API_URL, json=payload, headers=headers, timeout=25)
            break
        except requests.exceptions.RequestException:
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                return {
                    "email": email,
                    "status": "Thất bại",
                    "otp": "N/A",
                    "link": None,
                    "link_status": "Lỗi kết nối (Server mail quá tải / Timeout)"
                }

    try:
        if response.status_code != 200:
            return {
                "email": email,
                "status": "Thất bại",
                "otp": "N/A",
                "link": None,
                "link_status": f"Lỗi HTTP {response.status_code}"
            }

        res_data = response.json()
        
        if res_data.get('response_code') == 200 or res_data.get('message') == "Login successful":
            emails_list = res_data.get('data', {}).get('emails', [])
            
            if not emails_list:
                return {
                    "email": email,
                    "status": "Thành công",
                    "otp": "Hòm thư trống",
                    "link": None,
                    "link_status": "Chưa thấy yêu cầu đăng nhập"
                }
            
            latest_email = emails_list[0]
            date_str = latest_email.get('date') or latest_email.get('created_at') or latest_email.get('time')

            if not is_within_15_minutes(date_str):
                return {
                    "email": email,
                    "status": "Thành công",
                    "otp": "Không thấy OTP mới",
                    "link": None,
                    "link_status": "Chưa thấy yêu cầu đăng nhập"
                }

            subject = latest_email.get('subject', '')
            body_text = latest_email.get('body_text', '')
            body_html = latest_email.get('body_html', '')

            otp, link, link_status = extract_otp_and_link(subject, body_text, body_html)

            return {
                "email": email,
                "status": "Thành công",
                "otp": otp,
                "link": link,
                "link_status": link_status
            }
        else:
            return {
                "email": email,
                "status": "Thất bại",
                "otp": "N/A",
                "link": None,
                "link_status": res_data.get('message', 'Đăng nhập không thành công')
            }

    except Exception as e:
        return {
            "email": email,
            "status": "Thất bại",
            "otp": "N/A",
            "link": None,
            "link_status": f"Lỗi xử lý dữ liệu: {str(e)}"
        }

def icloud_row(email_addr, status, otp, link, link_status):
    return {"email": email_addr, "status": status, "otp": otp, "link": link, "link_status": link_status}


def icloud_parts(msg):
    """Tách nội dung mail thành (chữ thường, html đã bỏ style/script)."""
    text, html = "", ""
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        if ctype in ("text/html", "text/plain"):
            payload = part.get_payload(decode=True) or b""
            decoded = payload.decode(part.get_content_charset() or "utf-8", "replace")
            if ctype == "text/html":
                html += decoded
            else:
                text += decoded
    if html:
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for tag in soup(['style', 'script']):
                tag.decompose()
            html = str(soup)
        except Exception:
            pass
    return text, html


def icloud_accounts():
    """Hộp thư iCloud chính do BẠN quản lý (người dùng web không nhập mật khẩu).
    Khai báo bằng biến môi trường ICLOUD_ACCOUNTS (Render), dạng
    email1|mật_khẩu_ứng_dụng;email2|mật_khẩu_ứng_dụng
    và/hoặc file icloud_accounts.txt (VPS), mỗi dòng email|mật_khẩu_ứng_dụng. KHÔNG đưa lên GitHub."""
    raw = os.environ.get("ICLOUD_ACCOUNTS", "")
    if os.path.exists("icloud_accounts.txt"):
        with open("icloud_accounts.txt", encoding="utf-8") as f:
            raw += "\n" + f.read()
    out = []
    for item in re.split(r"[;\n]", raw):
        item = item.strip()
        if "|" in item and not item.startswith("#"):
            user, pw = item.split("|", 1)
            if EMAIL_RE.match(user.strip()):
                out.append((user.strip(), pw.strip().replace(" ", "")))
    return out


def scan_icloud_mailbox(main, password, wanted):
    """Quét một hộp thư chính, trả về ({alias: dòng kết quả}, có_lỗi)."""
    found = {}
    try:
        m = imaplib.IMAP4_SSL(ICLOUD_IMAP_HOST, 993, timeout=20)
        try:
            m.login(main, password)
            m.select("INBOX", readonly=True)          # chỉ đọc, không đổi trạng thái đã đọc
            since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%d-%b-%Y")
            _, data = m.uid("search", None, "SINCE", since)
            now = datetime.now(timezone.utc)
            for uid in data[0].split()[::-1][:ICLOUD_MAX_MAILS]:     # mới nhất trước
                if len(found) == len(wanted):
                    break
                _, md = m.uid("fetch", uid, "(BODY.PEEK[])")
                msg = message_from_bytes(md[0][1])
                try:
                    sent = parsedate_to_datetime(msg["Date"])
                    if sent.tzinfo is None:
                        sent = sent.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if (now - sent).total_seconds() / 60 > ICLOUD_MAX_MINUTES:
                    break

                headers = []
                for h in ("To", "Cc", "Delivered-To", "X-Original-To"):
                    headers += msg.get_all(h, [])
                hits = {a.lower() for _, a in getaddresses(headers) if a} & wanted - set(found)
                if not hits:
                    continue

                try:
                    subject = str(make_header(decode_header(str(msg.get("Subject", "")))))
                except Exception:
                    subject = ""
                text, html = icloud_parts(msg)
                visible = BeautifulSoup(html, 'html.parser').get_text(" ") if html else text
                otp_m = re.search(r'(?<!\d)\d{6}(?!\d)', f"{subject} {visible}")
                _, link, _ = extract_otp_and_link(subject, text, html)
                if link and not SAFE_URL_RE.match(link):
                    link = None
                if not link and not otp_m:
                    continue                             # không phải mail xác minh
                for alias in hits:
                    found[alias] = icloud_row(
                        alias, "Thành công",
                        otp_m.group(0) if otp_m else "Không thấy OTP",
                        link, "Có link" if link else "Chưa thấy yêu cầu đăng nhập")
        finally:
            try:
                m.logout()
            except Exception:
                pass
        return found, False
    except Exception as e:
        print(f"[iCloud] lỗi hộp thư {main}: {type(e).__name__}")   # chỉ ghi log phía server
        return found, True


def check_icloud_aliases(lines):
    """Người dùng chỉ nhập email (alias). Server tự tìm trong các hộp thư iCloud của bạn."""
    rows, order, seen = [], [], set()
    for line in lines[:100]:
        line = line.strip()
        if not line:
            continue
        alias = line.split('|')[0].strip().lower()       # nếu lỡ dán email|... thì bỏ phần sau, không dùng
        if not EMAIL_RE.match(alias):
            rows.append(icloud_row("Dòng không hợp lệ", "Thất bại", "N/A", None, "Chỉ nhập email, mỗi dòng một email"))
        elif alias not in seen:
            seen.add(alias)
            order.append(alias)

    accounts = icloud_accounts()
    wanted = set(order)
    found, errors = {}, 0
    if accounts and wanted:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(accounts))) as executor:
            for res, had_error in executor.map(lambda a: scan_icloud_mailbox(a[0], a[1], wanted), accounts):
                errors += 1 if had_error else 0
                for k, v in res.items():
                    found.setdefault(k, v)

    for alias in order:
        if alias in found:
            rows.append(found[alias])
        elif not accounts:
            rows.append(icloud_row(alias, "Thất bại", "N/A", None, "Hệ thống chưa cấu hình hộp thư iCloud"))
        elif errors == len(accounts):
            rows.append(icloud_row(alias, "Thất bại", "N/A", None, "Không đọc được hộp thư, thử lại sau"))
        elif errors:
            rows.append(icloud_row(alias, "Thất bại", "N/A", None, "Chưa thấy mail, một hộp thư đang lỗi nên có thể thiếu kết quả, thử lại"))
        else:
            rows.append(icloud_row(alias, "Thành công", "Không thấy OTP mới", None, "Chưa thấy yêu cầu đăng nhập"))
    return rows


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/verify', methods=['POST'])
def api_verify():
    data = request.get_json() or {}
    accounts = data.get('accounts', [])
    source = data.get('source', 'system')

    if source == 'icloud':
        results = check_icloud_aliases(accounts)
    else:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = list(executor.map(check_single_account, accounts))

    return jsonify({"results": [r for r in results if r is not None]})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

CHEAPLUXURY_API_URL = "https://cheapluxurymail.xyz/login"
MAX_WORKERS = 8

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/verify', methods=['POST'])
def api_verify():
    data = request.get_json() or {}
    accounts = data.get('accounts', [])

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(check_single_account, accounts))

    return jsonify({"results": [r for r in results if r is not None]})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

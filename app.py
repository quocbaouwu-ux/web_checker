import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

CHEAPLUXURY_API_URL = "https://cheapluxurymail.xyz/login"

def is_within_15_minutes(date_str):
    """Kiểm tra xem email có được gửi trong vòng 15 phút gần đây không (dùng thư viện có sẵn)"""
    if not date_str:
        return False
    try:
        # Thử parse thời gian dạng chuẩn RFC 2822 hoặc ISO
        try:
            email_time = parsedate_to_datetime(date_str)
        except Exception:
            # Fallback nếu định dạng ISO string (2026-09-30T17:57:00Z)
            email_time = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        
        if email_time.tzinfo is None:
            email_time = email_time.replace(tzinfo=timezone.utc)
        
        # Thời gian hiện tại UTC
        now = datetime.now(timezone.utc)
        
        # Tính khoảng cách thời gian (tính bằng giây)
        diff_in_seconds = (now - email_time).total_seconds()
        
        # 15 phút = 900 giây
        return 0 <= diff_in_seconds <= 900
    except Exception:
        # Nếu không parse được định dạng ngày, mặc định chấp nhận
        return True

def extract_otp_and_link(subject, body_text, body_html, auto_click=False):
    otp_code = "Không thấy OTP"
    verify_link = None
    
    full_text = f"{subject or ''} {body_text or ''} {body_html or ''}"
    
    # 1. Tìm mã OTP 6 chữ số
    digits = re.findall(r'\b\d{6}\b', full_text)
    if digits:
        otp_code = digits[0]

    # 2. Bóc tách Link xác minh từ HTML / Text
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

    # 3. Xử lý kích hoạt
    link_status = "Chưa thấy yêu cầu đăng nhập"
    if verify_link:
        if auto_click:
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
            })
            try:
                resp = session.get(verify_link, timeout=10, allow_redirects=True)
                if resp.status_code in [200, 301, 302]:
                    link_status = "Đã xác minh"
                else:
                    link_status = f"Lỗi HTTP {resp.status_code}"
            except Exception:
                link_status = "Lỗi kích hoạt"
        else:
            link_status = "Có link"

    return otp_code, verify_link, link_status

def check_single_account(email, password, auto_click=False):
    try:
        payload = {
            'email': email,
            'password': password
        }
        headers = {
            'Content-Type': 'application/json'
        }
        
        response = requests.post(CHEAPLUXURY_API_URL, json=payload, headers=headers, timeout=12)
        
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
            
            # Lấy thư mới nhất
            latest_email = emails_list[0]
            date_str = latest_email.get('date') or latest_email.get('created_at') or latest_email.get('time')

            # Kiểm tra xem mail có trong vòng 15 phút gần đây không
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

            otp, link, link_status = extract_otp_and_link(subject, body_text, body_html, auto_click=auto_click)

            return {
                "email": email,
                "status": "Thành công",
                "otp": otp,
                "link": link,
                "link_status": link_status
            }
        else:
            msg = res_data.get('message', 'Đăng nhập không thành công')
            return {
                "email": email,
                "status": "Thất bại",
                "otp": "N/A",
                "link": None,
                "link_status": msg
            }

    except Exception as e:
        return {
            "email": email,
            "status": "Thất bại",
            "otp": "N/A",
            "link": None,
            "link_status": f"Lỗi kết nối: {str(e)}"
        }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/verify', methods=['POST'])
def api_verify():
    data = request.get_json() or {}
    accounts = data.get('accounts', [])
    auto_click = data.get('auto_click', False)

    results = []
    for line in accounts:
        if '|' in line:
            parts = line.split('|')
            email = parts[0].strip()
            password = parts[1].strip()
            res = check_single_account(email, password, auto_click=auto_click)
            results.append(res)
        else:
            results.append({
                "email": line,
                "status": "Thất bại",
                "otp": "N/A",
                "link": None,
                "link_status": "Sai định dạng email|password"
            })

    return jsonify({"results": results})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

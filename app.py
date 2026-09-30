import os
import re
from bs4 import BeautifulSoup
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

CHEAPLUXURY_API_URL = "https://cheapluxurymail.xyz/login"

def extract_otp_and_link(subject, body_text, body_html):
    otp_code = "Không thấy OTP"
    verify_link = None
    
    full_text = f"{subject or ''} {body_text or ''} {body_html or ''}"
    
    # 1. Tìm mã OTP 6 chữ số
    digits = re.findall(r'\b\d{6}\b', full_text)
    if digits:
        otp_code = digits[0]

    # 2. Bóc tách Link xác minh từ HTML / Text
    target_html = body_html if body_html else body_text
    if target_html:
        try:
            soup = BeautifulSoup(target_html, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                text_inside = a_tag.get_text().strip().upper()
                href = a_tag['href']
                keywords = ["TẠI ĐÂY", "TAI DAY", "XÁC MINH", "XÁC NHẬN", "VERIFY", "CONFIRM", "CLICK", "ACTIVATE"]
                if any(kw in text_inside for kw in keywords):
                    verify_link = href
                    break
            if not verify_link:
                all_links = [a['href'] for a in soup.find_all('a', href=True) if 'http' in a['href']]
                if all_links:
                    verify_link = all_links[0]
        except Exception:
            pass

    if not verify_link:
        urls = re.findall(r'(https?://[^\s<>"]+)', full_text)
        if urls:
            verify_link = urls[0]

    return otp_code, verify_link

def check_single_account(email, password):
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
                    "link_status": "Chưa nhận được thư"
                }
            
            latest_email = emails_list[0]
            subject = latest_email.get('subject', '')
            body_text = latest_email.get('body_text', '')
            body_html = latest_email.get('body_html', '')

            otp, link = extract_otp_and_link(subject, body_text, body_html)

            return {
                "email": email,
                "status": "Thành công",
                "otp": otp,
                "link": link,
                "link_status": "Có link" if link else "Không tìm thấy link"
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

    results = []
    for line in accounts:
        if '|' in line:
            parts = line.split('|')
            email = parts[0].strip()
            password = parts[1].strip()
            res = check_single_account(email, password)
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

import os
import re
from flask import Flask, render_template, request, jsonify, make_response
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

def extract_otp_and_link(subject, body_text, body_html):
    otp_code = "Không thấy OTP"
    verify_link = None
    
    # Gộp nội dung để quét mã OTP 6 số
    full_text = f"{subject} {body_text}"
    digits = re.findall(r'\b\d{6}\b', full_text)
    if digits:
        otp_code = digits[0]

    # 1. Tìm link xác minh trong body_html
    target_html = body_html if body_html else body_text
    try:
        soup = BeautifulSoup(target_html, 'html.parser')
        for a_tag in soup.find_all('a', href=True):
            text_inside = a_tag.get_text().strip().upper()
            if "TẠI ĐÂY" in text_inside or "TAI DAY" in text_inside or "XÁC MINH" in text_inside:
                verify_link = a_tag['href']
                break
    except Exception:
        pass

    # 2. Tự động kích hoạt link xác minh
    link_status = "Không có link"
    if verify_link:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            resp = requests.get(verify_link, headers=headers, timeout=8, allow_redirects=True)
            if resp.status_code == 200:
                link_status = "Thành công"
            else:
                link_status = f"HTTP {resp.status_code}"
        except Exception:
            link_status = "Lỗi kích hoạt"

    return otp_code, verify_link, link_status

@app.route('/')
def index():
    response = make_response(render_template('index.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

@app.route('/api/verify', methods=['POST'])
def verify_accounts():
    try:
        data = request.get_json(silent=True) or {}
        account_lines = data.get('accounts', [])
        results = []

        for line in account_lines:
            line = str(line).strip()
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

            # Gọi API CheapLuxuryMail
            try:
                payload = {
                    "email": email_user,
                    "password": email_pass
                }
                api_resp = requests.post(
                    "https://cheapluxurymail.xyz/login",
                    json=payload,
                    timeout=10
                )

                if api_resp.status_code == 200:
                    json_data = api_resp.json()
                    emails_list = json_data.get('data', {}).get('emails', [])

                    if not emails_list:
                        results.append({
                            "email": email_user,
                            "status": "Thành công",
                            "otp": "Hòm thư trống",
                            "link": None,
                            "link_status": "Không có mail"
                        })
                    else:
                        # Lấy email mới nhất
                        latest_mail = emails_list[0]
                        subject = latest_mail.get("subject", "")
                        body_text = latest_mail.get("body_text", "")
                        body_html = latest_mail.get("body_html", "")

                        otp_code, verify_link, link_status = extract_otp_and_link(subject, body_text, body_html)

                        results.append({
                            "email": email_user,
                            "status": "Thành công",
                            "otp": otp_code,
                            "link": verify_link,
                            "link_status": link_status
                        })
                else:
                    results.append({
                        "email": email_user,
                        "status": "Lỗi",
                        "otp": f"HTTP {api_resp.status_code}",
                        "link": None,
                        "link_status": "Sai pass hoặc Server mail lỗi"
                    })

            except Exception as e:
                results.append({
                    "email": email_user,
                    "status": "Lỗi",
                    "otp": "Lỗi API",
                    "link": None,
                    "link_status": f"Lỗi: {str(e)}"
                })

        return jsonify({"results": results})

    except Exception as global_e:
        return jsonify({"results": [], "error": str(global_e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

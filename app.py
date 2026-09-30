import os
import re
from flask import Flask, render_template, request, jsonify, make_response
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

def extract_otp_and_link(subject, body_text, body_html):
    otp_code = "Không thấy OTP"
    verify_link = None
    
    # 1. Tìm mã OTP 6 số
    full_text = f"{subject} {body_text} {body_html}"
    digits = re.findall(r'\b\d{6}\b', full_text)
    if digits:
        otp_code = digits[0]

    # 2. Tìm link TẠI ĐÂY / XÁC MINH
    target_html = body_html if body_html else body_text
    
    try:
        soup = BeautifulSoup(target_html, 'html.parser')
        # Tìm qua thẻ <a>
        for a_tag in soup.find_all('a', href=True):
            text_inside = a_tag.get_text().strip().upper()
            href = a_tag['href']
            
            keywords = ["TẠI ĐÂY", "TAI DAY", "XÁC MINH", "XÁC NHẬN", "VERIFY", "CONFIRM"]
            if any(kw in text_inside for kw in keywords):
                verify_link = href
                break
                
        # Nếu không thấy từ khóa, lấy link http/https đầu tiên trong thẻ <a>
        if not verify_link:
            all_links = [a['href'] for a in soup.find_all('a', href=True) if 'http' in a['href']]
            if all_links:
                verify_link = all_links[0]
    except Exception:
        pass

    # Nếu mail dạng text thuần không có thẻ a, quét link bằng Regex
    if not verify_link:
        urls = re.findall(r'(https?://[^\s<>"]+)', full_text)
        if urls:
            verify_link = urls[0]

    # 3. TỰ ĐỘNG BẤM LINK (Auto Click)
    link_status = "Không tìm thấy link"
    if verify_link:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
            resp = requests.get(verify_link, headers=headers, timeout=10, allow_redirects=True)
            
            if resp.status_code in [200, 201, 202, 204]:
                link_status = "Đã bấm (Thành công)"
            else:
                link_status = f"Lỗi HTTP {resp.status_code}"
        except Exception:
            link_status = "Lỗi khi kích hoạt link"

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
                            "link_status": "Chưa có mail"
                        })
                    else:
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
                        "link_status": "Sai pass hoặc Server lỗi"
                    })

            except Exception as e:
                results.append({
                    "email": email_user,
                    "status": "Lỗi",
                    "otp": "Lỗi kết nối",
                    "link": None,
                    "link_status": f"Lỗi: {str(e)}"
                })

        return jsonify({"results": results})

    except Exception as global_e:
        return jsonify({"results": [], "error": str(global_e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

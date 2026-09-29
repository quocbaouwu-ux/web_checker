from flask import Flask, render_template, request, jsonify
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import re

app = Flask(__name__)

CHEAPLUXURY_API_URL = "https://cheapluxurymail.xyz/email/get"

def extract_verify_link(content):
    """
    Hàm bóc tách link xác minh từ nội dung mail (HTML / Text).
    Ưu tiên thẻ <a> chứa chữ "TẠI ĐÂY" hoặc các từ khóa xác minh.
    """
    if not content:
        return ""

    # 1. Ưu tiên tìm thẻ href có chứa từ khóa hoặc thẻ bao quanh chữ "TẠI ĐÂY"
    tai_day_match = re.search(r'href=["\'](https?://[^"\']+)["\'][^>]*>.*?TẠI\s*ĐÂY', content, re.IGNORECASE | re.DOTALL)
    if tai_day_match:
        return tai_day_match.group(1)

    # 2. Tìm tất cả các liên kết URL trong nội dung
    all_links = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', content)
    
    # Lọc lấy link chứa các từ khóa xác minh phổ biến
    for link in all_links:
        link_lower = link.lower()
        if any(k in link_lower for k in ['verify', 'confirm', 'activate', 'token', 'auth', 'code', 'xac-minh']):
            return link

    # 3. Nếu không khớp từ khóa, lấy link đầu tiên tìm được
    return all_links[0] if all_links else ""


def check_single_account(account_str):
    """
    Hàm xử lý cho từng tài khoản trên 1 luồng.
    """
    account_str = account_str.strip()
    if not account_str:
        return None

    # Tách email và password
    if '|' in account_str:
        parts = account_str.split('|', 1)
        email, password = parts[0].strip(), parts[1].strip()
    elif ':' in account_str:
        parts = account_str.split(':', 1)
        email, password = parts[0].strip(), parts[1].strip()
    else:
        email = account_str
        password = ""

    payload = {
        "email": email,
        "password": password
    }

    headers = {
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            CHEAPLUXURY_API_URL,
            json=payload,
            headers=headers,
            timeout=12
        )

        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("response_code") == 200:
                emails_list = res_json.get("data", {}).get("emails", [])
                
                if emails_list:
                    latest_email = emails_list[0]
                    body_html = latest_email.get("body_html", "") or ""
                    body_text = latest_email.get("body_text", "") or ""
                    
                    content = body_html if body_html else body_text
                    verify_link = extract_verify_link(content)

                    if verify_link:
                        return {
                            'account': account_str,
                            'email': email,
                            'status': 'THÀNH CÔNG',
                            'link': verify_link
                        }
                    else:
                        return {
                            'account': account_str,
                            'email': email,
                            'status': 'ĐÃ ĐỌC (KHÔNG CÓ LINK)',
                            'link': ''
                        }
                else:
                    return {
                        'account': account_str,
                        'email': email,
                        'status': 'HÒM THƯ TRỐNG',
                        'link': ''
                    }
            else:
                msg = res_json.get("message", "Lỗi API")
                return {
                    'account': account_str,
                    'email': email,
                    'status': f'LỖI: {msg}',
                    'link': ''
                }
        else:
            return {
                'account': account_str,
                'email': email,
                'status': f'HTTP {response.status_code}',
                'link': ''
            }

    except requests.exceptions.Timeout:
        return {
            'account': account_str,
            'email': email,
            'status': 'LỖI: TIMEOUT',
            'link': ''
        }
    except Exception as e:
        return {
            'account': account_str,
            'email': email,
            'status': f'LỖI: {str(e)}',
            'link': ''
        }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/process', methods=['POST'])
def process():
    data = request.get_json()
    if not data or 'accounts' not in data:
        return jsonify({'error': 'Dữ liệu không hợp lệ'}), 400

    raw_text = data.get('accounts', '')
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return jsonify({'error': 'Danh sách tài khoản rỗng'}), 400

    results_map = {}

    # Chạy 20 luồng song song
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_acc = {
            executor.submit(check_single_account, line): line 
            for line in lines
        }
        
        for future in as_completed(future_to_acc):
            res = future.result()
            if res:
                results_map[res['account']] = res

    # Sắp xếp kết quả đúng thứ tự nhập vào
    final_results = []
    for idx, line in enumerate(lines, start=1):
        res = results_map.get(line, {
            'account': line,
            'email': line,
            'status': 'LỖI KHÔNG XÁC ĐỊNH',
            'link': ''
        })
        final_results.append({
            'id': idx,
            'email': res['email'],
            'status': res['status'],
            'link': res['link']
        })

    return jsonify({'results': final_results})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
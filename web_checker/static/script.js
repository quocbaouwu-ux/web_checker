// Khi người dùng bấm nút gửi dữ liệu
async function verifyEmails() {
    const resultContainer = document.getElementById('result'); // ID phần tử chứa kết quả
    
    // 1. TẮT / ẨN dòng chữ Loading xoay xoay (không cho hiển thị)
    // Nếu bạn có thẻ hiển thị loading, ẩn nó đi hoặc không gán nội dung "Đang kết nối..." vào:
    resultContainer.innerHTML = ''; 

    try {
        const response = await fetch('/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ accounts: document.getElementById('emailList').value })
        });
        
        const data = await response.json();

        // 2. CHỈ HIỂN THỊ LINK "TẠI ĐÂY" KHI CÓ KẾT QUẢ
        if (data.results && data.results.length > 0) {
            let htmlContent = '';
            data.results.forEach(item => {
                if (item.link) {
                    // Chỉ hiển thị chữ TẠI ĐÂY dẫn tới link xác minh
                    htmlContent += `<p><a href="${item.link}" target="_blank" style="color: blue; text-decoration: underline; font-weight: bold;">TẠI ĐÂY</a></p>`;
                } else {
                    htmlContent += `<p>Không tìm thấy link</p>`;
                }
            });
            resultContainer.innerHTML = htmlContent;
        } else {
            resultContainer.innerHTML = 'Không tìm thấy kết quả.';
        }
    } catch (error) {
        resultContainer.innerHTML = 'Có lỗi xảy ra!';
    }
}
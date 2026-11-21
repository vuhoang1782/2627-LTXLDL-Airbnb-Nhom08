AI sử dụng:CLaude(main) + deepseek + gemini
Download.py: tham khảo cách xác định file lỗi, không lồi qua việc thiết lập format file: như file calendar phải có cột prices, ngày,...
(vấn đề: code AI cho rằng string khác số, nên trả về báo cáo sai, do csv vẫn giữ nguyên string, thứ 2 là cột prices ở mốc 3,4 không tồn tại, và sau khi xem xét thêm, thấy không phù hợp (do dùng prices từ listings nên bỏ qua)
gặp 1 số bug khi mà dùng AI mà đã là file có sẵn, khi mà gọi file, thì gọi file cũ, đã sửa bằng việc thêm --force ở cuối, đè lên cái trước.

- thử nghiệm check bug bằng jupyter notebook, thử tự code lại và comment
- rút gọn lại những phần không cần thiết, để code sạch và tối giản hơn.

Sorting.py: là file ultility được dùng để check tỷ lệ nan trong các file listing, reviews và calendar, là bước đầu để làm qa và xác định các cột cần thiết,có thể sử dụng cho qa.py
- AI được dùng để nêu pseudo code cho việc kiểm tra độ nan của các file.
- Bổ sung thêm cột check giữa các file và loại bỏ 1 số thành phần không cần thiết, tập trung vào nhiệm vụ check nan


qa.py: kiểm tra trước bằng định dạng file .csv để có thể kiểm tra liệu ids đã được điền chuẩn chưa (liệu có theo đúng số của listings, reviews như đã giao trong đề không ?)
tiến hành gán cờ, phát hiện 1 số lỗi, và đã kiểm tra tay lại.
- tích hợp thêm 1 só phần việc trong việc lọc file và xét llm, ưu tiên làm llm trước

bỏ toàn bộ code base 1 tháng rưỡi ? for what ? code 1700 dòng, full AI, rồi cuối cùng chọn code 1500 dòng ?

Tối ưu các code của bản 1500 dòng, chỉnh sửa phần download cho thuần download, loại bỏ ý tưởng filter trong download, giữ tinh thần code của tôi
- Download.py được chỉnh sửa dựa trên code base cũ của tôi, bỏ bước interim, đánh giá là bước trung gian gây tốn thời gian và bộ nhớ, rồi qa vẫn phải check regex, chỉnh sửa lại, làm 1 thể ở qa.
- Ý tưởng AI đưa ra là tạo 1 file filter data để xử lý Interim
  => Phản đối, filterdata phải thêm cả import, thêm run và thêm các hàm, lệnh chạy và report, tôi đánh giá là nên cho những phần filter vào qa, và các id report cũng cho nốt vào qa
- QA đẩy lên 400 dòng tính cả comment và docstring, tuy vậy, tối ưu hơn về bộ nhớ, phần này nhờ AI support về xác định module nào cho kpi
- KPI dựa trên phần cũ, bỏ một số safeguard.
(AI dùng file excel, dẫn đến lỗi sai ids, đặc biệt nghiêm trọng ở file reviews llm do số quá lớn dẫn đến lệch review, giải pháp: chuyển thành dạng csv, lưu ids ở dạng string, không phải int)

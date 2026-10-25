AI sử dụng:CLaude
Download.py: tham khảo cách xác định file lỗi, không lồi qua việc thiết lập format file: như file calendar phải có cột prices, ngày,...
(vấn đề: code AI cho rằng string khác số, nên trả về báo cáo sai, do csv vẫn giữ nguyên string, thứ 2 là cột prices ở mốc 3,4 không tồn tại, và sau khi xem xét thêm, thấy không phù hợp (do dùng prices từ listings nên bỏ qua)
gặp 1 số bug khi mà dùng AI mà đã là file có sẵn, khi mà gọi file, thì gọi file cũ, đã sửa bằng việc thêm --force ở cuối, đè lên cái trước.

- thử nghiệm check bug bằng jupyter notebook, thử tự code lại và comment

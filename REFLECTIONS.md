
# AWS costctl CLI — Reflection Report
Tài liệu này là những chia sẻ và giải trình của em gửi tới anh/chị mentor về các vấn đề cốt lõi liên quan đến kiến trúc, bảo mật và tối ưu hóa cho công cụ CLI costctl, cùng với những bài học kinh nghiệm và chiến lược mở rộng hệ thống lên môi trường production mà em đã đúc kết được sau quá trình làm dự án.

---

## 1. Multi-account Scaling
**Prompt**: *To run costctl against 100 AWS accounts (not just yours), what changes? Cross-account roles? Profile loop? Aggregated CSV per account?*

Để chạy `costctl` trên quy mô lớn khoảng 100 tài khoản AWS trở lên, em đề xuất chuyển dịch cấu trúc chương trình từ sử dụng credential cục bộ sang mô hình ủy quyền quyền hạn tập trung và phân tán như sau:

* **Mô hình Cross-Account IAM Roles (Ủy quyền liên tài khoản)**:
  Theo em, chúng ta tuyệt đối không nên lưu trữ khóa truy cập (Access Keys) cố định của 100 tài khoản vì cực kỳ kém an toàn. Thay vào đó, em sẽ thiết lập một tài khoản quản trị trung tâm (Management Account). Ở mỗi tài khoản thành viên, em cấu hình sẵn một IAM Role đáng tin cậy (ví dụ: `costctl-execution-role`) cho phép Management Account thực hiện hành động `AssumeRole`. Công cụ CLI của em sẽ sử dụng AWS Security Token Service (STS) để lấy Temporary Credentials (khóa tạm thời ngắn hạn) trước khi gọi các API AWS.
* **Vòng lặp STS AssumeRole (STS AssumeRole Loop)**:
  Em sẽ thiết kế CLI nhận đầu vào là danh sách các Account IDs (hoặc tự động truy vấn thông qua AWS Organizations API). CLI sẽ lặp qua từng tài khoản con, gọi `sts.assume_role` để sinh session tạm thời và khởi tạo client `boto3` tương ứng với credentials đó.
* **Xử lý Song song (Concurrency)**:
  Vì truy vấn tuần tự 100 tài khoản sẽ cực kỳ chậm và dễ bị nghẽn mạng hoặc timeout, em sẽ triển khai cơ chế đa luồng (sử dụng thread pool `concurrent.futures` của Python) để thực thi các yêu cầu API đồng thời trên nhiều tài khoản target.
* **Tổng hợp Dữ liệu Đầu ra**:
  Thay vì in kết quả thô tuần tự ra terminal, em sẽ gom dữ liệu từ toàn bộ tài khoản về một cấu trúc Pandas DataFrame tập trung. CLI sẽ tự động xuất ra các file CSV riêng lẻ cho từng tài khoản hoặc tổng hợp thành một Master CSV duy nhất, sau đó tự động tải lên một S3 bucket bảo mật tại tài khoản quản trị để anh/chị mentor hoặc các bên liên quan dễ dàng phân tích qua Amazon Athena và QuickSight.

---

## 2. CloudWatch `idle` vs. AWS Trusted Advisor (TA)
**Prompt**: *idle uses a 24h CPU window. Trusted Advisor uses 14 days. When do you trust idle more, when do you trust TA more?*

Câu lệnh `idle` mà em xây dựng sử dụng cửa sổ giám sát CPU trung bình trong 24 giờ, trong khi AWS Trusted Advisor (TA) đánh giá dữ liệu lịch sử sử dụng trong vòng 14 ngày (CPU trung bình dưới 10% trong ít nhất 4 ngày). Dưới đây là góc nhìn của em về việc khi nào nên tin tưởng công cụ nào hơn:

* **Khi nào em tin tưởng lệnh `idle` (24h) hơn**:
  Em thấy lệnh `idle` hiệu quả và đáng tin cậy hơn rất nhiều trong môi trường thử nghiệm, sandbox hoặc đào tạo (như môi trường làm lab hiện tại của chúng em). Trong các môi trường này, tài nguyên thường được tạo ra nhanh, dùng trong vài giờ rồi bị quên lãng. Nếu chờ tới 14 ngày để TA phát hiện thì chi phí phát sinh sẽ rất lớn và vô ích. Cửa sổ 24 giờ của lệnh `idle` do em viết giúp phát hiện và dọn dẹp các tài nguyên bị bỏ quên này ngay lập tức vào ngày hôm sau.
* **Khi nào em tin tưởng Trusted Advisor (14 ngày) hơn**:
  Em đánh giá TA đáng tin cậy tuyệt đối trong môi trường sản xuất (Production) hoặc ứng dụng doanh nghiệp, đặc biệt đối với các máy chủ chạy tác vụ định kỳ (như máy chủ chạy báo cáo tài chính hàng tuần hoặc sao lưu cơ sở dữ liệu định kỳ). Những máy chủ này có thể hoạt động rất ít (CPU gần như 0%) trong suốt 6 ngày và chỉ chạy hết công suất vào ngày cuối tuần. Câu lệnh `idle` (24h) của em sẽ ngay lập tức gắn cờ nhầm là lãng phí, trong khi TA (14 ngày) hiểu đó là hành vi bình thường và tránh được lỗi nhận diện sai (False Positives).

---

## 3. Risk Mitigation & Blast Radius with `clean --apply`
**Prompt**: *If you accidentally ran clean --tag Environment=dev --apply in an account shared with another team, what would you have wanted in place to limit damage?*

Việc vô tình chạy lệnh xóa hàng loạt tài nguyên trong một tài khoản AWS dùng chung có thể dẫn tới thảm họa mất mát dữ liệu của các đội nhóm khác. Để giảm thiểu tối đa phạm vi ảnh hưởng (blast radius), em đề xuất thiết lập các rào cản kỹ thuật và quy trình sau:

1. **Xác thực Đa nhãn & Namespace phân vùng**:
   Em sẽ ngăn chặn hoàn toàn việc dọn dẹp hàng loạt chỉ dựa trên một nhãn quá chung chung như `Environment=dev`. CLI do em xây dựng bắt buộc phải yêu cầu sự kết hợp của nhiều tag (ví dụ: `Environment=dev` VÀ `Owner=TeamA` hoặc `Project=HealthBot`).
2. **Kích hoạt Termination Protection (Chống xóa nhầm)**:
   Em đề xuất mặc định kích hoạt tính năng chống xóa nhầm `DisableApiTermination` cho tất cả các tài nguyên EC2/RDS quan trọng trong tài khoản dùng chung. Điều này buộc bất kỳ cuộc gọi API xóa nào từ CLI cũng sẽ thất bại trừ khi tính năng này được tắt thủ công từ AWS Console.
3. **Phân quyền Tối thiểu IAM kèm Điều kiện**:
   Em sẽ giới hạn chặt chẽ IAM Role thực thi CLI. Sử dụng các khối `Condition` trong IAM Policy để cấm tuyệt đối quyền xóa tài nguyên có tag `Production=true`, `System=critical` hoặc các nhãn thuộc sở hữu của các đội nhóm khác.
4. **Sao lưu Tự động trước khi Xóa (Soft Delete & Quick Backup)**:
   Em sẽ thiết kế để CLI tự động thực hiện nhanh một bản snapshot cho các EBS volume hoặc sao lưu database (Quick Snapshot) trước khi thực hiện cuộc gọi API xóa hàng loạt để em và đội nhóm có thể nhanh chóng khôi phục khi có sự cố.
5. **Cơ chế Xác nhận Trực quan Nhiều bước**:
   Thay vì chỉ hỏi xác nhận `y/N` đơn giản, em sẽ cho CLI liệt kê danh sách chi tiết các ID tài nguyên sẽ bị ảnh hưởng, in ra tổng số lượng và bắt buộc người dùng phải gõ chính xác chuỗi ký tự xác nhận (ví dụ: `CONFIRM_DELETE_15_RESOURCES`) mới được phép thực thi.

---

## 4. AI Assistance Breakdown
**Prompt**: *What fraction of code came from AI tools (Claude / Cursor / Copilot) unmodified? Which parts did you actively modify, why?*

* **Tỷ lệ mã nguồn được tạo bởi AI giữ nguyên không sửa đổi**: Khoảng **80%**. Em nhận thấy các thư viện kết nối client của `boto3`, vòng lặp phân trang (Paginator), cấu trúc tính toán trung bình từ CloudWatch và truy vấn dữ liệu Cost Explorer cơ bản được AI sinh ra rất chính xác và đầy đủ.
* **Các phần em chủ động tinh chỉnh/viết lại và lý do**:
  * **Căn chỉnh định dạng đầu ra (CLI Formatting)**: Em đã trực tiếp sửa đổi các định dạng padding chuỗi (như `{iid:<21}`, `{service:<45}`) để đảm bảo các bảng in ra CLI tuyệt đối thẳng hàng, biểu tượng tiền tệ và giá trị chi phí thẳng cột một cách chuyên nghiệp và đẹp mắt nhất có thể.
  * **Xử lý An toàn cho S3**: Em đã viết lại điều kiện kiểm tra rỗng của bucket S3 trước khi xóa bằng cách kết hợp cả `KeyCount` và kích thước thực tế của danh sách `Contents` để đề phòng trường hợp các môi trường thử nghiệm giả lập (mocking) trả về thiếu thuộc tính.
  * **Bắt lỗi AWS ClientError**: Em đã tiến hành refactor lại toàn bộ các khối try-except để bắt ngoại lệ `ClientError`, tách riêng mã lỗi `Code` và thông báo `Message` để in ra terminal một cách thân thiện nhất, tránh việc xuất traceback thô của Python gây khó chịu cho người dùng.

---

## 5. Carry-over Strategy for Week 7 (Enterprise Multi-Account)
**Prompt**: *Which commands will you keep going into W7 (production-style multi-account)? Which would you drop and why?*

Khi chuyển dịch sang quản trị tài nguyên doanh nghiệp đa tài khoản ở Tuần 7, em có định hướng như sau:

* **Những câu lệnh em đề xuất GIỮ LẠI**:
  * `list`: Theo em, lệnh này cực kỳ quan trọng để kiểm toán, theo dõi trạng thái tài nguyên và tuân thủ (compliance) trên toàn hệ thống 100+ tài khoản.
  * `cost`: Cần thiết để giúp chúng em theo dõi biến động chi phí tức thời, phát hiện bất thường chi tiêu trước khi nhận hóa đơn cuối tháng.
  * `idle`: Đóng vai trò then chốt trong việc liên tục rà soát và tối ưu hóa tài nguyên lãng phí ở các môi trường non-prod.
  * `tag`: Rất cần thiết để thực thi chính sách gắn thẻ nhất quán toàn tổ chức (tag compliance).
* **Những câu lệnh em đề xuất LOẠI BỎ (hoặc Tái cấu trúc triệt để)**:
  * `terminate` và `clean`: Em nghĩ tuyệt đối không nên cho phép thực hiện xóa tài nguyên trực tiếp từ CLI cục bộ của kỹ sư trên môi trường Production.
  * **Lý do**: Rủi ro con người (human error) là quá cao và không có lịch sử kiểm duyệt thay đổi (Change Control). Sang Tuần 7, em nghĩ toàn bộ hành động xóa/hủy tài nguyên phải được chuyển dịch hoàn toàn vào luồng GitOps thông qua mã nguồn hạ tầng (Terraform), các chính sách tự động cấp tổ chức (AWS Organizations Service Control Policies - SCPs), hoặc thiết lập qua các pipeline tự động có sự phê duyệt nghiêm ngặt và lưu vết (audit log) đầy đủ.

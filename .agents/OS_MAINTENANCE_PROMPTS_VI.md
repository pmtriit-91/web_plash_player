# Cẩm nang prompt bảo trì Universal Agent OS V9

## Audit chỉ đọc

> Chạy Agent OS doctor, kiểm tra Core manifest, vendor lock, routing, skill và ranh
> giới ownership. Không sửa file. Phân biệt rõ release-owned, application-owned và
> runtime. Báo cáo bằng chứng, phần chưa xác minh và rủi ro contamination.

## Lập kế hoạch nâng cấp

> Đọc `.agents/skills/agent-os-maintenance/SKILL.md`, challenge kiến trúc và lập kế
> hoạch có blast radius, rollback, migration cho client, vendor admission gates và
> kiểm chứng. Không coi GitHub popularity hay NotebookLM là authority.

Với candidate release đã được người dùng chỉ định, chạy planner chỉ đọc:

```bash
python3 .agents/_tools/agent_os_lifecycle.py plan-update --source /path/to/candidate/.agents
```

`ready_to_apply: false` là kết quả bắt buộc khi source chưa có verified provenance,
Core đang dirty hoặc có đường dẫn ngoài release boundary. Planner không phải quyền
apply và không được dùng để tự chọn master.

## Thực thi bản nâng cấp đã được cho phép

> Bảo vệ thay đổi chưa commit và tuyệt đối không sửa `project/**`,
> `skills/project-memory/**` hay `skills/project-local/**`. Sau thay đổi, chạy
> lifecycle validation, routing validation, evals và `git diff --check`. Chỉ tạo lại
> manifest bằng lệnh có `--confirm`; không tự stage hay commit.

## Kiểm tra bản phát hành

```bash
python3 .agents/_tools/agent_os_lifecycle.py doctor
python3 .agents/_tools/agent_os_lifecycle.py verify-core
python3 .agents/_tools/agent_os_lifecycle.py verify-vendors
python3 .agents/_tools/agent_os_lifecycle.py validate-skills
python3 .agents/_tools/validate-routing-sync.py
python3 .agents/_tools/run-agent-os-evals.py
```

`verify-adapter` có thể trả về `UNBOUND`; đây là trạng thái an toàn khi repository
chưa có binding chính thức, không phải bằng chứng Core bị hỏng.

## Khởi tạo hoặc sửa Project Adapter

> Chỉ thực hiện khi người dùng cho phép rõ ràng. Audit root marker, workspace,
> package script, context entrypoint và Project ID từ repository hiện tại; loại mọi
> contamination từ dự án cũ. Ghi binding trong application-owned scope, chạy
> `build-adapter-fingerprint --confirm`, rồi yêu cầu `verify-adapter` và `doctor`
> cùng PASS trước khi nạp Project Memory làm authority.

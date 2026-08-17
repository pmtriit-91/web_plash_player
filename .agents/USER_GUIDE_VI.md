# Hướng dẫn Universal Agent OS V9

Agent OS là lớp điều phối agent có thể dùng lại giữa nhiều repository. Bản phát hành
không được chứa tên dự án, đường dẫn máy cá nhân, lệnh riêng của ứng dụng hay ký ức từ
dự án khác.

## Cách hoạt động

- `AGENTS.md` ở root giúp Codex và client tương thích tìm thấy `.agents/AGENTS.md`.
- Core và routing chỉ nạp workflow/skill cần thiết cho nhiệm vụ hiện tại.
- `project/**` và `skills/project-memory/**` thuộc ứng dụng, không thuộc bản phát hành.
- Khi chưa có Project Adapter hợp lệ, trạng thái là `UNBOUND`; Agent OS chỉ cho phép
  audit và kiểm tra integrity, không coi Project Memory là authority.

Kiểm tra trạng thái bằng:

```bash
python3 .agents/_tools/agent_os_lifecycle.py doctor
```

## Skill hiện hành

Skill lõi có thể tự khám phá:

- `agent-os-maintenance`: bảo trì release, ownership, provenance và vendor supply chain.
- `notebooklm-research`: nghiên cứu nguồn và tạo Studio artifact có kiểm soát qua
  NotebookLM MCP; chỉ nạp khi nhiệm vụ yêu cầu NotebookLM.
- `thinking/constitution-first`: đối chiếu nhiệm vụ với mission và tiêu chí thành công.
- `thinking/architecture-challenge-framework`: phản biện kiến trúc trước thay đổi lớn.

`project-memory` là projection do từng ứng dụng sở hữu và chỉ có authority khi
adapter ở trạng thái `BOUND` đồng thời Context Memory ở trạng thái `FRESH`.

Người dùng không cần nhớ tên hoặc vị trí skill. Router V2 đọc descriptor nhỏ gọn để
lọc theo lifecycle/permission, chọn đúng một capability chính và giải thích bằng
confidence, evidence, alternatives và lý do loại trừ. Có thể xem cùng nguồn dữ liệu
mà Control Center sẽ sử dụng sau này:

```bash
python3 .agents/_tools/agent_os_resolver.py list
python3 .agents/_tools/agent_os_resolver.py show --capability agent_os_maintenance
python3 .agents/_tools/agent_os_resolver.py simulate --prompt "audit Agent OS integrity"
```

Nếu không capability nào đạt ngưỡng, router dùng `standard_feature` cho nhiệm vụ hiện
tại và phát một capability-gap chỉ đọc để nghiên cứu sau. Router không tự tải skill.
Capability bị `disabled`, `quarantined`, `deprecated` hoặc `manual-only` không được
tự động chọn.

## Nghiên cứu và lắp skill

Agent có thể tự phát hiện capability gap, đọc snapshot tĩnh và đề xuất `vendor-pin`,
`adapt-local-skill`, `adapt-local-principles`, `project-local`, `research-only` hoặc
`reject`. Người dùng không cần mở vendor để nhớ cách gọi. Tuy vậy discovery không tự
động cài hay kích hoạt skill.

```bash
python3 .agents/_tools/agent_os_research.py status
python3 .agents/_tools/agent_os_research.py validate-registry
```

Research Lab bắt buộc full commit, license phù hợp và hash file; chặn archive opaque,
symlink thoát snapshot, prompt injection, global installer, Git/deploy automation và
framework cạnh tranh boot/router/memory. Script upstream bị quarantine và không bao
giờ được chạy ở giai đoạn research. GitHub Trending, stars và NotebookLM chỉ là tín
hiệu nghiên cứu; connector lỗi không làm hỏng boot hoặc skill đang active.

Candidate đang được nghiên cứu và receipt của connector nằm trong
`_runtime/research/**`, không đi vào release. Candidate `project-local` luôn thuộc dự
án sử dụng và không được lắp vào portfolio phổ quát.

## Vòng đời capability tự động

Sau khi agent đã tạo candidate và assembly hợp lệ, người dùng chỉ cần review một plan
và approve một lần để lắp đồng bộ skill bytes, routing, descriptor, decision,
provenance vendor nếu có, shadow eval, lifecycle receipt và manifest working-baseline:

```bash
python3 .agents/_tools/agent_os_cli.py skills plan-integration \
  --candidate /duong-dan/candidate.json --assembly /duong-dan/assembly.json
python3 .agents/_tools/agent_os_cli.py skills apply-integration \
  --plan PLAN_ID --confirm
```

Plan khóa Git HEAD, hash policy/eval, protected digest, candidate hash, thời hạn,
exact diff và byte trước/sau. Apply dùng lock toàn cục, ghi manifest cuối cùng và tự
khôi phục toàn bộ byte nếu lỗi. Nếu tiến trình bị ngắt giữa transaction, mọi apply mới
bị chặn cho đến khi người dùng xác nhận recovery.

Update checker giữ pin cũ active cho đến khi plan mới được apply. `manual-only`,
`disabled`, `quarantined`, `deprecated` và rollback đều dùng transaction có review.
Usage receipt chỉ lưu HMAC của task và metadata đã redaction, không lưu raw prompt.
MCP vẫn chỉ đọc; commit, push và verified release vẫn là approval riêng.

## Kiểm tra khả năng phát hành công khai

Verified release dùng cho private beta không tự động có nghĩa là được phép public.
Có thể chạy audit chỉ đọc sau để xem blocker mà không gọi mạng hoặc sửa trạng thái:

```bash
python3 .agents/_tools/agent_os_cli.py publication audit
```

Audit kiểm tra giấy phép của chính dự án, `SECURITY.md`, third-party notices, full SHA
của GitHub Actions, provenance vendor/research và chữ ký secret trong file Git quản
lý. Nếu gặp secret, kết quả chỉ in đường dẫn và mã rule, không in giá trị. Dù toàn bộ
gate kỹ thuật pass, `publication_ready` vẫn là `false` cho đến khi người sở hữu kiểm
tra visibility/security trên host và phê duyệt public riêng. Hiện giấy phép dự án là
quyết định pháp lý chưa được Agent OS tự chọn.

## Project Genesis

Core phát hành schema, doctor, transaction engine và placeholder
`project-template/genesis.json`; mỗi dự án sở hữu `project/genesis.json`,
`project/genesis-confirmations/**` và `project/genesis-projection.json`. Placeholder
luôn mang identity `unbound-consumer` và không được copy nguyên byte thành dữ liệu dự
án.

```bash
python3 .agents/_tools/agent_os_cli.py genesis doctor
python3 .agents/_tools/agent_os_cli.py genesis plan-migration
python3 .agents/_tools/agent_os_cli.py genesis apply-migration --plan PLAN_ID --confirm
python3 .agents/_tools/agent_os_cli.py genesis plan-confirmation --input /duong-dan/candidate.json
python3 .agents/_tools/agent_os_cli.py genesis apply-confirmation --plan PLAN_ID --confirm
python3 .agents/_tools/agent_os_cli.py genesis projection
python3 .agents/_tools/agent_os_cli.py genesis recover --confirm
```

`apply-migration --confirm` chỉ cho phép thực hiện plan kỹ thuật và luôn tạo draft;
nó không xác nhận mission, primary user hay product truth. `apply-confirmation` là
thao tác riêng: plan phải hiển thị exact claim delta, khóa Git HEAD, Project Binding,
fingerprint, revision, source/evidence hash và chỉ khi người sở hữu xác nhận nghĩa của
nội dung thì mới tạo durable receipt. Agent không được suy ra sự xác nhận này từ câu
lệnh “tiếp tục”, từ README, NotebookLM, Context Memory hoặc quyền migration.

Boot chỉ nạp claim khi source là `confirmed` và projection tối đa 64 KiB khớp revision
cùng source hash. Các state `missing`, `draft`, `stale`, `conflicting` và
`contaminated` chỉ trả state/reason, không tiết lộ claim như sự thật. Transaction dùng
backup, write-ahead receipt, atomic replace, post-doctor verification, rollback và
explicit recovery; không tự commit hoặc push.

## Context Memory phổ quát

Agent OS chỉ đóng gói engine, policy, schema và template. Dữ liệu thật luôn nằm trong
`project/context/**`; projection nhỏ cho client nằm ở
`skills/project-memory/SKILL.md`. Cả hai vùng đều thuộc dự án và không đi vào release.

```bash
python3 .agents/_tools/agent_os_cli.py memory doctor
python3 .agents/_tools/agent_os_cli.py memory load --tier hot
python3 .agents/_tools/agent_os_cli.py memory initialize
python3 .agents/_tools/agent_os_cli.py memory refresh
python3 .agents/_tools/agent_os_cli.py memory propose /duong-dan/record.json
python3 .agents/_tools/agent_os_cli.py memory apply --plan PLAN_ID --confirm
```

- `hot`: identity, trạng thái hiện tại, guardrail và issue quan trọng; có thể load lúc boot.
- `warm`: decision, architecture, convention và known issue; chỉ load khi cần.
- `cold`: research/history; NotebookLM chỉ được ở tầng này với authority
  `research-only`.

Mỗi record phải trỏ đến evidence và hash hiện tại. Sai project/remote, source stale,
hai nguồn cùng authority mâu thuẫn, task trùng scope hoặc base commit cũ đều được đánh
dấu trước mutation. `STALE` có thể đọc để đối chiếu nhưng không có authority;
`DEGRADED` bị chặn.

Task claim và handoff cũng tạo plan exact diff rồi mới apply. Handoff lưu kết quả đã
xác minh, rủi ro còn lại, next action và evidence; không lưu conversation. Compaction
chỉ summarize rồi archive cold research/history, không xóa record gốc hoặc decision
đang active. Validator tái dựng canonical transition: mọi original không được chọn
phải giữ nguyên, original được chọn chỉ đổi `active` thành `archived`, summary là
record mới duy nhất và projection không được đổi. Doctor cũng so projection với bản
render canonical; nếu chỉ projection lệch hoặc mất, lệnh `memory refresh` tạo plan
`repair-projection` một file để review/apply thay vì sửa trực tiếp. MCP chỉ đọc; CLI
và Control Center mới có write transaction.

## Retention và portability của Continuity

Retention không suy diễn từ tên file. Policy giữ `critical-active`, required hoặc
state-aware đang active, dependency target, completion evidence và recovery artifact.
Archive chỉ chép exact byte đã xác minh vào artifact deterministic, giữ nguyên source
và provenance; summary không trở thành authority mới.

Generation 1 chỉ cung cấp inspection và archive do người dùng chọn explicit. Mọi
reference hiện đều có `prune_eligible=false`; `age` và `count` mới là vocabulary của
policy tương lai, chưa phải threshold đang chạy và không kích hoạt xóa tự động.
Receipt archive có trạng thái `durable-verified` và chỉ hợp lệ khi mở lại được
canonical archive, exact file set, hash payload và Git provenance reachable.

```bash
python3 .agents/_tools/agent_os_cli.py continuity retention
python3 .agents/_tools/agent_os_cli.py continuity plan-archive /duong-dan/reference-ids.json
python3 .agents/_tools/agent_os_cli.py continuity apply-archive --plan PLAN_ID --confirm
```

Bundle offline là thư mục có manifest strict, không phải zip/tar opaque. Export lấy
provider-driven transitive closure được dựng lại từ exact Git commit reachable, bind
project ID, Binding, Adapter fingerprint, Core, catalog/profile/policy và hash từng
payload; mọi byte trong closure phải đã Git-durable. Vì vậy bundle tự thêm, bỏ hoặc
sửa source rồi rehash vẫn bị chặn. Destination phải chưa tồn tại; parent phải tồn tại
trước và giữ nguyên là thư mục thật, không symlink, cho đến lúc publish. Git chỉ được
đọc bằng literal path lookup hoặc scoped-prefix enumeration có bound; filesystem scan
đếm mọi file, directory và entry bị bỏ qua, nên non-JSON clutter hay cây empty
directory không thể né budget.
`inspect-bundle` chỉ xác nhận integrity; bundle chưa có authority cho đến khi restore
tương thích và doctors canonical pass. Receipt export mang trạng thái
`external-unverified` và giữ inline manifest snapshot có bound để mở lại exact Git
closure: đó là provenance của lần export, không phải bằng chứng durable rằng thư mục
ngoài repository vẫn còn tồn tại. Nếu archive/export lỗi sau publish, runtime chỉ báo
rolled back khi đã chứng minh cả false receipt lẫn artifact đều không còn; cleanup
không trọn vẹn có reason code và state flag riêng.

```bash
python3 .agents/_tools/agent_os_cli.py continuity plan-export --destination /duong-dan/bundle
python3 .agents/_tools/agent_os_cli.py continuity apply-export --plan PLAN_ID --confirm
python3 .agents/_tools/agent_os_cli.py continuity inspect-bundle --source /duong-dan/bundle
python3 .agents/_tools/agent_os_cli.py continuity plan-restore --source /duong-dan/bundle
python3 .agents/_tools/agent_os_cli.py continuity apply-restore --plan PLAN_ID --confirm
```

Restore sai project/Binding/fingerprint/Core, payload bị sửa hoặc thừa, path escape,
symlink, các chữ ký secret/prompt/reasoning được hỗ trợ, target stale hay bundle tự
nâng quyền ghi Core đều bị chặn trước write. Privacy gate là scanner theo contract và
structured field đã khai báo, không phải detector tổng quát cho mọi secret hoặc dữ
liệu che giấu. Core và identity chỉ `verify-only`; application target được backup
vào durable application directory không symlink trước atomic replace. Receipt thành
công ghi `rollback_ready`, phải mở lại được backup và bind project cùng sáu contract
hash vào exact Git blob reachable; nó không tuyên bố rollback đã xảy ra.
Nếu apply lỗi, `rollback_verified` chỉ đúng khi exact byte thật sự được phục hồi;
rollback không đầy đủ dùng reason code riêng và khai rõ false applied receipt đã xóa
được hay chưa.
Các lệnh này không commit/push. W5 chỉ mở mutation qua CLI, không mở thêm MCP write
surface. Việc mở lại receipt thành công chỉ chứng minh retained before-image còn
nguyên, không chứng minh target chưa drift sau thời điểm receipt được tạo.

## Control Center

Mở Settings UI local bằng:

```bash
python3 .agents/_tools/agent_os_cli.py settings serve
```

Lệnh in ra URL localhost kèm session token có hạn. UI không dùng CDN/cloud, không
chạy nền và nếu hỏng cũng không ảnh hưởng boot, CLI, MCP hoặc router. Skill card cho
biết mục đích, khi dùng/không dùng, nguồn, commit/license, integration mode, risk,
permission, eval, decision và số activation receipt đã redaction; raw prompt không
được lưu mặc định.

Thay đổi settings, capability hoặc Context Memory luôn tạo plan có exact diff, Git HEAD, hash
trước/sau, protected digest và expiry. Nút Apply chỉ hoạt động sau xác nhận và
revalidate; lỗi sẽ rollback. Core hard safety không thể tắt từ UI. Commit/push vẫn
tách riêng và mặc định không có.

Sau khi người dùng phê duyệt sửa binding, tạo lại fingerprint rồi kiểm tra adapter:

```bash
python3 .agents/_tools/agent_os_lifecycle.py build-adapter-fingerprint --confirm
python3 .agents/_tools/agent_os_lifecycle.py verify-adapter
```

Fingerprint khóa ba nhóm dữ liệu binding-critical: identity/workspace, command
descriptor có package evidence, và context entrypoint. Nó không hash nội dung memory
hay task log thường xuyên thay đổi.

Có thể kiểm tra một candidate release theo chế độ chỉ đọc:

```bash
python3 .agents/_tools/agent_os_lifecycle.py plan-update --source /duong-dan/toi/.agents
```

Lệnh xác minh source manifest, tính Core diff, phân loại dirty path, tạo digest cho
vùng application-owned và trả `plan_id`; nó không ghi dữ liệu. Source
`working-baseline` luôn bị đánh dấu provenance chưa đủ tin cậy cho apply.

Sau khi review exact diff, verified source có thể được apply bằng transaction yêu cầu
`--confirm`. Transaction chỉ ghi release-owned path, kiểm tra protected digest và tự
rollback nếu post-apply verification thất bại. Commit, push và publish vẫn là các
quyền riêng biệt, không được suy ra từ việc approve update.

## Dùng trên nhiều dự án và nhiều client

Codex là client chuẩn và đọc `AGENTS.md`. Danh sách client nằm trong một registry có
thể kiểm tra bằng:

```bash
python3 .agents/_tools/agent_os_cli.py clients list
```

`CLAUDE.md` và `GEMINI.md` tùy chọn chỉ chuyển hướng về `AGENTS.md`; chúng không chứa
policy riêng và không tự chứng minh rằng mọi phiên bản client đều auto-discover file.
Khi đóng gói, có thể chọn shim bằng `--client`; root `AGENTS.md` vẫn luôn có mặt.

Bản V8 cũ hoặc V9 working-baseline phải dùng migration transaction, không copy đè:

```bash
python3 .agents/_tools/agent_os_cli.py migration inspect
python3 .agents/_tools/agent_os_cli.py migration plan --source /duong-dan/release/.agents
python3 .agents/_tools/agent_os_cli.py migration apply --plan PLAN_ID --confirm
```

Plan khóa source manifest, Git HEAD, họ phiên bản, release inventory và digest vùng
project-owned. Repository dirty, bridge custom cần merge tay hoặc source chưa verified
đều bị chặn. Apply backup byte cũ, verify Core mới, giữ Project Adapter/Memory và có
rollback tường minh.

Bộ acceptance dựng ba repo tạm không liên quan (Node monorepo, Python service và site
tài liệu), yêu cầu `BOUND` + `FRESH`, đồng thời kiểm tra path kiểu Windows/POSIX và
package tái lập. CI chạy cùng suite trên Ubuntu, macOS và Windows.

Bộ vendor hiện hành là 8 skill kỹ thuật được chọn lọc từ `addyosmani/agent-skills`,
khóa tại một commit MIT cụ thể. `notebooklm-mcp-cli` và `obra/superpowers` được ghi
nhận là nguồn nghiên cứu đã pin; chỉ phần nguyên lý phù hợp được chuyển hóa vào local
Core/skill. Registry chỉ nạp một skill phù hợp; popularity hoặc GitHub Trending không
đủ để đưa nguyên một framework vào release.

Agent OS không tự stage, commit, push, cài package, sửa cấu hình toàn cục hoặc chạy
lệnh dự án chưa được chứng minh và cho phép.

# BE_FETD 与 FDEM3D 真实参数网页管理实现说明

## 1. 数据依据

- BE 样例：`docs/be_fetd/GroundedWireSource.dat`、`LoopSource.dat`
- BE 说明：`docs/be_fetd/BE_FETD_参数文件设置说明.docx`
- FDEM 样例：`docs/fdem3d_frequency_domain/GroundedWireSource.dat`、`LoopSource.dat`
- FDEM 说明：`docs/fdem3d_frequency_domain/FDEM_3D_参数文件设置说明.docx`
- Schema：`be-fetd-params-v1`、`fdem3d-frequency-source-v1`

BE 真实样例使用 GB18030；FDEM 使用 UTF-8。解析器支持普通小数和 E/D 科学计数法。保存会规范化行序、数值和注释，不保留上传文件的原排版。

## 2. 网页功能

“BE/FDEM 参数”页面可切换程序及 Grounded wire / Loop：

1. 加载当前工作区文件；
2. 上传 `.dat` 并解析到网页，上传动作本身不保存；
3. 载入系统真实默认参数；
4. 编辑时间或频率/求解器、空气域、材料、源几何和接收点；
5. 增删和复制材料、导线段、回线顶点和接收点；
6. CAS 保存或下载当前文件；
7. 从本人相同程序、相同源类型的历史任务归档加载参数。

历史归档只读。历史版本加载到表单后，保存只更新当前工作区，不会修改 `archives/`。

## 3. 任务语义

BE/FDEM 提交页仍选择 stdin `1` 或 `2`，但不再要求任务内上传 `.dat`：

- 1：快照当前 `GroundedWireSource.dat`
- 2：快照当前 `LoopSource.dat`

后台在用户工作区锁内将该程序的两个当前文件复制到 staging，并校验页面显示的所选文件 SHA-256。任务保存所选文件的真实 DTO、schema 和 hash。排队后继续编辑当前文件不会改变 staging 或归档。

runner 仍以 exe-only argv 启动，并通过 stdin 发送 `b"1\n"` 或 `b"2\n"`。运行成功、失败、取消、超时或服务恢复后，工作目录的两个参数文件都会从内部当前镜像恢复。归档始终复制 staging 快照。

## 4. 一致性与安全

- 工作副本：`storage/{user}/programs/{program_key}/{filename}`
- 权威镜像：`storage/{user}/.workspace-state/{program_key}/{filename}`
- 保存、提交快照、同步、运行和恢复共用用户 advisory lock。
- PREPARING、RUNNING、ARCHIVING、ARCHIVE_FAILED 期间禁止保存。
- SHA-256 optimistic concurrency 防止多个页面互相覆盖。
- API 只接收注册表中的 program/source，不接收服务端路径。
- 上传上限 10 MiB；材料、空气域、几何及接收点有数量上限。
- 程序同步只更新 exe/DLL，不覆盖用户参数。

坐标是否位于 `mesh.mphtxt` 的有效四面体内，本期仍由正式 exe 运行时检查。

## 5. 迁移

`scripts/migrate_source_real_params.py` 支持 dry-run 和正式执行：

- 合法真实当前文件采用为权威镜像；
- 已知旧占位文件先备份再使用真实默认文件；
- 未知无效文件保留并将工作区标记 ERROR；
- 历史归档只读扫描，可解析版本只回填数据库 DTO/schema/hash；
- 任何情况下都不重写 archive 文件。

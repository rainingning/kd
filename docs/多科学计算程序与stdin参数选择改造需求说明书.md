# 多科学计算程序与 stdin 参数选择改造需求说明书

## 1. 范围

平台固定支持 `DCR_3D.exe`、`BE_FETD.exe`、`FDEM3D_Frequency_Domain.exe`。不修改 Fortran 源码；同一用户三个程序共享“最多一个运行进程”的调度限制。

## 2. 工作区

每个用户按程序隔离运行目录：

```text
storage/{user_id}/programs/dcr_3d/
storage/{user_id}/programs/be_fetd/
storage/{user_id}/programs/fdem3d_frequency_domain/
```

每个目录包含对应 exe、`libiomp5md.dll`、`mesh/mesh.mphtxt` 和 `Forward_data/`。DCR 使用 `model_DC.dat`；另外两个程序始终同时包含 `GroundedWireSource.dat` 和 `LoopSource.dat`。

## 3. 新程序提交规则

1. 页面用 radio button 要求用户选择：
   - 1：`GroundedWireSource.dat`
   - 2：`LoopSource.dat`
2. 用户在 BE/FDEM 参数页面维护两个真实格式当前 `.dat`；提交任务时只上传 mesh，并携带所选当前参数的 SHA-256。
3. 后台在工作区锁内把两个当前 `.dat` 快照到 staging，运行时安装该不可变快照，结束后恢复最新当前文件。排队后编辑不会改变已提交任务。
4. 程序无命令行参数启动，cwd 必须是该用户的对应程序目录。
5. 新程序通过 `process.communicate(input=b"1\n")` 或 `b"2\n"` 写入 stdin 并模拟回车；输入后程序不再读取其他控制台参数。
6. Windows 隐藏控制台窗口；继承系统 PATH，并设置 `GFORTRAN_UNBUFFERED_ALL=1`、`FORT_BUFFERED=0`。

## 4. 版本、同步和安全

- 三个程序具有独立 manifest、版本和 SHA-256。
- 新程序 manifest 同时覆盖 exe、dll 和两个默认 `.dat`。
- 新用户一次性初始化三个程序；管理员可查看程序级状态并批量同步。
- 程序 key、文件名、cwd 和 stdin 映射来自服务端固定注册表，客户端不能提交任意路径或 stdin 文本。

## 5. 归档

所有终态任务归档 mesh、stdout、stderr、完整 `Forward_data/` 和 `task.json`。DCR 归档 `model_DC.dat`；新程序始终从 staging 归档两个 `.dat`，并记录程序 key、source type、stdin 选择、参数 schema、所选参数 SHA-256 和实际文件 hashes。

## 6. 兼容性

历史任务和参数模板回填为 `dcr_3d`；旧不可变归档不重写。旧 DCR 活动工作区迁入 `programs/dcr_3d/`，用户级 staging 和 archives 保持原路径。

## 7. 后续结构化参数扩展

BE/FDEM 四套真实参数格式和结构化网页管理已在后续版本实现，详细规则见 `BE_FETD与FDEM3D真实参数网页管理实现说明.md`。

# DCR_3D 程序模板目录

生产部署时由受信任的运维人员放置以下文件（exe/dll 已被 `.gitignore` 排除）：

```text
program_template/
├── DCR_3D.exe
├── libiomp5md.dll
└── program-manifest.json
```

`program-manifest.json` 格式：

```json
{
  "version": "1.0.0",
  "exe": "DCR_3D.exe",
  "dll": "libiomp5md.dll",
  "exe_sha256": "64 位小写十六进制 SHA-256",
  "dll_sha256": "64 位小写十六进制 SHA-256"
}
```

可用 PowerShell 计算摘要：

```powershell
(Get-FileHash .\DCR_3D.exe -Algorithm SHA256).Hash.ToLower()
(Get-FileHash .\libiomp5md.dll -Algorithm SHA256).Hash.ToLower()
```

后端启动、用户创建和程序同步均会校验 manifest。缺少文件或摘要不一致时，后端拒绝执行相关操作。

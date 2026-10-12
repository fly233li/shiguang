# 时光计：升级与数据兼容约定

用户要求覆盖安装后保留全部历史。修改和发布本项目时必须遵守以下约定：

- 正式数据路径固定为当前 Windows 用户的 `%LOCALAPPDATA%\Shiguang\usage.sqlite3`。不可随应用版本、品牌、安装目录或工作目录变化。演示与测试必须使用隔离目录。
- 发布包只包含程序及源码，不包含用户数据库、WAL/SHM 或备份。不得在更新、构建、卸载步骤中删除或重置用户数据。
- 数据库结构版本与应用发布版本分开。已存在的数据库先校验，再通过 SQLite backup API 创建并验证完整备份，最后才事务化迁移。禁止无条件覆盖 `PRAGMA user_version`，禁止删除旧库后重建，禁止用文件复制代替运行中的 SQLite 一致性备份。
- 不支持的高版本、损坏、结构不符、升级备份失败应停止启动并保留原始记录。不要自动恢复旧备份或静默切换为空数据库。
- 每个发布版本必须更新 `timelight/__init__.py`；启动时 `main.py` 将该版本传入 `Store`，保证版本变化触发保护。保留全部升级和手动备份。
- 变更存储时新增相应兼容测试，运行 `python -m unittest discover -s tests -v`。构建后运行 `tools/verify_upgrade.py` 验证旧版生成的数据经同目录覆盖后仍完整，并可继续计时。
- `build.ps1` 的干净 PATH 避免打入开发机其他软件的 ICU DLL，不能移除。禁止覆盖正在运行的程序目录；构建到 `dist/<版本>/Shiguang`。

存储与备份契约位于 `timelight/storage.py`、`timelight/data_protection.py`。升级和手动恢复步骤见 `README.md`。

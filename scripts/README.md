# 本机联调工具（Windows）

业务代码仍为Java；这些Python脚本只用于本机部署和测试夹具管理。

依赖：scripts/requirements-local.txt。Java21、已构建的Java JAR、Node/Vite依赖、
本机MySQL客户端和已安装的Ollama模型。

配置：根目录.env.local（Git忽略，禁止提交真实密码）。
至少填写DB_HOST、DB_PORT、DB_NAME、DB_USERNAME、DB_PASSWORD。
AI_SERVICE_KEY可留空，由本地脚本随机生成；它只传给Java和FastAPI。
不要使用VITE_变量保存服务器密钥。

2026-10-27真实联调已通过。当前MySQL项目库由本次初始化创建，原SQL中的旧个人数据未导入。
目标库不存在时先执行initialize；该命令拒绝覆盖已有库。

命令（项目根目录）：

```powershell
python scripts/local_stack.py check-config
python scripts/local_stack.py prepare
python scripts/local_stack.py start
python scripts/live_smoke.py
python scripts/local_stack.py stop
```

prepare会读取实际MySQL并在迁移前备份。start要求备份目标指纹匹配。
start会先检查Ollama及选定模型是否可用。模型目录和单独启动Ollama的方法见联调报告。
stop验证本项目进程命令后才停止，不停止MySQL和Ollama。
start-ai-preview只启动FastAPI和Vue，不启动Java，也不连接业务数据库。
预览模式运行时，先执行stop，再执行完整start。

.local-run保存私有备份、进程信息和日志；不纳入Git。
Java密码迁移由Java LegacyPasswordMigration执行，不在Python中实现业务认证逻辑。

安全检查：
python -u -m unittest discover -s scripts -p test_local_stack.py -v

重新打包JAR前先stop，避免Windows文件锁。
详细实测结果：docs/local-integration-2026-10-27.md。

M3 已增加健康档案增量迁移和平台规则 RAG。prepare 保留现有用户数据，新增授权默认关闭。
知识库导入使用 python scripts/run_knowledge.py sync "<绝对路径>/python-ai/knowledge/manifest.json"。
新增真实联调：python -u scripts/m3_live_smoke.py，仅使用并清理独立合成账号。
完整导入、评估和撤回机制见 docs/M3-implementation.md。

M4.1：python scripts/prepare_tool_model.py --use-local-config 创建项目独立工具模型别名；
复用现有 Qwen2.5 权重，不覆盖原模型。真实联调：python -u scripts/m4_live_smoke.py。
工具边界和模型模板说明见 docs/M4.1-implementation.md。

M4.2：先停止服务，prepare 备份并增加资格字段及草稿表，再重新打包 Java 并 start。
真实草稿与并发检查：python -u scripts/m42_live_smoke.py。
旧商品不自动变为可售；联调脚本只给本次合成商品添加测试资格，结束后清理。
说明与审查：docs/M4.2-implementation.md、docs/M4.2-review.md。

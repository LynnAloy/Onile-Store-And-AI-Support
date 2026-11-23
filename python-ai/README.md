# DeepseekDoc AI service — M4.2

Python 3.11+ / FastAPI。业务身份、药品、订单、库存和支付仍由 Java 管理。
本服务提供 AI 会话、平台规则 RAG 与经明确授权的个性化上下文，使用 Ollama 原生接口。
健康档案仍由 Java 管理，未授权不读取详情，不进入公共向量索引。
当前平台规则知识库、导入/评估命令和授权撤回机制见 ../docs/M3-implementation.md。
现已支持 Ollama 原生只读工具调用：商品搜索、商品详情、本人订单摘要。
工具协议、调用上限、本机模型模板和联调方式见 ../docs/M4.1-implementation.md。
新增独立商品意图授权的 prepare_order_draft；不持有确认或支付能力，收货信息仅走 Java。
详见 ../docs/M4.2-implementation.md 与 ../docs/M4.2-review.md。

## 本地启动

先完成 docs/M1-implementation.md 中的Java数据库迁移，并启动Java业务服务。

在本目录打开PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:JAVA_BASE_URL = "http://127.0.0.1:8080"
$env:AI_SERVICE_KEY = "<与Java相同的至少32字符随机密钥>"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "deepseek-r1:1.5b"
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Java必须使用同一个AI_SERVICE_KEY。没有有效密钥时Python启动校验失败。
.env.example只提供配置示例，不会被自动读取。模型必须已安装并可通过Ollama访问。

前端在 DeepseekDoc 目录执行 npm run dev。Vite将 /api 转发到Java8080，
/ai 转发到FastAPI8000。AI请求仅携带Java签发的短期代理凭证。

GET /ai/health 是进程存活检查，不代表Java、模型或数据库端到端可用。
GET /openapi.json 与 /docs 提供服务契约；部署时应通过入口代理限制开发文档访问。

## 自动化检查

```powershell
python -m compileall -q app tests
python -u -m unittest discover -s tests -v
```

测试使用临时会话数据库和HTTP模拟传输，不访问真实MySQL或外部模型。
Windows受限沙箱可能阻止asyncio建立事件循环，需要在具有相应系统权限的终端运行。

## 数据与限制

默认数据库为本服务data/conversations.db，可用AI_DATABASE_PATH修改。
它只包含conversations和turns，不保存Java登录凭证、代理凭证、服务密钥或业务表。
SQLite适合当前单机演示；多个应用节点部署前应迁移至共享数据库，并保留相同并发规则。
对话可能包含用户健康描述，数据库文件应设置适当访问权限，不要纳入Git。

上下文默认保留最近10个完整成功轮次，并受6000字符预算限制；当前输入最多4000字符。
字符预算不是精确token计数。模型上下文窗口8192，最大输出1024 tokens；
不同模型的分词与上下文支持需要实际模型联调确认。
输出同时受12000字符限制；超时、截断、空回答不会被记为成功。
MODEL_TEMPERATURE默认0.2，允许0至1；本机联调脚本使用0以稳定复现合成用例。

完整接口、事件、运行边界和后续任务见 docs/M2-implementation.md。

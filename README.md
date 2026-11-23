# 家庭健康咨询与购药辅助平台

Vue负责交互，Java负责业务，Python负责AI应用。

| 层 | 技术 | 当前能力 |
|---|---|---|
| 前端 | Vue3、Vite、Pinia、Element Plus | 用户/钱包/购药页面、AI会话与流式回答 |
| 业务后端 | Java21、Spring Boot3.5.3、MyBatis Plus、MySQL | 认证、药品、库存、订单、钱包、代理授权 |
| AI服务 | Python3.11+、FastAPI、HTTPX、Ollama、NumPy | 多轮对话、授权上下文、混合检索、查询工具与受限草稿准备 |
| AI会话存储 | 独立SQLite | 仅AI对话；不保存订单、库存或钱包 |

M1：认证和业务安全已完成代码与隔离测试。
M2：FastAPI对话迁移已完成代码与隔离测试，Java不再依赖Spring AI。
2026-10-27已完成真实MySQL、Java、FastAPI、Ollama及前端代理联调。
当前入口：http://127.0.0.1:3000/main；详细报告见docs/local-integration-2026-10-27.md。

## 开发入口

- Java：mybatis-plus-demo/mybatis-plus-demo
- 前端：DeepseekDoc
- AI：python-ai

先阅读 docs/M1-implementation.md，完成现有MySQL升级和Java环境配置。
再按 python-ai/README.md 和 docs/M2-implementation.md 配置AI服务与模型。
Java与Python使用同一AI_SERVICE_KEY，前端不保存服务密钥。
本机配置保存在Git忽略的.env.local；启停和复验见scripts/README.md。

## 检查

- Java目录：mvn test -B -ntp
- Python目录：python -u -m unittest discover -s tests -v
- 前端目录：npm test；npm run build

检查报告：docs/M1-validation.md、docs/M2-validation.md、docs/M3-implementation.md。
服务契约：docs/java-python-contract.md、docs/java-python-contract.openapi.json、
docs/fastapi-contract.openapi.json。

M3 框架与平台规则库已完成；医学资料待提供并审核。
M4.1 已增加真实商品/本人订单只读工具。M4.2 已增加商品资格、独立授权及未付款草稿，M5 再完善支付状态机。

## M3 健康档案授权与 RAG

已增加个人中心健康档案、可撤回的模型上下文授权、平台规则混合检索及可追溯引用。
Java 管理业务和档案，Python 管理 AI；首批只导入平台规则。
实现、部署和验证入口：[M3 说明](docs/M3-implementation.md)。

## M4.1 只读工具调用

支持实时查询商品、商品详情和本人订单，提供工具状态与结果卡片、历史轨迹和受控错误。
本机使用基于已有权重和官方工具模板创建的独立模型别名，原模型保留。
实现、部署与验证：[M4.1 说明](docs/M4.1-implementation.md)。

## M4.2 草稿准备与用户确认

从商品卡片选择商品数量，独立授权 AI 准备草稿，再到“我的草稿”核对并确认收货资料。
确认不扣款、不减库存、不代表成交。存量商品默认未知/待审核，需真实审核资料才能开放。
实现与契约：[M4.2 说明](docs/M4.2-implementation.md)。完成后审查：[审查记录](docs/M4.2-review.md)。

购买对话现支持生成待核对数量清单并预填选择；未审核商品可选择，但仍不能准备草稿。
说明与验证：[选择及数量修复](docs/purchase-selection-fix.md)。


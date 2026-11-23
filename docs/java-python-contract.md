# Java 与 Python 接口契约 v1（M1）

状态：Java只读接口及M2 FastAPI对话服务均已实现并纳入各自自动化测试。
Java 保留用户、健康档案、药品、库存、订单、钱包与支付业务；Python 不直连业务数据库。
机器可读契约见同目录 java-python-contract.openapi.json。

## 授权流程

1. 浏览器用 USER 登录凭证调用 POST /api/auth/agent-token。
2. Java 返回随机 AGENT_READ token、userId、scope、expiresAt。expiresAt 为 Unix 秒。
3. M2 浏览器调用 FastAPI 时只提交该短期代理凭证，不提交完整 USER token。
4. Python 在受信代码中携带 Authorization: Bearer <agent-token> 和 X-AI-Service-Key 访问 Java 内部接口。
5. Java 同时验证服务密钥、代理凭证、父会话有效性及资源归属。用户身份来自授权上下文。
6. 服务密钥至少32字符，仅在 Java/Python 环境变量中保存，不发送给浏览器、提示词或工具参数。

USER 凭证默认2小时；代理凭证最多5分钟，且不超过父会话期限。
重新登录或退出会撤销该用户全部会话和代理凭证。父会话到期也会使代理失效。
令牌不是 JWT，客户端不得解析其中内容；数据库仅保存 SHA-256 摘要。
部署时通过私网与 HTTPS 调用，服务密钥独立于用户凭证。空密钥默认关闭内部接口。

## 已实现接口

| 方法 | 路径 | 身份 | 返回 |
|---|---|---|---|
| POST | /api/auth/agent-token | USER | 代理凭证及过期时间 |
| GET | /internal/ai/v1/me | AGENT_READ + 服务密钥 | 当前授权用户与权限 |
| GET | /internal/ai/v1/medicines?name=关键词 | 同上 | 实时商品列表 |
| GET | /internal/ai/v1/medicines/{id} | 同上 | 商品详情 |
| GET | /internal/ai/v1/orders/{orderId} | 同上 | 当前用户订单摘要 |

内部接口不接受 userId 作为授权依据。订单摘要不包含收货人、电话和地址。
现有药品表只有名称、价格和库存，尚无处方属性、说明书关联或审核结论，
因此 M1 商品查询不能支持临床适用性判断或自动购药决策。

商品价格和订单金额的单位是人民币元，Java 使用 BigDecimal，Python 应使用 Decimal。
不要使用二进制浮点数参与金额计算。库存仅表示查询时刻的值。

## 错误处理

错误体统一为 {"code":"错误码","message":"可显示信息"}。
400 为参数/业务校验失败；401 为无效身份或密码验证失败；403 为权限不足；
404 为资源不存在或订单不属于当前用户；409 为冲突；429 为验证频次限制；500 为服务异常。
Python 遇到401应要求重新授权，不能循环重试；工具层应将错误转为受控结果。
GET 可进行有限次退避重试；未来的写操作必须复用同一个幂等键，不得盲目重试。
禁止把登录/支付密码、完整用户token、服务密钥或收货信息拼入模型上下文。
M3 健康档案仅允许通过明确授权的白名单接口获取，详见 M3-implementation.md；默认不共享。

## M4/M5 后续契约边界（未实现）

- 新增 AGENT_ORDER_PREPARE 权限及待确认订单接口时，必须使用单独授权和严格字段白名单。
- 模型只能提交商品ID、数量与请求幂等键，不能提交用户ID、成交价格、余额或已支付状态。
- Java 校验购药条件、处方属性、价格与库存后创建 pending 订单。
- 订单确认、支付验证和最终扣款继续使用 USER 业务接口，不能授予智能体。
- 当前 POST /api/orders 是经用户支付密码验证后立即完成的钱包交易，是旧流程的 M1 加固，
  尚未拆分为草稿、确认、支付状态机。代理凭证访问它固定返回403。
- 第三方支付沙箱、支付回调验签及一次性支付授权凭证属于 M5。

## M2 FastAPI 侧接口（已实现）

POST /ai/v1/conversations创建会话，GET同路径列出当前用户会话。
GET /ai/v1/conversations/{id}/messages读取当前用户历史；
POST同路径接收message、requestId并返回SSE流。
Authorization只承载代理凭证，会话归属由Java验证所得用户决定。
当前事件为start、context、delta、error、done；M4已增加tool_started与tool_result。
详情见M2-implementation.md，机器可读定义见fastapi-contract.openapi.json。

## M3 个性化与 RAG（已实现）

新增 GET /internal/ai/v1/personalization-status 和 /personalization-context，
沿用代理凭证和服务密钥双重认证，响应禁止缓存。默认仅返回 enabled:false/revision；
用户明确保存授权后，context 才返回健康白名单，不含身份联系方式。
新增 USER 接口 PUT /api/user/profile/details 同事务保存档案、授权与版本；
其完整请求/响应、撤回语义、SSE context 事件和知识引用字段见 M3-implementation.md。

## M4.1 只读工具调用（已实现）

Python 注册 search_medicines、get_medicine、get_my_order，模型仅通过原生 tool_calls 选择。
全部使用现有 AGENT_READ + 服务密钥，不新增写权限。
商品搜索增加 limit（Java 默认10、范围1–20），按商品ID稳定升序；
Python 工具默认5、最多10。详情ID必须为正数，订单号限定1–64位字母数字、下划线、短横线。
SSE 新增 tool_started、tool_result；历史 GET 返回 toolEvents。
结果卡片是带查询时间的快照，历史恢复与回放不重新查询业务接口。
完整事件、调用上限、错误和模型模板部署见 M4.1-implementation.md。

## M4.2 订单准备授权与草稿（已实现）

新增 AGENT_ORDER_PREPARE，仅能读取自身订单准备绑定和创建该绑定的未付款草稿。
不能访问普通 USER 接口、确认或支付，也不能代替 AGENT_READ。
USER 通过 POST /api/auth/order-agent-token 明确提交商品数量，最长授权300秒；
DELETE 同路径撤销。Java 签发固定请求键，商品顺序规范化后精确绑定。
内部 GET /internal/ai/v1/order-preparation 返回用户、商品、请求键与期限；
POST /internal/ai/v1/order-drafts 携带 Idempotency-Key，只能准备/恢复该草稿。
USER 使用 /api/order-drafts、/{id}、/{id}/confirm、/{id}/cancel 核对、恢复和确认/取消。
FastAPI 消息新增 purchaseIntent，并要求独立 X-Order-Agent-Token 请求头；
主 Authorization 仍为 AGENT_READ，两者用户必须一致，凭证不进入模型或会话存储。
只有本轮明确商品授权时才提供 prepare_order_draft 工具；模型不能确认或支付。
商品资格、金额、价格、库存与版本均由 Java 校验，草稿不扣款、不减库存。
CONFIRMED 不是 PAID。收货字段仅走 Java USER 接口，内部和模型视图不返回。
完整参数、状态和幂等/撤销边界见 M4.2-implementation.md，机器定义已更新到4.2.0。

## 购买清单交互修复

新增只读 propose_purchase 工具：从本轮真实商品查询与当前消息提取商品数量，
以 tool_result.result.proposal 返回待核对清单，不签发授权、不创建草稿。
未审核商品也可进入选择并保留明确数量，但准备接口继续受 SALE_NOT_ALLOWED 门禁控制。
未指定数量保留null，多规格要求用户选择；已授权阶段不再提供预览工具。
数量校验、前端行为与真实回归证据见 purchase-selection-fix.md。

## M4.3 验收审查补充

Java 契约版本4.3.0，FastAPI路径和消息请求保持兼容。
DELETE /api/auth/order-agent-token 增加可选 requestKey 查询参数：
省略时撤销当前用户全部准备授权；提供合法 UUID 时只撤销当前用户的对应授权，
不存在或属于他人的请求键不泄露存在性，返回统一成功；格式无效返回400，绝不退化为全部撤销。
已保存草稿继续保留。仅 USER 可调用，代理角色不能调用。

浏览器若在准备授权返回前撤回、换会话或离开页面，会丢弃迟到响应，
使用发起时的 USER 凭证和迟到授权的 requestKey 定向清理；不会使用新账号的凭证，
不会误撤销随后新建的准备授权，也不会向 AI 继续发送草稿请求。
已退出的原会话返回401视为原授权已随会话失效，不触发新账号退出。

tool_started/tool_result 可增加 invocationSource=runtime_grounded，表示**服务端只读清单恢复**。
该路径只在本轮真实目录查询后、原文所有数量/完整商品名均能对应时运行；
单一明确名称未给数量时保留null。它不是模型原生调用，不签发授权、不创建草稿，
评测分别统计 nativeProposalCall 与 runtimeProposalFallback。
多规格未确定时由目录结果确定性提示选择，禁止擅自拆分数量。
只查询、不要购买等消息不触发运行时购买提醒。

历史恢复填回原结构化数量但不自动恢复选择或授权。
完整演示、重建、清理和边界说明见 M4.3-operations.md；证据见 M4.3-validation.md。

## M5.1-A 支付契约设计冻结（历史设计）

原始增量设计契约已归档为archive/m51-payment-design.openapi.json（5.1.0-design.1）。
USER独占草稿checkout、私有支付订单、支付密码验证、授权签发/撤销、pay与close。
AGENT_READ、AGENT_ORDER_PREPARE、Python服务与LLM均不得调用上述USER写流程，
不得持有X-Payment-Authorization，也不新增支付工具或转发支付密码。
旧内部订单摘要维持字段白名单；新支付状态接入后仍禁止返回收货与授权凭证。
具体状态、幂等、权限及迁移边界见M5.1-A-design.md。

## M5.1-B Java支付后端（已实现，按环境启用）

支付机器契约m51-payment.openapi.json更新为5.1.0，六个操作标记为IMPLEMENTED_BACKEND_FEATURE_GATED。
Java/Python机器契约同步更新为5.1.0，4.3版本保留在archive/java-python-contract-4.3.openapi.json。
FastAPI接口和Python工具权限不变，不新增付款、验证密码或签发支付授权工具。

payments.enabled=false保持原业务接口；true时草稿checkout创建待支付订单，旧POST /api/orders返回409。
模型get_my_order继续只读且按用户隔离，字段仍为orderId/status/totalPrice/currency/items：
启用支付时status为PENDING_PAYMENT/PAID/CLOSED/LEGACY_UNVERIFIED，金额和单价为两位小数字符串；
关闭时保持原业务状态及JSON数值。机器契约明确支持两种模式，不能把completed推断为新流程PAID。
模型摘要不包含收货信息、支付授权、支付密码、余额、请求键或流水编号。
USER私有订单查询支持paymentRequestKey恢复已提交结果；恢复查询不发起付款。

仅18080/18000/13000隔离演示栈按迁移证明启用；正常8080/8000/3000保持关闭。
实现、重现命令、事务边界和验证证据见M5.1-B-implementation.md。

## M5.1-C 独立付款交互（已实现，按环境启用）

未增加模型工具或Java/Python业务接口，5.1.0请求与响应保持兼容。
Vue新增/payment/:orderId与/payments；CONFIRMED草稿可进入待支付订单，验证密码和提交付款分为两次明确操作。
密码与授权仅存内存；sessionStorage仅保存按用户/订单分隔的请求键、版本和已确认回滚重试标记。
UNKNOWN或网络中断仅GET恢复，不自动重新验证、换键或再次扣款；REGISTERED不代表已确认回滚。
授权迟到、离页和切号使用原USER会话、订单与authorizationId定向撤销，不借用新账号身份。
VITE_PAYMENTS_ENABLED由本机启动器直接继承已校验的后端支付开关，默认关闭。
正常环境仍为旧业务流程；隔离演示环境同步开放新UI和后端，旧购药提交入口显示草稿流程指引。
具体状态、浏览器边界和检验证据见M5.1-C-implementation.md。

## M5.1-D 综合故障验收与恢复补充

支付契约更新为5.1.1；六个USER操作、金额字符串、参数和权限保持兼容，Java/Python摘要契约仍为5.1.0。
Java每15秒扫描一次超过120秒仍REGISTERED的PAY请求，每批最多50条，按用户→请求→订单→授权的锁顺序核查。
已付款只修复请求元数据为SUCCEEDED，不重复记账；未结算请求提交REJECTED/PAYMENT_ATTEMPT_EXPIRED，撤销旧授权。
原付款持有用户锁时核查等待；核查先提交拒绝时，迟到付款因REJECTED检查停止，不能继续扣款。
恢复任务不签发授权、不创建订单、不修改余额/库存/积分/财务流水。支付关闭时任务直接返回，不读取不存在的新表。
客户端仍仅GET恢复UNKNOWN，确认旧请求已结束后，才允许用户重新验证并明确提交新请求。
故障代理仅为本机演示验收工具，正式Java接口没有新增故障开关或管理后门；验收结束后已停止代理并撤销路由。
实现和完整证据见M5.1-D-implementation.md、M5.1-D-validation.md。

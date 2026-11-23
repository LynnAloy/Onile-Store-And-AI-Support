# M2：FastAPI模型对话迁移

后续状态：2026-10-27已完成真实环境联调，见local-integration-2026-10-27.md。
下文“验证边界”保留M2开发阶段记录；当前实际验证结果以联调报告为准。

本次完成M2；任务拆分见M2-plan.md。
Java仍承担用户与全部交易业务。Python新增的是AI会话服务，没有替换Java业务数据库。

## 已实现

- FastAPI独立服务、环境校验、健康检查、统一JSON错误及机器可读OpenAPI。
- 浏览器向Java换取AGENT_READ短期凭证，Python通过Java内部me接口校验用户。
- Python不接收前端指定身份、模型名称或历史消息；不读取健康档案、钱包或收货信息。
- Python独立SQLite仅保存AI会话与轮次，支持按用户列出与恢复会话。
- Ollama适配层使用 /api/chat 流式NDJSON；只转发公开content，不展示thinking字段。
- 历史上下文只使用成功完成的轮次，保持user/assistant成对，限制轮数和字符数。
- 请求幂等、单会话生成互斥、单用户最多2个活跃生成。
- SSE心跳、增量、完成和错误，模型连接/总超时、响应格式校验、长度限制。
- 连接取消保存部分回答并标为interrupted；失败标为failed，不混入后续成功上下文。
- 完成回答先落库再发done；重复请求回放结果，不再次调用模型。
- 生成期间每约10秒重新校验Java授权；失效或身份服务不可用时停止生成。
- 进程异常留下的processing轮次在租约超时后视为interrupted，新请求可恢复。
- Vue支持新建、选择、恢复会话，停止生成、刷新历史、错误与未完成状态。
- 代理凭证仅在组件客户端内存缓存，401最多续取一次；退出或切换账号时清除。
- 移除Java的Spring AI、WebFlux依赖、MessageController及模型配置；旧/stream和/message拒绝访问。

## 路由与请求

| 方法 | 路径 | 含义 |
|---|---|---|
| GET | /ai/health | 进程存活 |
| POST | /ai/v1/conversations | 创建当前用户会话 |
| GET | /ai/v1/conversations | 最近100个当前用户会话 |
| GET | /ai/v1/conversations/{id}/messages | 最近100个轮次，按时间顺序 |
| POST | /ai/v1/conversations/{id}/messages | 流式生成 |

业务接口的Authorization使用Java短期代理凭证。Java USER凭证不发送给AI服务。
创建请求：{"title":"新对话"}。title可省略。
生成请求：{"requestId":"UUID","message":"用户问题"}；不允许额外字段。
会话ID和请求ID采用UUID。message最多4000字符，JSON请求体最多32768字节。

用户隔离：无权访问的会话统一404，列出会话只返回当前用户所有的数据。
同一个requestId：
- 相同内容且completed：回放已保存回答；
- 相同内容仍processing：409 TURN_IN_PROGRESS；
- 不同内容：409 IDEMPOTENCY_CONFLICT；
- 原请求failed/interrupted：409 TURN_NOT_REPLAYABLE，用户明确重试应使用新requestId。

同一会话同时生成返回409 CONVERSATION_BUSY；
同用户已有两个活跃生成返回429 TOO_MANY_ACTIVE_TURNS。

## SSE协议

Content-Type: text/event-stream；Cache-Control: no-store；X-Accel-Buffering: no。
每个事件使用event字段和JSON data，空行分隔：

```text
event: start
data: {"conversationId":"...","requestId":"...","replayed":false}

event: delta
data: {"text":"回答片段"}

event: done
data: {"requestId":"...","status":"completed","replayed":false}
```

失败使用event:error，data为{"code":"MODEL_TIMEOUT","message":"..."}。
error为终止事件，不能据此展示“回答完成”；连接直接断开且没有done也不视为成功。
部分文字保留并显示失败/中断状态。前端按普通文本渲染，不插入模型返回的HTML。
空闲等待时最多约10秒发送一次注释心跳，非每个模型token都写数据库。

流开始前的错误使用HTTP状态和JSON；一旦响应流开始，模型错误通过HTTP200中的error事件返回。
客户端不能只检查HTTP200判断回答成功。

## 运行与部署

1. 按M1说明迁移MySQL，配置数据库凭据并启动Java8080。
2. 在Java和Python各自终端设置相同的AI_SERVICE_KEY；不能放入VITE_变量。
3. 启动Ollama并准备目标模型。Java不再需要任何模型配置。
4. 按python-ai/README.md启动FastAPI8000。
5. 启动Vue3000。生产入口需将 /api 转发Java，/ai 转发FastAPI，
   关闭SSE代理缓冲并将代理读取超时设置为至少260秒。
6. 所有数据接口均依赖Java；Python不能在身份服务故障时降级为匿名会话。
7. Python会话库不需要修改现有MySQL表；该SQLite文件是独立AI数据，不是业务数据源。

模型默认读取超时30秒，总时长120秒；总时长可配置至最多240秒。
生成租约为总时长加30秒。进程异常后，旧请求在租约结束后可恢复。
客户端停止后，服务器会取消模型任务；不同ASGI服务实现可能在下一次断开检测/写入时感知，
检测间隔约10秒，期间新请求可能短暂收到会话繁忙提示。

## 验证边界

自动化使用临时SQLite、Java HTTP模拟与Ollama NDJSON模拟验证Python服务，
Java代理接口另由真实Spring/H2业务测试验证。未宣称已在真实MySQL、Ollama和浏览器中完成端到端联调。
M1数据库迁移仍未自动对现有MySQL执行。

部署前需要真实环境验收：登录、换取代理授权、新建对话、多轮输出、取消、
退出后授权失效、两个用户会话隔离和已安装模型的上下文能力。
AI不会在M2执行药品查询、下单或支付。临床知识、RAG评测和工具调用属于后续阶段。

协议实现参考：[Ollama chat API](https://github.com/ollama/ollama/blob/main/docs/api.md)
及[FastAPI StreamingResponse](https://fastapi.tiangolo.com/advanced/custom-response/)。

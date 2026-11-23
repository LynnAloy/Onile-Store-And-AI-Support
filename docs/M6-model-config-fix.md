# 清单抽屉修复与管理员模型配置

清单无法打开的原因是抽屉内引用了仅存在于消息循环中的 message，打开抽屉时渲染失败。已移除该越界引用，数量控件沿用 authorizing 状态。

管理员导航新增“模型配置”：GET/PUT /api/admin/ai-config。普通 USER、代理令牌不能修改；管理员保存必须提供 expectedVersion、model、endpoint。原子替换各环境受保护目录下的 model-config.json，记录更新时间与操作者，不保存到前端存储。服务重启后仍保留配置。远程 endpoint 要求 HTTPS，本机可使用 HTTP，不允许 URL 内嵌凭据或查询参数。

当前支持 Ollama /api/chat 协议，endpoint 为服务根地址，例如 http://127.0.0.1:11434，不是完整 /api/chat 路径；模型需支持工具调用。现已支持选择 OpenAI 兼容协议，按基础地址拼接 /chat/completions，也接受完整 /chat/completions 地址。API Key 可在页面设置，GET 不回传明文；空值同目标保留，更换目标或协议不沿用，支持主动清除。密钥保存在受保护服务端配置文件中。

Python 每次模型调用读取原子配置快照，已有正在生成的调用继续原配置，新调用使用新配置。更换目标时不转发原环境的模型 API key。RAG 嵌入模型地址保持独立。配置保存不会自动发送测试对话；配置不可读时明确失败，不静默退回其他服务。

回归：Python 85 项、前端 64 项及生产构建；Java ModelConfigTests 验证原子保存、旧版本拒绝、URL 校验，CommerceBusinessTests 回归管理员和资金边界。


## OpenAI 兼容协议补充

DeepSeek 使用 OpenAI 兼容协议，基础地址可填 https://api.deepseek.com，模型名称填写服务商实际可用的模型ID，API Key 只在管理员表单输入，不发送到聊天。标准 /v1 服务则填对应 https://.../v1。兼容接口通过 SSE 接收回答，按 tool_calls.index 合并分片参数，转为统一工具协议；工具历史中补齐 tool_call_id 并把 arguments 编码为 JSON 字符串。工具执行仍需原有结构校验和 Java 权限。异常或截断不静默回退。

当前适配 Chat Completions 非思考文本/工具模式，不承诺所有厂商专有思考模式、图片或 Responses API 兼容。RAG 嵌入服务仍单独使用本机 Ollama。

协议参考：
- https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events
- https://api-docs.deepseek.com/api/create-chat-completion/

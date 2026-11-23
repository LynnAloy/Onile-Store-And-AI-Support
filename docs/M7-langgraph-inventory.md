# LangGraph 库存与订单工具

聊天入口使用 LangGraph 的 Agent → 工具 → Agent 循环。模型收到工具 JSON Schema 后选择调用，工具节点校验参数和当前会话授权，将 Java 结果作为工具消息交还模型。参考项目的 Agent 仅作为架构参考。

- `list_inventory` 按 ID 游标读取 Java 的实时目录，每页最多 20 项，页面默认折叠原始库存卡。按症状查找时，模型依据药名和常见用途，用 `analyze_inventory` 对本页每个 ID 提交布尔值 `matchesNeed`。服务端核对 ID 覆盖范围并回填名称、库存、价格和草稿资格。匹配流程无需上传审核资料。
- `search_medicines` 与 `get_medicine` 查询指定名称或 ID。购买清单工具 `propose_purchase` 仅接受本轮查到的商品，并核对用户原文中的商品和数量。
- `prepare_order_draft` 仅在服务器已取得独立的商品和数量授权时出现在工具列表中。Java 按授权和幂等键写入未付款草稿，后续确认和付款由既有结账流程处理。

`deepseek-flash` 的 OpenAI 兼容接口要求工具循环带回调用 ID 和本轮工具调用对应的 `reasoning_content`。适配器只在当前请求的模型上下文中回传这些协议字段。

本地服务运行时，在项目根目录执行 `python scripts/langgraph_inventory_smoke.py`。脚本创建并清理独立验收账号，通过页面代理调用真实模型和 Java 目录。追加 `--draft` 会选择一个真实可售商品，授权生成未付款草稿，读回状态，取消验收草稿并复查库存。

使用 `python scripts/langgraph_inventory_smoke.py --score` 逐例验证库存列表、商品详情、缺失商品、用途匹配、多轮追问、购买数量及授权草稿。脚本从 Java 获取库存快照作为比对依据，并通过本人订单接口读回已创建的草稿。每条用例输出实际工具轨迹，只有通过率严格高于 90% 时才以成功状态退出。

# M3：健康档案授权与可追溯 RAG

实现日期：2026-10-27。保留 Java 业务栈；Python 负责模型、检索和对话编排。
当前交付是平台规则 RAG 和个性化上下文框架，不包含医学语料审核、AI 下单工具或第三方支付。

## 个人中心与授权

个人中心新增身高、体重、病史自由文本、过敏、用药、生活习惯和其他健康说明。
病史标签支持自定义输入。数值支持清空，身高 30–260 cm、体重 1–500 kg、最多一位小数；
这些是输入边界，不是临床判定标准。BMI 只作数学展示。

使用一个默认关闭的复选框：“同意将个人信息作为模型上下文以获得个性化建议”。
点击保存后才生效，不勾选也可普通对话。Java 保存健康档案和授权；
旧账户迁移默认不授权，不推断或自动补齐旧用户的同意。

模型上下文只允许年龄、性别、身高、体重、BMI 和健康描述。
姓名、生日、账号、邮箱、手机号、住址、余额和密码不在结构化字段白名单。
自由文本若由用户主动写入身份信息，仍属于其授权的原文内容，白名单不是自动脱敏器；
页面提示不填写身份编号或密码。健康资料标记为本人自述，不作诊断事实。

Python 不保存档案原文快照，不对档案调用 embedding，不把档案放进公共知识库。
聊天内容和模型回答可能包含用户主动提供或授权引用的信息，属于私有聊天记录；
撤回不自动删除历史记录，也不能追回已发给模型的数据。

## Java / Python 接口

外部新增 PUT /api/user/profile/details（USER 凭证），完整替换资料：

~~~json
{
  "basic": {
    "userId": "当前用户或省略",
    "nickname": "昵称",
    "age": 30,
    "medicalHistory": ["本人输入的病史标签"]
  },
  "health": {
    "heightCm": 180.0,
    "weightKg": 72.0,
    "medicalHistoryText": "本人自述",
    "allergiesText": "",
    "medicationsText": "",
    "lifestyleText": "",
    "healthNotes": "",
    "aiProfileConsent": false
  }
}
~~~

basic 沿用原 Profile 字段，但新接口为完整快照，省略的可选字段会清空；
health.aiProfileConsent 必填 Boolean。不要向此接口传余额、密码或授权版本号。
响应包含 saved、aiProfileConsent、profileContextVersion。
原 PUT /api/user/profile 继续是兼容的部分更新，不能通过它改变授权。
任何资料保存使版本递增；授权切换另写 profile_consent_events（同事务）。

内部新增两个 GET，均要求 AGENT_READ + X-AI-Service-Key，且 Cache-Control:no-store：

- /internal/ai/v1/personalization-status：仅 enabled 和 revision。
- /internal/ai/v1/personalization-context：未同意时仅 enabled:false/revision；
  已同意时增加 profile 白名单，空字段不传。

用户身份来自已验证的代理会话，不接收模型提供的用户身份。
Java 依旧管理药品、价格、库存、订单和钱包；代理权限不能扣款。

每轮绑定档案授权/版本和知识库版本。准备阶段、模型调用前、流式期间约每秒、
完成前重新验证；变化时中止并记录 failed，错误码 PERSONALIZATION_CHANGED 或 KNOWLEDGE_CHANGED。
轮询受 Java 请求超时影响，不能保证零延迟撤回，也无法撤回已经发出的 delta。
同一 requestId 在绑定改变后返回 409 CONTEXT_CHANGED，不能回放旧个性化答案。
后续上下文排除旧版本的个性化轮次与旧知识版本轮次；用户自己新发的聊天消息仍进入模型。
前端保存后也会取消本页进行中的生成，服务端检查覆盖其他标签页。

SSE 新增 context 事件，位于 start 后、delta 前，包含：
citations、retrieval、personalizationApplied、profileRevision、omittedHealthFields。
personalizationApplied 表示本轮绑定了授权，字段可能因预算整体省略；
省略时保留字段名供追踪，不截断过敏史或否定句。历史 GET 返回对应公开引用/授权版本元数据。

## RAG 实现

参考 Local_RAG_Advanced.ipynb 的父子切分、混合检索、RRF、多查询和 HyDE 思路，
未执行或导入其中的 Unreal 文档，也不删除其数据库或文件。

默认链路：

1. 运营者维护 manifest.json，包含稳定 ID、版本、来源、类型、审核人和审核日期。
2. 仅 approved 文档进入检索；pending/withdrawn 不可作为证据。
3. Markdown 分节，父块上限 1200 字符，子块 300、重叠 60；保留尾部文本，稳定父子 ID。
4. Ollama 原生 /api/embed，truncate:false；bge-m3 模型摘要和实际维数写入索引，
   校验非零、有限值并归一化。嵌入失败不截断原文重试。
5. 归一化向量精确余弦检索 + 中文双字词/英文词 BM25；按相似度降序；
   BM25 使用正 IDF 并要求至少两个不同匹配词。
6. RRF 融合、候选上限 8、按父块去重，最多返回 3 个父块，受总上下文预算再裁剪。
7. 将来源版本、父子 ID、片段随 [S1] 等引用提供给模型和界面。
   引用 ID 越界会使轮次失败；这不是医学事实核验或全文蕴含验证。

SQLite 存公开文档和 float32 向量，NumPy 精确检索，适合本机小规模毕业设计，
导入上限 10000 子块。该方案无需 Chroma 常驻服务，规模增长后应替换为向量数据库。
导入在事务外计算全部嵌入，成功后事务替换；失败保留旧索引，启动不清库。
模型摘要或维度不匹配时明确失败并要求重建。withdraw 即时增加知识版本，令在途回答失效。

可选扩展均默认关闭：

- sync --semantic：额外句向量计算以选择子块边界。
- RAG_QUERY_REWRITE=true：原问题 + 最多两个改写，原查询始终保留。
- RAG_HYDE=true：假设文段只影响向量召回，永远不作引用证据。
- RAG_LLM_RERANK=true：结构化 0–10 分的 LLM pointwise 相关性重排；
  它不是训练过的 Cross-Encoder；辅助调用失败回退原始融合并标注 fallbacks。

公共规则库不能包含个人档案。CLI 为可信运营者本地工具，无匿名上传或在线审核接口；
reviewer/date 为维护者声明，尚未实现独立审核身份签署。
修改文档需更新 manifest 版本再 sync；withdraw 后若重新同步仍标 approved 的旧清单，
会再次发布，应先把清单也标 withdrawn。生产化应增加审核角色、发布审批和不可变版本存档。

## 本机管理命令

在项目根目录（脚本读取被忽略的 .env.local，不打印密钥）：

~~~powershell
python scripts/local_stack.py stop
python scripts/local_stack.py prepare
# 在 Java 项目目录执行 mvn package -B -ntp
python scripts/run_knowledge.py sync "<项目绝对路径>/python-ai/knowledge/manifest.json"
python scripts/run_knowledge.py status
python scripts/run_knowledge.py search "支付密码错误五次会怎样"
python scripts/run_knowledge.py evaluate "<项目绝对路径>/python-ai/knowledge/evaluation.json" --output "<项目绝对路径>/.local-run/rag-evaluation.json"
python scripts/local_stack.py start
python -u scripts/m3_live_smoke.py
~~~

prepare 先备份现有数据库，再按列检测执行增量迁移；SQL 手工部署入口为
V002_personalization.sql，勿重复直接执行其 ALTER。
本机服务脚本共享 .local-run/knowledge.db；独立启动默认 python-ai/data/knowledge.db，
请显式设置 KNOWLEDGE_DATABASE_PATH，避免导入和服务读取不同数据库。
独立 CLI：在 python-ai 目录运行 python -m app.knowledge_cli --help。

目前仅收录四份平台规则：档案授权、演示钱包、订单校验、AI 功能边界。
未收录药品说明书或医学知识。平台规则不能支持临床用药结论，模型不可据此自动购药。

## 验证

Java 34 项、Python 44 项、前端 18 项、运行脚本 8 项，共 104 项通过；
Java package、Python compileall 和 Vite build 通过。
前端包体积警告仍存在，未作为功能失败。

真实 bge-m3:latest 索引：4 文档、5 父块、5 子块、1024 维。
固定评估集 9 条：8 条规则命中、1 条无关问题不召回；
HitRate@3=1.0，MRR=1.0。样本很小且只覆盖平台规则，不代表医疗检索质量。
评估不是 RAGAS，不以大模型自评分冒充召回指标。
真实环境新功能联调 6 组通过，覆盖默认关闭、权限和数值校验、内部白名单、
真实模型个性化、规则引用、生成中撤回、撤回后普通对话及授权审计。
原有登录、钱包支付、并发库存、会话记忆等 8 组真实回归通过。
结果分别见 .local-run/m3-live-results.json 与 .local-run/live-results.json；
报告只记录合成测试结果，不包含用户档案或凭证。所有测试夹具按本次账号范围清理。


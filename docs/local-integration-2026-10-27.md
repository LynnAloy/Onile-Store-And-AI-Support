# 实际环境联调报告（2026-10-27）

状态：已完成本机实际环境联调。Vue → Java/MySQL、Vue → FastAPI → Java授权/Ollama 均通过真实HTTP验证。

## 当前服务

| 服务 | 地址/版本 | 状态 |
|---|---|---|
| Vue/Vite | http://127.0.0.1:3000/main | 运行中，真实浏览器入口已确认 |
| Java | http://127.0.0.1:8080 | 运行中，仅监听回环地址 |
| FastAPI | http://127.0.0.1:8000 | 运行中，仅监听回环地址 |
| MySQL | 3306，版本9.7.0，服务MySQL1224 | 运行中 |
| Ollama | 127.0.0.1:11434，版本0.21.2 | 运行中 |
| 模型 | Qwen2.5:latest | 使用现有本地模型，未下载新模型 |

本机联调读取超时60秒、总时长180秒、生成温度0。
应用默认温度0.2，可通过MODEL_TEMPERATURE配置，范围0至1。
首次独立冷启动生成约37.55秒；最终预热采样首段0.44秒，
首轮总时长0.91秒，第二轮0.28秒。
这些是本次样本记录，不是持续性能基准。

## 真实数据库处理

目标DeepSeekDoc在本机原先不存在，认证成功后核对未发现名称匹配的项目库。
本次新建该独立项目库，使用原MySqlDSD.sql的7张表结构和3条实训药品演示数据。
没有导入原SQL中的旧用户、联系方式或历史订单，没有修改其他数据库。

迁移前已完成mysqldump备份：
.local-run/backups/DeepSeekDoc-20261027-090028-827941.sql

已执行M1结构升级：
- users.password、users.walletPassword均为VARCHAR(255)；
- 新增auth_sessions、security_attempts、checkout_requests。
- 新库原有用户数为0，本次没有旧明文账号需要转换。

数据库凭据和随机服务密钥保存在Git忽略的.env.local。
.env.local及.local-run的访问权限限制为当前用户与SYSTEM。
密码和token未写入公开报告或联调输出。

## 8组真实检查

1. Vue页面、开发代理、匿名访问拒绝。
2. 真实MySQL注册登录、健康档案JSON往返与用户隔离。
3. 支付密码错误拒绝、演示钱包扣款、订单幂等与订单隔离。
4. 真实MySQL最后一件库存并发购买：只成功一单、只发生一次相应扣款、不超卖。
5. Java/Python双重授权与会话归属校验；完整USER凭证不能冒充代理。
6. 真实Ollama流式生成、多轮项目代号记忆、历史持久化与幂等回放。
7. 经真实Vue代理断开请求后，模型生成停止，轮次标记interrupted。
8. 退出登录后用户会话与代理授权均失效，其他用户不受影响。

最终真实检查时间：2026-10-27 09:24:11。
完整机器结果保存在.local-run/live-results.json。

支付检查使用本次独有的虚构商品和演示充值卡，只改变项目内部测试账本；
没有外部支付通道、真实资金或药品履约。

## 联调中修复的问题

- Ollama系统环境指向空模型目录：仅为本次服务进程设置用户已有模型目录，未改系统全局设置。
- Windows日志编码导致中文就绪字符串无法识别：改用LOCAL_BACKEND_READY，并修正前端端口提示。
- Oracle javapath启动器留下实际JDK子进程并锁住JAR：启动脚本改用JAVA_HOME/bin/java.exe。
- 本机127.0.0.1前端Origin被CORS拒绝：明确允许localhost与127.0.0.1两个本机来源；
  非法来源仍被拒绝，并加入回归测试。
- 代理目标统一为127.0.0.1，避免IPv4/IPv6 localhost解析差异。
- 真实模型曾一次未正确回忆随机合成代号；独立诊断核对历史，并增加显式温度配置。
  使用本机联调温度0后，最终完整用例通过。模型回答质量评测留待M3固定评测集。
- 新增安全初始化、迁移前备份、目标指纹检查、模型可用性检查及限于本项目的进程管理脚本。

## 清理与保留

本次专用命名空间中的临时用户、失败计数、商品、充值卡和AI会话均为0残留。
原3条演示商品的ID、价格和库存与初始值一致。
最终复核中有用户新产生的正常账号/会话，这些数据均保留，未按全表行数清空。
详细只读复核结果保存在.local-run/cleanup-results.json。

## 自动化回归

| 检查 | 结果 |
|---|---|
| Java编译、业务及新增CORS回归 | 30项通过 |
| Python对话与生成参数回归 | 26项通过 |
| 前端SSE与代理授权测试 | 15项通过 |
| 本地部署脚本安全检查 | 8项通过 |
| Python语法、Java JAR打包、前端生产构建 | 通过 |

共79项自动化测试通过，另有8组真实链路检查。
前端保留现有大包体积提示，构建成功。

## 启停与复现

项目根目录执行：

```powershell
python scripts/local_stack.py stop
python scripts/local_stack.py start
python scripts/live_smoke.py
```

stop仅停止本项目记录且核验归属的Java、FastAPI、Vue，不停止MySQL或Ollama。
重新构建JAR前先stop，避免Windows文件锁。
prepare用于数据库检查、备份和必要的结构迁移；
initialize仅用于目标库不存在的首次初始化，拒绝覆写现有库。

如果Ollama未运行，请在独立PowerShell终端设置本次进程的模型目录后启动：

```powershell
$env:OLLAMA_MODELS = Join-Path $env:USERPROFILE '.ollama/models'
$env:OLLAMA_HOST = '127.0.0.1:11434'
ollama serve
```

更多命令见scripts/README.md。所有服务目前保留运行，仅供本机访问。

## 验证范围

本次覆盖真实跨服务HTTP链路和浏览器入口；登录后逐项浏览器点击流程未另行录制。
RAG、药品工具调用、AI待确认订单及第三方支付仍按后续里程碑推进。

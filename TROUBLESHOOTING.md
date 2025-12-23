# quantTrader 故障排查指南

## 🔐 获取 API Token

### 方法 1: 从前端界面获取（推荐）

1. **登录** quantFinance 前端
2. 点击右上角头像旁的 **「API Token」** 按钮
3. 点击 **「生成 Token」** 或 **「重新生成」**
4. **立即复制** 显示的 Token（30秒后自动隐藏）
5. 保存到 quantTrader 的 `config.json` 文件

**特点：**
- ✅ Token 有效期：7 天
- ✅ 可随时重新生成（旧 Token 仍有效直到过期）
- ✅ 界面友好，一键复制
- ⚠️  Token 只显示一次，请妥善保存

### 方法 2: 从登录响应获取

登录成功后，响应中包含 `access_token` 字段：

```bash
curl -X POST http://your-backend:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "your_username",
    "password": "your_password"
  }'
```

响应：
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "user": { ... }
}
```

---

## 问题：Trader 连接但不执行交易

### 快速诊断步骤

#### 1️⃣ 运行诊断脚本（推荐）

```bash
# 基础诊断（检查 API 连接）
python diagnose_trader.py --config config.json

# 完整诊断（包含 MongoDB 检查）
python diagnose_trader.py \
  --config config.json \
  --mongo-uri "mongodb://localhost:27017/finance" \
  --user-id "your_user_id"
```

诊断脚本会自动检查：
- ✅ 配置文件是否正确
- ✅ API 连接是否正常
- ✅ Token 是否有效
- ✅ 是否有符合条件的信号
- ✅ 信号字段是否完整

---

#### 2️⃣ 启用详细日志

修改 `config.json`：

```json
{
  "api_base_url": "http://your-backend:8000/api",
  "api_token": "your_token",
  "poll_interval": 1.0,
  "log_level": "DEBUG"  ← 改为 DEBUG
}
```

重启 Trader：

```bash
python -m quant_trader.cli --config config.json
```

**期望看到的日志：**

```
INFO - quantTrader started. API=http://...
INFO - Poll interval: 1.0 seconds
INFO - Broker type: SimulatedBroker
DEBUG - Polling for signals...
DEBUG - GET http://.../trader/signals with params={'limit': 50, ...}
DEBUG - API returned 2 signals
INFO - Fetched 2 pending signals
INFO - Processing signal: order_id=TEST-001, symbol=000858.SZ, action=BUY, size=100
DEBUG - Placing order to broker: TEST-001
INFO - Order placed successfully: order_id=TEST-001, broker_order_id=SIM-...
INFO - ✓ Execution reported successfully: order_id=TEST-001, symbol=000858.SZ, action=BUY
```

---

#### 3️⃣ 检查信号必需字段

Backend 的 `/api/trader/signals` 端点会过滤信号，**必须同时满足**：

| 字段 | 必需值 | 说明 |
|------|--------|------|
| `user_id` | 匹配 token | Backend 自动验证 |
| `is_executable` | `true` | 必须显式设置 |
| `mode` | `"live"` | 必须是实盘模式 |
| `status` | `"pending"` 或 `"retry_pending"` | 待执行状态 |

**检查现有信号：**

```bash
# 连接 MongoDB
mongo mongodb://localhost:27017/finance

# 查看信号
db.trade_signals.find({
  user_id: "your_user_id"
}).pretty()

# 检查是否缺少字段
db.trade_signals.find({
  user_id: "your_user_id",
  $or: [
    { is_executable: { $ne: true } },
    { mode: { $ne: "live" } }
  ]
})
```

**修复缺少字段的信号：**

```bash
# 将所有 pending 信号设置为可执行
db.trade_signals.updateMany(
  {
    user_id: "your_user_id",
    status: { $in: ["pending", "retry_pending"] }
  },
  {
    $set: {
      is_executable: true,
      mode: "live"
    }
  }
)
```

---

#### 4️⃣ 测试插入信号

使用测试脚本插入带所有字段的信号：

```bash
export MONGO_URI="mongodb://localhost:27017/finance"
export MONGO_USER_ID="your_user_id"

python insert_test_signal.py \
  --symbol 000858.SZ \
  --action BUY \
  --size 100 \
  --price 15.5 \
  --strategy "test_strategy"
```

测试脚本会自动设置：
- ✅ `is_executable: true`
- ✅ `mode: "live"`
- ✅ `status: "pending"`

---

#### 5️⃣ 常见问题排查

##### 问题 1: Token 过期

**症状：**
```
ERROR - HTTP error fetching signals: 401 - {"detail":"Could not validate credentials"}
```

**解决：**
1. 重新登录获取新 token
2. 检查 backend `.env` 中的 `JWT_ACCESS_EXPIRE_MINUTES` 设置
3. 建议设置为 7 天：`JWT_ACCESS_EXPIRE_MINUTES=10080`

---

##### 问题 2: API 地址错误

**症状：**
```
ERROR - Failed to fetch signals: ConnectionError(...)
```

**检查：**
1. Backend 是否在运行？`curl http://your-backend:8000/docs`
2. URL 是否正确？注意 `http://` vs `https://`
3. 端口是否正确？默认 8000
4. 网络是否连通？`ping your-backend`

---

##### 问题 3: 信号被其他 Trader 处理

**症状：**
- 日志显示 `No pending signals found`
- 但数据库中有 pending 信号

**检查：**
1. 是否有多个 Trader 在运行？
2. 信号的 `user_id` 是否匹配？
3. 信号是否已经被处理（status 改变）？

---

##### 问题 4: Broker 抛出异常

**症状：**
```
ERROR - ✗ Failed to process signal TEST-001: [错误信息]
INFO - Marked signal as retry_pending: TEST-001
```

**排查：**
1. 检查 Broker 配置是否正确
2. miniQMT: 检查 `xt_path` 和 `account_id`
3. 查看完整异常堆栈（`exc_info=True`）

---

#### 6️⃣ 验证完整流程

**手动验证步骤：**

1. **插入测试信号**
   ```bash
   python insert_test_signal.py --symbol 000858.SZ --action BUY --size 100
   ```

2. **观察 Trader 日志**
   应该在 1-2 秒内看到处理日志

3. **检查信号状态**
   ```bash
   mongo finance --eval "db.trade_signals.find({order_id: /TEST/}).pretty()"
   ```
   
   状态应该从 `pending` → `submitted` → `filled`

4. **检查执行记录**
   ```bash
   mongo finance --eval "db.trade_executions.find({order_id: /TEST/}).pretty()"
   ```

---

## 日志级别说明

| 级别 | 输出内容 |
|------|---------|
| **ERROR** | 只显示错误 |
| **WARNING** | 错误 + 警告 |
| **INFO** | 常规运行信息（推荐） |
| **DEBUG** | 详细调试信息（排查问题时使用） |

---

## 联系支持

如果以上步骤都无法解决问题，请提供：

1. **配置文件**（隐藏 token）
2. **完整日志输出**（log_level=DEBUG）
3. **诊断脚本输出**
4. **示例信号数据**（MongoDB 查询结果）

---

## 更新日志

- 2024-12-22: 添加详细调试日志
- 2024-12-22: 创建诊断脚本
- 2024-12-22: 增强错误处理

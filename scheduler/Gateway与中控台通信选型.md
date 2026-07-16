# Gateway ↔ 中控台通信选型：为什么用 NATS 而不是 gRPC

> 2026-07-08

## 结论

**NATS request-reply**。和当前 Scheduler 调用完全相同的模式，0 新增依赖。

## 当前架构

```
                    ┌─────────────┐
                    │   Gateway   │
                    └──┬───┬───┬──┘
          NATS         │   │   │        NATS
    ┌──────────────────┘   │   └──────────────────┐
    ▼                      ▼                      ▼
┌────────┐          ┌───────────┐          ┌──────────┐
│  Edge  │          │ Scheduler │          │  中控台   │
│ Agent  │          │ (CP-SAT)  │          │ (motor)  │
└────────┘          └───────────┘          └──────────┘
 设备模拟器            求解服务              小车调度
```

Gateway 和 Edge Agent、Scheduler 都走 NATS。中控台加入后，如果走 gRPC，Gateway 就有了两套通信协议。

## 逐一对比

### 1. 部署复杂度

| | NATS | gRPC |
|---|------|------|
| 端口 | 0（复用 NATS 连接） | 1 个新端口 |
| 服务发现 | 0（NATS subject 即地址） | 需要注册中心或硬编码 IP |
| 健康检查 | 0（NATS 连接断开即不可达） | 需要 health check |
| TLS/mTLS | 0（复用 NATS 已有的） | 需要单独配置 |
| Docker Compose | 不加任何新容器 | 加端口映射 |

### 2. 调用模式

中控台调度小车是**长耗时异步操作**（5s+），不是瞬时 RPC。

```
Gateway 发: "从 A 到 B"
中控台:    调度小车 → 等待到达 → 回复"到了"
Gateway:   收到回复，推进下一个子步骤
```

| | NATS request-reply | gRPC unary |
|---|:---:|:---:|
| 超时控制 | `Request(subj, payload, 10s)` 一行 | deadline 配置 |
| 请求排队 | JetStream queue group 自带 | 需要自己实现 |
| 取消请求 | `msg.Respond(nil)` 或超时 | context cancel |
| 进度通知 | 中控台 pub 进度消息 | 需要 streaming RPC |

### 3. 与现有代码的复用

NATS 方案：

```go
// 和调用 Scheduler 完全相同的模式
reply, err := natsBus.Request("bioflow.*.*.*.motor.control.move", payload, 10*time.Second)
```

gRPC 方案需要：

```protobuf
// 新 proto 文件
service MotorController {
    rpc Move(MoveRequest) returns (MoveResponse);
}
// 新生成代码 + 新 client 封装 + 新连接管理 + 新错误处理
```

**NATS 方案新增代码量：~5 行。gRPC 方案：~100 行 + proto 文件 + 编译步骤。**

### 4. 运维

| | NATS | gRPC |
|---|------|------|
| 排查问题 | `nats sub "bioflow.*.*.*.motor.>"` 一行看所有消息 | 需要抓包或开 tracing |
| 重放/调试 | NATS 自带 JetStream 回放 | 没有 |
| 中控台挂了 | NATS 消息不丢（JetStream），重启后继续 | gRPC 连接断开，请求丢失 |
| 灰度 | subject 路由 | 需要单独网关 |

### 5. 中控台侧实现

NATS 方案：中控台只是一个 NATS 客户端，订阅 subject，收到请求后调度小车，完成后 `msg.Respond`。和写一个 Edge Agent 一样简单。

gRPC 方案：中控台需要起 gRPC server，管理端口，写 proto，生成代码。

## 什么时候该用 gRPC

- 强类型接口契约（几百个 RPC 方法需要 IDL 管理）
- 需要 client/server streaming（比如大文件流式传输）
- 已有 gRPC 基础设施（服务网格、负载均衡）

**中控台一个 `Move` 方法，这些都用不上。**

## 总结

| 维度 | NATS | gRPC |
|------|:---:|:---:|
| 新依赖 | 0 | protoc + proto 文件 + grpc-go |
| 新端口 | 0 | 1 |
| 服务发现 | 0 | 需要 |
| 消息持久化 | JetStream 自带 | 无 |
| 代码量 | ~5 行 | ~100 行 |
| 运维工具 | `nats` CLI | grpcurl |
| 和现有架构一致性 | ✅ | ❌ |

**选 NATS 不是因为 gRPC 不行，是因为不值得为 1 个方法引入第二套协议。**

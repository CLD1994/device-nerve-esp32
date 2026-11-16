# 文档导航

本目录按“当前使用、实现参考、可选实验、历史证据”分层。当前指南以本分支源码为依据；历史结果只证明对应版本和条件，不是当前版本的完整验收。

## 当前使用与协议

| 需要做什么 | 入口 |
|---|---|
| 接线、供电、接口选择 | [硬件与供电](hardware.md) |
| 构建、烧录、建立串口连接 | [入门](getting-started.md) |
| 完整标定或重启后确认左参考 | [标定](calibration.md) |
| 编写上位机、查命令与错误 | [通信协议](protocol.md) |
| 核对速度、加速度、持久化与频率上限 | [运动默认值](motion-defaults.md) |
| 选择宿主工具或测试 | [工具目录](../tools/README.md)、[宿主核心测试](../host_tests/README.md)、[测试固件](../test/README.md) |

## 实现与诊断

- [架构与数据所有权](reference/architecture.md)：组件边界、原生单位和业务解释层。
- [MT6835 帧参考](reference/mt6835.md)：帧、CRC 与器件约束。
- [编码器采样](encoder-sampling.md)：采样任务、时间戳和速度窗。
- [测量有效性](measurement-validity.md)：消费者如何判断样本新鲜、连续和可用。
- [遥测](telemetry.md)：状态输出时序，与采样/控制频率的区别。
- [连续增长判据](following-error-window.md)：STEP_LOSS 判定开关与测试。
- [STEP_LOSS 诊断](step-loss-diagnostic.md)：事件、运行身份、轨迹、observe-only 的独立开关及限制。
- [TMC 运行期诊断](tmc-runtime-diagnostic.md)：事件前后低频 DRV_STATUS/GSTAT 缓存与证据限制。
- [TMC 只读诊断](tmc-readonly.md)：寄存器读回能力与证据边界。

## 实验工具

实验不是正式控制入口。它们可能主动运动，应先读各自前提，不能把旧台位参数直接用于不同装置。

- [加速度探索](experiments/acceleration.md)
- [50 kHz 离线预算](experiments/step50k-budget.md)
- [单次高速探针](experiments/step50k-probe.md)
- [两次往返探针](experiments/roundtrip-probe.md)
- [工具目录中的独立实验工程](../tools/README.md)

## 历史记录与维护约定

[历史证据索引](archive/README.md)保留实测报告、原始证据及独有实施验证记录。空白验收模板和已执行的逐步计划不再作为当前入口；其原版本可以通过固定提交链接追溯。

- 协议、接线、默认值各有一个权威入口，其他文档引用而不复制整份参数表。
- 当前代码变化时同步更新相关指南；不要将临时聊天步骤作为新的长期文档。
- 有独特测量/验证价值的结果注明版本、条件和未验证范围后归档；无独特事实的过程文档删除，保留 Git 历史。
- 保留顶层 `protocol.md`、`hardware.md` 等稳定路径，减少上位机项目与外部引用的迁移成本。

- [摆杆测量失效诊断](pole-diagnostic.md)：停止后读取有效到无效首证据与采样日志边界。

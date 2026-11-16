# device-nerve-esp32 · 倒立摆运动端固件

当前应用是 ESP32-S3 倒立摆小车控制器：上位机发送目标速度，固件负责步进斜坡、
编码器采样、标定参考、模式与故障处置，并报告位置、摆角和速度。
硬件为 TMC2209 步进驱动、两路 MT6835 磁编码器和 CH224Q 供电管理。
这是当前已实现的串口单动作应用，不是已经完成的通用 Wi-Fi/蓝牙控制平台。

## 从哪里开始

| 要做的事 | 文档入口 |
| --- | --- |
| 了解接线、供电和日志通道 | [硬件](docs/hardware.md) |
| 构建、烧录并首次连接 | [开发与启动](docs/getting-started.md) |
| 两点标定、保存或重启后恢复左参考 | [标定](docs/calibration.md) |
| 编写上位机或核对响应 | [协议](docs/protocol.md) |
| 排查测量无效、丢步与状态时序 | [文档导航](docs/README.md) |
| 使用查询、诊断或实验脚本 | [主机工具](tools/README.md) |
| 运行软件测试或目标测试镜像 | [宿主测试](host_tests/README.md) / [目标测试](test/README.md) |

本仓库的 [protocol.md](docs/protocol.md) 是固件现行线协议入口；
[cartpole](https://github.com/CLD1994/cartpole) 是训练与策略部署的消费者仓库。
历史实测、旧板记录和已经执行的计划不作为当前版本验收证明，集中见[归档](docs/archive/README.md)。

## 当前行为边界

- 上电保持禁用。供电验证和位置参考满足后，仍需显式 `ENABLE`。主机发起运动前另行确认测量有效性，ENABLE 成功不代表速度窗已有效。
- 固件接收单动作 `VEL`；速度、正常加减速与看门狗减速分别受运行参数约束，见[运动默认值](docs/motion-defaults.md)。
- `STATE` 目标为 500 Hz；编码器默认目标采样率 2 kHz。它们不是上位机模型控制频率或实时性保证。
- `STEP_LOSS` 默认仍进入故障处置。连续增长判据、事件推送、轨迹诊断和 observe-only 是不同构建选项，见[丢步判据](docs/following-error-window.md)和[诊断](docs/step-loss-diagnostic.md)。
- observe-only 只改变 `STEP_LOSS` 的处置，不能理解为关闭全部保护，也不能让旧上位机自动具备事件处理能力。

## 代码入口

- [main/app_main.c](main/app_main.c)：实例创建与组装。
- `components/`：设备驱动、类别接口、业务坐标解释、模式机和协议。
- [组件架构](docs/reference/architecture.md)：职责和数据流，接口声明以对应头文件为准。
- `tools/`：PC 联调及只读诊断；`experiments/`：装置专用实验，不属于正常运行流程。
- `test/`：独立 ESP-IDF 测试工程；`host_tests/`：可在宿主运行的测试与替身。

开发约束见 [AGENTS.md](AGENTS.md)。文档各主题只维护一份现行说明，其他入口通过链接引用。

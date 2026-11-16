# 宿主工具

先阅读[入门与串口选择](../docs/getting-started.md)。串口工具的默认波特率不一定等于当前固件配置，始终核对 `--baud`。工具提供能力，不代表已经完成现场验证。

## 日常控制与只读诊断

| 入口 | 用途与边界 |
|---|---|
| `cartpole_host.py` | 查询、标定、配置、使能及速度命令；不同子命令会改变设备状态，先看 `--help` |
| `step_loss_capture.py` / `step_trace_capture.py` | SL1 / SLT4 只读证据采集；版本匹配见下文 |
| `tmc_trace_capture.py` | 只读导出运行期 DRV_STATUS 缓存，见[运行期诊断](../docs/tmc-runtime-diagnostic.md) |
| `tmc_readonly.py` | TMC 寄存器读回，见 [TMC 指南](../docs/tmc-readonly.md)；不证明真实电流或扭矩 |
| `velocity_validity.py` | 速度有效性检查，见 [测量有效性](../docs/measurement-validity.md) |
| `max_accel_run.py` | 加速度试验入口，见 [专用指南](../docs/experiments/acceleration.md) |

## 历史验收与压力脚本

`host_sim.py`、`host_sim_sweep.py`、`host_sim_stress.py`、`t3_stress_test.py` 保留作历史测试代码参考，不是当前主线的一键验收流程。其旧模式、标定和运动假设必须先逐项对照现行协议，不应未经审查直接运行于真机。

`host_sim.py` 默认生成 `docs/acceptance.md`，这只是旧脚本的输出路径，不是当前文档入口。需要复用时显式给 `--report` 指定新的日志路径，不覆盖归档报告。旧结果见[历史证据](../docs/archive/README.md)。

## 真机实验工具

这些工具不是生产控制器，也不自动恢复故障或使能。Python 串口入口依赖 `pyserial`，
在 Windows 原生终端运行；固件在 ESP-IDF 容器内构建。先阅读各入口的现场前提。

- [低速方向与停稳](../experiments/low-speed-probe/README.md)：小幅单向运动。
- [400 mm/s 加速度基线](../experiments/accel-5000-probe/README.md)：固定单次基线。
- [50 kHz 离线预算](../docs/experiments/step50k-budget.md)：不打开串口、不运动。
- [单次高速探针](../docs/experiments/step50k-probe.md)：显式预算输入，全部预算通过才允许执行。
- [两次往返探针](../docs/experiments/roundtrip-probe.md)：固定装置专用，低速接近端点，停稳后反向。
- [独立 STEP 测量固件](../experiments/step-frequency-isolated/README.md)：需物理隔离动力路径。

所有日志由用户指定新文件保存，不提交到仓库。实验结果不能替代实际速度、
加速度、温升、波形和停止距离的独立测量。对照记录见[实验结论](../docs/archive/2026-11-13-experiment-results.md)。

## 开发与维护边界

运动探针共用 [probe_link.py](probe_link.py) 的串口会话与预检，不依赖低速脚本的命令行入口。
串口、单调时钟与等待函数由构造参数注入；测试使用内存替身，不打开真实串口。
各运动脚本负责自己的轨迹、时限和停止条件。专用往返脚本不是训练控制器，
其风险确认不能替代通用控制器的制动设计。

这些文件不参与生产固件的构建，也不增加生产固件的常驻任务、内存或串口流量。
独立STEP工程需单独构建和烧录；它不运行生产模式机和编码器任务，
因而只能检查隔离条件下的STEP输出，不能替代完整固件的负载验证。

主机侧回归可在仓库根目录执行：

```bash
python -m unittest discover -s tools -p 'test_*.py'
bash experiments/step-frequency-isolated/tests/run.sh
```

前者验证主机工具的协议与行为，后者验证独立STEP测量控制逻辑。
ESP-IDF目标构建、波形和机械运动仍需在目标环境单独验证。

## STEP_LOSS 可选诊断

`step_loss_capture.py` 支持 SL1 VERSION=1/2 快照；`step_trace_capture.py`
读取新 SLT4 事件前后软件轨迹。两者都只发查询，不使能/复位/运动。
诊断开关、observe-only主机责任及帧定义见 [STEP_LOSS诊断](../docs/step-loss-diagnostic.md)。
本工具不读取旧实验SLT2/3，须与固件版本匹配。


## 联调会话的 STEP_LOSS 事件策略

`cartpole_host.py` 严格识别 `EVENT STEP_LOSS <event_id> <run_id> <device_us>`，
不再将合法通知计为 UNKNOWN，也不把事件伪装成 MODE FAULT。事件 ID 和运行 ID
必须为非零 uint32，设备时间必须为非负 int64；畸形、未知事件和越界字段仍按原
UNKNOWN 规则处理，活动会话仍会中止。

全局选项 `--step-loss-policy report|stop` 必须放在子命令之前：

- `report` 是默认值：保存并显示合法事件，不清除最新 STATE、不改变测量有效性门禁，
  不因该事件自动发送任何指令；调用方原来的控制流程继续执行。
- `stop`：活动会话先保存事件并锁存中止，再通过异常交给命令入口；入口先尝试
  `VEL 0`，之后输出包含事件身份的原因，退出码为 1。零速请求不保证已经物理停稳。
  非活动会话仍只报告，不自动运动或使能。

例如只读观察事件可执行：

```powershell
python tools/cartpole_host.py --port COM11 --baud 460800 --step-loss-policy report state --secs 10
```

使用 `Rig` 的程序可通过同名构造参数 `step_loss_policy` 指定策略。`last_step_loss_event`
记录最近合法通知的 `event_id`、`run_id`、`device_us` 与 `host_received_at`；
`event_count` 是收到的合法事件行数，重复通知也计数，不代表独立故障数。
这些字段不证明事件属于当前运行，工具没有自动核验 RUN 身份，也不会把旧或重复通知
当作新运行。需要关联时调用方应自行核对运行身份。

`report` 不取消 VEL_VALID、未知数据、状态新鲜度或原有模式处理，也不会修改固件的
STEP_LOSS 停车/observe-only 配置。报告通过与 MODE/OK 相同的同步输出接口显示，
输出慢时可能阻塞；该联调工具不是硬实时控制器。`stop` 活动路径不先输出，避免在
零速请求前新增 stdout 阻塞。其他直接使用 Rig 的调用方须处理异常并请求停止，不能
假设 Rig 自行发出了零速。串口库仅在默认真实串口工厂使用时导入，内存替身测试不依赖设备。

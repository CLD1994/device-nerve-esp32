# STEP_LOSS：可选事件、诊断与上位机处置

## 三个独立配置

| Kconfig | 默认 | 功能 |
|---|---|---|
| `CARTFSM_STEP_LOSS_EVENTS` | n | 首次事件通知、运行身份查询；小型邮箱，无轨迹 |
| `CARTFSM_STEP_LOSS_DIAGNOSTICS` | n | 触发快照和事件前后软件轨迹，自动选择 EVENTS |
| `CARTFSM_STEP_LOSS_OBSERVE_ONLY` | n | 放弃固件 STEP_LOSS 停车，交由上位机处理；自动选择 EVENTS，但不选择 DIAGNOSTICS |

诊断开关不改变失步判据或停车，后两者分别由窗口判据和 OBSERVE_ONLY 控制。
全部关闭时沿用原主线检测与停车，不分配轨迹/快照，不做诊断时间戳或附加快照读取。

OBSERVE_ONLY 打开后，命中 STEP_LOSS 不改 READY、目标速度/加速度、驱动使能；
之后仍接受 VEL。上位机必须自行决定继续或停车。这不是自动恢复或消除误差，
不会重置编码器或软件 STEP 位置。供电故障、编码器失效、命令看门狗和软限位不变。

## 事件和运行身份

每次成功 ENABLE 增加设备启动期内 `run_id`，重新布防；每轮只锁存首次命中。
RESET 不清除已保存证据。新运行首次命中才替换旧证据。

```text
RUN?                          -> OK RUN <run_id>
EVENT STEP_LOSS <event_id> <run_id> <device_us>
```

事件在监督路径内只写固定邮箱；遥测任务异步格式化并发送，不令监督任务等待 UART。
事件没有 ACK/重放，新 ENABLE 会清理尚未发送的旧邮箱；已取出的事件仍可能稍晚发出。
因此上位机必须按 RUN? 身份校验，不能把旧运行事件套到当前会话。设备重启后 ID 重新开始。
关闭 EVENTS/DIAGNOSTICS/OBSERVE_ONLY 时 `RUN?` 返回 `ERR RUN_DISABLED`。
事件可丢失、可延迟，不是有保证的停机信号。正常停车构建也可选事件，但它不会替代 MODE。

## SL1 触发快照

`STEPLOSS?` 只允许 DISABLED 或 FAULT 已停稳；READY/仍减速返回 `ERR STEPLOSS_BUSY`。
诊断未编入返回 `ERR STEPLOSS_DISABLED`；没有事件返回 `ERR STEPLOSS_NONE`。

格式 `SL1 <event_id> <field> <integer>`，以 `SL1 <event_id> END 1` 完成。
VERSION=2 保留原字段，增加 TRIGGER、HARD_UM、GROWTH_UM、WINDOW_US、GROWING_WINDOWS，
见[窗口判据](following-error-window.md)。工具同时支持原 VERSION=1。

字段包括参与判断的 E/C、比较和接受时间、运行ID、接受前目标速度、缓存编码器
样本时间/序号/有效性、失败和连续性序号。E 与 C 非同时读取；C 为软件指令位置，
不是物理脉冲或实际电机位置。CRC/有效性也不是传感器真实运动的证明。

## SLT4 事件前后软件轨迹

`STEPTRACE?` 使用与快照相同的停稳门限；后段尚未收完时也返回 `ERR STEPTRACE_BUSY`。

- 最多128条触发前/附近记录、32条触发后记录；每条最小间隔5ms，不是精确采样频率。
- 两个固定160条缓冲在触发时 O(1) 交换，不复制整条轨迹。只读现有缓存及软件计数，
  无额外 SPI、PCNT、GPIO、动态分配或日志输出。
- 后段有界，约160ms以上，实际以时间戳为准；新 ENABLE 可提前结束旧后段，保留实际数量。
- 本版不包含实验 SLT2/3 的 PCNT/EN/SPI 原始帧，也不包含4秒B/S读取对照。
  不可用旧 SLT3 解析器读取，需同步本仓库 `step_trace_capture.py`。

```text
SLT4 HEADER <event> <run> <count> <post_count> <complete>
SLT4 ROW <event> <index> <observed_us> <sample_us> <c_begin_us> <c_end_us> <e_um> <c_um> <sample_seq> <target_mm_s> <encoder_v_mm_s> <metadata> <sample_valid> <velocity_valid> <last_read_ok>
SLT4 END <event> <count>
```

complete=1，行顺序为最旧到最新；最后post_count条为触发后的记录。
最早一条到触发点不一定覆盖完整640ms，例如刚使能就触发。样本时刻和传输时刻不能混用。
取证不会证明编码器、传动比或电机运动正确，也不应以软件轨迹替代独立物理测量。

## 主机只读取证

设备停稳后运行（不自动使能、复位、配置或发送运动）：

```powershell
& $python .\tools\step_loss_capture.py --port COM11 --baud 460800 --out .\step-loss-new.json
& $python .\tools\step_trace_capture.py --port COM11 --baud 460800 --out .\step-trace-new.json
```

每次使用新文件名，不覆盖已有证据。未完整收到END不得当作成功报告。

## 验证范围

宿主替身覆盖诊断关闭、事件单独、诊断、observe-only单独及组合；覆盖首次触发、
重新ENABLE、128+32界限、查询门限、窗口软/硬边界与 WDT 新喂狗竞态。
这些不是 ESP32-S3 实时开销、UART 负载或真机验收；目标构建和现场验证单独记录。

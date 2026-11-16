# 跟随误差：判定与处置分开配置

这里 E 是编码器测得的位置，C 是软件 STEP 指令累计位置；二者不是同一时刻的物理运动测量，误差触发不等于已经定位出电机失步原因。

`CONFIG_CARTFSM_FOLLOWING_ERROR_WINDOW=y` 启用连续增长窗口判据；默认 n，
关闭时保持原 `|E-C| > STEP_LOSS_UM` 立即触发行为。本功能不重置软件 STEP 累计位置。

开启后：
- `|E-C| >= CARTFSM_FOLLOWING_ERROR_HARD_UM` 立即触发（含等号）。
- 每个观察窗口计算绝对误差的增长。增长达到配置门限的连续窗口数达到要求，
  且当前误差严格大于 `STEP_LOSS_UM` 时触发。
- 误差不再增长/增长不足，连续计数归零。新运行或时钟倒退重建窗口。
- 监督延迟时按实际窗长比例提高增长门限，避免把较长时间的积累当成过快增长。

| 构建配置 | 默认 | 范围 |
|---|---:|---:|
| `CARTFSM_FOLLOWING_ERROR_HARD_UM` | 6000 µm | 1000–50000 |
| `CARTFSM_FOLLOWING_ERROR_WINDOW_MS` | 50 ms | 5–200 |
| `CARTFSM_FOLLOWING_ERROR_GROWTH_UM` | 1000 µm/窗 | 100–10000 |
| `CARTFSM_FOLLOWING_ERROR_WINDOWS` | 2 | 2–10 |

这些默认值不等于现场已经验收的最佳参数；过去现场使用的50mm硬限等是实验选择，
不自动写入正式默认。`STEP_LOSS_UM` 仍通过现有 CONFIG 设置，窗口参数为构建期配置。
独立硬限优先于软阈值，设置较小硬限会更早触发。

判定只是输出 STEP_LOSS。默认处置仍为固件 FAULT 减速停车。
显式开启 `CONFIG_CARTFSM_STEP_LOSS_OBSERVE_ONLY=y` 后，固件仅通知、保留正常
VEL 控制，不因 STEP_LOSS 改目标或关闭驱动，由上位机负责处置。
该开关不关闭供电/编码器故障、WDT、软限位等其他保护，且不依赖重型轨迹诊断。

SL1 VERSION=2 的 TRIGGER：1=硬限，2=连续增长，3=传统即时阈值。

实现依据：[Kconfig](../components/cartfsm/Kconfig)、[判据](../components/cartfsm/cartfsm_following_error.h)。事件身份、快照和轨迹另见[诊断说明](step-loss-diagnostic.md)。

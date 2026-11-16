# 倒立摆串口协议（上位机 ↔ ESP32-S3）

UART 为 3.3 V TTL、共地、8N1、ASCII 行文本。波特率由 `CONFIG_CARTPROTO_UART_BAUD` 决定，当前 Kconfig 默认 **1000000**；上位机必须匹配实际构建配置，不能将现场示例的 460800 当成固定协议值。链路上分两个面，共用一条物理串口，按行首单词分发：

- **数据面**：ESP32-S3 → 上位机 的 500 Hz 状态流（`STATE` 行），统一 `STATE` 同帧携带物理量与双路独立测量有效性。
- **控制面**：双向的命令与应答。上位机以命令驱动 ESP32-S3：运动命令（`VEL`）、标定与流程命令（`MARK LEFT`/`MARK RIGHT`/`ENABLE`/`DISABLE`/`RESET`）、状态查询（`QUERY`）、运行参数配置（`CONFIG`）。固件以模式事件（`MODE` 行）与配置/标定应答（`OK`/`ERR` 行）回应。

消息名与枚举值用完整英文单词，不用缩写——保留便于调试的可读格式，但必须计入带宽预算；字段保持固定顺序的十进制整数，不采用 key=value（每种行只有一个固定格式，键名重复约 40% 字节却不消除任何歧义）。所有行首单词与枚举词**大小写敏感，全大写**。

带宽核算（含换行，8N1每字节10位）：四个int32字段的保守最长文本为54字节，
500 Hz时为27 kB/s，占460800发送容量46.08 kB/s的58.6%。
`STATE -249 3141592 0 0\n` 为23字节，占约25.0%。
控制命令使用反向通道，不与STATE简单相加；MODE/OK/ERR应答共用固件发送通道。
1 Mbps 下对应占用为27.0%和11.5%。这些是线路预算，不是已测稳定性或延迟保证。验证方法见[状态流验证指南](telemetry.md)。

多圈累计、单位换算和符号约定在固件侧完成，坐标原点由手动两点标定（`MARK LEFT`/`MARK RIGHT`）建立，线路上传输的已是物理量，端侧程序不做标定换算。

## 数据面：统一状态流（目标 500 Hz，周期 2 ms）

```text
STATE boot8 tick8 flags1 cartseq4 poleseq4 cartage4 poleage4 x8 theta8 vx8 vth8\n
```

这是固定宽度十六进制文本：每项间一个空格，12 个 token，含 LF 共 82 字节。输出小写，接收允许大小写；没有 `0x` 前缀。工具解码后仍用十进制和物理单位展示。旧四字段 STATE、独立 VEL_VALID 和 CART_STATE1 已移除，不提供旧协议兼容。

| 字段 | 编码及含义 |
|---|---|
| boot8 | 本次遥测启动的随机 uint32 身份，零合法，不保证永不碰撞 |
| tick8 | 组帧时设备微秒时间的低 32 位，约 71.58 分钟环绕 |
| flags1 | 仅 0..3；bit0 小车有效、bit1 摆杆有效 |
| cartseq4 / poleseq4 | 各自成功采样序号的低 16 位，零是合法环绕值 |
| cartage4 / poleage4 | 组帧时设备同钟采样年龄 µs；有效路为 0..20000，无效路 ffff |
| x8 / theta8 | int32 二补码：小车位置 µm、摆杆角度 µrad；有效角度限定 ±3141592 |
| vx8 / vth8 | int32 二补码：小车速度 mm/s、摆杆角速度 mrad/s |

无效路必须规范化为 seq=0000、age=ffff、该路两个数值=00000000。这些是无效占位，不是新测得的零，消费者须返回缺失值，不得参与控制或停稳判定。小车路对应 x/vx，摆杆路对应 theta/vth。每路位置、速度、时间和序号来自同一测量快照，两路不保证同时采样。

所有模式均发送状态，即使两路无效；有效性与数值在同一帧原子表达。小车原点仍由两点标定或已有长度下的左参考确认建立，flags 不能证明标定正确。速度噪声、群延迟与物理精度须现场验证。

## 控制面：模式机、命令与应答

### 固件模式机

| 模式 | 电机 | 进入方式 |
|---|---|---|
| `DISABLED` | 关闭使能 | 上电默认；正常停稳后DISABLE，或FAULT经RESET回到此态 |
| `READY` | 使能，静止或跟踪 `VEL` | DISABLED 且两点标定完成后收到 `ENABLE` |
| `FAULT` | 常规故障斜坡停机；POWER立即停止STEP并禁用 | 故障，见转换表 |

模式转换（完整分类）。坐标由手动两点标定建立，标定语义见[标定保存指南](calibration.md)：

| 当前态 | 事件 | 次态 |
|---|---|---|
| DISABLED | `MARK LEFT` / `MARK RIGHT`（见标定决策表） | DISABLED |
| DISABLED | `ENABLE`（标定完成 `CAL_DONE`） | READY |
| READY | STEP_LOSS（未开启 observe-only）/ 编码器故障 / 供电失效 | FAULT |
| READY | `DISABLE`且引擎精确零速 | DISABLED |
| FAULT | 收到 `RESET` | DISABLED |

### `MODE` 行：模式事件与查询应答

使能、禁用、复位会推送模式。常规故障先进入 FAULT 并减速，停稳后才推送故障模式；POWER 故障立即停止并推送。`QUERY` 回答查询时的模式，可能早于常规故障的停稳推送：

```
MODE <mode> <reason>\n
```

| reason | 含义 |
|---|---|
| `NONE` | 无（非 FAULT 转换） |
| `STEP_LOSS` | 编码器位置与软件 STEP 位置的跟随误差触发；不直接证明物理丢脉冲或失步 |
| `AS5600` | 小车编码器读取失败（历史器件名：rev2 起小车位实为板载 MT6835，字面量为线协议冻结值） |
| `MT6835` | 摆角编码器读取失败 |
| `POWER` | 供电验证失效或供电样本过期，立即停止STEP并禁用 |

`MODE` 行无 ACK，端侧晚开串口会错过开机以来的转换，因此端侧在启动同步和任何需要复核的时刻发 `QUERY` 补一拍。

### 命令

```
VEL <v_mm_s>\n            目标速度 [mm/s]，钳位 ±VEL_MAX 后斜坡跟踪
MARK LEFT\n               记当前实测位置为左端，回 OK MARK_LEFT <E µm>
MARK RIGHT\n              记右端并完成标定，回 OK MARK_RIGHT <L µm>
CONFIRM LEFT\n           用已保存行程确认当前位置为左参考点；不使能
CALIB?\n                 查询保存与本次定位状态（见标定保存指南）
ENABLE\n                  标定完成且20V供电验证有效后使能进 READY，推 MODE READY NONE
DISABLE\n                 READY且引擎零速时禁用；运动中ERR BUSY；FAULT不清除
RESET\n                   清除 FAULT
QUERY\n                   查询当前模式，回答一行 MODE
CONFIG <NAME> <value>\n   设置运行参数，回答 OK 或 ERR
CONFIG?\n                 dump 全部参数（调试与日志记录用）
CONFIG? <NAME>\n          只读单个参数，回答 OK <NAME> <value>
```

`CONFIG? <NAME>` 的 NAME 与 `CONFIG` 使用相同词法 `[A-Z0-9_]{1,15}`。已登记参数仅回复一行 `OK <NAME> <value>`；词法合法但未登记的参数回复 `ERR <NAME>`；多余参数、非法名称等语法错误仍按既有规则静默丢弃。单项查询在三种模式下均只读，不修改参数、NVS、模式或运动目标，也不重置运动看门狗。无参数 `CONFIG?` 保留按注册表顺序输出全部参数的行为。主机可轮转单项查询避免全量回复突发；查询能力不保证主机控制截止或设备实际响应耗时。

标定命令在非 DISABLED 模式返回对应 `ERR`；`ENABLE` 在非 DISABLED 模式静默忽略。在 DISABLED 下，ENABLE 先检查供电（失败回 `ERR POWER`），再检查参考（失败回 `ERR ENABLE`）。`VEL`/`RESET` 在不适用态静默忽略。两点行程合法窗为 100000–1000000 µm，负行程拒绝；存储、参考及标记次序见[标定保存指南](calibration.md)。

命令 × 模式矩阵（完整分类）：

| 命令 | DISABLED | READY | FAULT |
|---|---|---|---|
| `VEL` | 忽略 | 执行 | 忽略 |
| `MARK LEFT` / `MARK RIGHT` | 执行或 `ERR`（标定决策表） | `ERR` | `ERR` |
| `ENABLE` | 供电验证有效且标定完成才执行，否则 `ERR POWER` / `ERR ENABLE` | 忽略 | 忽略 |
| `DISABLE` | 幂等回MODE DISABLED NONE | 精确零速才禁用，否则ERR BUSY | 回当前MODE与原因，不改变故障 |
| `RESET` | 忽略 | 忽略 | → DISABLED |
| `QUERY` | 回 `MODE` | 回 `MODE` | 回 `MODE` |
| `CONFIRM LEFT` | 执行或 `ERR`（见标定保存指南） | `ERR` | `ERR` |
| `CALIB?` | 接受 | 接受 | 接受 |
| `CONFIG` | 接受 | 仅非摆角/非X_INV参数 | 拒绝（`ERR`） |
| `CONFIG?` / `CONFIG? <NAME>` | 接受 | 接受 | 接受 |

`VEL` 语义：固件以不超过 `ACC_MAX` 的加速度向目标速度过渡，换向经零速；收到新 `VEL` 即更新目标并保持到下一条。非法行静默丢弃，目标不变。

命令看门狗：超过 `WDT_MS` 未收到有效 `VEL` 命令（链路断、端侧程序死）时，以 `ACC_MAX` 减速到 0，**保持 READY**——看门狗是瞬态保护，不改变模式机，命令恢复即继续跟踪。

软限位窗口 `X_MARGIN_UM`：标定行程 `L` 确定后，有效运动窗口为 `[−L/2+m, +L/2−m]`（`m = X_MARGIN_UM`）。`x` 越出窗口后，`VEL` 中向外的分量被替换为 0，向内不受限；增大 `X_MARGIN_UM` 会缩小窗口，运行中修改立即生效；软限位不是预先规划的制动距离保证。

### 参数注册表（`CONFIG` 命令可配置项）

| NAME | 默认值 | 合法范围 | 单位 | 含义 |
|---|---|---|---|---|
| `VEL_MAX` | 1250 | 1 – 2000 | mm/s | `VEL` 命令硬钳位 |
| `ACC_MAX` | 10000 | 100 – 30000 | mm/s² | 斜坡加速度上限 |
| `WDT_MS` | 100 | 10 – 1000 | ms | 命令看门狗超时 |
| `X_MARGIN_UM` | 10000 | 1000 – 50000 | µm | 软限位两端余量（窗口 `[−L/2+m, +L/2−m]`） |
| `POLE_ZERO_URAD` | 0 | −3141592 – 3141592 | µrad | 摆角零位偏置：输出 θ = 原始读数 − 本值，使机械直立对应 0。标定法：θ₀ 取直立原始读数（可由下垂读数 + 180° 反推，比手扶更准），本值 = θ₀ |
| `POLE_INV` | 0 | 0 – 1 | — | 摆角符号翻转，使摆顶向 +x 倾斜为正 |
| `X_INV` | 0 | 0 – 1 | — | 小车 +x 方向翻转，使命令与 `x_um`/`vx_mm_s` 满足符号约定 |
| `STEP_LOSS_UM` | 3000 | 500 – 20000 | µm | 跟随误差软阈值；传统判据超过即触发，窗口判据见下文；处置另由 observe-only 决定 |

默认运动目标的说明见[运动参数默认值](motion-defaults.md)。STEP 引擎将所有带符号目标钳位至 ±50 kHz；在当前 40 steps/mm 下对应 1250 mm/s。它是软件请求上限；现场试验范围与适用边界见该说明，不能据此保证所有负载下的实际速度。

`CONFIG` 语义：成功时回 `OK <NAME> <value>`（回显归一化后的值），参数立即生效；未知 NAME、超出范围、或当前模式为 FAULT 时回 `ERR <NAME>`。`POLE_ZERO_URAD` 和 `POLE_INV` 仅在 DISABLED 接受，NVS提交成功后才应用和回OK，失败回 `ERR CAL_STORAGE`；重启恢复。`X_INV` 也仅在DISABLED修改。其他参数使用默认值或由端侧会话配置。完整持久化、重启参考门和故障语义见[标定保存指南](calibration.md)。运行中收紧限制（增大 `X_MARGIN_UM`、调低 `ACC_MAX` 等）立即约束当前运动；放宽不产生任何主动运动。

## 符号约定（实机验证方法）

摆角零位使用编码器的单圈绝对角，不以固件启动姿态归零。固件保存的
`POLE_ZERO_URAD` 和 `POLE_INV` 在机械安装和方向不变时可以跨重启复用，
NVS恢复规则见[标定保存指南](calibration.md)。
`RESET` 只清故障，不重置编码器累计状态或运行参数。
若零偏来自旧固件的开机相对角，升级后须重新标定，不能直接沿用该数值。
绝对角读取与累计位置的区别见
[编码器类别契约](reference/architecture.md#原生单位与解释层)。

- +x = 发 `VEL 200` 时小车实际移动的方向；同方向用手把摆顶掰过去时 `theta_urad` 必须增大。任一不符，先改固件符号再联调。
- `x_um` 沿 +x 增大；两个速度量与各自位置量同号。

## 时序

- 状态流目标为500 Hz（2 ms）。默认采样为2 kHz；速度窗使用33个成功样本（1 kHz回退配置使用17个），均为名义约16 ms，分母为实际采样时间差且总跨度不得超过32 ms。增加报告率不会缩短这个估计窗口。
- STATE的每路位置/角度与速度来自同一快照，两路之间不保证同步，也不携带时间戳、序号或校验和。不得仅由报告率推断新样本率或端到端延迟。
- 默认FreeRTOS tick为1000 Hz。构建要求tick能精确表示1 ms和报告周期，误配置时编译失败，不采用截断后的错误周期。
- 状态报告与控制频率解耦：接收500 Hz状态不要求每帧推理。上位机按自身调度消费最新完整有效帧；当前主线仅接受单动作目标速度 `VEL`，没有速度与加速度双动作协议。
- 端到端延迟须分别测量采样、传输、主机调度和执行响应；不能由报告率推算，也不在本协议中承诺固定延迟。

## 操作与验证入口

- 首次标定、重启左参考与NVS保存：[标定指南](calibration.md)。
- 状态流速率、带宽、有效性与验收边界：[遥测验证](telemetry.md)。
- 跟随误差判定：[窗口判据](following-error-window.md)；事件和只读取证：[诊断](step-loss-diagnostic.md)。
- 运动前确认 QUERY、CALIB?、供电和测量有效性，不能将某次现场参数或实验结果当成通用配置。

协议实现入口：[解析器](../components/cartproto/cartproto_parse.c)、[模式机](../components/cartfsm/cartfsm.c)、[参数注册表](../components/cartparams/params.c)、[遥测发送](../components/telemetry/telemetry.c)。硬件时序、标定重复性和速度估计指标仍需针对具体构建进行实测。

## 20 V 供电状态与运动门禁

ENABLE还要求供电验证有效；否则返回`ERR POWER`，不使能。供电验证条件与时序见
[硬件说明](hardware.md#14-正式固件的供电门禁)。标定、QUERY和CONFIG读取不要求供电就绪。
运行中供电失败/样本超时触发`MODE FAULT POWER`，立即停止STEP并禁用驱动，不承诺缺电
时的斜坡制动。`POWER`是新增reason值。RESET可将模式回DISABLED，但不会清除电源故障
锁定；输入恢复也不自动使能，须排查后重启验证。原有标定使能前提不变。

## 正常停止后的禁用

`DISABLE` 不自动减速，不是急停。先发送 `VEL 0`，观察小车停稳，再执行主机工具的 `disable`。READY下只有步进引擎精确速度为零才清目标、停止发步并关闭EN，随后回`MODE DISABLED NONE`；速度非零时回`ERR BUSY`且不改变目标或模式。DISABLED下重复执行幂等；FAULT下仅回当前故障，不清故障或中断已有停机流程。

速度判断与清目标在引擎锁内原子执行，输出锁防止并发VEL穿过禁用流程；后到VEL在DISABLED下忽略。禁用保留有效位置参考和保存参数，也不清供电失败锁；再次ENABLE仍需供电和参考门禁。

引擎速度为零不证明机械静止。关闭EN会失去保持力，不得把本命令作为对滑行、外力或坠落的安全保证。不可手推制造丢步故障来代替禁用。

## 测量有效性

有效路要求速度窗口、最近读帧及采样时效满足算法；小车还要求累计位置连续性有效。默认窗口 33 点、名义约 16 ms，允许总跨度不超过 32 ms；它不是端到端延迟保证。窗口恢复不恢复丢失的圈数，累计连续性失效仍须在 DISABLED 下重新确认参考。

模型及双路工具必须要求 flags=3；`vel` 小车调试只要求 bit0，摆杆无效仍记录，不伪造摆角。任一所需路无效、损坏或未知报文、时间身份异常、过期都锁存当前运动失败；后续恢复不能自动恢复原试验。固件 `FAULT MT6835`（连续读失败保护）等模式保护不因单路调试被绕过。

序号采用模 16 位半区间前进检查：差 0 是重复，1..32767 是前进，其余拒绝。重复不能刷新观测/停稳窗口；同序号改变测量值亦拒绝。每路以展开的设备时间减样本年龄重建采样时刻，新序号必须严格前进、重复序号必须对应同一采样时刻，无效期间和停车观察仍保留水位。设备 tick 使用对应的模 32 位半区间检查，设备 boot 改变需重新建立会话，不在活动控制中自动重基线。2 kHz 时序号半区间仅约 16.384 秒，不能用此机制恢复长时间断流；超时必须先停止。

工具的新鲜度使用设备报告年龄、主机同钟接收后经过时间及相对于会话基线的输运积压增长，不直接相减主机与设备绝对时间。诊断运动门限为 100 ms，模型可以要求更严格门限。初始就存在的恒定传输延迟无法据此证明不存在；设备时间也不是端到端时钟同步。串口排队、同步日志和主机调度仍可能延迟停止。

无效路占位不能续命、凑成四维观测或作为静止证据。停车重新观察使用后续真实新样本并保留身份/序号水位，不能清除原运动失败锁存。协议没有 CRC，严格格式检查不能发现所有仍符合格式的比特损坏。

## TMC 只读核查

`TMC?` 仅在 `DISABLED` 且软件 STEP 引擎静止时允许，其他状态返回 `ERR TMC_BUSY`。
返回 `TMC1 NAME VALID RAW BEGIN_US END_US` 五行及 `TMC1 END`，不改变配置或使能。
字段、静止读数限制及 Windows 使用方式见 [TMC 只读诊断](tmc-readonly.md)。
### STEP_LOSS 可选故障快照

`STEPLOSS?` 需要构建时开启 `CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS`（默认关闭）。
关闭时在任何模式返回 `ERR STEPLOSS_DISABLED`；失步检测和故障停车不受影响。
开启时在DISABLED或FAULT已停稳时导出最后一条被接受的STEP_LOSS证据，
READY或仍减速时回`ERR STEPLOSS_BUSY`，无记录回`ERR STEPLOSS_NONE`。
应答采用`SL1 <event_id> <field> <integer>`逐字段输出并以`END 1`结束。
记录是设备固定RAM中的触发拍，不是MODE输出时的状态，不改变原故障判断。
字段、工具、生命周期及非同步限制见[STEP_LOSS诊断](step-loss-diagnostic.md)。

### 可选 STEP_LOSS 事件与处置

`CONFIG_CARTFSM_STEP_LOSS_EVENTS` 提供 `RUN?` 与
`EVENT STEP_LOSS <event_id> <run_id> <device_us>`，每个成功ENABLE运行只报告首次触发。
事件无ACK/重放，晚到事件须核对run_id。
`CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS` 增加停稳后 `STEPTRACE?` 的SLT4软件轨迹。
显式 `CONFIG_CARTFSM_STEP_LOSS_OBSERVE_ONLY` 取消上表中由STEP_LOSS导致的FAULT，
保留READY及VEL控制，由上位机处置；不取消其他故障与WDT/软限位。
三项均默认关闭，observe-only不依赖轨迹诊断。
可选连续增长/硬限判据与传统STEP_LOSS_UM即时判据见
[跟随误差](following-error-window.md)；完整字段和兼容范围见
[诊断说明](step-loss-diagnostic.md)。


## 可选运行期 TMC 状态缓存

`TMCTRACE?` 只读导出 `CONFIG_CARTFSM_TMC_TRACE` 保存的 DRV_STATUS 与 GSTAT 事件窗口。
该配置默认关闭，开启时选择 STEP_LOSS 事件开关，不自动选择软件轨迹或 observe-only。
仅允许在 DISABLED 或 FAULT 且引擎已停、事件后窗已完成或被新运行截断时读取。
它不执行现场寄存器读取，不改变运动、故障、标定或配置状态。

```text
TMCT2 BEGIN <event_id> <run_id> <event_us> <state> <count> <pre_count> <period_us> <post_window_us> <ended_us>
TMCT2 ROW <event_id> <index> <seq> <begin_us> <end_us> <status> <reg> <raw>
TMCT2 END <event_id> <count>
```

所有字段为非负十进制整数，设备时间单位为 µs。字段含义如下：

| 字段 | 约束与语义 |
|---|---|
| `event_id` / `run_id` | 非零事件与运行身份，须与相应 STEP_LOSS 事件匹配；ROW/END 重复事件身份用于核对 |
| `event_us` / `ended_us` | 事件触发和窗口结束的设备单调时间；不得用主机到达时间替代 |
| `state` | 1 表示设备时间已达到 event_us + 5000000；2 表示新运行提前结束旧窗口，不应视作完整后窗 |
| `count` / `pre_count` | 总记录数最多 284，前窗最多 80，后窗最多 204；允许零条，不代表驱动正常 |
| `period_us` / `post_window_us` | 轮次等待间隔 50000、后窗时长 5000000；实际间隔由样本时间计算 |
| `index` / `seq` | index 从 0 连续至 count−1；seq 严格递增但允许间断；锁忙/读取失败也有序列 |
| `begin_us` / `end_us` | MCU 尝试读取前后的时间，end >= begin；锁忙的两时刻也不保证相等 |
| `status` / `raw` | status=0 时 raw 为所标寄存器的有效 uint32；1 为 UART 锁忙，2 为读取错误，后两者 raw=0 仅占位，不得解码为无告警 |

前窗记录 end 在 `[event_us−2000000, event_us]` 内，后窗 end 在
`[event_us, event_us+5000000]` 内。事务跨过事件时刻归后窗；已提交记录与事件同微秒
时可以属于前窗，由 pre_count 明确分界。跨截止时刻的结果不采入；窗口按真实时间结束，
不是按样本数量计算 5 秒。跨运行的在途读取结果不混入新运行。

拒绝/失败行：`ERR TMCTRACE_DISABLED`（未编入）、`NONE`（无事件记录）、
`UNAVAILABLE`（诊断运行资源不可用）、`BUSY`（运行、减速、后窗采集中等不可读取状态）、
`CHANGED`（导出期间快照改变）、`FORMAT`（组帧失败）；后五项同样带 `TMCTRACE_` 前缀。
任何错误、缺行、重复索引、身份混用或 END 计数不符都不能视为有效完整报告。

本协议读取低频缓存，不能排除样本间瞬态或所有供电问题，不提供告警位永久锁存保证。
工具、原厂位语义和观测限制见[运行期 TMC 诊断](tmc-runtime-diagnostic.md)。

TMCT2 的 `reg` 为 1（GSTAT/0x01）或 111（DRV_STATUS/0x6F），其他寄存器值非法。
每轮依次独立尝试 DRV_STATUS、GSTAT，最后等待 50 ms；两个事务各自带时间戳和状态，
可分属不同事件窗口，不能合并为同步快照。统计间隔必须按寄存器分别计算；运行/模式切换可能取消第二次读取，不能要求行严格交替或成对。

旧 TMCT1 的 BEGIN/END 字段顺序相同，ROW 没有 reg 字段，所有记录均为 DRV_STATUS；
容量为前 40、后 102、总 142 条。新版采集工具兼容 TMCT1，但输出的 version 仍为 1，
不宣称拥有 GSTAT 证据；TMCT2 输出 version=2，不能在一次应答中混用版本。
GSTAT 的 R+WC、上次读取以来措辞及 uv_cp 非锁存限制见运行期诊断指南；本功能不发送寄存器清除写入。

### 统一加减速度配置

`ACC_MAX` 同时控制正常速度斜坡、`VEL 0`、命令看门狗与受控故障停车。`WDT_MS` 仅控制无有效命令等待时间，故障断电或驱动失效不保证能执行受控减速。配置查询只报告 `ACC_MAX`，不再接受或报告独立的 `WDT_DEC`，旧命令不作兼容。两项原本都是运行时RAM配置，本次不涉及NVS迁移或擦除；FAULT状态仍不允许写配置。

### 摆杆测量失效首证据 `POLEDIAG?`

仅编入 `CONFIG_MAGNETIC_ENCODER_POLE_DIAGNOSTICS` 时可用；查询只允许 DISABLED 或 FAULT 且已结束故障减速。查询不使能、不清除记录、不重新读取 SPI。每次成功 ENABLE 按运行身份重新布防；失败的 ENABLE 不清证据。启动运行身份为0。

```
POLED1 BEGIN <run_id> <captured> <transitions> <dropped>
POLED1 BEFORE <observed_us> <sampled_us> <age_us> <fill> <required> <span_us> <gap_us> <seq> <failure_seq> <continuity_seq> <has_sample> <last_attempt_ok> <ok> <velocity_valid> <reason_bits> <raw_counts> <status>
POLED1 AFTER  <同 BEFORE 字段顺序>
POLED1 FAIL <kind> <failure_seq> <failure_us> <b0> <b1> <b2> <b3> <b4> <b5>
POLED1 END <run_id>
```

`captured=0` 时只有 BEGIN/END，不伪造快照。`captured=1` 表示本运行先出现有效样本，随后保存了首次观测到的无效条件；此后恢复或失效不覆盖首证据。BEFORE 是本运行失效前最近有效观测，不保证紧邻硬件采样。AFTER 是失效观测，SPI失败清窗时 `fill` 可为0。`transitions` 是本运行观测的有效到无效次数；`dropped` 是启动以来日志队列丢弃累计，均饱和而不回绕。

时间均是设备启动后的单调微秒；`age_us` 为观测时点减最近成功采样时点，无样本为-1，时钟回退也可能为负。`fill/required` 是窗口已有/所需点数（17或33），`span_us` 为实际速度窗跨度，`gap_us` 为连续性预算；三个序列区分成功采样、读取失败和连续性中断。布尔字段只允许0/1；`raw_counts/status` 是缓存成功样本，不是失败帧解码结果。

原因位图可同时成立：1无样本、2最近读取失败、4健康位无效、8窗口未满、16窗口跨度超限、32样本过期、64时钟回退、128速度计算无效且未细分。该位图解释软件判据，不直接证明硬件根因。

FAIL 的协议分类为0无失败、1 SPI事务错误、2全零帧未确认、3 CRC不符；后六项为0..255的原始字节。FAIL保存冻结时最近一次读取失败，必须比较失败序列/时间与AFTER，不能将历史失败直接归因于当前过期或窗口错误。全零帧无法区分合法零角与线路全低，当前仍保守拒绝，不声称已经解决合法零角可用性。

错误使用 `ERR POLEDIAG_DISABLED`、`POLEDIAG_NONE`、`POLEDIAG_BUSY`、`POLEDIAG_FORMAT`，分别表示未编入、无绑定编码器、当前不可导出和格式错误。操作与验证边界见[摆杆失效诊断](pole-diagnostic.md)。


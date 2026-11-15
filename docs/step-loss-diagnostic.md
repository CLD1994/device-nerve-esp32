# STEP_LOSS 故障快照

## 何时开启

这是排查失步原因的可选诊断功能，默认关闭。需要采集触发证据时，在
`idf.py menuconfig` 的 `cartfsm - 模式机` 中开启
`CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS`，重新构建并烧录。排查完成后关闭此项。

关闭时仍执行失步检测和故障停车，但不分配快照记录、不读取快照专属元数据、
不采集比较时间或维护诊断会话号；`STEPLOSS?` 在任何模式均返回
`ERR STEPLOSS_DISABLED`。关闭期间的故障不能在日后开启诊断后补采。

以下记录与导出行为仅适用于开启诊断的固件。

## 记录时刻与保障边界

监督任务沿用当前配置的累计误差或窗口增长判据。`TRIGGER` 区分硬限、
连续增长或传统阈值；诊断不修改任何阈值或运动参数。
模式机接受故障后，先提交斜坡停车，再复制一条固定大小RAM记录。
实时路径不格式化、不发送串口、不动态分配内存、不写NVS。故障前轨迹见下节。
同一FAULT期间不会反复覆盖首次记录；RESET保留记录，下一次被接受的
STEP_LOSS替换它。后续POWER等故障不覆盖此记录；它不是当前MODE原因的别名。重启、烧录或断电后记录丢失，不能追溯此前故障。

E位置与编码器时间、序列、速度来自同一次快照，这个E实际参与本次比较。
C读取发生在之后，记录读取前后时间包络，**不声称E/C同时采样**。
C是固件软件STEP累计位置，不是外部逻辑分析仪测到的实际脉冲或机械位置。
MODE FAULT输出在故障停车完成后发生，不能用它的主机接收时间代替触发时间。

诊断元数据不可取得时使用标量位置读取执行相同阈值判断，并记录
`META_AVAILABLE=0`。时钟顺序异常同样不屏蔽故障，只在读出时报告
`TIME_ORDER_OK=0`。元数据缺失时编码器附加字段的零值不是有效测量。
开启诊断后，同快照读取与设备时间采集仍有执行成本，需要真机验证，不能
由宿主测试断言对监督时序零影响。

## 只读导出

仅在DISABLED或FAULT已完成停车时执行，READY或FAULT仍在减速时返回
`ERR STEPLOSS_BUSY`；没有记录返回`ERR STEPLOSS_NONE`。诊断不会自行停机、
复位、清故障、配置或使能。请勿同时运行其他占用控制串口的工具。

```powershell
python tools/step_loss_capture.py --port COM11 --baud 460800 --out step-loss-evidence.json
```

工具只发送`STEPLOSS?`，检查完整写入，不调用可能无限等待驱动排空的`flush`。
接收期限从写入返回后开始计算，串口读取本身仍有短超时；这不是整个程序
或文件写入严格3秒完成的保证。收到完整同一事件后才保存新文件，不覆盖已有文件。
若当前正处READY，先使用既有安全停机流程处理；不要为读取记录发送RESET
来掩盖尚未确认的现场状态。记录只能说明触发时比较了什么，不能单独证明
物理失步、皮带打滑、接线正确或实际STEP波形正确。

线协议是显式查询应答，不主动混入遥测：

```text
SL1 <event_id> VERSION 2
SL1 <event_id> <field> <integer>
...
SL1 <event_id> END 1
```

STATE、VEL_VALID等常规行可在应答之间出现，专用工具只忽略完整合法的
这些背景行；拒绝不同event_id拼接、重复字段、未知字段、缺失字段和超时。
未实现SL1解析的工具，不应在查询期间同时读取串口。

## 字段语义

- `RUN_COMPARE`、`RUN_ACCEPT`：比较开始时与模式机接受时的使能会话编号。
  两者不同表示中间发生会话切换，不能直接用于同一次运动归因。
- `T_COMPARE_US`：位置差判定成立后的设备单调时间；`T_ACCEPT_US`是进入
  故障转换锁后接受故障的时间，不是UART输出时间。
- `C_BEGIN_US`、`C_END_US`：C读取时间包络；`TIME_ORDER_OK`检查这些设备时标顺序；为0时不能按这些时标直接归因运动时序。
- `E_SENSOR_UM`：传感器快照转换位置；`E_COMPARED_UM`是实际比较输入。
  构建启用测试注入时，两者可能不同；不能将注入后的E称作实测。
- `C_UM`、`ERROR_UM`、`THRESHOLD_UM`：本次使用的C、带符号E−C和阈值。
- `TARGET_ACCEPT_MM_S`：故障被接受时、停车修改前的目标速度，不是实测车速。
- `META_AVAILABLE`：是否取得同一编码器快照。0时其余编码器附加字段不可用于推断。
- `ENC_V_MM_S`、`ENC_V_VALID`、`ENC_SPAN_US`：滤波速度、有效位和实际窗口跨度。
- `SAMPLE_US`、`AGE_US`、`SAMPLE_SEQ`：成功读帧完成时间、比较时样本年龄和序列。
  年龄无法计算时为−1；有效位与年龄不能由日志传输速度替代。
- `FAILURE_SEQ`、`CONTINUITY_SEQ`、`GAP_US`：读取失败历史、连续性历史、实例预算。
- `SAMPLE_VALID`、`LAST_READ_OK`：是否已有成功样本、最近一次读帧是否成功。

## 离线验证

宿主运行脚本分别编译诊断开启和关闭两种配置。关闭配置验证正负方向失步检测、
阈值边界、故障斜坡停车与停稳禁用、查询拒绝，以及不读取诊断元数据或时钟。
`host_tests/cartfsm_step_loss_diag_test.c`使用隔离替身测试3000/3001µm边界、
正负方向、同一比较输入、故障停车期间不打印、首次记录保持、RESET保持、
元数据/时钟异常仍故障、停稳导出及解析命令。`tools/test_step_loss_capture.py`
覆盖完整应答、事件混合、字段重复/缺失、未知行和拒绝应答。测试不操作设备。

```bash
bash host_tests/test_cartfsm_step_loss.sh
bash host_tests/test_cartfsm_calibration.sh
bash host_tests/test_measurement_validity.sh
python -m unittest discover -s tools -p test_step_loss_capture.py
```

模式机测试链接独立编译的生产模块，通过命令注册入口、公开状态查询和
任务注册入口驱动行为。共享测试夹具提供存储、时钟、轴和传感器替身，
不包含生产实现文件，也不读取或修改模式机内部变量。


## 故障前监督轨迹与 WDT 时间顺序修复

开启同一 `CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS` 后，监督任务维护128条固定内存环形记录。
普通记录至少相隔5ms，触发拍强制追加；约覆盖最后0.64秒，但时间跨度以记录时标为准，
不是精确采样周期。模式机接受STEP_LOSS、提交停车后，把尾段复制到独立冻结缓冲。
两个缓冲在宿主编译布局合计30KiB（目标实际用量以构建map为准），没有实时串口流量。
RESET及下一轮ENABLE不清冻结证据，下一次STEP_LOSS才替换；重启、烧录、断电丢失。

保持停止状态，关闭其他占用COM11的程序，在Windows运行：

```powershell
& $python .\tools\step_trace_capture.py --port COM11 --baud 460800 --out $traceReport
```

`$traceReport`须为新的JSON文件路径。工具在打开前将DTR/RTS设为false，然后只发一次
`STEPTRACE?`；这降低打开串口触发自动复位的风险，但不保证驱动不存在瞬态。
只在停稳的FAULT或DISABLED允许读取，忙碌、缺记录和诊断关闭沿用STEPLOSS错误码。
旧 `STEPLOSS?` 和现有SL1字段不变，新的独立命令不会给旧解析器追加未知字段。

旧版 SLT1 协议（85c9fa2）：`SLT1 event BEGIN count run`，依次`SLT1 event ROW index <21整数>`，
最后`SLT1 event END count`。21列的权威顺序见
[`step_trace_capture.py` 的 FIELDS](../tools/step_trace_capture.py)。设备端顺序与此对应。

- E、sample_seq、raw_counts、sample_us来自同一编码器快照，raw_counts是实现方向处理后的单圈值。
- C是随后读取的软件STEP累计，c_begin_us/c_end_us包住该次读取；E、C和引擎快照并不同步。
- observed_us是准备记录的设备时间，不是引擎快照完成时间。target_mm_s是记录时固件接受的目标。
- engine_v_q16 / engine_target_q16为有符号steps/s乘65536；engine_position_steps为软件STEP计数。
- engine_stopped和engine_timer_running是软件标志。部分现有写路径在引擎锁外，不能把整行当原子硬件快照。
- wdt_stale_time_count统计ISR入口时间早于后来接受的喂狗时刻的次数；修复后该拍按未超时处理。
  wdt_expired_count统计真正超时判定次数，不是独立事件数。两者上电累计、UINT32_MAX饱和，停机不清。
- 新守卫防止无符号时间差下溢，保留原有严格大于WDT期限的条件；没有更改超时值、制动或误差阈值。

这些记录能区分软件计数、编码器序列和引擎状态变化，不等于物理STEP、DIR、驱动接收或电机失步证明。
WDT竞态修复不等于已证明解决现场故障；原有停表/启动交错等其它问题仍需独立验证。

### SLT2：STEP 输入路径与 EN 读回

`STEPTRACE?` 现在返回 `SLT2`，保留原 21 列并追加以下 9 列：
`pcnt_count pcnt_valid pcnt_init_error pcnt_read_error pcnt_overflow_invalid pcnt_begin_us pcnt_end_us en_level en_read_error`。
新版 `tools/step_trace_capture.py` 同时读取 SLT1/SLT2；旧脚本不支持 SLT2，请同步工具。

诊断开启时使用一个 PCNT 单元、一个通道，STEP GPIO5 上升沿计数，DIR GPIO6 高时正计数、低时负计数；不启用毛刺滤波。保持输出功能并打开输入路径。EN GPIO21 读回（低有效），仅表征 MCU 引脚输入电平，不等于驱动器内部使能或电机电流。
PCNT 使用 ±30000 硬件限值和溢出累计；软件计数是 32 位：按现有最高 50 kHz，启动后最多一小时有效（单向 1.8 亿步）；计数绝对值达到 INT32_MAX/2 或寿命到期会永久失效并停止观察计数，需重启恢复。任意外部高频输入超出此界限的证明范围。失效时不得将零/旧计数理解为“没有脉冲”。初始化/读取失败单独记录，不改变运动、安全门限或启动条件。

PCNT 是独立的启动后净计数，**不随左标定或软件位置重定基清零**。比较同一有效时间段的 PCNT 增量与 `engine_position_steps` 增量，不比较绝对值。各字段异步读取，以 `pcnt_begin_us/pcnt_end_us` 识别时间窗；邻近边沿允许一两步读数差。PCNT 正负边沿可能抵消，净计数不是总边沿数。

该计数只能证明 MCU 输入矩阵看到了 STEP 边沿，不能证明引脚外连线、TMC 接收、脉宽、驱动电流或机械位移。若软件与 PCNT 同步增长而编码器停住，排查范围转向驱动器/接线/机械及编码器证据；若 PCNT 不增长，先检查有效性、初始化错误和引脚路由，再判断 STEP 输出链。EN 必须看故障前冻结数据，不能将故障后的正常禁用误判为原因。

PCNT 溢出累计由 ESP-IDF 内置中断处理：每单向 30000 步发生一次（50 kHz 时约 0.6 秒）。未修改 STEP ISR、速度设定或门限，但新增 PCNT 中断及约 5 ms 一次诊断读取仍可能造成测量扰动；须现场确认时序，不能宣称零开销。诊断初始化失败不会阻止原运动控制，应先看 `pcnt_init_error`，不要把未工作的诊断当作输出故障。

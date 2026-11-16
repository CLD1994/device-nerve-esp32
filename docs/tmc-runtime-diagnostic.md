# 运行期 TMC2209 驱动状态诊断

该功能在运行期间低频依次读取 `DRV_STATUS` 和 `GSTAT`，保留 STEP_LOSS 事件前后的驱动状态缓存。两次读取是独立事务，不是同步寄存器快照。它不同于停机后执行 [TMC?](tmc-readonly.md) 的即时寄存器查询。此诊断不发送寄存器写入或写 1 清除命令，不修改驱动配置，不自动使能、复位或运动，也不改变 STEP_LOSS 的处置策略。

## 启用与采集边界

`CONFIG_CARTFSM_TMC_TRACE` 默认关闭，启用时自动选择 `CONFIG_CARTFSM_STEP_LOSS_EVENTS`，不选择轨迹诊断或 observe-only，不改变固件因 STEP_LOSS 停车的配置。

在已激活 ESP-IDF 的固件仓库终端执行 `idf.py menuconfig`，进入 Component config → cartfsm 模式机，启用对应 TMC 运行期诊断项；保存后核对 `sdkconfig` 含 `CONFIG_CARTFSM_TMC_TRACE=y`，然后执行：

```bash
idf.py build
idf.py flash
```

串口选择与 ESP-IDF 环境见[入门](getting-started.md)。这些是构建/烧录步骤，不包含运动命令；烧录后参考状态按[标定指南](calibration.md)处理。需要关闭对照时清除该选项再构建烧录。

启用后，低优先级任务每轮先尝试读取 DRV_STATUS（0x6F），再尝试读取 GSTAT（0x01），各自使用零等待锁尝试；两次事务后等待 50 ms，因此同一寄存器的实际起始间隔还包含事务耗时与调度延迟，不补跑迟到采样；记录事务开始/结束时间和结果；锁忙直接记为 busy，读取失败独立记录。共享 UART 的额外事务会增加总线和 CPU 负载，不能声称绝对无阻塞或无调度干扰。应保留关闭诊断的对照运行。

正式固件的常规 VEL、EN、停止路径不访问 TMC UART；但扩展任务通过 settings 或 TMC 写接口更改配置仍可能竞争。采证期间不要同时进行这类扩展配置写入。该功能不证明驱动器收到的物理 STEP、真实相电流或机械运动。

采样任务在没有运行身份时不发起读取；事件前仅在 READY 时发起读取，离开 READY 后不再为前窗开启新事务。事件已触发且后窗尚未结束时，即使进入 FAULT 或 DISABLED，仍可继续采满该后窗；后窗冻结后不再发起读取，直到新运行重新布防。已经在途的事务与是否纳入缓存分别受运行身份和时间窗口检查，不能把查询时静止误认为整段采样均发生在静止时。

每次运行的首个 STEP_LOSS 事件关联 `run_id`、`event_id` 和设备单调时间 `event_us`：

- 事件前保留最多 80 条寄存器事务、最近 2 秒内的样本。
- 事件后按真实设备时间继续采集 5 秒，最多 204 条寄存器事务。不是凑齐记录条数就宣称完成 5 秒。
- 新运行可提前截断旧事件后窗，报告 `state=2`；正常完整结束为 `state=1`。`ended_us` 记录结束时间。
- 事务跨过事件时刻归后窗，但保留 begin/end，不能称作触发瞬间的同步读数。跨运行的在途结果不混入新运行。
- 查询只读取已完成或已截断的缓存；设备运行、减速或仍在采集时拒绝。工具不会为查询改变设备模式。

## Windows 只读导出

先完成当前实验并使设备处于允许查询的停稳状态，避免其他程序同时占用串口。工具不负责停机；不要把下面的查询当作停机命令。使用与已烧录固件匹配的仓库版本，在 PowerShell 执行：

```powershell
$python = 'C:\Users\cldus\IsaacLab\.venv\Scripts\python.exe'
$tool = 'C:\Users\cldus\workspace\device-nerve-esp32\tools\tmc_trace_capture.py'
$out = Join-Path $PWD ('tmc-trace-' + [guid]::NewGuid().ToString('N') + '.json')
& $python $tool --port COM11 --baud 460800 --out $out
if ($LASTEXITCODE -eq 0) { Get-Content $out -Raw -Encoding utf8 }
```

按实际解释器、仓库、串口和波特率替换路径。工具依赖 pyserial，但解析测试不导入串口库、不连接硬件。它只发送一次 `TMCTRACE?`，不会发送 ENABLE、RESET、VEL、配置写入或其他寄存器查询。完整校验后才独占新建输出文件，不覆盖旧报告；超时、缺行、重复行、身份或版本不匹配均报错，不生成成功报告。退出码 0 表示采集结构完整，不表示驱动无故障。

## TMCT2 数据与统计（兼容 TMCT1）

帧定义以[通信协议](protocol.md)为权威。BEGIN 包含事件/运行身份、事件时间、完成状态、总数、前窗条数、目标周期、后窗时长及实际结束时间；ROW 包含事件身份、行索引、采样序列、事务 begin/end、状态、寄存器地址及原始寄存器值；END 再核对身份与数量。

`status=0` 才解码 raw；`status=1` 为锁忙，`status=2` 为读取失败。后两者的 raw=0 只是占位，报告保留该值且 `decoded=null`，不得解释为全部告警位为零。序列严格递增但不要求连续。新报告 version=2，以 `statistics.by_register.GSTAT` 和 `DRV_STATUS` 分别统计有效、锁忙、读取失败数量，以及同一寄存器相邻事务开始间隔和事务时长的最小/最大/平均值；不能将两个不同寄存器之间的间隔当作采样周期。没有可统计间隔时为 null，不用零伪装正常。

新版工具也接受旧固件 TMCT1（仅 DRV_STATUS，最多 40 前/102 后共 142 条），输出 version=1；它不把旧报告补成拥有 GSTAT 数据的新报告。混用版本、寄存器未知或字段数量不匹配均拒绝。TMCT2 最多 80 前/204 后共 284 条，reg=1 表示 GSTAT，reg=111 表示 DRV_STATUS；原始 raw 与每次事务时戳始终保留。

解码依据 [TMC2209 数据手册 Rev1.09](https://www.analog.com/media/en/technical-documentation/data-sheets/TMC2209_datasheet_rev1.09.pdf)及[现有驱动定义](../components/tmc2209/tmc2209.c)：OTPW/OT、S2GA/B、S2VSA/B、OLA/B、CS_ACTUAL、STEALTH、STST，并始终保存 raw。CS_ACTUAL 是寄存器刻度，不是实测相电流。OLA/OLB 必须结合当时速度、电流和工作模式解释，不能单凭停机后的位值断定运行中断线。

## GSTAT 读取与标志生命周期

依据上述原厂 Rev1.09 第 24 页，GSTAT 的 bit0=reset、bit1=drv_err、bit2=uv_cp。表头标为 R+WC，并说明写 1 清对应标志；reset 和 drv_err 的文字同时用“上次读取以来”描述。因此不能未经板端核验便承诺读取绝无标志副作用，也不能断言每次读都会清除。工具保存每次 raw，不发送清除写入，不自行重置驱动。

`drv_err` 表示驱动曾因过温或短路关断，并注明仅当错误条件消失后才可清除；持续为 1 可能是历史锁存，不能把每一行 1 当作新故障或直接归因本次供电。`uv_cp` 明确不是锁存位，不需要清除，短暂欠压可能在两次轮询间消失。reset=1 也不是已定位到本轮的独立复位事件。读回/清除行为及板端时序仍需实测。

增加 GSTAT 使每轮最多多一次 UART 事务，实际负载和轮次间隔都可能上升。DRV_STATUS 与 GSTAT 即使相邻两行也具有独立 begin/end，事件前后归属分别判断；不按两行配对推断同时发生。运行或模式切换可能取消第二次读取，因此导出行不保证严格交替或成对。

## 如何解释证据

用户最新提供的现机铭牌为 **42BYGH47-401AS，1.7 A、1.8°、0.55 N·m**。铭牌电流的 RMS/峰值口径与当前驱动配置尚未核实；旧型号的 0.9 A 不能用于判断现机。铭牌额定值、settings 请求电流、CS_ACTUAL 刻度和实测相电流不是同一证据，本诊断不会据此调整电流。

- OTPW/OT 是过温预警/关断状态；S2G、S2VS 是相应短路状态。若出现，结合事务时间与事件窗口定位，不把低频读取称为精确故障时刻。
- 无这些标志不能排除驱动原因。采样间瞬态可能漏掉；温度下降或 ENN 禁用、TOFF=0 等状态变化可能使相关标志消失，必须结合具体位的芯片语义。
- GSTAT.uv_cp 只能反映读到时的电荷泵欠压状态，不能替代 VBUS 测量，也不能排除所有供电问题。不要将“未检出过温/短路/uv_cp”扩展成“供电和驱动一定正常”。
- 停机后查询只取运行时缓存，不再现场读取 DRV_STATUS 作为事件证据。没有事件、功能关闭或未形成可读缓存，必须保留相应错误，不能报告空白正常数据。
- 需要在真实目标上验证任务开销、串口交付、采样间隔与板端故障行为。宿主协议测试不能替代 ESP-IDF 构建和台架测量。

固件宿主测试：`bash host_tests/test_tmc_trace.sh`（缓存窗口、任务适配、协议开关）及 `bash host_tests/test_tmc.sh`（UART 只读与锁忙）。这些测试不证明 ESP-IDF 的双核调度或电气行为。

主机解析测试：`python -m unittest discover -s tools -p 'test_tmc_trace_capture.py'`；全套工具回归见[工具目录](../tools/README.md)。

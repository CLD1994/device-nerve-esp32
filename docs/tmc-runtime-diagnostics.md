# TMC 运行期状态记录

`CONFIG_CARTFSM_TMC_TRACE` 默认关闭。开启后，独立任务记录 TMC2209 的
`DRV_STATUS` 与 `GSTAT`，并保存本轮第一次 `STEP_LOSS` 前后的软件读取结果。
它只提供故障分析证据，不改变电流、使能、运动目标或故障停车规则。
当前停止态的寄存器查询另见 [TMC 只读诊断](tmc-readonly.md)。

## 采集与运行身份

每次成功 `ENABLE` 分配新运行 ID。采集任务在 CPU0、优先级1运行，完成一轮
两个独立寄存器事务后等待50ms；调度和 UART 耗时会使实际间隔更长，不补采错过的时点。
UART 互斥锁忙时立即记录 `BUSY`，不会等待锁；取得锁后的 UART 事务仍可能等待响应超时。
监督任务和 STEP 中断不执行这些读取。一次跨越新运行开始的读取结果会被丢弃。

首次 `STEP_LOSS` 用事件 ID 关联固定缓冲。最多保存事件前2秒、80条事务和事件后
5秒、204条事务；两个寄存器各占一条。事件处理只交换缓冲，不复制整段记录。
采集时间窗结束后冻结；新运行提前开始会截断旧窗口，并保留旧证据直到下一事件覆盖。
默认关闭时不创建采集任务或轨迹缓冲，也不额外访问 UART。

记录时间是软件 UART 调用的开始与结束，不是驱动芯片内部锁存时刻。
两个寄存器不是同时读取。成功读到零与读取失败不同；失败或忙状态的 `raw=0`
只是占位，不能解码成“没有故障”。GSTAT 读取可能影响驱动历史标志，不能视为
完全无观测影响的测量；程序不发送 GSTAT 写清命令。记录不能证明实际相电流、
故障瞬间的驱动状态或丢步根因。

## 停机后导出

仅 `DISABLED` 或已完成停车的 `FAULT` 允许 `TMCTRACE?`。查询只导出冻结的内存
记录，不读取驱动、不清除记录、不自动禁用或复位。窗口仍在收集时返回忙，应等待
窗口结束。上位机查询与 `ENABLE` 由同一命令任务串行执行。

```powershell
python tools/tmc_trace_capture.py --port COM11 --baud 460800 --out tmc-trace.json
```

协议使用整数、空格分隔，每行以 LF 结束：

```text
TMCT2 BEGIN event_id run_id event_us state count pre_count period_us post_us ended_us
TMCT2 ROW event_id index seq begin_us end_us status reg raw
TMCT2 END event_id count
```

- `state=1` 表示到达窗口尾，`state=2` 表示新运行截断；`0` 仍在收集中，不导出。
- `index` 从0连续递增；`seq` 是已接收事务的递增序号，跨运行保留。
- `status` 为0成功、1锁忙、2读取失败；`reg` 为111（DRV_STATUS）或1（GSTAT）。
- `pre_count` 是事件前已纳入记录的条数。时间恰好等于事件时刻时，已入缓冲的
  事务属于前窗，在途后提交的事务属于后窗，不能只依时间相等重新分类。
- `period_us` 是轮次之间的等待时间，`post_us` 是事件后窗口长度，不代表实测采样周期。

错误码：`TMCTRACE_DISABLED` 未编入；`TMCTRACE_UNAVAILABLE` 任务未创建成功；
`TMCTRACE_NONE` 尚无事件；`TMCTRACE_BUSY` 设备未停稳或窗口仍收集；
`TMCTRACE_CHANGED` 导出记录身份变化；`TMCTRACE_FORMAT` 输出格式化失败。
重启会清空 RAM，事件与运行 ID 不保证跨重启唯一。

## 软件验证与待验范围

```bash
bash host_tests/test_tmc_trace.sh
bash host_tests/test_tmc.sh
```

核心测试验证窗口边界、容量、首事件和跨运行丢弃。任务测试通过任务调度、时钟及
驱动公开接口替身验证采集和导出；命令集成测试验证开关与运行态门禁。UART 测试
验证响应身份、CRC、回声与非等待式锁获取。目标构建和真实硬件时序、UART竞争、
运行期性能须分别验证，宿主测试通过不代表这些现场性质已获验证。

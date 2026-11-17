# 统一 STATE 状态流验证

## 线格式与范围

目标500Hz（2ms），单条可读十进制 `STATE flags x theta vx vth`。每路有效位与测量同帧，无效路0占位解码为缺失值。详细单位和语法见[协议](protocol.md)。旧四字段STATE、VEL_VALID及CART_STATE1不兼容。

固件负责检查采样新鲜、最近读取成功、速度窗口和连续性；这些条件是组帧前判断。vel仅要求小车路，其它双路工具及模型要求两路。真实FAULT不豁免。

调度目标来自 `telemetry_timing.h`，超过周期后重基准、不追赶历史帧；任务、UART锁及发送队列仍可能延迟。默认1kHz FreeRTOS tick，可表示1ms的配置有编译检查。

## 带宽及未验证边界

合法帧含LF为16..53字节。500Hz最宽帧占26500B/s；460800 baud 8N1单向容量46080B/s，约57.5%，余19580B/s供MODE/EVENT/回复。当前Kconfig默认1M不代表现场配置，必须按真实构建匹配。下行命令在另一方向，但资源仍共享。

512字节TX缓冲在460800下约11.1ms，缓冲不能增加带宽；大诊断响应要求停机，短查询/事件仍有突发。500Hz帧率和400Hz模型时序须现场验证，软件测试不证明通过。

没有tick/age/seq/boot，主机不能识别设备采样重复、相对输运积压或所有重启。刚收到的有效帧也可能已在UART/USB滞留。仍保留接收超时、缓冲积压限制、模式及命令期限，但它们不证明端到端新鲜度。没有CRC，UNKNOWN=0不能证明无合法数值损坏。

## 不驱动电机的验收

保持 DISABLED，关闭其它串口占用，以现场 COM11/460800 为例：

```powershell
python tools/cartpole_host.py --port COM11 --baud 460800 query
python tools/cartpole_host.py --port COM11 --baud 460800 state --secs 30 --expected-hz 500
```

状态命令不发送运动目标；它统计所需双路均有效的 STATE，不是全部线上帧率。无效帧即使格式合法也不计入有效 STATE，未指定频率时有数据并不证明期间没有无效帧。频率±1Hz、无未知行只是有效帧接收验收，不是有效性、物理比例或端到端延迟证明。检查多次长采集、帧间隔/尾延迟、排队和有效路变化；不要逐帧打印而拖慢接收。未解决通信异常前不据平均频率扩大运动范围。

## 无硬件回归

```bash
bash host_tests/test_telemetry_timing.sh
python -m unittest discover -s tools -p 'test_*.py'
```

Python需要pyserial，测试用替身不连接串口。格式回归覆盖四种有效组合、极值、无效占位、固件年龄失效、主机接收超时及损坏；目标ESP-IDF构建与跨仓库消费者验证另记录，均不替代硬件验收。

# STATE 状态流验证

## 范围与兼容性

固件以500 Hz（每2 ms）为STATE报告目标。消息名称、字段顺序、单位、
换行格式和各模式持续报告的行为不变；现有行解析器可以继续使用。
编码器采样仍为1 kHz，速度估计仍跨16个计划采样间隔，不把推理耗时等同于
可用观测或闭环频率。本阶段不启用1 kHz报告。

[调度常量](../components/telemetry/telemetry_timing.h)是代码中的速率来源。
默认 `CONFIG_FREERTOS_HZ=1000`；编译检查同时覆盖编码器已有的1 ms节拍要求。
能精确表示1 ms的其他tick频率允许通过，不能表示的配置明确编译失败。
不得用增加tick频率来绕过系统级调度验证。

`vTaskDelayUntil` 是调度目标，不保证每帧精确间隔2 ms。高优先级任务、
UART发送队列和主机接收都可能带来延迟或突发。发送缓冲不能增加持续带宽。

## 不驱动电机的现场验收

保持DISABLED，先关闭其他占用控制串口的程序。沿用已经验证过的控制口和
匹配的固件波特率，不因本次升级顺带改波特率、编码器配置或电机参数。
以Windows控制口COM9、460800为例（端口按实际替换）：

```powershell
python tools/cartpole_host.py --port COM9 --baud 460800 query
python tools/cartpole_host.py --port COM9 --baud 460800 state --secs 30 --expected-hz 500
```

`query` 必须确认 `MODE DISABLED NONE`。第二条仅接收状态，不发送运动命令。
`--expected-hz` 的频率容差为±1 Hz；同时要求至少收到一帧且UNKNOWN为0，
否则退出码为1。省略该参数只报告实测频率、检查有数据和UNKNOWN，
**不代表500 Hz验收通过**。旧固件可显式传 `--expected-hz 200`。

建议连续重复30秒采集，并做数分钟持续接收；保存原始字节与接收时间时，
避免逐帧打印拖慢接收。检查：

- 平均帧率、异常行与查询应答；平均值不能替代帧间隔或尾延迟分布。
- 接收程序是否积压旧帧；控制端应消费最新完整状态，不逐条回放积压数据。
- 在已确认安全、驱动禁用且可手动移动的条件下覆盖位置/速度字段变长的情况。
- 主机重新打开端口后是否恢复正常；打开边界上的半行不与持续运行中的损坏混为一谈。

现有ASCII行没有序号、时间戳或CRC。UNKNOWN为0不能证明没有整帧遗漏或
仍可解析的数值损坏；严格时延和完整性测量需要独立仪器或另行设计的诊断。
任何通信异常未解决前，不凭平均500 Hz结果继续加速度或运动测试。

## 带宽与回退

8N1每字节占10位，460800的单向理想容量为46080字节/秒。
静止示例 `STATE -249 3141592 0 0\n` 含换行23字节，500 Hz占25.0%；
四个int32字段最宽文本含换行54字节，500 Hz占58.6%。实际角度范围可缩短
部分帧，但不应只用静止帧估算运动时的流量。MODE/OK/ERR共享发送容量。

这些数值只说明理论容量，未证明适配器、USB驱动或当前任务负载下的性能。
230400及115200不足以覆盖上述最宽帧持续500 Hz，不能作为直接降档回退。
遇到问题先保留日志，再回到先前已验证的固件/频率组合；不要在同一实验中
同时改变波特率、状态帧格式和采样率。1 kHz报告要在500 Hz实测后另行评估。

## 无硬件回归

以下为持续维护的代码与编译契约测试，不连接串口：

```bash
bash host_tests/test_telemetry_timing.sh
cc -std=c11 -Wall -Wextra -Werror \
  -Ihost_tests/stub -Icomponents/telemetry/include \
  host_tests/telemetry_format_test.c components/telemetry/telemetry_format.c \
  -o /tmp/telemetry_format_test
/tmp/telemetry_format_test
python -m unittest discover -s tools -p test_cartpole_host.py
```

Python测试需要pyserial，串口使用替身。编译契约测试覆盖合法tick以及
会截断/不能精确表达1 ms的配置；宿主组帧测试验证宽帧长度及现有字段格式。
这些测试不替代ESP-IDF目标构建、任务调度或真实UART验收。

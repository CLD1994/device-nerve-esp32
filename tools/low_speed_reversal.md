# 低速连续目标变化探针

`low_speed_reversal.py` 复用 `probe_link.py` 会话、标定预检和
`low_speed_probe.py` 停稳确认。无需修改或烧录固件。

固定目标依次为 +20、+5、+20、−20、−5、−20、+20、−20 mm/s，每段
250 ms，共 2 秒。阶段之间直接改变目标，不先等待物理停稳；实际速度仍由固件
梯形加减速产生，因此不保证每段都达到目标速度。工具不自动回中、使能或清故障。

## 执行前提与配置

保持摆杆自然下垂，勿运行模型控制器或其他占用串口的软件。人工核实电源为20V、
编码器位置比例、两侧净空及独立断电。示波器 CH1 测 STEP；可用20 ms/div Single
观察起步，后续变化需另选触发位置或扩大可用采集窗口。一次短记录不代表全程。

`run` 要求 READY NONE，标定有效，起步速度绝对值≤1 mm/s。
它设置 VEL_MAX=20、ACC_MAX=所选加速度、WDT_MS=100、WDT_DEC=100；退出后保持这些值。
加速度默认100 mm/s²，显式传入 `--acceleration 10000` 可使用10000 mm/s²，
仅改变 ACC_MAX；速度、时长、位置预算、看门狗减速度及其他门控均不变。
10000使换向更急，可能增加机械冲击；WDT_DEC仍为100，不随正常加速度提升。运行前后无需修改 STEP_LOSS 判据。

非零目标最多发到2秒截止点，每25ms重发；主机迟到超过50ms、状态失效或固件
故障则中止。每个收到的位置检查轨道边界和起点±30mm预算。边界沿用预检：
半行程减固件 X_MARGIN_UM 再减50mm。这是诊断探针自身的局部预算，不改生产控制器。

退出路径尝试 VEL 0，并在收到连续200ms低速且位移≤100μm的状态后发送 DISABLE。
停稳确认最长1秒；未确认时要求人工断电，不自动清除FAULT。主机时间限制不是硬实时
保证，系统卡顿时仍依赖固件看门狗；位置预算也不是物理停止距离保证。

## Windows PowerShell

在包含本文件的固件仓库目录执行，`$python` 使用安装了 pyserial 的解释器：

```powershell
$python = 'C:\Users\cldus\IsaacLab\.venv\Scripts\python.exe'
$log = Join-Path $env:TEMP ('low-reversal-' + [guid]::NewGuid().ToString('N') + '.jsonl')
# 可选：DISABLED下只读预检，需使用另一个唯一日志名。
# & $python .\tools\low_speed_reversal.py --port COM11 --baud 460800 --out $log plan
& $python .\tools\cartpole_host.py --port COM11 --baud 460800 enable
if ($LASTEXITCODE -eq 0) {
    & $python .\tools\low_speed_reversal.py --port COM11 --baud 460800 --out $log run --confirm-motion --acceleration 10000
    "探针退出码：$LASTEXITCODE"
}
& $python .\tools\cartpole_host.py --port COM11 --baud 460800 query
"日志：$log"
```

如果启动前参数/文件错误导致探针未打开串口，现场应另行 DISABLE；不要把退出码0
解释为机械运动正确。模式为FAULT时保留故障并采集诊断，不自动RESET或重新ENABLE。

日志用 perf_counter 的主机时间记录每条发送命令、原始接收块和编码器批次。
`encoder_batch.states` 每行顺序为 x_um、theta_urad、velocity_mm_s、angular_velocity_mrad_s；
`target_mm_s` 是最近成功写入串口的目标，不是固件接受时刻或实测速度。
一批STATE共享主机记录时刻，不代表传感器同时采样。本工具不读软件STEP计数C，
不能单凭它证明电气脉冲或电机失步；需结合示波器与故障冻结证据。

验证范围：语法编译、CLI帮助及差异检查；未实机运行，不宣称已复现故障。

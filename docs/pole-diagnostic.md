# 摆杆测量失效诊断

`STATE flags=1` 表示小车测量有效、摆杆测量无效，不是 STEP_LOSS 标志。一次读帧失败就会重置角速度窗口；也可能因窗口未满、跨度过大或样本过期而失效。健康位连续失败阈值与速度窗口有效性不同。本功能保存软件判据证据，不放宽门禁，也不自动使能或复位。

## 构建与只读收集

在 `idf.py menuconfig` 的 **Component config → magnetic_encoder - 磁编码器类别** 中启用 `MAGNETIC_ENCODER_POLE_DIAGNOSTICS`（默认关闭），按现有目标板配置构建烧录。用户实际目标构建结果和装置采样性能仍需单独验证，宿主测试不能替代。

每次成功 ENABLE 会按运行身份重新布防首记录；窗口和保护本身不重置。发生异常并结束运动后，在 DISABLED 或已经结束故障减速的 FAULT 状态读取，**先读取证据，再开始下一次运行**。查询不会清记录，不要求为采证再次运动。

```powershell
$poleTool = Join-Path $firmwareRepo 'tools\pole_diag_capture.py'
$poleReport = Join-Path $exportRoot ('pole-diag-' + [guid]::NewGuid().ToString('N') + '.json')
& $python $poleTool --port COM11 --baud 460800 --out $poleReport
if ($LASTEXITCODE -ne 0) { throw '摆杆诊断读取失败，不使用不完整报告' }
Get-Content $poleReport -Raw -Encoding utf8
```

`$firmwareRepo` 应指向当前固件仓库，`$exportRoot` 是已有报告目录。工具只发送 `POLEDIAG?`，验证版本、顺序、字段范围与BEGIN/END运行身份；只在完整响应后新建JSON，保留诊断原文，不覆盖已有文件。明确拒绝时按错误处理，不自动修改设备状态。

## 如何解释

先看 `captured` 和 `run_id`，确认是否属于刚结束的运行。尚未捕获不表示所有数据都正常：从未形成有效窗口就持续无效、未被观察到的短暂失效等不构成已捕获转换。比较BEFORE/AFTER的窗口、时间、序列与原因位图；然后检查FAIL是否确属该次失败。字段权威定义见[协议](protocol.md#摆杆测量失效首证据-polediag)。

全零响应可能来自合法零角，也可能是线路全低。没有独立健康证据时当前继续保守拒绝，不能凭CRC为0断定通信正常，也不能把全零断言为断线。当前修订增加回归测试和明确诊断语义，没有解除这一歧义。

## 采样日志与影响边界

采样线程中的运行期失败、恢复和STATUS变化只写固定长度RAM事件；低优先级消费者在采样锁外格式化输出，队列满时保留首失效证据并累计丢日志数量。消费者复用统计任务，统计开关关闭时也需要消费原本的运行期日志，因此会有低优先级任务；消费者创建失败可见，RAM记录仍有界保留。初始化日志不属于运行期采样路径。

可选首证据诊断不增加SPI采样，但锁内元数据复制仍有成本；低优先级日志也有系统和USB输出开销。默认诊断关闭不保存首快照。不能宣称对实时性能完全零影响，比较实验须保持构建选项一致。诊断不证明磁场、电气连接或真实机械运动，也不保证捕获每个短暂故障。

离线回归入口：
```bash
bash host_tests/test_mt6835_hw.sh
bash host_tests/test_pole_diagnostic.sh
```
该测试验证读帧契约与保守全零处理，不连接设备。

POLED1 格式检查同时模拟目标工具链 `uint32_t` 为 `unsigned long` 的参数类型，并以 `-Werror=format` 编译诊断开/关路径；这只是宿主类型拼写回归，不替代 ESP32-S3 的 ESP-IDF 目标构建。

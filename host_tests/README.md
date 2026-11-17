# 宿主测试

本目录使用 C 编译器和软件替身验证固件局部契约，不需要连接设备。
它不同于 [ESP-IDF 测试镜像](../test/README.md)，不能证明目标构建、双核调度、
SPI/UART 电气时序或真实运动。测试分类与替身规则见[测试规则](../.agents/rules/testing.md)。

在仓库根目录按需串行执行；脚本使用临时路径，未经隔离不要并行跑同一组：

```bash
bash host_tests/test_cartfsm_calibration.sh
bash host_tests/test_cartfsm_power.sh
bash host_tests/test_cartfsm_step_loss.sh
bash host_tests/test_encoder_sampling.sh
bash host_tests/test_encoder_2khz.sh
bash host_tests/test_measurement_validity.sh
bash host_tests/test_telemetry_timing.sh
bash host_tests/test_tmc.sh
bash host_tests/test_settings_startup_current.sh
```

各脚本定义具体编译源、替身和断言范围。更多纯函数测试如电流时序、PD状态、摆角和换算，
命令见[目标测试指南中的宿主章节](../test/README.md)，不要把上述列表称作全仓测试集。
编码器连续性替身见 [encoder_reference_stubs](encoder_reference_stubs/README.md)。

Python 主机工具测试在 [tools](../tools/README.md)，不属于这里的固件 C 测试。
正式固件不得链接 `host_tests` 替身；测试通过后仍须在目标 SDK 构建与现场独立验收。

## 可选诊断

- `bash host_tests/test_pole_diagnostic.sh`：纯状态、注入读帧与时钟、停止态查询/重新布防；包含跨运行在途读取和无新读取失败的窗口过期。
- `bash host_tests/test_tmc_trace.sh`：有界记录、跨运行丢弃、串口查询门禁。
- `python -m unittest discover -s tools -p 'test_*.py'`：包括 POLED2/TMCT2 严格解析与不完整记录拒绝。

目标构建须分别开启和关闭两个诊断开关，主机测试不能替代 ESP-IDF ABI/格式检查。

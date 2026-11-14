# Tools directory

This directory contains host-side tools and test scripts.

- `host_sim.py` — Host simulator and end-to-end acceptance script (T12)
  Usage: `python tools/host_sim.py <PORT> --phase 1` → power-cycle the board → `python tools/host_sim.py <PORT> --phase 2` (需 pyserial；快速自检用 `--skip-power-cycle --fast`，报告写入 `docs/acceptance.md`)

## 真机实验工具

这些工具不是生产控制器，也不自动恢复故障或使能。Python 串口入口依赖 `pyserial`，
在 Windows 原生终端运行；固件在 ESP-IDF 容器内构建。先阅读各入口的现场前提。

- [低速方向与停稳](../experiments/low-speed-probe/README.md)：小幅单向运动。
- [400 mm/s 加速度基线](../experiments/accel-5000-probe/README.md)：固定单次基线。
- [50 kHz 离线预算](../docs/step50k-plan.md)：不打开串口、不运动。
- [单次高速探针](../docs/step50k-probe.md)：显式预算输入，全部预算通过才允许执行。
- [两次往返探针](../docs/roundtrip-probe.md)：固定装置专用，低速接近端点，停稳后反向。
- [独立 STEP 测量固件](../experiments/step-frequency-isolated/README.md)：需物理隔离动力路径。

所有日志由用户指定新文件保存，不提交到仓库。实验结果不能替代实际速度、
加速度、温升、波形和停止距离的独立测量。对照记录见[实验结论](../docs/experiment-results.md)。

## 开发与维护边界

运动探针共用 [probe_link.py](probe_link.py) 的串口会话与预检，不依赖低速脚本的命令行入口。
串口、单调时钟与等待函数由构造参数注入；测试使用内存替身，不打开真实串口。
各运动脚本负责自己的轨迹、时限和停止条件。专用往返脚本不是训练控制器，
其风险确认不能替代通用控制器的制动设计。

这些文件不参与生产固件的构建，也不增加生产固件的常驻任务、内存或串口流量。
独立STEP工程需单独构建和烧录；它不运行生产模式机和编码器任务，
因而只能检查隔离条件下的STEP输出，不能替代完整固件的负载验证。

主机侧回归可在仓库根目录执行：

```bash
python -m unittest discover -s tools -p 'test_*.py'
bash experiments/step-frequency-isolated/tests/run.sh
```

前者验证主机工具的协议与行为，后者验证独立STEP测量控制逻辑。
ESP-IDF目标构建、波形和机械运动仍需在目标环境单独验证。

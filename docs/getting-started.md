# 开发、烧录与首次连接

## 构建环境

项目使用 ESP-IDF v6.1、ESP32-S3。先在已安装 SDK 的终端加载环境；
SDK 目录由实际安装位置决定，不要求固定在某个 Windows 用户目录。

```bash
# 在仓库根目录、已加载 ESP-IDF 环境的终端执行
idf.py build
idf.py -p FLASH_PORT flash
```

`FLASH_PORT` 替换为原生 USB 的烧录端口。正式工程不编入组件 Unity 测试；
测试镜像单独按 [test/README.md](../test/README.md) 构建，不能用测试入口代替正式固件。

构建前核对 `sdkconfig`；[sdkconfig.defaults](../sdkconfig.defaults) 和 Kconfig 只是缺省来源，
不会覆盖已经保存的配置。特别检查协议波特率、日志通道、采样与诊断开关。

## 三条通道不要混用

接线、引脚和电气条件以[硬件文档](hardware.md)为准：

- 原生 USB：烧录和默认日志，不是 PC 运动协议入口。
- UART0：上位机协议，3.3 V TTL、共地。
- UART1：可选日志通道，须按硬件文档配置。

固件 `CONFIG_CARTPROTO_UART_BAUD` 当前默认 **1000000**，而一些 Python 工具仍默认
**460800**。命令必须显式选用与实际固件一致的 `--baud`。旧会话中的 COM 编号和
460800 不能证明新固件的串口配置。

## 只读连接检查

PC 端需要 Python 与 `pyserial`。以下命令在仓库根执行，把 `CONTROL_PORT` 替换为实际控制口，
示例波特率仅适用于采用默认 1000000 的固件：

```bash
python tools/cartpole_host.py --port CONTROL_PORT --baud 1000000 query
python tools/cartpole_host.py --port CONTROL_PORT --baud 1000000 calib-status
python tools/cartpole_host.py --port CONTROL_PORT --baud 1000000 dump
python tools/cartpole_host.py --port CONTROL_PORT --baud 1000000 state --secs 2
```

查询不自动标定或使能。后续执行 `ENABLE` 若返回 `ERR POWER`，检查启动供电验证及实际 VBUS，
不能仅凭“电源已接通”认定固件应当 READY。完整状态和响应见[协议](protocol.md)。

## 烧录后标定与配置

首次装配、维护改变机械关系或保存记录无效时，按[标定指南](calibration.md)进行全量标定。
若只是重启且保存记录有效，则确认同一左参考点；恢复后仍保持 DISABLED。
运动参数如 `ACC_MAX` 与保存的标定字段不是同一套持久化数据，运行前读回核对。

普通 `idf.py flash` 不是全片擦除命令，但不能据此保证任何自定义烧录流程都保留 NVS：
检查分区表、烧录文件和应用初始化行为。`erase-flash` 会清除保存数据。
烧录后以 `CALIB?`、参数回读和实际机械关系核验，不把“烧录成功”当作标定有效。

要进行运动，另按具体工具的条件选择目标、净空与停机方式；本页不自动发出使能或速度命令。

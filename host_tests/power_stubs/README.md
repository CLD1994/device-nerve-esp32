# 供电门禁测试替身

仅供cartpower适配器与cartfsm电源门的宿主单元测试。保留生产头文件声明，
替换ESP-IDF/FreeRTOS边界；任务由测试显式调度，互斥量为单线程替身。
这些测试不能证明双核调度、真实互斥时延、I2C超时或实际停止距离。
编译命令见[test/README.md](../../test/README.md#正式固件20v门禁的宿主回归)。

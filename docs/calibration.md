# 标定保存与重启后的左参考确认

本功能保存装置参数，不保存断电时的小车位置，也不自动回零。小车编码器的单圈绝对角无法区分断电后的整圈位移。每次启动保持 `DISABLED`；即使存在完整记录，也必须手动建立本次位置参考，才能另行 `ENABLE`。

## 首次标定

保持电机禁用，将小车停稳于可重复到达的左标记，执行 `mark-left`；再手推到右标记，停稳后执行 `mark-right`。两个标记之间的**小车同一点位移**是行程，不是两挡块间空距。

```powershell
python tools/cartpole_host.py --port COM11 --baud 460800 mark-left
python tools/cartpole_host.py --port COM11 --baud 460800 mark-right
python tools/cartpole_host.py --port COM11 --baud 460800 calib-status
```

`MARK LEFT` 成功前先保存行程失效记录。此后掉电也不能恢复旧行程；必须完成右点或重新从左点开始。`MARK RIGHT` 保存行程和机械比例后，建立以中点为零的位置参考，并同步步进指令位置；不使能电机。当前行程合法范围仍为 100～1000 mm。超出该范围不能用恢复命令绕过。

`CONFIG POLE_ZERO_URAD` 与 `CONFIG POLE_INV` 在 `DISABLED` 下保存成功后才应用。它们可以在轨道标定之前或之后配置，重启后恢复；其他运行参数仍按原逻辑使用。零偏默认值不代表摆角已做物理校准。

## 同一装置重启

1. 确认传动、编码器磁铁、每转距离与左标记没有改变。
2. 手推至**首次两点标定使用的同一左标记**，停稳。
3. 执行下列命令。成功只建立位置，不发送运动指令。

```powershell
python tools/cartpole_host.py --port COM11 --baud 460800 confirm-left
python tools/cartpole_host.py --port COM11 --baud 460800 calib-status
```

左参考的位置为整数 `-L/2` µm（奇数行程按整数除法向零取整）；新位置同步至步进指令计数。成功后仍须独立执行 `enable`。用户必须保证实际停在左标记，软件不能检测挡块或替用户确认物理位置。

采样门禁只验证读取成功、CRC与时间连续性，不是磁铁或机械安装自检。MT6835的磁弱、欠压、过速状态目前仍沿驱动的告警策略处理，不进入本次参考门禁；请人工确认磁铁安装、状态告警及读数随小车运动的对应关系。

## 固件扩展命令

现有协议说明的入口是 [protocol.md](protocol.md)。以下为本固件新增接口；配套主项目协议文档需要同步后，上位机才能将其作为共同协议使用。

| 命令 | 成功回执 | 前提 |
|---|---|---|
| `CONFIRM LEFT` | `OK CONFIRM_LEFT <负半行程µm>` | DISABLED、有保存的有效行程、比例匹配、非两点标定进行中、位置读数有效且稳定 |
| `CALIB?` | 四行 `OK CAL_STATE`、`OK CAL_LENGTH_UM`、`OK CAL_SAVED`、`OK CAL_STORAGE` | 只读，可在所有模式查询 |

`CAL_STATE`：0=无可用定位，1=等待右点，2=本次已定位，3=有保存行程但等待左确认。`CAL_LENGTH_UM` 为可用保存行程，不可用时为0；`CAL_SAVED` 为是否存在比例匹配的有效行程；`CAL_STORAGE` 为最近一次载入或写入的 ESP-IDF 错误码，0表示成功。缺记录或记录损坏会保留诊断码，不伪装为已保存。查询不代表物理位置正确。

标记/确认时需连续100 ms采样，位置跨度不超过100 µm，每次检查都需新样本，最近样本不超过20 ms，期间不能出现读失败或采样空窗。条件不满足会拒绝，不修改原点。轨道两点之间也必须维持编码器连续采样；失败后应重新 `mark-left`。样本失效后，即使后来恢复读数，本次位置也须重新确认；READY 下按现有编码器故障路径停机。

## 存储失败与恢复

记录位于 NVS 的 `cartcal` 命名空间，固定版本格式、CRC32和范围校验；一次完整 blob 写入及提交，不持续写入200 Hz位置流。NVS保证记录更新的掉电恢复；应用只接受完整且校验通过的版本。未知版本不自动解释或迁移，擦除NVS也会使记录丢失，需重新标定。

- `ERR CAL_STORAGE`：写入未确认成功。角配置不在RAM生效；右点保留等待右点，可同位置重试。左点失败不开始新两点标定，当前定位门关闭；此前完整记录可能仍存在，查询后决定重新标定或左确认。不要把写失败当成已保存。
- `ERR CAL_REFERENCE`：参考连续性或比例发生变化。若右点记录已写入但定基失败，则保留已保存行程、禁止使能，手推回左点执行确认；如果仍显示等待右点，则重新 `mark-left`。
- `ERR CONFIRM_LEFT`：参考点未确认，保持禁用。检查状态、记录、传动比例和编码器，停稳后再试。
- 改变轨道、传动、磁铁或编码器安装，必须主动重新两点标定；比例不匹配的保存行程不能恢复。恢复出厂/NVS清除后不能用旧行程自动建立位置。

首次刷入本功能时，旧固件RAM标定不会自动进入NVS，需要重新两点标定并设置摆角参数。本功能未替代制动距离与最大加速度的真机验收；原有软限位不是提前制动保证。

## 宿主回归与真机验收边界

从仓库根目录执行下列单元测试，硬件、NVS、任务调度使用受接口约束的替身：

```bash
gcc -std=c11 -Wall -Wextra -Werror \
  -Icomponents/cartcal/host_stub -Icomponents/cartcal/include \
  -Icomponents/cartparams/include -Icomponents/settings/include \
  host_tests/cartcal_test.c components/cartcal/cartcal.c \
  components/cartparams/params.c -lm -o /tmp/cartcal-test
/tmp/cartcal-test

gcc -std=c11 -Wall -Wextra -Werror \
  -Icomponents/cartfsm/host_stub -Icomponents/cartcal/host_stub -Ihost_tests/stub \
  $(find components -type d -name include -printf '-I%p ') \
  host_tests/cartfsm_calibration_test.c components/cartfsm/cartfsm_core.c \
  components/cartparams/params.c -lm -o /tmp/cartfsm-calibration-test
/tmp/cartfsm-calibration-test

python -m unittest discover -s tools -p 'test_*.py'
```

采样和参考点单元测试命令见[对应替身说明](../host_tests/encoder_reference_stubs/README.md)。存储测试覆盖记录缺失、损坏、版本、范围、失效记录与各存储阶段失败；FSM测试覆盖保存、重启、禁用门、确认、原点同步、配置写失败与重试。

宿主通过不能证明ESP-IDF目标构建、NVS物理断电一致性、实际传感器采样连续性或电机安全。真机验收应保持电机禁用，分别验证：两点保存后重启不能直接ENABLE；左确认后坐标恢复；断电后移动再确认；存储记录清除后拒绝恢复；标定期间移动/传感器失败拒绝操作。最后单独完成低速限位与加速度验收。不要由测试脚本自动使能或撞挡块。

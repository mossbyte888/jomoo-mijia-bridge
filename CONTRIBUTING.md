# 参与贡献

欢迎提交兼容性报告、文档修正和代码改进。当前重点是 SQ9650、ZS800J 的通用米家接入和 HA 控制。

提交问题请说明：型号与可获得的固件版本、HA / Xiaomi Home / 集成版本、蓝牙部署方式、重现步骤、预期结果和实际结果。区分“状态可读取”“指令写出”“设备读回目标值”“现场动作完成”，不要只用蓝牙写入成功证明功能可用。

请脱敏 MAC、IP、小米账号 ID、访问令牌、家庭成员和设备位置；不要上传整个 HA 配置目录、原厂小程序包或未经许可的第三方源码。

代码修改应配合可复现的合成数据测试。协议扩展需给出字段意义和验证依据；机械动作应保留空闲检查、反馈确认及不盲目重放原则。新增型号需独立建模，不能只改型号列表。

本仓库中的单元测试不连接真实设备：

```bash
python3 -m unittest discover -s tests -v
```

提交截图请仅保留相关通用面板，隐藏账号、网络地址和个人自动化内容。

使用真实 HA 2026.10.1 API 的独立测试位于 `tests_ha/`。可在本机 Docker 运行，不访问家庭设备或账号：

```bash
docker run --rm --network none --entrypoint python \
  -v "$PWD:/work:ro" -w /work \
  ghcr.io/home-assistant/home-assistant:2026.10.1 \
  -m unittest discover -s tests_ha -v
```

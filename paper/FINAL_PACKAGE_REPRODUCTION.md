# 最终候选包独立复现记录（1.1.1-rc1）

> 产物：`RosSystem-CreativeWork-Full-1.1.1-rc1.tar.gz`
> SHA-256：`d69737cf9dbd039a4a0b8a127eb15bb3db55b5514512c119befd46d5e0fe32d2`（2,453,717 B）
> 离线包：`RosSystem-creative-work-1.1.1-rc1.tar.gz`
> SHA-256：`2fa7892deee52c079a76b51064acf7357f7b4bd7d655b3ab04d5081efa00a2b9`（110,269 B）
> 打包来源提交：`ca32a6c047ba617ec01aae0b05e872b4a2296620`（见包内 `runtime/BUILD_INFO.json`；
> 工作树 tracked 干净）。验收文档提交 `40fded5` **晚于**打包，不能称为打包源码提交。
> 环境：同宿主、新目录 `/tmp/v111last`、新容器 `rg_last2`（单测）/ `rg_last3`（组件）；
> 镜像 `rosystem-jazzy:1.1.0`；**不是第三方主机**。

## 1. 已实际执行

| 步骤 | 结果 | 证据/说明 |
| --- | --- | --- |
| `sha256sum -c` 两个包 | **OK** | 终端输出；`dist/*.sha256` |
| 解压 | OK | `/tmp/v111last/RosSystem-CreativeWork-Full` |
| 密钥材料扫描 | 无 `.pem/.key/.p7s` | `find` 结果为空 |
| 目录检查 | `runtime/`、`dashboard/`、`paper/`、`reports/`、`evidence/` 存在 | `ls` |
| `colcon build --symlink-install` | **4/4，0 失败** | `/tmp/build.log` |
| `setup_sros2.sh`（native） | 新实验室 CA + 权限复核 PASS | `/tmp/setup.log` |
| DDS Enforce 7 场景 | **7/7 PASS** | 最终包 `last-dds-20261022T051500Z/summary.json` |
| 全量单测 | **921 passed / 17 skipped / 0 failed（603.8 s）** | `rg_last2` `/tmp/unit.log`；**原始日志 NOT_RECOVERED**，见 `UNIT_TEST_LOG_RECOVERY_STATUS.md` |
| DDS 负向 6/6 | **6/6 PASS** | 最终包 `last-ddsneg-20261022T051700Z` |
| M2 身份链 17/17 | **17/17 PASS** | 最终包 `last-m2-20261022T052000Z` |
| Gateway 14/14 | **14/14 PASS** | 最终包 `last-gw-20261022T052300Z` |
| P07 13/13 | **13/13 PASS** | 最终包 `last-p07-20261022T052500Z` |
| P09 10/10 | **10/10 PASS** | 最终包 `last-p09-20261022T052700Z` |
| 三真实 L1/L2/L3 | PASS/PASS/BLOCKED | 最终包 `last-three-20261022T053000Z` |
| Dashboard tests | **18 passed** | 最终包根目录 `tests/test_dashboard.py` |
| `/api/research` | 200，ARCHIVED，12 items | 最终包 `dashboard/server.py` |

## 2. 精确性与限制

1. 最终 sha 包上重跑了 **SHA/解压/密钥扫描/colcon/DDS 7/7/全量单测 921 passed/17 skipped**；
2. DDS 负向 6/6、M2 17/17、Gateway 14/14、P07 13/13、P09 10/10、三真实
   L1/L2/L3 与 Web 18 项均在**最终 sha 包**上重跑；
3. `tests/unit` 在包内跳过 17 项；**完整原始 stdout 未归档**，17 项明细与原因见
   `FINAL_PACKAGE_SKIPPED_TESTS.csv` 与 `FINAL_UNIT_TEST_EVIDENCE_AUDIT.md`；
   跳过项未被计为 PASS；
4. 这是 **SAME_HOST_FRESH_ENV_VERIFIED**，不是 `THIRD_PARTY_HOST_VERIFIED`；
5. 未做浏览器截图（无无头浏览器）；
6. 最终包中的 `paper/` 与 `reports/` 是构建时的快照；本文件若在构建后更新，
   以仓库版本为准；
7. 本文件在 `40fded5` 之后的文档提交中更新，更新只涉及论文/证据，不改包 SHA。

## 3. 复现命令

```bash
cd submission/creative-work
sha256sum -c dist/RosSystem-CreativeWork-Full-1.1.1-rc1.tar.gz.sha256
tar -xzf dist/RosSystem-CreativeWork-Full-1.1.1-rc1.tar.gz -C /tmp/v111last
docker run --rm -v /tmp/v111last/RosSystem-CreativeWork-Full/runtime:/ws \
  -w /ws rosystem-jazzy:1.1.0 bash -lc \
  'source /opt/ros/jazzy/setup.bash && colcon build --symlink-install'
```

## 4. 结论

`LATEST_ARCHIVE_REPRODUCED = PASS（SAME_HOST_FRESH_ENV）`；
`THIRD_PARTY_HOST_REPRODUCED = NOT_RUN`。

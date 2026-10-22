# 1.1.0 Web 研究证据展示验证

> 结论：**WEB_RESEARCH_EVIDENCE = PASS**（只读归档展示）；截图 **NOT_RUN**（环境无无头浏览器）。
> 证据：`artifacts/research/v110/web/`

## 1. 新增能力

- 新只读端点 `GET /api/research`；
- 新面板「1.1.0 研究证据」；
- 证据类别固定为 **`ARCHIVED_RESEARCH_EVIDENCE`**，并显式 `online_evidence=false`；
- 页面文案明确：归档研究证据不是本次在线运行；`ONLINE_EVIDENCE` 只指当前 controller
  运行产生的事实；`REPLAY` 仍指 1.0.3 离线回放；
- 不改变原有 `ONLINE` / `REPLAY` / `UNAVAILABLE` 徽章与受控在线能力。

## 2. 实测响应

| 路径 | HTTP | 说明 |
| --- | --- | --- |
| `/api/health` | 200 | 现有健康检查 |
| `/api/research` | 200 | 新研究证据快照，12 个条目 |
| `/` | 200 | 页面包含「1.1.0 研究证据」面板 |

`/api/research` 关键字段：

```json
{"evidence_class":"ARCHIVED_RESEARCH_EVIDENCE","online_evidence":false,
 "acceptance":{"status":"INCOMPLETE","exit_code":9},
 "items":[{"id":"DDS_ENFORCE","status":"PASS","value":"7/7"}, ...]}
```

条目状态：

| ID | 状态 | 值 |
| --- | --- | --- |
| DDS_ENFORCE | PASS | 7/7 |
| DDS_NEGATIVE | PASS | 6/6 |
| M2_IDENTITY | PASS | 17/17 |
| GATEWAY | PASS | 14/14 |
| REPEATS | PASS | 30/30 |
| THREE_REAL_L1 | PASS | PASS |
| THREE_REAL_L2 | PASS | PASS |
| THREE_REAL_L3 | BLOCKED | BLOCKED |
| M1_GATE | FALSE | false |
| P07 | PASS | 13/13（隔离） |
| P09 | PASS | 10/10 |
| ACTION_BINDING | NOT_VERIFIED | — |

## 3. 测试

```bash
cd submission/creative-work
python3 -m pytest tests/test_dashboard.py -q
# 18 passed
```

测试包含：

- 快照必须是 `ARCHIVED_RESEARCH_EVIDENCE` 且 `online_evidence=false`；
- 不能被误当 `ONLINE_EVIDENCE` 或 `REPLAY`；
- DDS/M2/Gateway/P07/P09 数字与证据一致；
- LEVEL3=BLOCKED、ACTION_BINDING=NOT_VERIFIED、acceptance=INCOMPLETE；
- 路径穿越与原有白名单测试未退化。

## 4. 截图状态

环境（宿主与容器）没有 `chromium`/`playwright`/`wkhtmltoimage`，因此没有生成截图。
不伪造图片。已保存：

- `resp_api_health.txt`
- `resp_api_research.txt`
- `resp_.txt`（页面 HTML）
- `server.log`
- `summary.json`（含各文件 SHA-256）

若需要正式论文截图，可在有浏览器的环境执行：

```bash
cd submission/creative-work
python3 dashboard/server.py --port 8791
# 浏览器打开 http://127.0.0.1:8791/，截取「1.1.0 研究证据」面板
```

## 5. 限制

- 这是**归档展示**，不是在线实验；
- 页面不重新计算 PASS/FAIL，只读取 `dashboard/research_evidence.json`；
- 快照需在证据更新后由 `scripts/build_research_evidence.py` 重新生成；
- 没有浏览器级视觉回归（截图/像素）证据。

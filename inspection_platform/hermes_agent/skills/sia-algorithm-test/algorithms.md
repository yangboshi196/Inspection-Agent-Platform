# vaio 算法目录（detecttype 对照）

来源：`vaio-analysis-core` → `GET /v1/algorithms`（`Algorithm_*.json`）。

| detecttype | 名称 | 平台 ID | 备注 |
|------------|------|---------|------|
| 1000 | 五临边-未戴安全带检查 | vaio-1000 | |
| 1001 | 打架检测 | vaio-1001 | |
| 1002 | 探伤作业禁止进入 | vaio-1002 | 含 tracker |
| 1003 | 船只检测 | vaio-1003 | 含 tracker；COCO `boat` 类 |
| 1004 | 玩手机检测 | vaio-1004 | |
| 1005 | 焊接作业-跌倒摔倒 | vaio-1005 | |
| 1006 | 识别交通道路人员安全隐患行为 | vaio-1006 | |
| 1007 | 码头捡螺入侵 | vaio-1007 | |
| 1008 | 裸土检测 | vaio-1008 | |
| 1009 | 石头裸露识别 | vaio-1009 | |
| 1010 | 动火无监护人检查 | vaio-1010 | |
| 1011 | 消火栓隐患检查 | vaio-1011 | |
| 1012 | 非工作时段禁止进入 | vaio-1012 | 含 tracker |
| 1013 | 卸货作业禁止进入 | vaio-1013 | 含 tracker |
| 1014 | 吊车作业禁止进入 | vaio-1014 | 含 tracker |
| 1015 | 深基坑-未戴安全带检查 | vaio-1015 | |
| 1016 | 人员密集区-跌倒摔倒 | vaio-1016 | |
| 1017 | 动火作业火光检测 | vaio-1017 | |
| 1018 | 卧倒摔倒识别 | vaio-1018 | 含 tracker |
| 1019 | 人脸识别-编排 | vaio-1019 | 需 dface 授权 |

## 关键词 → detecttype（便于自然语言匹配）

| 用户说法 | detecttype |
|----------|------------|
| 船、船只、船舶、boat | 1003 |
| 裸土、扬尘 | 1008 |
| 石头、裸露 | 1009 |
| 打架、斗殴 | 1001 |
| 手机 | 1004 |
| 安全帽、安全带、五临边 | 1000 |
| 深基坑 | 1015 |
| 人脸 | 1019 |
| 跌倒、摔倒 | 1016 / 1018 / 1005 |
| 动火、火光 | 1017 |
| 码头、捡螺 | 1007 |

## 任务 JSON 字段说明

- **`detecttype`**：必填，等于上表 ID（**不是** `algorithm_id` 别名）
- **`src_data_type`**：本地文件 `2`，RTSP/HTTP 流 `1`
- **`config`**：可与配方 `userparam` 对齐；至少建议 `holddowntime`、`sensitivity`
- **`config.defence`**：**C++ 核心必填**（非空数组）。MCP / Python REST 缺失时自动注入全屏防区；直连 `POST :9200/v1/tasks` 须手动提供

### config.defence 结构

```json
"defence": [{
  "areaattr": 0,
  "points": [
    {"x": 0, "y": 0},
    {"x": 100, "y": 0},
    {"x": 100, "y": 100},
    {"x": 0, "y": 100}
  ]
}]
```

| 字段 | 说明 |
|------|------|
| `areaattr` | `0`=检测防区，`8`=布控线（≥2 点），`9`=反向区域 |
| `points[].x/y` | **0–100** 整数，相对画面宽高的百分比 |

缺 `defence` 时 C++ 报 `ParseDetectRegionConf fail` → `tool init fail` → `CreateGraph fail`。  
配方文件里的 `userparam.inverseregion` **不会**替代任务 JSON 中的 `defence`。

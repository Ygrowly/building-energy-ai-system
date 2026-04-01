# MCP 接口说明：`forecast_multi_6_12h_bundle.pkl`
本文档描述如何将 `yp_tool/forecast_multi_6_12h_bundle.pkl` 封装为 **MCP（Model Context Protocol）** 可调用的工具：包括 **artifact 结构**、**逻辑入参/出参**、建议的 `tools/list`** 元数据** 与 `tools/call`** 载荷示例**。实现侧需在 **Python + scikit-learn + joblib** 环境中加载该文件（与训练环境一致）。

---

## 1. 文件与加载
| 项 | 值 |
| --- | --- |
| 路径（相对仓库根） | `yp_tool/forecast_multi_6_12h_bundle.pkl` |
| 格式 | `joblib` 序列化的 `dict` |


```python
import joblib
from pathlib import Path

path = Path("yp_tool/forecast_multi_6_12h_bundle.pkl")
artifact = joblib.load(path)
pipe = artifact["pipeline"]          # sklearn MultiOutputRegressor
feature_cols = artifact["feature_cols"]  # list[str]，列顺序固定
target_cols = artifact["target_cols"]    # list[str]，与 predict 输出列顺序一致
```

---

## 2. Artifact 字段说明
| 键 | 类型 | 含义 |
| --- | --- | --- |
| `pipeline` | `sklearn.multioutput.MultiOutputRegressor` | 已拟合；内含 10 个子模型（每目标一个 `Pipeline`: 预处理 + `VotingRegressor`） |
| `feature_cols` | `list[str]` | **推理时 **`DataFrame`** 必须包含且仅按此顺序取列**（与训练 `tool.ipynb` 中特征工程一致） |
| `target_cols` | `list[str]` | 10 个回归目标名，与 `predict` 返回矩阵 **列顺序一一对应** |
| `horizons_h` | `list[int]` | 固定为 `[6, 12]`（小时） |
| `target_kpis` | `list[str]` | 5 个被预测的物理量列名（原始 KPI） |
| `model_name` | `str` | 文档/审计用标识，如 `MultiOutput_Voting_HGB_RF_6_12h` |


### 2.1 `target_cols` 顺序（固定）
与 `predict_proba` 不同，此处为 **回归** `predict`，输出形状 `(n_samples, 10)`，列顺序为：

1. `y_water_l_tplus6h`
2. `y_electricity_kwh_tplus6h`
3. `y_sim_supply_temp_c_tplus6h`
4. `y_sim_return_temp_c_tplus6h`
5. `y_hac_energy_tplus6h`
6. `y_water_l_tplus12h`
7. `y_electricity_kwh_tplus12h`
8. `y_sim_supply_temp_c_tplus12h`
9. `y_sim_return_temp_c_tplus12h`
10. `y_hac_energy_tplus12h`

语义：在**当前时刻 t**（该行对应的小时戳），预测 **t+6h**、**t+12h** 时刻上述 5 个量的数值（与训练时 `shift(-6)` / `shift(-12)` 标签定义一致）。

---

## 3. 推理契约（核心）
### 3.1 输入
+ **类型**：行数 `n >= 1` 的 **特征矩阵**，在 Python 中为 `pandas.DataFrame`，且包含 `artifact["feature_cols"]` 中的 **全部列名**，缺失列应拒绝请求。
+ **数值**：与训练数据同 **量纲**（`water_l`、`electricity_kwh`、温度 ℃、`hac_energy` 等）。
+ **特征来源**：训练时使用 **滞后 (1,2,3,6,12,24)**、**24h 滚动统计**、`hour/dow/month`、`Ta/Tdew/hum/rh` 等由 `yp_tool/kpi_with_anomalies.csv` 经 `tool.ipynb` 流程生成。**MCP 服务端必须复现同一套特征工程**（或仅接受已算好的特征行），否则数值无效。

### 3.2 调用
```python
X = df[feature_cols]   # 列顺序与 feature_cols 一致
Y_hat = pipe.predict(X)  # ndarray, shape (n, 10), float64
```

### 3.3 输出
+ **形状**：`(n_samples, 10)`。
+ **映射**：第 `j` 列 = `target_cols[j]` 的预测值。
+ **建议返回给 MCP 客户端**：JSON 数组，每元素为对象，键为 `target_cols` 中的名字，值为 `float`；可同时附 `timestamp`、`building_id` 等业务键（由服务端在组包时加入）。

---

## 4. 建议的 MCP 工具定义
以下为 `tools/list` 中单个 `Tool` 的推荐描述（字段名遵循 MCP 常见约定；具体以你所用 SDK 为准）。

### 4.1 工具元数据
| 字段 | 建议值 |
| --- | --- |
| `name` | `building_kpi_forecast_6h_12h` |
| `description` | 根据楼宇历史 KPI 与气象特征，预测未来第 6、12 小时的 `water_l`、`electricity_kwh`、`sim_supply_temp_c`、`sim_return_temp_c`、`hac_energy` 共 10 个标量。输入须为已按训练管线构造的特征行（或由服务端从原始时序自动构造）。 |
| `inputSchema` | 见下节 JSON Schema |


### 4.2 `inputSchema`（JSON Schema 草案）
**模式 A（推荐用于生产）**：客户端传 **原始时序窗口**，由 **MCP 服务端** 复现 `tool.ipynb` 特征逻辑后调用 `predict`。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["building_id", "rows"],
  "properties": {
    "building_id": { "type": "string", "description": "楼宇 ID，与训练数据一致" },
    "rows": {
      "type": "array",
      "minItems": 25,
      "description": "按时间升序的时序行，至少覆盖最大滞后 24h + 滚动窗口；每行字段需含训练用原始列",
      "items": {
        "type": "object",
        "required": [
          "timestamp",
          "water_l",
          "electricity_kwh",
          "sim_supply_temp_c",
          "sim_return_temp_c",
          "hac_energy",
          "airTemperature",
          "dewTemperature",
          "humidity",
          "humidity_rh_pct"
        ],
        "properties": {
          "timestamp": { "type": "string", "format": "date-time" },
          "water_l": { "type": "number" },
          "electricity_kwh": { "type": "number" },
          "sim_supply_temp_c": { "type": "number" },
          "sim_return_temp_c": { "type": "number" },
          "hac_energy": { "type": "number" },
          "airTemperature": { "type": "number" },
          "dewTemperature": { "type": "number" },
          "humidity": { "type": "number" },
          "humidity_rh_pct": { "type": "number" }
        }
      }
    }
  }
}
```

**模式 B（调试/内部）**：直接传 **一条已构造好的特征向量**（键名 = `feature_cols`）。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["features"],
  "properties": {
    "features": {
      "type": "object",
      "description": "键为 feature_cols 中的列名，值为 number；须与训练时特征工程完全一致",
      "additionalProperties": { "type": "number" }
    }
  }
}
```

---

## 5. `tools/call` 请求/响应示例
### 5.1 请求（模式 B 极简）
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "building_kpi_forecast_6h_12h",
    "arguments": {
      "features": {
        "electricity_kwh_lag1": 40.1,
        "hour": 14,
        "Ta": 8.2
      }
    }
  }
}
```

> 注意：真实调用时 `features` 必须 **补全 **`feature_cols`** 全部键**，上面仅为结构示例。
>

### 5.2 响应（建议 `structuredContent` 或等价载荷）
```json
{
  "forecasts": [
    {
      "y_water_l_tplus6h": 72.5,
      "y_electricity_kwh_tplus6h": 38.2,
      "y_sim_supply_temp_c_tplus6h": 59.8,
      "y_sim_return_temp_c_tplus6h": 54.1,
      "y_hac_energy_tplus6h": 25.0,
      "y_water_l_tplus12h": 71.0,
      "y_electricity_kwh_tplus12h": 36.5,
      "y_sim_supply_temp_c_tplus12h": 60.0,
      "y_sim_return_temp_c_tplus12h": 54.5,
      "y_hac_energy_tplus12h": 24.2
    }
  ],
  "model_name": "MultiOutput_Voting_HGB_RF_6_12h",
  "horizons_h": [6, 12]
}
```

若 `n_samples > 1`，`forecasts` 为与行同序的数组。

---

## 6. 错误与边界
| 情况 | 建议 HTTP/MCP 错误信息 |
| --- | --- |
| 缺列 / 列名与 `feature_cols` 不一致 | `invalid_input: missing or unknown feature columns` |
| `pkl` 无法加载（版本、路径） | `model_load_failed` |
| 非数值 / NaN 过多 | `invalid_input: non-numeric or excessive NaN` |


---

## 7. 依赖与部署提示
+ **Python**：与训练时相近版本；**scikit-learn**、**joblib**、**pandas**、**numpy**。
+ **进程内加载**：`joblib.load` 后常驻内存，避免每次 `tools/call` 重复读盘。
+ **多进程**：`MultiOutputRegressor` 子模型已在训练时确定；推理时 `predict` 一般为线程安全读，写共享状态需注意。
+ **与 MCP 的关系**：MCP 只规定 **工具发现与调用协议**；本 `pkl` **不是** ONNX/Torch 权重，需在服务端用 **sklearn 解释执行**。

---

## 8. 与训练代码的对应关系
特征与标签定义以仓库内 `yp_tool/tool.ipynb` 为准；修改该 notebook 后应 **重新训练并覆盖 pkl**，并 **同步更新** 本文档中的 `target_cols` 与 `inputSchema`（若 `feature_cols` 发生变化）。


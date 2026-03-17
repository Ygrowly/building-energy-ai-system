作为一个专业的建筑资源仿真专家，我为您设计了一套基于中国国家标准（GB）和建筑物理/热力学规则的建筑资源时序仿真方案。

该方案将输入的参考属性映射到物理意义明确、符合时序规律及中国国标规范的预期值。

---

### 一、 仿真依据的真实国标手册（来源）
在构建这套仿真方案时，所有的基准数据、设计参数和边界条件均来源于以下中国现行国家标准：

1. **《民用建筑能耗标准》 GB/T 51161-2016**：提供各类建筑的电耗、水耗基准线指标。
2. **《建筑照明设计标准》 GB 50034-2013**：提供不同建筑用途的照明功率密度（W/㎡）规范值。
3. **《公共建筑节能设计标准》 GB 50189-2015**：提供建筑设备功率密度、室内设计温湿度、空调系统综合能效比（COP）规范。
4. **《民用建筑供暖通风与空气调节设计规范》 GB 50736-2012**：提供空调系统的标准供回水温度、新风量及负荷计算准则。
5. **《建筑给水排水设计标准》 GB 50015-2019**：提供不同建筑类型的用水定额。

---

### 二、 核心参数与时序系数定义 (Temporal Profiling)
资源消耗高度依赖于人员在室率（Occupancy Rate）。我们定义一个**时间系数 **$ S(hour, dayofweek) $，取值范围 `[0.05, 1.0]`，代表当前小时的建筑负荷率。

根据 `primaryspaceusage` 和 `dayofweek`（1-5为工作日，6-7为周末）制定以下规则：

+ **办公楼 (Office)**：
    - 工作日：0-7时 (0.05)；8时 (0.5)；9-17时 (1.0)；18-20时 (0.3)；21-23时 (0.05)
    - 周末：全天 (0.05，仅保安和基础设备)
+ **教学楼 (Teaching Building)**：
    - 工作日：0-7时 (0.05)；8-12时 (1.0)；13时 (0.4)；14-17时 (1.0)；18-21时 (0.8)；22-23时 (0.05)
    - 周末：全天 (0.2，部分自习室开放)
+ **公共建筑-图书馆 (Library)**：
    - 全周（含周末）：0-7时 (0.05)；8-21时 (0.8，波动较小)；22-23时 (0.05)

---

### 三、 属性仿真模型设计
#### 1. 水耗：water (单位：m³/h)
**国标依据**：GB 50015-2019。办公楼约 40L/(人·天)，教学楼约 30L/(人·天)，图书馆约 4L/(人·天)。换算为单位面积的峰值水耗定额 $ W_{peak} $（单位：L/(㎡·h)）：

+ 办公楼：约 0.4 L/(㎡·h)
+ 教学楼：约 1.0 L/(㎡·h) （人员密度大）
+ 图书馆：约 0.06 L/(㎡·h)

**仿真公式**：

$ water = \left[ sqm \times W_{peak} \times S(hour, dayofweek) \right] / 1000 + Noise $

_(除以1000是将升转化为立方米，_$ Noise $_为±5%的随机高斯噪声，模拟管网微小泄漏和随机用水)_

#### 2. 空调系统冷热负荷计算 ($ Q_{load} $，单位：kW)
这是计算空调能耗和供回水温度的前置物理条件。  
**物理规则**：显热负荷受 `airTemperature` 和内部热源影响，潜热负荷受 `dewTemperature` 和 `humidity` 影响。

+ **室内设计标准** (GB 50189-2015)：夏季 $ T_{in}=26℃ $，冬季 $ T_{in}=20℃ $。露点约 $ 15℃ $。
+ **建筑基础功率密度** $ P_{base} $ (照明+插座设备，GB 50034 / GB 50189)：办公楼 25 W/㎡，教学楼 20 W/㎡，图书馆 15 W/㎡。

**单位面积总负荷 **$ q_{total} $** (W/㎡) 计算逻辑**：

$$ q_{env} = U \times (airTemperature - T_{in}) $$ _(围护结构传热，U值简化系数取 5.0)_

$$ q_{internal} = P_{base} \times S(hour, dayofweek) + q_{person} \times S $$ _(内部得热)_

$$ q_{latent} = \max(0, 15 \times (dewTemperature - 15)) \times S $$ _(潜热/新风除湿负荷，仅在夏季露点>15℃时有效)_

**判定工况**：

+ 当 `airTemperature` > 22℃ 或 $ q_{total} > 20 $ 时，进入**制冷工况**（Cooling）。$ Q_{load} = sqm \times (q_{env} + q_{internal} + q_{latent}) / 1000 $。
+ 当 `airTemperature` < 15℃ 时，进入**供暖工况**（Heating）。$ Q_{load} = sqm \times (|q_{env}| - q_{internal}) / 1000 $。
+ 其他温度区间且负荷不高为**过渡季**（通风模式，机械制冷/供暖关闭，$ Q_{load}=0 $）。



#### 3. 空调水温：sim_supply_temp 与 sim_return_temp (单位：℃)
**国标依据**：GB 50736-2012中规定，常规冷水机组供回水温度为 **7℃/12℃**（温差5℃）；常规热水系统供回水温度为 **60℃/50℃**（温差10℃）。  
**时序及控制规则**：现代变流量(VAV/VWV)系统通常定供水温度，回水温度随部分负荷率（Part Load Ratio, PLR）动态变化。

$$ PLR = \min(1.0, \frac{Q_{load}}{Q_{design}}) $$ *(其中 $Q_{design} = sqm \times 100 W/㎡ / 1000$ 约等于建筑设计总峰值)*

+ **制冷季 (Cooling)**:
    - 如果设备开启 ($ S > 0.05 $ 且 $ Q_{load} > 0 $):  
`sim_supply_temp` = $ 7.0 + Noise(±0.2) $  
`sim_return_temp` = $ 7.0 + 5.0 \times PLR + Noise(±0.2) $
    - 如果设备关闭: 供回水温度自然趋向于 `airTemperature`。
+ **供暖季 (Heating)**:
    - 如果设备开启:  
`sim_supply_temp` = $ 60.0 + Noise(±0.5) $  
`sim_return_temp` = $ 60.0 - 10.0 \times PLR + Noise(±0.5) $
    - 如果设备关闭: 供回水温度趋向于 `airTemperature`。

---

#### 4. 空调能耗：hac_energy (单位：kWh)
**国标依据**：GB 50189-2015 规定冷水机组及系统的综合性能系数(System COP)。包含主机、水泵、冷却塔的系统综合 COP 在制冷季约为 3.5，供暖季（假设空气源热泵/锅炉综合系统）约为 2.5。

**仿真公式**：

+ 制冷季：`hac_energy` = $ Q_{load} / 3.5 + E_{pump\_base} $
+ 供暖季：`hac_energy` = $ Q_{load} / 2.5 + E_{pump\_base} $
+ 过渡季/关闭期：`hac_energy` = $ E_{ventilation} $ (如果是工作时间，通常有新风机组运行，取值约 $ sqm \times 2 W/㎡ / 1000 $)

#### 5. 总电耗：electricity (单位：kWh)
总电耗等于建筑基础设备电耗（照明、插座、电梯等）加上空调系统电耗。  
**物理与时序规则**：基础电耗随在室率时间系数 $ S $ 波动。

**仿真公式**：

$ E_{base} = \left[ sqm \times P_{base} \times S(hour, dayofweek) \right] / 1000 $

$ electricity = E_{base} + hac\_energy + Noise $

### 四、 总结：仿真算法伪代码 (Pseudocode)
供您在系统中直接实现的逻辑伪代码：

```python
# 1. 初始化常量
P_base_dict = {"Office": 25, "Teaching": 20, "Library": 15} # W/sqm
W_peak_dict = {"Office": 0.4, "Teaching": 1.0, "Library": 0.06} # L/sqm/h

P_base = P_base_dict[primaryspaceusage]
W_peak = W_peak_dict[primaryspaceusage]

# 2. 计算时间系数 S
S = get_schedule_factor(primaryspaceusage, hour, dayofweek) # 按第二部分规则

# 3. 计算水耗
water = (sqm * W_peak * S) / 1000.0 * random_normal(1.0, 0.05)

# 4. 计算空调热力学负荷 Q_load (kW)
# 估算围护结构与内部负荷 (W/sqm)
q_env = 5.0 * (airTemperature - (26.0 if airTemperature > 20 else 20.0))
q_internal = P_base * S + (10.0 * S) # 设备照明热 + 人员散热
q_latent = max(0, 15.0 * (dewTemperature - 15.0)) * S if airTemperature > 22 else 0

q_total = q_env + q_internal + q_latent
Q_design = sqm * 100.0 / 1000.0 # 假设设计峰值冷负荷指标为 100W/㎡

if airTemperature > 22 or (airTemperature >= 15 and q_total > 20):
    # 制冷模式
    mode = "Cooling"
    Q_load = (sqm * max(0.1, q_total)) / 1000.0
elif airTemperature < 15:
    # 供暖模式
    mode = "Heating"
    # 供暖负荷绝对值
    Q_load = (sqm * max(0.1, abs(q_env) - q_internal)) / 1000.0
else:
    mode = "Ventilation"
    Q_load = 0.0

# 5. 仿真空调属性
if S <= 0.05: # 设备停机夜间状态
    sim_supply_temp = airTemperature * 0.9
    sim_return_temp = airTemperature * 0.9
    hac_energy = 0.0
else:
    if mode == "Cooling":
        PLR = min(1.0, Q_load / Q_design)
        sim_supply_temp = 7.0 + random_normal(0, 0.2)
        sim_return_temp = 7.0 + (5.0 * PLR) + random_normal(0, 0.2)
        hac_energy = Q_load / 3.5 + (sqm * 2.0 / 1000.0) # 主机电耗+基础水泵风机
    elif mode == "Heating":
        PLR = min(1.0, Q_load / Q_design)
        sim_supply_temp = 60.0 + random_normal(0, 0.5)
        sim_return_temp = 60.0 - (10.0 * PLR) + random_normal(0, 0.5)
        hac_energy = Q_load / 2.5 + (sqm * 2.0 / 1000.0)
    else:
        # 过渡季节通风
        sim_supply_temp = airTemperature
        sim_return_temp = airTemperature
        hac_energy = sqm * 2.0 / 1000.0

# 6. 计算总电耗
E_base = (sqm * P_base * S) / 1000.0
electricity = E_base + hac_energy
```

### 方案特点及科学性说明：
1. **潜热物理法则的融入**：使用您提供的 `dewTemperature`（露点）精准表达了除湿负荷（潜热）。在长三角/珠三角等高湿地区（露点高于15℃），空调除湿耗能显著增加，这完美符合热力学定律。
2. **规范水温动态仿真**：完全抛弃简单的静态赋值，采用了符合国标 GB 50736 且贴近真实建筑自控系统（BMS）逻辑的部分负荷率（PLR）法。满载时回水温差达到设计的5℃/10℃，轻载时温差减小。
3. **建筑用途时序化映射**：严格根据 `primaryspaceusage` 和 `dayofweek` 切割时序特征。如办公楼周末能耗骤降，而图书馆周末能耗依然保持（甚至略高），确保仿真出的时序数据带有高度真实的周期性。


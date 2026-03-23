"""
Test: if we treat ALL rows as weekday (S computed as if weekday=True),
does the deviation disappear?
"""
import numpy as np
import pandas as pd

df = pd.read_csv("fwwb01_kpis_timeseries(6).csv")
alice = df[df['building_id'] == 'Fox_office_Alice'].copy()
ts = pd.to_datetime(alice['timestamp'])
alice['hour'] = ts.dt.hour

sqm = 1880.68; P_base = 22.0; q_person = 12.0
U_env = 5.0; cop_c = 3.6; cop_h = 2.7
pump_run = sqm * 1.0 / 1000; pump_standby = sqm * 0.15 / 1000
vent_active = sqm * 2.2 / 1000; vent_min = sqm * 0.6 / 1000
force_low = 8.0; force_high = 30.0; min_on_load = 0.05

def S_office(h, is_weekday):
    if not is_weekday: return 0.08
    if h <= 6: return 0.08
    if h == 7: return 0.2
    if h == 8: return 0.6
    if 9 <= h <= 17: return 1.0
    if 18 <= h <= 20: return 0.35
    return 0.10

def run_pipeline(S, label):
    Ta = alice['air_temp_c'].values.astype(float)
    Td = alice['dew_temp_c'].values.astype(float)
    T_in = np.where(Ta < 18, 20.0, 26.0)
    q_env = U_env * (Ta - T_in)
    q_internal = (P_base + q_person) * S
    q_latent = np.maximum(0, 15 * (Td - 15)) * S
    q_total = q_env + q_internal + q_latent

    is_cooling = np.zeros(len(alice), dtype=bool)
    is_heating = np.zeros(len(alice), dtype=bool)
    mode = 0
    for i in range(len(alice)):
        if mode == 1 and Ta[i] <= 22.0 and q_total[i] <= 14.0: mode = 0
        elif mode == -1 and Ta[i] >= 16.0: mode = 0
        if mode == 0:
            hd = Ta[i] <= 14.0 or (q_env[i] <= -18.0 and Ta[i] < 17.0)
            cd = Ta[i] >= 24.0 or q_total[i] >= 22.0
            if hd: mode = -1
            elif cd: mode = 1
        is_cooling[i] = mode == 1
        is_heating[i] = mode == -1

    Q_load = np.zeros(len(alice))
    Q_load[is_cooling] = sqm * np.maximum(0, q_env[is_cooling] + q_internal[is_cooling] + q_latent[is_cooling]) / 1000
    Q_load[is_heating] = sqm * np.maximum(0, np.abs(q_env[is_heating]) - q_internal[is_heating]) / 1000

    hvac_on = (Q_load > min_on_load) & ((S > 0.08) | (Ta < force_low) | (Ta > force_high))
    Q_load = np.where(hvac_on, Q_load, 0)
    Q_design = sqm * 100 / 1000
    PLR = np.clip(Q_load / max(Q_design, 1e-6), 0, 1)
    E_vent = np.where(S > 0.12, vent_active, vent_min)

    hac_nom = np.zeros(len(alice))
    cool_on = is_cooling & hvac_on; heat_on = is_heating & hvac_on; tran = ~(cool_on | heat_on)
    hac_nom[cool_on] = Q_load[cool_on] / cop_c + pump_run + 0.5 * E_vent[cool_on]
    hac_nom[heat_on] = Q_load[heat_on] / cop_h + pump_run + 0.4 * E_vent[heat_on]
    hac_nom[tran] = pump_standby + E_vent[tran]

    E_base = sqm * P_base * S / 1000
    elec_nom = np.maximum(0, E_base + hac_nom)

    hac_dev = np.where(hac_nom > 0.01, (alice['hac_energy'].values - hac_nom) / hac_nom * 100, 0)
    elec_dev = np.where(elec_nom > 0.01, (alice['electricity_kwh'].values - elec_nom) / elec_nom * 100, 0)

    hac_gt500 = np.sum(np.abs(hac_dev) > 500)
    hac_gt100 = np.sum(np.abs(hac_dev) > 100)
    hac_gt20 = np.sum(np.abs(hac_dev) > 20)
    elec_gt15 = np.sum(np.abs(elec_dev) > 15)

    print(f"\n=== {label} ===")
    print(f"HAC dev: mean={np.mean(hac_dev):.1f}%, median={np.median(hac_dev):.1f}%, std={np.std(hac_dev):.1f}%")
    print(f"Elec dev: mean={np.mean(elec_dev):.1f}%, median={np.median(elec_dev):.1f}%, std={np.std(elec_dev):.1f}%")
    print(f"HAC |dev|>500%: {hac_gt500}, >100%: {hac_gt100}, >20%: {hac_gt20}")
    print(f"Elec |dev|>15%: {elec_gt15}")
    return hac_gt500, elec_gt15

# Test 1: Use timestamp-derived weekday (current approach)
S_ts = np.array([S_office(h, ts.dt.dayofweek.values[i] < 5) for i, h in enumerate(alice['hour'])])
run_pipeline(S_ts, "Timestamp-derived weekday (current)")

# Test 2: Treat ALL hours as weekday
S_allwd = np.array([S_office(h, True) for h in alice['hour']])
run_pipeline(S_allwd, "ALL weekday (ignore weekends)")

# Test 3: What if the original data used dayofweek where Saturday=7 (not counted as weekday)?
# pandas: Mon=0..Sun=6; if original had Mon=1..Sun=7 and weekday=dow<=5 means Mon-Fri
# Same as timestamp-derived -> same result. Skip.

# Test 4: What if we just don't gate hvac_on with S at all?
# (let state machine alone decide)
def run_no_s_gate():
    Ta = alice['air_temp_c'].values.astype(float)
    Td = alice['dew_temp_c'].values.astype(float)
    S = S_ts
    T_in = np.where(Ta < 18, 20.0, 26.0)
    q_env = U_env * (Ta - T_in)
    q_internal = (P_base + q_person) * S
    q_latent = np.maximum(0, 15 * (Td - 15)) * S
    q_total = q_env + q_internal + q_latent

    is_cooling = np.zeros(len(alice), dtype=bool)
    is_heating = np.zeros(len(alice), dtype=bool)
    mode = 0
    for i in range(len(alice)):
        if mode == 1 and Ta[i] <= 22.0 and q_total[i] <= 14.0: mode = 0
        elif mode == -1 and Ta[i] >= 16.0: mode = 0
        if mode == 0:
            hd = Ta[i] <= 14.0 or (q_env[i] <= -18.0 and Ta[i] < 17.0)
            cd = Ta[i] >= 24.0 or q_total[i] >= 22.0
            if hd: mode = -1
            elif cd: mode = 1
        is_cooling[i] = mode == 1
        is_heating[i] = mode == -1

    Q_load = np.zeros(len(alice))
    Q_load[is_cooling] = sqm * np.maximum(0, q_env[is_cooling] + q_internal[is_cooling] + q_latent[is_cooling]) / 1000
    Q_load[is_heating] = sqm * np.maximum(0, np.abs(q_env[is_heating]) - q_internal[is_heating]) / 1000

    # NO S gate, just Q_load > min and extreme temp
    hvac_on = Q_load > min_on_load
    Q_load = np.where(hvac_on, Q_load, 0)
    Q_design = sqm * 100 / 1000
    PLR = np.clip(Q_load / max(Q_design, 1e-6), 0, 1)
    E_vent = np.where(S > 0.12, vent_active, vent_min)

    hac_nom = np.zeros(len(alice))
    cool_on = is_cooling & hvac_on; heat_on = is_heating & hvac_on; tran = ~(cool_on | heat_on)
    hac_nom[cool_on] = Q_load[cool_on] / cop_c + pump_run + 0.5 * E_vent[cool_on]
    hac_nom[heat_on] = Q_load[heat_on] / cop_h + pump_run + 0.4 * E_vent[heat_on]
    hac_nom[tran] = pump_standby + E_vent[tran]

    E_base = sqm * P_base * S / 1000
    elec_nom = np.maximum(0, E_base + hac_nom)

    hac_dev = np.where(hac_nom > 0.01, (alice['hac_energy'].values - hac_nom) / hac_nom * 100, 0)
    elec_dev = np.where(elec_nom > 0.01, (alice['electricity_kwh'].values - elec_nom) / elec_nom * 100, 0)

    print(f"\n=== No S-gate (state machine alone decides HVAC on/off) ===")
    print(f"HAC dev: mean={np.mean(hac_dev):.1f}%, median={np.median(hac_dev):.1f}%, std={np.std(hac_dev):.1f}%")
    print(f"Elec dev: mean={np.mean(elec_dev):.1f}%, median={np.median(elec_dev):.1f}%, std={np.std(elec_dev):.1f}%")
    print(f"HAC |dev|>500%: {np.sum(np.abs(hac_dev)>500)}, >100%: {np.sum(np.abs(hac_dev)>100)}, >20%: {np.sum(np.abs(hac_dev)>20)}")
    print(f"Elec |dev|>15%: {np.sum(np.abs(elec_dev)>15)}")

run_no_s_gate()

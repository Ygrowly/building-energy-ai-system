"""Verify: with Saturday=weekday, Sunday=weekend, deviation stats."""
import numpy as np
import pandas as pd

df = pd.read_csv("fwwb01_kpis_timeseries(6).csv")

# Process ALL buildings
for bid in df['building_id'].unique():
    bdf = df[df['building_id'] == bid].copy()
    ts = pd.to_datetime(bdf['timestamp'])
    bdf['hour'] = ts.dt.hour
    # ISO: Mon=1..Sun=7; notebook: only Sunday=weekend
    bdf['iso_dow'] = ts.dt.isocalendar().day.values
    bdf['is_weekday'] = bdf['iso_dow'] != 7  # only Sunday is weekend

    if 'office' in bid.lower(): usage = 'office'
    elif bid == 'Fox_public_Henry': usage = 'library'
    else: usage = 'teaching'

    def S_office(h, wd):
        if not wd: return 0.08
        if h <= 6: return 0.08
        if h == 7: return 0.2
        if h == 8: return 0.6
        if 9 <= h <= 17: return 1.0
        if 18 <= h <= 20: return 0.35
        return 0.10
    def S_teaching(h, wd):
        if not wd: return 0.15
        if h <= 6: return 0.08
        if h == 7: return 0.2
        if 8 <= h <= 12: return 1.0
        if h == 13: return 0.45
        if 14 <= h <= 17: return 1.0
        if 18 <= h <= 21: return 0.75
        return 0.10
    def S_library(h, wd):
        if h <= 6: return 0.10
        if h == 7: return 0.2
        if 8 <= h <= 21: return 0.85
        return 0.15

    sfunc = {'office': S_office, 'teaching': S_teaching, 'library': S_library}[usage]
    S = np.array([sfunc(h, w) for h, w in zip(bdf['hour'], bdf['is_weekday'])])
    S = np.clip(S, 0.08, 1.0)

    params = {'office': (22, 12, 0.36, 1880.68), 'teaching': (24, 13, 0.48, 1664.52), 'library': (20, 11, 0.30, 1251.3)}
    P_base, q_person, W_peak, sqm = params[usage]
    U = 5.0; cop_c = 3.6; cop_h = 2.7
    pump_run = sqm*1.0/1000; pump_sb = sqm*0.15/1000
    vent_a = sqm*2.2/1000; vent_m = sqm*0.6/1000

    Ta = bdf['air_temp_c'].values.astype(float)
    Td = bdf['dew_temp_c'].values.astype(float)
    T_in = np.where(Ta < 18, 20.0, 26.0)
    q_env = U * (Ta - T_in)
    q_int = (P_base + q_person) * S
    q_lat = np.maximum(0, 15*(Td-15)) * S
    q_tot = q_env + q_int + q_lat

    is_c = np.zeros(len(bdf), bool); is_h = np.zeros(len(bdf), bool)
    mode = 0
    for i in range(len(bdf)):
        if mode == 1 and Ta[i] <= 22 and q_tot[i] <= 14: mode = 0
        elif mode == -1 and Ta[i] >= 16: mode = 0
        if mode == 0:
            if Ta[i] <= 14 or (q_env[i] <= -18 and Ta[i] < 17): mode = -1
            elif Ta[i] >= 24 or q_tot[i] >= 22: mode = 1
        is_c[i] = mode == 1; is_h[i] = mode == -1

    QL = np.zeros(len(bdf))
    QL[is_c] = sqm * np.maximum(0, q_env[is_c]+q_int[is_c]+q_lat[is_c]) / 1000
    QL[is_h] = sqm * np.maximum(0, np.abs(q_env[is_h])-q_int[is_h]) / 1000

    hvac_on = (QL > 0.05) & ((S > 0.08) | (Ta < 8) | (Ta >= 30))
    QL = np.where(hvac_on, QL, 0)
    PLR = np.clip(QL / max(sqm*100/1000, 1e-6), 0, 1)
    Ev = np.where(S > 0.12, vent_a, vent_m)

    hac_n = np.zeros(len(bdf))
    co = is_c & hvac_on; ho = is_h & hvac_on; tr = ~(co|ho)
    hac_n[co] = QL[co]/cop_c + pump_run + 0.5*Ev[co]
    hac_n[ho] = QL[ho]/cop_h + pump_run + 0.4*Ev[ho]
    hac_n[tr] = pump_sb + Ev[tr]

    Eb = sqm * P_base * S / 1000
    elec_n = np.maximum(0, Eb + hac_n)

    hd = np.where(hac_n > 0.01, (bdf['hac_energy'].values - hac_n)/hac_n*100, 0)
    ed = np.where(elec_n > 0.01, (bdf['electricity_kwh'].values - elec_n)/elec_n*100, 0)

    print(f"\n=== {bid} ({usage}) ===")
    print(f"HAC dev: mean={np.mean(hd):.1f}%, median={np.median(hd):.1f}%, std={np.std(hd):.1f}%")
    print(f"  |dev|>500%: {(np.abs(hd)>500).sum()}, >100%: {(np.abs(hd)>100).sum()}, >20%: {(np.abs(hd)>20).sum()}")
    print(f"Elec dev: mean={np.mean(ed):.1f}%, median={np.median(ed):.1f}%, std={np.std(ed):.1f}%")
    print(f"  |dev|>15%: {(np.abs(ed)>15).sum()}")

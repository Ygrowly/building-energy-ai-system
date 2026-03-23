"""
Core question: Does the notebook output CSV exist with nominal columns?
If so, compare our expected vs notebook's nominal to find the systematic discrepancy.
If not, run the FULL notebook logic on the same CSV data and compare.
"""
import numpy as np
import pandas as pd
import glob

# Check if notebook output CSV with nominal columns exists
for f in glob.glob("*.csv"):
    df_check = pd.read_csv(f, nrows=2)
    if 'hac_energy_nominal' in df_check.columns:
        print(f"Found nominal columns in: {f}")
        print(f"  Columns: {list(df_check.columns)}")

# The database CSV
df = pd.read_csv("fwwb01_kpis_timeseries(6).csv")
ts = pd.to_datetime(df['timestamp'])

# Check: does the CSV's timestamp imply the correct dayofweek?
# 2016-01-02 should be Saturday (dayofweek=5 in pandas)
sample = df[df['timestamp'] == '2016-01-02 07:00:00']
for _, row in sample.iterrows():
    t = pd.to_datetime(row['timestamp'])
    print(f"\n{row['building_id']} @ {row['timestamp']}:")
    print(f"  pandas dayofweek: {t.dayofweek} ({t.strftime('%A')})")
    print(f"  hac_energy: {row['hac_energy']:.4f}")
    print(f"  sim_supply_temp_c: {row['sim_supply_temp_c']}")

# Now the REAL question: with the SAME data, what does the notebook compute?
# Let's replicate the notebook's FULL pipeline on the database CSV and compare
# nominal values with actual values

alice = df[df['building_id'] == 'Fox_office_Alice'].copy()
alice_ts = pd.to_datetime(alice['timestamp'])
alice['hour'] = alice_ts.dt.hour
alice['dow_pandas'] = alice_ts.dt.dayofweek  # Mon=0, Sat=5
alice['is_weekday'] = alice['dow_pandas'] < 5

# Compute S exactly as notebook would (from timestamp)
def S_office(h, is_weekday):
    if not is_weekday: return 0.08
    if h <= 6: return 0.08
    if h == 7: return 0.2
    if h == 8: return 0.6
    if 9 <= h <= 17: return 1.0
    if 18 <= h <= 20: return 0.35
    return 0.10

S = np.array([S_office(h, wd) for h, wd in zip(alice['hour'], alice['is_weekday'])])
sqm = 1880.68
P_base = 22.0; q_person = 12.0; W_peak = 0.36
U_env = 5.0; water_base = 0.004; water_weather = 0.002
cop_c = 3.6; cop_h = 2.7
pump_run = sqm * 1.0 / 1000; pump_standby = sqm * 0.15 / 1000
vent_active = sqm * 2.2 / 1000; vent_min = sqm * 0.6 / 1000

Ta = alice['air_temp_c'].values
Td = alice['dew_temp_c'].values

T_in = np.where(Ta < 18, 20.0, 26.0)
q_env = U_env * (Ta - T_in)
q_internal = (P_base + q_person) * S
q_latent = np.maximum(0, 15 * (Td - 15)) * S
q_total = q_env + q_internal + q_latent

# State machine (same logic)
cool_on_ta=24; cool_off_ta=22; cool_on_q=22; cool_off_q=14
heat_on_ta=14; heat_off_ta=16; heat_on_qenv=-18
force_low=8.0; force_high=30.0; min_on_load=0.05

cool_demand = (Ta >= cool_on_ta) | (q_total >= cool_on_q)
heat_demand = (Ta <= heat_on_ta) | ((q_env <= heat_on_qenv) & (Ta < heat_off_ta + 1))

is_cooling = np.zeros(len(alice), dtype=bool)
is_heating = np.zeros(len(alice), dtype=bool)
mode = 0
for i in range(len(alice)):
    if mode == 1 and Ta[i] <= cool_off_ta and q_total[i] <= cool_off_q: mode = 0
    elif mode == -1 and Ta[i] >= heat_off_ta: mode = 0
    if mode == 0:
        if heat_demand[i]: mode = -1
        elif cool_demand[i]: mode = 1
    is_cooling[i] = mode == 1
    is_heating[i] = mode == -1

Q_load = np.zeros(len(alice))
Q_load[is_cooling] = sqm * np.maximum(0, q_env[is_cooling] + q_internal[is_cooling] + q_latent[is_cooling]) / 1000
Q_load[is_heating] = sqm * np.maximum(0, np.abs(q_env[is_heating]) - q_internal[is_heating]) / 1000

# NOTEBOOK's exact hvac_on condition: S > 0.08 (strict)
hvac_on = (Q_load > min_on_load) & ((S > 0.08) | (Ta < force_low) | (Ta > force_high))
Q_load = np.where(hvac_on, Q_load, 0)

Q_design = sqm * 100 / 1000
PLR = np.clip(Q_load / max(Q_design, 1e-6), 0, 1)

E_vent = np.where(S > 0.12, vent_active, vent_min)
hac_nominal = np.zeros(len(alice))
cool_on = is_cooling & hvac_on
heat_on = is_heating & hvac_on
tran = ~(cool_on | heat_on)
hac_nominal[cool_on] = Q_load[cool_on] / cop_c + pump_run + 0.5 * E_vent[cool_on]
hac_nominal[heat_on] = Q_load[heat_on] / cop_h + pump_run + 0.4 * E_vent[heat_on]
hac_nominal[tran] = pump_standby + E_vent[tran]

E_base = sqm * P_base * S / 1000
elec_nominal = np.maximum(0, E_base + hac_nominal)

supply_nominal = Ta.copy().astype(float)
return_nominal = Ta.copy().astype(float)
supply_nominal[cool_on] = 7.0
return_nominal[cool_on] = 7.0 + 5.0 * PLR[cool_on]
supply_nominal[heat_on] = 60.0
return_nominal[heat_on] = 60.0 - 10.0 * PLR[heat_on]

# Compare nominal (our calculation) vs actual (CSV values)
alice['hac_nominal'] = hac_nominal
alice['elec_nominal'] = elec_nominal
alice['supply_nominal'] = supply_nominal
alice['return_nominal'] = return_nominal

alice['hac_dev_pct'] = np.where(hac_nominal > 0.01, 
    (alice['hac_energy'] - hac_nominal) / hac_nominal * 100, 0)
alice['elec_dev_pct'] = np.where(elec_nominal > 0.01,
    (alice['electricity_kwh'] - elec_nominal) / elec_nominal * 100, 0)

print("\n=== Deviation statistics (actual CSV vs our nominal calculation) ===")
print(f"HAC energy deviation: mean={alice['hac_dev_pct'].mean():.1f}%, "
      f"median={alice['hac_dev_pct'].median():.1f}%, "
      f"std={alice['hac_dev_pct'].std():.1f}%")
print(f"Electricity deviation: mean={alice['elec_dev_pct'].mean():.1f}%, "
      f"median={alice['elec_dev_pct'].median():.1f}%, "
      f"std={alice['elec_dev_pct'].std():.1f}%")

# How many rows have >20% deviation in hac?
hac_anomaly = alice[abs(alice['hac_dev_pct']) > 20]
print(f"\nHAC |deviation| > 20%: {len(hac_anomaly)} / {len(alice)} ({100*len(hac_anomaly)/len(alice):.1f}%)")
elec_anomaly = alice[abs(alice['elec_dev_pct']) > 15]
print(f"Elec |deviation| > 15%: {len(elec_anomaly)} / {len(alice)} ({100*len(elec_anomaly)/len(alice):.1f}%)")

# The KEY question: what are the rows with extreme deviation?
extreme = alice[abs(alice['hac_dev_pct']) > 500].copy()
print(f"\nHAC |deviation| > 500%: {len(extreme)}")
if len(extreme) > 0:
    print(extreme[['timestamp', 'hac_energy', 'hac_nominal', 'hac_dev_pct', 'sim_supply_temp_c', 'supply_nominal', 'air_temp_c', 'hour', 'is_weekday']].head(20).to_string())

# Check supply temp deviation
alice['supply_dev'] = abs(alice['sim_supply_temp_c'] - supply_nominal)
supply_anomaly = alice[alice['supply_dev'] > 1.5]
print(f"\nSupply temp |dev| > 1.5°C: {len(supply_anomaly)} / {len(alice)} ({100*len(supply_anomaly)/len(alice):.1f}%)")

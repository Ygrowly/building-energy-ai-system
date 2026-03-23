"""Run notebook state machine logic on the database CSV to see what it produces."""
import numpy as np
import pandas as pd

df = pd.read_csv("fwwb01_kpis_timeseries(6).csv")
# Add hour/dow from timestamp (same as notebook would if dayofweek column missing)
ts = pd.to_datetime(df['timestamp'])
hour = ts.dt.hour.values
dow_pandas = ts.dt.dayofweek.values  # Mon=0, Sat=5, Sun=6
dow = dow_pandas + 1  # Mon=1, Sat=6, Sun=7
weekday = dow <= 5

# Building type
BUILDING_ID_TO_TYPE = {"Fox_public_Henry": "library"}
PRIMARYSPACEUSAGE_TO_TYPE = {"office": "office", "education": "teaching", "public services": "library"}

def classify(bid, psu):
    if bid in BUILDING_ID_TO_TYPE: return BUILDING_ID_TO_TYPE[bid]
    key = str(psu).strip().lower()
    if key in PRIMARYSPACEUSAGE_TO_TYPE: return PRIMARYSPACEUSAGE_TO_TYPE[key]
    return "teaching"

# We don't have primaryspaceusage in this CSV, infer from building_id
usage = df['building_id'].map(lambda bid: "office" if "office" in bid.lower() else ("library" if bid == "Fox_public_Henry" else "teaching"))

# S functions
def S_office(h, wd):
    if not wd: return 0.08
    if h <= 6: return 0.08
    if h == 7: return 0.2
    if h == 8: return 0.6
    if 9 <= h <= 17: return 1.0
    if 18 <= h <= 20: return 0.35
    return 0.10

S = np.array([S_office(h, w) if u == "office" else 0.15 for h, w, u in zip(hour, weekday, usage.values)])
S = np.clip(S, 0.08, 1.0)

# Params (unified = office)
sqm_map = {"Fox_office_Alice": 1880.68, "Fox_education_Louie": 1664.52, "Fox_public_Henry": 1251.3}
sqm = df['building_id'].map(sqm_map).values

P_base_map = {"office": 22.0, "teaching": 24.0, "library": 20.0}
q_person_map = {"office": 12.0, "teaching": 13.0, "library": 11.0}
P_base = usage.map(P_base_map).values
q_person = usage.map(q_person_map).values

U_env = 5.0
Ta = df['air_temp_c'].ffill().bfill().fillna(20).values
Td = df['dew_temp_c'].ffill().bfill().fillna(10).values

T_in = np.where(Ta < 18.0, 20.0, 26.0)
q_env = U_env * (Ta - T_in)
q_internal = (P_base * S) + (q_person * S)
q_latent = np.maximum(0.0, 15.0 * (Td - 15.0)) * S
q_total = q_env + q_internal + q_latent

# Hysteresis params (office, unified)
cool_on_ta = 24.0; cool_off_ta = 22.0; cool_on_q = 22.0; cool_off_q = 14.0
heat_on_ta = 14.0; heat_off_ta = 16.0; heat_on_qenv = -18.0
force_on_low = 8.0; force_on_high = 30.0; min_on_load = 0.05

cool_demand = (Ta >= cool_on_ta) | (q_total >= cool_on_q)
heat_demand = (Ta <= heat_on_ta) | ((q_env <= heat_on_qenv) & (Ta < heat_off_ta + 1.0))

is_cooling = np.zeros(len(df), dtype=bool)
is_heating = np.zeros(len(df), dtype=bool)

group_key = df['building_id'].fillna("unknown").astype(str)
for bid in group_key.unique():
    idx = np.where(group_key.values == bid)[0]
    ts_sort = pd.to_datetime(df.iloc[idx]['timestamp'])
    ord_idx = idx[np.argsort(ts_sort.values)]
    mode = 0
    for j in ord_idx:
        if mode == 1 and Ta[j] <= cool_off_ta and q_total[j] <= cool_off_q:
            mode = 0
        elif mode == -1 and Ta[j] >= heat_off_ta:
            mode = 0
        if mode == 0:
            if heat_demand[j]: mode = -1
            elif cool_demand[j]: mode = 1
        is_cooling[j] = mode == 1
        is_heating[j] = mode == -1

Q_load = np.zeros(len(df))
Q_load[is_cooling] = sqm[is_cooling] * np.maximum(0.0, q_env[is_cooling] + q_internal[is_cooling] + q_latent[is_cooling]) / 1000.0
Q_load[is_heating] = sqm[is_heating] * np.maximum(0.0, np.abs(q_env[is_heating]) - q_internal[is_heating]) / 1000.0

hvac_on = (Q_load > min_on_load) & ((S > 0.08) | (Ta < force_on_low) | (Ta > force_on_high))
Q_load_orig = Q_load.copy()
Q_load = np.where(hvac_on, Q_load, 0.0)

# Check Alice weekend
alice_mask = df['building_id'] == 'Fox_office_Alice'
alice_weekend = alice_mask & (dow_pandas >= 5)

print("=== Fox_office_Alice Weekend Analysis ===")
print(f"Total weekend rows: {alice_weekend.sum()}")
print(f"State machine: is_cooling={is_cooling[alice_weekend].sum()}, is_heating={is_heating[alice_weekend].sum()}, transition={(~is_cooling[alice_weekend] & ~is_heating[alice_weekend]).sum()}")
print(f"hvac_on=True on weekend: {hvac_on[alice_weekend].sum()}")
print(f"hvac_on=False on weekend: {(~hvac_on[alice_weekend]).sum()}")
print(f"  of which had Q_load_orig > 1: {(alice_weekend & ~hvac_on & (Q_load_orig > 1)).sum()}")

# Show the rejected rows
rejected = alice_weekend & ~hvac_on & (Q_load_orig > 1)
rej_df = df[rejected][['timestamp', 'air_temp_c', 'hac_energy', 'sim_supply_temp_c']].copy()
rej_df['S'] = S[rejected]
rej_df['Q_load_orig'] = Q_load_orig[rejected]
rej_df['is_cooling'] = is_cooling[rejected]
rej_df['is_heating'] = is_heating[rejected]
print(f"\nRejected rows (hvac_on=False but Q_load_orig>1): {len(rej_df)}")
print(rej_df.head(20).to_string())

# Compare with actual hac_energy from CSV
rej_actual_hac_high = df[rejected & (df['hac_energy'] > 5)]
print(f"\nOf these, actual CSV hac_energy > 5: {len(rej_actual_hac_high)}")
print(f"This means the notebook DID have hvac_on=True for these rows")
print(f"  (since hac_energy values up to {df[rejected]['hac_energy'].max():.2f} cannot come from pump+vent alone)")

# Check what's different: S=0.08 exactly in our recomputation
print(f"\nS values on rejected rows: {np.unique(S[rejected])}")
print(f"Ta range on rejected rows: [{Ta[rejected].min():.1f}, {Ta[rejected].max():.1f}]")
print(f"force_on_low={force_on_low}, force_on_high={force_on_high}")
extreme_on_rejected = (Ta[rejected] < force_on_low) | (Ta[rejected] > force_on_high)
print(f"Extreme condition True on rejected rows: {extreme_on_rejected.sum()}")

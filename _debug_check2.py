"""Check what the notebook's internal state produces for Fox_office_Alice on weekends."""
import copy
import numpy as np
import pandas as pd

# Reproduce notebook logic for a specific building
input_path = "fwwb01_realistic_with_anomalies_cleaned.csv"
try:
    df = pd.read_csv(input_path)
except FileNotFoundError:
    print(f"Input file {input_path} not found, using output CSV to reverse-check")
    # We'll check S values from the output CSV metadata
    df = None

if df is not None:
    for c in ["hour", "dayofweek", "sqm", "airTemperature", "dewTemperature", "humidity"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    if ("timestamp" in df.columns) and (df["hour"].isna().any() or df["dayofweek"].isna().any()):
        ts = pd.to_datetime(df["timestamp"], errors="coerce")
        df.loc[df["hour"].isna(), "hour"] = ts.dt.hour
        df.loc[df["dayofweek"].isna(), "dayofweek"] = ts.dt.dayofweek + 1

    if "timestamp" in df.columns and "building_id" in df.columns:
        df = df.drop_duplicates(subset=["building_id", "timestamp"], keep="first").reset_index(drop=True)

    hour = df["hour"].fillna(0).astype(int).clip(0, 23)
    dow = df["dayofweek"].fillna(1).astype(int).clip(1, 7)
    weekday = dow <= 5

    # S_office
    def S_office(h, is_weekday):
        if not is_weekday:
            return 0.08
        if 0 <= h <= 6: return 0.08
        if h == 7: return 0.2
        if h == 8: return 0.6
        if 9 <= h <= 17: return 1.0
        if 18 <= h <= 20: return 0.35
        return 0.10

    alice = df[df['building_id'] == 'Fox_office_Alice'].copy()
    alice_idx = alice.index

    S = np.array([S_office(h, wd) for h, wd in zip(hour.iloc[alice_idx].values, weekday.iloc[alice_idx].values)])
    
    alice_ts = pd.to_datetime(alice['timestamp'])
    alice_dow_pandas = alice_ts.dt.dayofweek  # Mon=0, Sat=5

    # Check Saturday rows
    sat_mask = alice_dow_pandas.values == 5
    print(f"Alice Saturday rows: {sat_mask.sum()}")
    
    s_on_sat = S[sat_mask]
    print(f"S values on Saturday: unique={np.unique(s_on_sat)}")
    
    # Check the specific row 2016-01-02 07:00:00
    target = alice[alice['timestamp'] == '2016-01-02 07:00:00']
    if len(target) > 0:
        ti = target.index[0]
        rel_idx = list(alice_idx).index(ti)
        print(f"\n2016-01-02 07:00:00:")
        print(f"  dow column value: {dow.iloc[ti]}")
        print(f"  weekday: {weekday.iloc[ti]}")
        print(f"  hour: {hour.iloc[ti]}")
        print(f"  S: {S[rel_idx]}")
        if 'airTemperature' in alice.columns:
            print(f"  airTemperature: {alice.loc[ti, 'airTemperature']}")
    
    # Check how many weekend S=0.08 rows have hvac_on=True in notebook
    Ta = df['airTemperature'].ffill().bfill().fillna(20.0).to_numpy()
    force_on_low = 8.0
    force_on_high = 30.0
    
    alice_ta = Ta[alice_idx]
    alice_s = S
    
    extreme = (alice_ta < force_on_low) | (alice_ta > force_on_high)
    s_gt_008 = alice_s > 0.08
    
    sat_with_s008 = sat_mask & (alice_s == 0.08)
    sat_s008_extreme = sat_with_s008 & extreme
    
    print(f"\nSaturday rows with S=0.08: {sat_with_s008.sum()}")
    print(f"  of those, with extreme temp: {sat_s008_extreme.sum()}")
    print(f"  of those, with extreme Ta < 8: {(sat_with_s008 & (alice_ta < force_on_low)).sum()}")
    print(f"  of those, with extreme Ta > 30: {(sat_with_s008 & (alice_ta > force_on_high)).sum()}")
    
    # So for S=0.08, neither s>0.08 nor extreme => hvac_on=False
    # But the output CSV shows high hac_energy for these rows
    # Let's check if hvac_on would be True for ANY S=0.08 rows
    all_s008 = alice_s == 0.08
    all_s008_extreme = all_s008 & extreme
    print(f"\nALL Alice rows with S=0.08: {all_s008.sum()}")
    print(f"  with extreme temp: {all_s008_extreme.sum()}")
    print(f"  Ta range when S=0.08: [{alice_ta[all_s008].min():.1f}, {alice_ta[all_s008].max():.1f}]")
else:
    print("Could not load input file")

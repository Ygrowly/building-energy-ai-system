import pandas as pd
df = pd.read_csv('fwwb01_realistic_with_anomalies_cleaned.csv')
dow_raw = df['dayofweek'].fillna(1).astype(int).clip(1, 7)
weekday = dow_raw <= 5
ts = pd.to_datetime(df['timestamp'])

print("Sample rows:")
for i in [0, 1, 6, 7, 23, 24]:
    real_day = ts.iloc[i].strftime("%A")
    print(f"  {df.iloc[i]['timestamp']} ({real_day})  raw_dow={df.iloc[i]['dayofweek']:.0f}  processed_dow={dow_raw.iloc[i]}  weekday={weekday.iloc[i]}")

print(f"\nAll unique raw dayofweek values: {sorted(df['dayofweek'].dropna().unique())}")

# Check: Sunday rows (real dayofweek=6 in pandas)
sundays = df[ts.dt.dayofweek == 6]
print(f"\nReal Sundays: {len(sundays)} rows")
if len(sundays) > 0:
    sun_dow = sundays['dayofweek'].unique()
    print(f"  Their raw dayofweek values: {sorted(sun_dow)}")

# Saturday rows
saturdays = df[ts.dt.dayofweek == 5]
print(f"\nReal Saturdays: {len(saturdays)} rows")
if len(saturdays) > 0:
    sat_dow = saturdays['dayofweek'].unique()
    print(f"  Their raw dayofweek values: {sorted(sat_dow)}")

# After notebook processing: how many treated as weekend?
weekend_in_notebook = (dow_raw > 5).sum()
weekday_in_notebook = (dow_raw <= 5).sum()
print(f"\nNotebook treatment: weekday={weekday_in_notebook}, weekend={weekend_in_notebook}")

# So which raw dow values map to weekend?
for v in sorted(df['dayofweek'].dropna().unique()):
    processed = int(max(1, min(7, v)))
    is_wd = processed <= 5
    real_days = ts[df['dayofweek'] == v].dt.strftime('%A').unique()[:3]
    print(f"  raw={v:.0f} -> processed={processed} -> weekday={is_wd}  (actual days: {list(real_days)})")

"""Understand the 271 'impossible' rows where S=0.08 but hac_energy is high."""
import numpy as np
import pandas as pd

df = pd.read_csv("fwwb01_kpis_timeseries(6).csv")
alice = df[df['building_id'] == 'Fox_office_Alice'].copy()
alice['ts'] = pd.to_datetime(alice['timestamp'])
alice['dow_pandas'] = alice['ts'].dt.dayofweek  # Mon=0
alice['hour'] = alice['ts'].dt.hour
alice['is_weekend'] = alice['dow_pandas'] >= 5

def S_office(h, is_weekday):
    if not is_weekday: return 0.08
    if h <= 6: return 0.08
    if h == 7: return 0.2
    if h == 8: return 0.6
    if 9 <= h <= 17: return 1.0
    if 18 <= h <= 20: return 0.35
    return 0.10

alice['S'] = [S_office(h, not w) for h, w in zip(alice['hour'], alice['is_weekend'])]

# S=0.08 rows
s008 = alice[alice['S'] == 0.08]
s008_hvac_on = s008[s008['hac_energy'] > 2.0]  # clearly HVAC running
s008_hvac_off = s008[s008['hac_energy'] <= 2.0]  # HVAC off

print(f"All Alice S=0.08 rows: {len(s008)}")
print(f"  HVAC ON (hac>2): {len(s008_hvac_on)}")
print(f"  HVAC OFF (hac<=2): {len(s008_hvac_off)}")
print()

# What hours are the HVAC ON rows?
print("HVAC ON rows by hour:")
print(s008_hvac_on.groupby('hour').size().to_string())
print()

# What hours are the HVAC OFF rows?
print("HVAC OFF rows by hour distribution:")
print(s008_hvac_off.groupby('hour').size().to_string())
print()

# Check: weekend vs weekday night
print("HVAC ON rows: weekend vs weekday-night:")
print(f"  Weekend: {s008_hvac_on['is_weekend'].sum()}")
print(f"  Weekday night: {(~s008_hvac_on['is_weekend']).sum()}")
print()

# Temperature distribution of HVAC ON vs OFF at S=0.08
print("Temperature stats:")
print(f"  HVAC ON  Ta range: [{s008_hvac_on['air_temp_c'].min():.1f}, {s008_hvac_on['air_temp_c'].max():.1f}], mean={s008_hvac_on['air_temp_c'].mean():.1f}")
print(f"  HVAC OFF Ta range: [{s008_hvac_off['air_temp_c'].min():.1f}, {s008_hvac_off['air_temp_c'].max():.1f}], mean={s008_hvac_off['air_temp_c'].mean():.1f}")
print()

# Are the HVAC ON rows the ones with Ta < 8 or > 30?
force_low = 8.0; force_high = 30.0
extreme_on = s008_hvac_on[(s008_hvac_on['air_temp_c'] < force_low) | (s008_hvac_on['air_temp_c'] > force_high)]
non_extreme_on = s008_hvac_on[(s008_hvac_on['air_temp_c'] >= force_low) & (s008_hvac_on['air_temp_c'] <= force_high)]
print(f"HVAC ON rows with extreme temp (<8 or >30): {len(extreme_on)}")
print(f"HVAC ON rows WITHOUT extreme temp: {len(non_extreme_on)}")
print()

# Show some non-extreme HVAC ON rows
if len(non_extreme_on) > 0:
    print("Sample non-extreme HVAC ON rows (these are the problematic ones):")
    print(non_extreme_on[['timestamp', 'hac_energy', 'sim_supply_temp_c', 'air_temp_c', 'hour', 'is_weekend', 'S']].head(20).to_string())
    print()
    
    # What's the supply temp pattern?
    heating = non_extreme_on[non_extreme_on['sim_supply_temp_c'] > 50]
    cooling = non_extreme_on[non_extreme_on['sim_supply_temp_c'] < 10]
    ambient = non_extreme_on[(non_extreme_on['sim_supply_temp_c'] >= 10) & (non_extreme_on['sim_supply_temp_c'] <= 50)]
    print(f"  Heating (supply>50): {len(heating)}")
    print(f"  Cooling (supply<10): {len(cooling)}")
    print(f"  Ambient (10-50): {len(ambient)}")

# Key question: among ALL S=0.08 rows, what fraction has HVAC on?
total_s008 = len(s008)
hvac_on_s008 = len(s008_hvac_on)
print(f"\nFraction of S=0.08 rows with HVAC on: {hvac_on_s008}/{total_s008} = {100*hvac_on_s008/total_s008:.1f}%")
print(f"Fraction with HVAC off: {total_s008 - hvac_on_s008}/{total_s008} = {100*(total_s008-hvac_on_s008)/total_s008:.1f}%")

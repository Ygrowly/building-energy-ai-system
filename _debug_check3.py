"""Reverse-check: compare notebook OUTPUT CSV hac_energy vs what pump+vent would give."""
import numpy as np
import pandas as pd

# The notebook's output CSV
try:
    df = pd.read_csv("fwwb01_realistic_with_simulated_kpis.csv")
    print("Using notebook output CSV: fwwb01_realistic_with_simulated_kpis.csv")
except FileNotFoundError:
    print("Notebook output CSV not found. Using imported CSV.")
    df = pd.read_csv("fwwb01_kpis_timeseries(6).csv")
    print("WARNING: This is the database import CSV, may not have nominal columns")

alice = df[df['building_id'] == 'Fox_office_Alice'].copy()
alice['ts'] = pd.to_datetime(alice['timestamp'])
alice['dow'] = alice['ts'].dt.dayofweek  # Mon=0, Sat=5, Sun=6
alice['hour'] = alice['ts'].dt.hour

sqm = 1880.68
pump_standby = sqm * 0.15 / 1000  # 0.2821 kWh
vent_min = sqm * 0.6 / 1000       # 1.1284 kWh
vent_active = sqm * 2.2 / 1000    # 4.1375 kWh
pump_standby_plus_vent = pump_standby + vent_active  # 4.42 kWh when S>0.12
pump_standby_plus_vent_min = pump_standby + vent_min # 1.4105 kWh when S<=0.12

print(f"\npump_standby + vent (S<=0.12): {pump_standby_plus_vent_min:.4f} kWh")
print(f"pump_standby + vent (S>0.12): {pump_standby_plus_vent:.4f} kWh")

weekend = alice[alice['dow'] >= 5]
print(f"\nOffice weekend rows: {len(weekend)}")

# How many weekend rows have hac_energy close to pump+vent (meaning hvac_on=False in notebook)?
tran_like = weekend[abs(weekend['hac_energy'] - pump_standby_plus_vent_min) < 0.1]
print(f"Weekend rows with hac_energy ≈ pump+vent_min ({pump_standby_plus_vent_min:.3f}): {len(tran_like)}")

# How many have HIGH hac_energy?
high_hac = weekend[weekend['hac_energy'] > 5]
print(f"Weekend rows with hac_energy > 5: {len(high_hac)}")

# Show some of these high hac rows
print("\nSample high-hac weekend rows:")
cols = ['timestamp', 'hac_energy', 'sim_supply_temp_c', 'sim_return_temp_c', 'air_temp_c']
if 'hac_energy_nominal' in alice.columns:
    cols.append('hac_energy_nominal')
print(high_hac[cols].head(10).to_string())

# If hac_energy_nominal column exists, check it
if 'hac_energy_nominal' in alice.columns:
    print("\n=== Checking hac_energy_nominal on weekends ===")
    nom_tran = weekend[abs(weekend['hac_energy_nominal'] - pump_standby_plus_vent_min) < 0.1]
    nom_high = weekend[weekend['hac_energy_nominal'] > 5]
    print(f"Weekend rows with hac_energy_NOMINAL ≈ pump+vent ({pump_standby_plus_vent_min:.3f}): {len(nom_tran)}")
    print(f"Weekend rows with hac_energy_NOMINAL > 5: {len(nom_high)}")
    
    print("\nSample nominal values for the high-hac rows:")
    print(high_hac[['timestamp', 'hac_energy', 'hac_energy_nominal', 'sim_supply_temp_c', 'sim_supply_temp_c_nominal', 'air_temp_c']].head(10).to_string())

import pandas as pd
df = pd.read_csv('fwwb01_kpis_timeseries(6).csv')
alice = df[df['building_id']=='Fox_office_Alice'].copy()
alice['ts'] = pd.to_datetime(alice['timestamp'])
alice['dow'] = alice['ts'].dt.dayofweek  # Mon=0, Sat=5, Sun=6
alice['hour'] = alice['ts'].dt.hour

weekend = alice[alice['dow'] >= 5]
# HVAC active = supply temp far from ambient (cooling: ~7, heating: ~60)
hvac_active = weekend[(weekend['sim_supply_temp_c'] < 10) | (weekend['sim_supply_temp_c'] > 50)]
print(f"Office weekend rows total: {len(weekend)}")
print(f"Office weekend rows with HVAC active in actual data: {len(hvac_active)}")
print(f"  (that's {100*len(hvac_active)/len(weekend):.1f}% of weekend hours)")
print()
print("Sample weekend HVAC-active rows:")
print(hvac_active[['timestamp','hac_energy','sim_supply_temp_c','sim_return_temp_c','air_temp_c','hour']].head(15).to_string())
print()

# Now check: how many weekend hours have hac_energy > 5 (significant HVAC usage)?
significant = weekend[weekend['hac_energy'] > 5]
print(f"Office weekend rows with hac_energy > 5 kWh: {len(significant)}")
print(f"  Min hac_energy in those: {significant['hac_energy'].min():.2f}")
print(f"  Max hac_energy in those: {significant['hac_energy'].max():.2f}")
print(f"  Mean hac_energy in those: {significant['hac_energy'].mean():.2f}")

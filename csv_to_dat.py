import pandas as pd
from pathlib import Path

csv_file = Path("TK_3519_HNN_2020-10-30_processed.csv")
output_file = csv_file.with_suffix(".dat")

df = pd.read_csv(csv_file)

t = pd.to_datetime(df["time_utc"])
elapsed = (t - t.iloc[0]).dt.total_seconds()

acc = df["acceleration_m_s2"] 

with open(output_file, "w") as f:
    for time, value in zip(elapsed, acc):
        f.write(f"{time:.3f}\t{value:.8f}\n")

print("Saved:", output_file)

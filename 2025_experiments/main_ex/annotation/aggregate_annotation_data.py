import os
import pandas as pd
import re
import json

# Directory containing raw data
base_directory = "raw_data"

# Output aggregated CSV file
output_csv = "aggregated_annotation.csv"

# Extract relevant data from filenames
def parse_filename(filename):
    match = re.search(r'_(\d+)-(\d+)-(\d+)$', filename)
    if match:
        return int(match.group(1)), int(match.group(2)), int(match.group(3))
    return None, None, None

# Process all CSV files
dataframes = []
experiment_durations = []

for file in sorted(os.listdir(base_directory)):
    if file.endswith(".csv"):
        filepath = os.path.join(base_directory, file)
        df = pd.read_csv(filepath)
        
        # Extract obstacles and trial number
        filename_base = os.path.splitext(file)[0]
        num_human, num_obstacles, trial = parse_filename(filename_base)
        
        # Filter relevant events
        experiment_start = df[df['event'] == 'experiment_start']['timestamp'].values[0]
        experiment_end = df[df['event'] == 'experiment_end']['timestamp'].values[0]
        
        df_filtered = df[(df['timestamp'] >= experiment_start) & (df['timestamp'] <= experiment_end)]

        # TODO: assert len(start) == len(end)
        df_filtered = df_filtered[~df_filtered['event'].isin(['experiment_start', 'experiment_end'])]
        
        # Append metadata
        experiment_durations.append({
            'num_obstacles': num_obstacles,
            'trial': trial,
            'experiment_start': experiment_start,
            'experiment_end': experiment_end
        })
        
        # Store processed data
        dataframes.append(df_filtered)

# Save aggregated CSV
aggregated_df = pd.concat(dataframes).sort_values(by='timestamp')
aggregated_df.to_csv(output_csv, index=False)

# Save experiment durations config
ex_duration_config = "ex_duration_config.json"
with open(ex_duration_config, "w") as f:
    json.dump(experiment_durations, f, indent=4)

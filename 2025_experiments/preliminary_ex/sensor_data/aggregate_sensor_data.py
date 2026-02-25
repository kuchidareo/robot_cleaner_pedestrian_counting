import os
import pandas as pd

def aggregate_csv_files(base_dir, output_file):
    all_data = []
    
    for subdir in os.listdir(base_dir):
        subdir_path = os.path.join(base_dir, subdir)
        if not os.path.isdir(subdir_path):
            continue
        
        acc_file = os.path.join(subdir_path, 'Accelerometer.csv')
        gyro_file = os.path.join(subdir_path, 'Gyroscope.csv')
        orient_file = os.path.join(subdir_path, 'Orientation.csv')
        
        if not all(os.path.exists(f) for f in [acc_file, gyro_file, orient_file]):
            print(f"Skipping {subdir} because one or more CSV files are missing.")
            continue
        
        # Read CSV files
        acc_df = pd.read_csv(acc_file).drop(columns=['seconds_elapsed'], errors='ignore')
        gyro_df = pd.read_csv(gyro_file).drop(columns=['seconds_elapsed'], errors='ignore')
        orient_df = pd.read_csv(orient_file).drop(columns=['seconds_elapsed'], errors='ignore')
        
        # Rename columns
        acc_df = acc_df.rename(columns={"z": "accelerometer_z", "y": "accelerometer_y", "x": "accelerometer_x"})
        gyro_df = gyro_df.rename(columns={"z": "gyroscope_z", "y": "gyroscope_y", "x": "gyroscope_x"})
        orient_df = orient_df.rename(columns={
            "qz": "orientation_qz", "qy": "orientation_qy", "qx": "orientation_qx", "qw": "orientation_qw",
            "roll": "orientation_roll", "pitch": "orientation_pitch", "yaw": "orientation_yaw"
        })
        
        # Merge dataframes on 'time'
        merged_df = acc_df.merge(gyro_df, on='time', how='outer').merge(orient_df, on='time', how='outer')
        merged_df['source_directory'] = subdir  # Add directory name for reference
        
        all_data.append(merged_df)
    
    # Concatenate all dataframes into a single dataframe
    final_df = pd.concat(all_data, ignore_index=True)
    
    # Save merged CSV
    final_df.to_csv(output_file, index=False)
    print(f"Saved aggregated data at {output_file}")

# Set paths
base_directory = "raw_data"
output_file = "aggregated_data.csv"

# Run aggregation
aggregate_csv_files(base_directory, output_file)

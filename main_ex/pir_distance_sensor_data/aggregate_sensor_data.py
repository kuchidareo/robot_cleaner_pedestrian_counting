import os
import glob
import csv
from datetime import datetime
import pandas as pd

def read_pir_files(directory):
    """
    Reads all PIR CSV files (filenames starting with 'PIRData_') from the given directory.
    Expected CSV format: Hrs,minn,sec,PirVal (with optional header).
    The filename is assumed to be in the format: PIRData_YYYY_MM_DD_HH_mm.csv or PIRData_YYYY_MM_DD_HH_mm_SS.csv.
    Combines the file's date with the row's time.
    Returns a list of dictionaries with keys: 'dt', 'pir', and 'ms' (initially 0).
    """
    pir_records = []
    pattern = os.path.join(directory, "PIRData_*.csv")
    for filepath in sorted(glob.glob(pattern)):
        base = os.path.basename(filepath)
        # Extract date string from filename
        date_str = base.replace("PIRData_", "").replace(".csv", "")
        try:
            # Try the format with seconds first
            file_date = datetime.strptime(date_str, "%Y_%m_%d_%H_%M_%S")
        except ValueError:
            try:
                # If that fails, try the format without seconds
                file_date = datetime.strptime(date_str, "%Y_%m_%d_%H_%M")
            except ValueError:
                continue

        with open(filepath, newline='') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                # Skip header or malformed rows.
                if not row or not row[0].strip().isdigit():
                    continue
                try:
                    hr = int(row[0].strip())
                    minute = int(row[1].strip())
                    sec = int(row[2].strip())
                    pir_value = row[3].strip()
                    # Combine the file date with the row's time values.
                    full_dt = file_date.replace(hour=hr, minute=minute, second=sec)
                    pir_records.append({'dt': full_dt, 'pir': pir_value, 'ms': 0})
                except (ValueError, IndexError):
                    continue
    return pir_records

def read_distance_files(directory):
    """
    Reads all distance CSV files (filenames starting with 'UltrasonicData_') from the given directory.
    Expected CSV format: Hrs,minn,sec,mic,Dis (with optional header).
    The filename is assumed to be in the format: UltrasonicData_YYYY_MM_DD_HH_mm.csv or UltrasonicData_YYYY_MM_DD_HH_mm_SS.csv.
    Combines the file's date with the row's time.
    Returns a list of dictionaries with keys: 'dt', 'distance', and 'ms' (initially 0).
    """
    distance_records = []
    pattern = os.path.join(directory, "UltrasonicData_*.csv")
    for filepath in sorted(glob.glob(pattern)):
        base = os.path.basename(filepath)
        date_str = base.replace("UltrasonicData_", "").replace(".csv", "")
        try:
            # Try the format with seconds first
            file_date = datetime.strptime(date_str, "%Y_%m_%d_%H_%M_%S")
        except ValueError:
            try:
                # If that fails, try the format without seconds
                file_date = datetime.strptime(date_str, "%Y_%m_%d_%H_%M")
            except ValueError:
                continue

        with open(filepath, newline='') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                if not row or not row[0].strip().isdigit():
                    continue
                try:
                    hr = int(row[0].strip())
                    minute = int(row[1].strip())
                    sec = int(row[2].strip())
                    # Column index 4 (fifth column) holds the distance value.
                    distance_value = row[4].strip()
                    full_dt = file_date.replace(hour=hr, minute=minute, second=sec)
                    distance_records.append({'dt': full_dt, 'distance': distance_value, 'ms': 0})
                except (ValueError, IndexError):
                    continue
    return distance_records

def assign_milliseconds(records):
    """
    Groups records by their full datetime (ignoring milliseconds) and assigns a millisecond offset.
    For each group with count c, the increment is calculated as 1000/c.
    Then, for each record in that group (in the original order), the i-th record gets an offset of int(round(i * (1000/c))).
    """
    # First pass: count occurrences per second (ignoring ms)
    counts = {}
    for rec in records:
        key = rec['dt'].strftime("%Y-%m-%d %H:%M:%S")
        counts[key] = counts.get(key, 0) + 1

    # Second pass: assign offsets according to the order of occurrence.
    group_counter = {}
    for rec in records:
        key = rec['dt'].strftime("%Y-%m-%d %H:%M:%S")
        total = counts[key]
        increment = 1000 / total  # even spacing within one second
        count = group_counter.get(key, 0)
        rec['ms'] = int(round(count * increment))
        group_counter[key] = count + 1

def create_dataframe(records, sensor_col, col_name):
    """
    Given a list of records, creates a pandas DataFrame with a timestamp column (formatted as
    'YYYY-MM-DD HH:MM:SS.mmm') and one sensor value column.
    sensor_col: the key in the record that holds the sensor value.
    col_name: the column name to use in the DataFrame.
    """
    timediff = 2 # UTC+2

    # Build a list of timestamps using dt and ms.
    timestamps = [
        f"{(rec['dt'] - pd.Timedelta(hours=timediff)).strftime('%Y-%m-%d %H:%M:%S')}.{rec['ms']:03d}"
        for rec in records
    ]
    values = [rec[sensor_col] for rec in records]
    df = pd.DataFrame({ 'timestamp': timestamps, col_name: values })
    # Use the timestamp as the index.
    df.set_index('timestamp', inplace=True)
    return df

def main():
    # Directory where your CSV files are stored.
    data_dir = "raw_data"

    # Read records from the PIR and distance CSV files.
    pir_records = read_pir_files(data_dir)
    distance_records = read_distance_files(data_dir)

    # Preserve the original order and assign milliseconds.
    assign_milliseconds(pir_records)
    assign_milliseconds(distance_records)

    # Create separate DataFrames.
    df_pir = create_dataframe(pir_records, 'pir', 'PIRvalue')
    df_distance = create_dataframe(distance_records, 'distance', 'distance')

    # Merge the two DataFrames with an outer join on their timestamp index.
    df_agg = pd.concat([df_pir, df_distance], axis=1, sort=True)
    df_agg.sort_index(inplace=True)

    # Write the aggregated data to CSV.
    output_file = "AggregatedData.csv"
    df_agg.to_csv(output_file, index_label='timestamp')
    print(f"Aggregated data written to {os.path.abspath(output_file)}")

if __name__ == "__main__":
    main()
def run_availability_analysis(data):
    if "reliability_score" not in data.columns:
        raise ValueError("Dataframe is missing required column 'reliability_score'")

    active = data["reliability_score"] > 0.7
    active_samples = int(active.sum())
    total_samples = len(data)
    availability = active_samples / total_samples if total_samples else 0.0

    print()
    print("===== AVAILABILITY ANALYSIS =====")
    print(f"Active Samples : {active_samples}")
    print(f"Total Samples  : {total_samples}")
    print(f"Availability   : {availability:.2%}")
    print()

    return {
        "active_samples": active_samples,
        "total_samples": total_samples,
        "availability": availability,
    }

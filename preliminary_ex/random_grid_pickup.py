import random

def random_pick(num_picks):
    selected_numbers = random.sample(range(1, 16), num_picks+1)  # Pick unique numbers
    return sorted(selected_numbers[:-1]), selected_numbers[-1]

# Example usage
print(random_pick(1))

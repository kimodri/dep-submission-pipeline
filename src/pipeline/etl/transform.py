import json
from pipeline.etl.bronze import transform_raw_to_bronze

if __name__ == "__main__":
    with open("data/raw/v2-response.json", "r") as f:
        data = json.load(f)

    print(data)
    print(type(data))

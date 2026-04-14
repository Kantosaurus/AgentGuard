import json
from datetime import datetime, timezone

def convert_jsonl_timestamps(input_path, output_path):
    """
    Convert 'ts' (milliseconds since epoch) in a JSONL file
    to ISO 8601 format, keeping the key as 'ts'.

    Args:
        input_path (str): Path to input JSONL file
        output_path (str): Path to output JSONL file
    """
    with open(input_path, 'r', encoding='utf-8') as infile, \
         open(output_path, 'w', encoding='utf-8') as outfile:

        for line in infile:
            line = line.strip()
            if not line:
                continue

            data = json.loads(line)

            if "ts" in data:
                # Convert milliseconds → seconds
                ts_seconds = data["ts"] / 1000.0

                # Convert to ISO 8601 (UTC)
                data["ts"] = datetime.fromtimestamp(
                    ts_seconds, tz=timezone.utc
                ).isoformat()

            outfile.write(json.dumps(data) + "\n")

if __name__ == "__main__":
    input_file = "C:/Users/zhaoh/Desktop/DL_Proj20/Theory-and-application-of-deep-learning/data/dataset/infinite/ssm-2026-03-16.jsonl"
    output_file = "C:/Users/zhaoh/Desktop/DL_Proj20/Theory-and-application-of-deep-learning/data/dataset/infinite/processed/ssm-2026-03-16.jsonl"

    convert_jsonl_timestamps(input_file, output_file)
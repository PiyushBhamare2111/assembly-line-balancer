"""Convert Scholl (1993) SALBP benchmark files (.IN2 + Excel optima) into this repo's CSV/JSON format.

Usage:
    python scripts/convert_scholl.py <folder containing "precedence graphs/" and "SALBP data sets.xlsx">

Source: https://assembly-line-balancing.de/salbp/benchmark-data-sets-1993/
(SALBP-data-sets.zip, Scholl 1993 / Scholl 1999).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

# file stem -> (display name used in the Excel sheet, csv stem)
INSTANCES = {
    "MERTENS": ("Mertens", "mertens"),
    "BOWMAN8": ("Bowman", "bowman"),
    "JAESCHKE": ("Jaeschke", "jaeschke"),
    "JACKSON": ("Jackson", "jackson"),
    "MITCHELL": ("Mitchell", "mitchell"),
    "HESKIA": ("Heskiaoff", "heskiaoff"),
    "BUXEY": ("Buxey", "buxey"),
    "SAWYER30": ("Sawyer", "sawyer"),
    "KILBRID": ("Kilbridge", "kilbridge"),
}


def parse_in2(path: Path):
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    n = int(lines[0])
    times = [int(x) for x in lines[1 : n + 1]]
    preds = {i: [] for i in range(1, n + 1)}
    for ln in lines[n + 1 :]:
        a, b = ln.split()[0].split(",")
        a, b = int(a), int(b)
        if a == -1:
            break
        preds[b].append(a)
    return times, preds


def optima(xlsx: Path, sheet: str, name: str):
    df = pd.read_excel(xlsx, sheet_name=sheet, header=None)
    out = {}
    for row in df.itertuples(index=False):
        if str(row[0]).strip() == name:
            try:
                out[str(int(row[1]))] = int(row[2])
            except (ValueError, TypeError):
                pass
    return out


def main(root: str, dest: str = "data/benchmarks"):
    root_p, dest_p = Path(root), Path(dest)
    dest_p.mkdir(parents=True, exist_ok=True)
    xlsx = root_p / "SALBP data sets.xlsx"
    meta = {}
    for stem, (name, csv_stem) in INSTANCES.items():
        times, preds = parse_in2(root_p / "precedence graphs" / f"{stem}.IN2")
        rows = [
            {"task_id": str(i), "description": f"{name} task {i}", "time": t,
             "predecessors": ";".join(str(p) for p in preds[i])}
            for i, t in enumerate(times, start=1)
        ]
        pd.DataFrame(rows).to_csv(dest_p / f"{csv_stem}.csv", index=False)
        meta[csv_stem] = {
            "name": name,
            "source_file": f"{stem}.IN2",
            "n_tasks": len(times),
            "total_time": sum(times),
            "salbp1_optima": optima(xlsx, "SALBP-1 data set", name),   # cycle time -> m*
            "salbp2_optima": optima(xlsx, "SALBP-2 data sets", name),  # stations -> c*
        }
    meta_out = {
        "source": "Scholl, A. (1993) SALBP benchmark data sets, https://assembly-line-balancing.de/salbp/benchmark-data-sets-1993/",
        "instances": meta,
    }
    (dest_p / "optima.json").write_text(json.dumps(meta_out, indent=2))
    print(json.dumps(meta_out, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:])

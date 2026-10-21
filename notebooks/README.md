# Notebooks (your exercises)

This folder is for analysis notebooks. Start by loading the database:

```python
import sqlite3, pandas as pd
con = sqlite3.connect("../data/blues.db")   # run `python -m pipeline.update` first
pms = pd.read_sql("SELECT * FROM player_match_stats JOIN players USING (player_id)", con)
long = pd.read_sql("SELECT * FROM player_match_stats_long", con)  # every raw stat, long format
```

Suggested exercises are listed in the roadmap in the main README.

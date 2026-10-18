# Data

`sample_reviews_synthetic.csv` contains **48 synthetic, hand-written example reviews** for a
fictional dungeon crawler. They are illustrative only, so the demo runs offline. They are not
real player reviews and should be described as synthetic in the report.

## Using real Steam reviews (recommended for the paper)

1. Download a Steam reviews dataset from Kaggle (search "Steam reviews dataset"). Most have a
   column called `review_text` or `review`, plus `review_score` / `voted_up`.
2. Save the CSV in this folder, e.g. `data/steam_reviews.csv`.
3. Run with:

   ```
   python run_demo.py --reviews data/steam_reviews.csv --review-limit 400
   ```

The loader auto-detects the text column (`review_text`, `review`, `content` or `text`).
Pick reviews for a dungeon-crawler / roguelike game so the complaints match this level model.

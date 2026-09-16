"""
SalesIQ synthetic data engine.
Generates a deterministic, internally-consistent e-commerce dataset
(products, customers, orders) plus a daily revenue series with realistic
seasonality/promo effects, used to power every dashboard page.
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

RNG_SEED = 42
HISTORY_DAYS = 270  # enough lookback for 30d lags + up to 240d "training history"

CATEGORIES = ["Electronics", "Sports", "Home & Garden", "Clothing",
              "Toys", "Beauty", "Food", "Books"]

PRODUCT_CATALOG = {
    "Electronics": [("Laptop", 45000), ("Speaker", 2200), ("Headphones", 1800),
                     ("Smartwatch", 3500), ("Tablet", 15000), ("Power Bank", 900),
                     ("Router", 1500), ("Webcam", 1200), ("Monitor", 9000), ("Mouse", 500)],
    "Sports": [("Football", 650), ("Cricket Bat", 1200), ("Yoga Mat", 700),
               ("Dumbbell Set", 2200), ("Badminton Racket", 900), ("Skipping Rope", 200),
               ("Running Shoes", 2500), ("Cycling Helmet", 1100), ("Gym Gloves", 350), ("Tennis Ball", 150)],
    "Home & Garden": [("Vase", 450), ("Table Lamp", 900), ("Garden Hose", 600),
                       ("Plant Pot", 250), ("Wall Clock", 700), ("Cushion Cover", 300),
                       ("Curtain Set", 1500), ("Doormat", 350), ("Storage Box", 550), ("Candle Set", 400)],
    "Clothing": [("Cap", 300), ("Jeans", 1400), ("T-Shirt", 500), ("Jacket", 2800),
                 ("Sneakers", 2200), ("Formal Shirt", 1100), ("Hoodie", 1600),
                 ("Socks Pack", 250), ("Belt", 600), ("Scarf", 400)],
    "Toys": [("Art Kit", 550), ("Building Blocks", 900), ("Puzzle Set", 400),
             ("RC Car", 1800), ("Board Game", 700), ("Action Figure", 600),
             ("Doll House", 2200), ("Kite", 150), ("Card Game", 300), ("Toy Train", 1300)],
    "Beauty": [("Face Cream", 450), ("Shampoo", 350), ("Perfume", 1800), ("Lipstick", 500),
               ("Sunscreen", 400), ("Hair Dryer", 1500), ("Nail Kit", 300),
               ("Face Wash", 250), ("Body Lotion", 400), ("Trimmer", 1200)],
    "Food": [("Tea Bags", 200), ("Coffee Beans", 650), ("Chocolate Box", 500),
             ("Cookies", 150), ("Honey Jar", 350), ("Spice Set", 450),
             ("Pasta Pack", 180), ("Cereal Box", 320), ("Namkeen Pack", 120), ("Juice Bottle", 90)],
    "Books": [("Novel", 350), ("Cookbook", 600), ("Self-Help Book", 400),
              ("Comic Book", 200), ("Biography", 500), ("Textbook", 900),
              ("Poetry Collection", 300), ("Travel Guide", 450), ("Children's Book", 250), ("Notebook Set", 150)],
}

FIRST_NAMES = ["Adam", "Priya", "Rahul", "Sara", "Vikram", "Neha", "John", "Anita",
               "David", "Meera", "Karan", "Fatima", "Rohan", "Divya", "Aman", "Kavya",
               "Arjun", "Sneha", "Michael", "Pooja", "Rajesh", "Isha", "Sameer", "Riya",
               "Nikhil", "Tanya", "Suresh", "Alia", "Varun", "Simran"]
LAST_NAMES = ["Lee", "Sharma", "Verma", "Khan", "Gupta", "Patel", "Singh", "Kumar",
              "Reddy", "Nair", "Mehta", "Joshi", "Rao", "Iyer", "Chopra", "Malhotra",
              "Bose", "Das", "Kapoor", "Agarwal"]


def _rng():
    return np.random.default_rng(RNG_SEED)


def build_products() -> pd.DataFrame:
    rng = _rng()
    rows = []
    pid = 1
    for cat in CATEGORIES:
        for name, base_price in PRODUCT_CATALOG[cat]:
            price = round(base_price * rng.uniform(0.9, 1.15), -1) or base_price
            stock = int(rng.integers(15, 160))
            rows.append({
                "product_id": pid, "name": name, "category": cat,
                "unit_price": float(price), "stock": stock,
            })
            pid += 1
    # force two deterministic low-stock items so the demo matches the reference UI
    df = pd.DataFrame(rows)
    df.loc[df["name"] == "Tea Bags", "stock"] = 4
    df.loc[df["name"] == "Football", "stock"] = 7
    return df


def build_customers(n=480) -> pd.DataFrame:
    rng = _rng()
    rows = []
    for cid in range(1, n + 1):
        fn = FIRST_NAMES[rng.integers(0, len(FIRST_NAMES))]
        ln = LAST_NAMES[rng.integers(0, len(LAST_NAMES))]
        rows.append({"customer_id": cid, "name": f"{fn} {ln}"})
    return pd.DataFrame(rows)


def _daily_base_revenue(dates: pd.DatetimeIndex) -> np.ndarray:
    """Weekly seasonality + slow trend + promo spikes + noise, in INR."""
    rng = _rng()
    n = len(dates)
    t = np.arange(n)
    trend = 2600 + t * 2.0
    weekly = 900 * np.sin(2 * np.pi * (dates.dayofweek.values / 7.0) + 1.2)
    weekend_boost = np.where(dates.dayofweek.values >= 5, 650, 0)
    noise = rng.normal(0, 550, n)
    promo_mask = rng.random(n) < 0.12
    promo_spike = np.where(promo_mask, rng.uniform(2500, 6500, n), 0)
    revenue = trend + weekly + weekend_boost + noise + promo_spike
    return np.clip(revenue, 300, None), promo_mask


class Dataset:
    """Lazily-built, process-wide singleton holding all synthetic tables."""
    def __init__(self):
        self.today = pd.Timestamp(datetime.utcnow().date())
        self.dates = pd.date_range(end=self.today, periods=HISTORY_DAYS, freq="D")
        self.products = build_products()
        self.customers = build_customers()
        self.daily_revenue, self.promo_mask = _daily_base_revenue(self.dates)
        self.orders = self._build_orders()

    def _build_orders(self) -> pd.DataFrame:
        rng = _rng()
        products = self.products
        customers = self.customers
        # cheaper items sell more units, but keep the skew moderate (sqrt-damped)
        # plus a floor so every product gets *some* sales history to forecast from
        raw_w = 1.0 / np.sqrt(products["unit_price"].values)
        raw_w = raw_w / raw_w.sum()
        floor = 0.3 / len(products)
        weights = raw_w * 0.7 + floor
        weights = weights / weights.sum()
        rows = []
        order_id = 1
        for i, day in enumerate(self.dates):
            day_rev_target = self.daily_revenue[i]
            spent = 0.0
            n_orders_today = max(3, int(day_rev_target / 260))
            for _ in range(n_orders_today):
                if spent >= day_rev_target * 1.15:
                    break
                cust_id = int(customers["customer_id"].iloc[rng.integers(0, len(customers))])
                p_idx = rng.choice(len(products), p=weights)
                prod = products.iloc[p_idx]
                qty = int(rng.integers(1, 4))
                discount = float(rng.choice([0, 0, 0, 5, 10, 15], p=[0.55, 0.1, 0.1, 0.1, 0.1, 0.05]))
                line_rev = prod["unit_price"] * qty * (1 - discount / 100.0)
                rows.append({
                    "order_id": order_id, "date": day, "customer_id": cust_id,
                    "product_id": int(prod["product_id"]), "category": prod["category"],
                    "qty": qty, "unit_price": float(prod["unit_price"]),
                    "discount_pct": discount, "revenue": round(float(line_rev), 2),
                    "is_promotion": bool(self.promo_mask[i]),
                })
                spent += line_rev
                order_id += 1
        return pd.DataFrame(rows)

    # ---- derived views -------------------------------------------------
    def daily_revenue_series(self) -> pd.DataFrame:
        df = self.orders.groupby("date")["revenue"].sum().reindex(self.dates, fill_value=0).reset_index()
        df.columns = ["date", "revenue"]
        promo = pd.Series(self.promo_mask, index=self.dates)
        df["is_promotion"] = promo.reindex(df["date"]).values
        return df


_DATASET = None


def get_dataset() -> Dataset:
    global _DATASET
    if _DATASET is None:
        _DATASET = Dataset()
    return _DATASET

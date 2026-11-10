import pandas as pd
L = pd.read_csv("data/processed/2026-06-14/listings.csv.gz", low_memory=False)
print("=== TẤT CẢ TÊN CỘT ===")
print(L.columns.tolist())
print("\n=== THỐNG KÊ SỐ LISTING MỖI KHU VỰC ===")
print(L["neighbourhood_cleansed"].value_counts().describe())
print("\n=== XEM TRƯỚC 5 DÒNG DỮ LIỆU ===")
print(L[["room_type", "price_usd", "number_of_reviews"]].head())

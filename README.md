# Streamlit – מנוע תמהילי קרנות השתלמות (RTL)

## מה יש כאן?
- `app.py` – האפליקציה המלאה
- `requirements.txt` – ספריות נדרשות

## איך מריצים מקומית
```bash
pip install -r requirements.txt
streamlit run app.py
```

## איך פורסים ב-Streamlit Community Cloud
1. פתח Repo ב-GitHub והעלה אליו את `app.py` ו-`requirements.txt`
2. היכנס ל-Streamlit Cloud → New app → בחר Repo → Deploy
3. מומלץ להגדיר Secrets:
   - `APP_PASSWORD` – סיסמה לפתיחת האפליקציה (ברירת מחדל בקוד: 1234)

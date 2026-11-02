# RAW permanence + Cloud catalog — סטטוס וראיות (2026-10-31)

סטטוסים: **PASS** = הורץ ועבר, עם הראיה · **FAIL** · **BLOCKED** = חסם חיצוני · **NOT_TESTED** = לא הורץ.

| # | יכולת | סטטוס | ראיה |
|---|---|---|---|
| 1 | סרטון מקור נשאר ב-`raw/` אחרי עיבוד (בייטים זהים) | **PASS** (S3 אמיתי מקומי / moto) | `scripts/test_raw_permanence_e2e.py`: run 1 → 24 מקורות ב-`raw/`, ETag זהה, `processed/` ריק |
| 2 | ריצה חוזרת לא מעבדת מחדש ולא מוחקת | **PASS** | אותו קובץ: run 2 מקבל 0; run 3 רק 3 חדשים; marker מצמיד גודל+ETag (קובץ שהוחלף מעובד שוב) |
| 3 | Reset/Rerun לא מוחק מקור | **PASS** | אותו קובץ: 2 מחזורי reset+run, `raw/` זהה; full clean מוחק רק `approved/` |
| 4 | Cleanup לא מוחק מקור | **PASS** | `web-api/scripts/video-storage-cleanup.test.ts` 10/10: מקורות `raw/`+`processed/` שורדים; `deleteStep` מסרב |
| 5 | Dedup לא מוחק | **PASS** | e2e + `test_exact_source_upload_dedup_contract.py`: callback מחיקה אפילו לא נקרא |
| 6 | אין מסלול מחיקה/העברה לא-נסקר בקוד | **PASS** | `scripts/test_raw_source_protection_contract.py`: מלאי כל אתרי המחיקה; הוכח שהוא נכשל כשמוסיפים אתר חדש |
| 7 | `delete_object/move_object` מסרבים למקור | **PASS** | אותו חוזה + e2e (`ProtectedSourceError`, ללא override) |
| 8 | שחזור מקורות מ-`processed/` — העתקה בלבד, הוכחת SHA-256, בלי דריסה, Dry Run | **PASS** (על S3 מקומי) | `scripts/test_raw_recovery.py` (24 בדיקות): מזהה `missing`/`unverifiable`/`sha_mismatch`/`conflict`/`elsewhere`; `apply` דורש אישור, הכול-או-כלום |
| 9 | מצב אמיתי של R2 | **PASS** (קריאה בלבד, 31.10.2026) | workflow חד-פעמי `inventory`+`plan` (run 41226399910, הוסר אחרי הריצה): `raw/` 93, `processed/` 23, `review/` 6; 116 מקורות עוקבים: 93 `raw_ok` + 23 `processed_only`, **0 חסרים**, 0 `raw/` לא מזוהים. 24 הסרטונים האמיתיים: 23 ב-`processed/` עם SHA-256 תואם לרשומה (verified=yes) ו-1 ב-`raw/`. 23 העתקות מתוכננות, **לא בוצעו** |
| 10 | רשומות DB (29 מקורות פעילים, 24 אמיתיים 6.5GB, 185 שנמחקו בעבר) | **PASS** (קריאה בלבד, מצטבר) | `STAGE1-REPORT.md` §2 |
| 11 | קטלוג ענן ב-Studio (שם, ענף, תאריך, משך, מצב פייפליין, מיקום, זמינות, תיוג) | **PASS** (S3 מדומה + ffmpeg אמיתי) | `annotation-studio/tests/cloud.test.mjs` 9/9 (SQLite **ו**-PostgreSQL), `tests/e2e/cloud.mjs` 7/7 |
| 12 | צפייה בסרטון מהענן עם גלילה (Range), בלי הורדה מלאה, בלי חשיפת מפתחות | **PASS** (מדומה) | 206 עם הבייטים המדויקים; 401 בלי טוקן; HTML/localStorage ללא מפתח |
| 13 | תיוג ספורטאי+אירוע, שמירה, סגירה/פתיחה | **PASS** (מדומה) | cloud e2e תרחישים 3–5 |
| 14 | אישור Ground Truth מחייב אימות SHA-256 מהבייטים | **PASS** | `SOURCE_UNVERIFIED` נחסם; אחרי אימות עובר; בייט הפוך בבאקט → `mismatch` |
| 15 | הבאקט לא שונה, רק GET/HEAD | **PASS** | כל הבדיקות: snapshot זהה, לוג ה-stub ללא PUT/POST/DELETE; בדיקה סטטית של `cloud.mjs` |
| 16 | חיבור אמיתי ל-R2 וצפייה בסרטון אמיתי | **BLOCKED / NOT_TESTED** | דורש טוקן קריאה בלבד (פעולה שלך, `CLOUD-QUICKSTART.md`) |
| 17 | Gate פריסה/Production | **NOT_TESTED בכוונה** | שום דבר לא נפרס; השינוי בפייפליין נכנס לתוקף רק אחרי מיזוג ופריסה |

## הרצות שבוצעו בסשן
* Studio SQLite **87/87**; PostgreSQL (חבילה מלאה) 86 + 1 דולג, 0 נכשלו; בידוד PG 8/8; cloud ב-PG 9/9.
* Playwright: מסכים **17/17**, זרימה מלאה **14/14**, ענן **7/7**.
* Python: 17 חוזים/e2e הקשורים, כולם עוברים; `web-api` cleanup 10/10.
* שלושה כשלים קיימים שאינם שלי (נבדקו מול `main`): `test_background_upload_contract`, `test_production_upload_api_smoke` (חסר psycopg), בדיקות `real_r2` (דורשות אישורי R2).

## מגבלות פתוחות
1. הגנה ברמת קוד בלבד; מפתח R2 של הפייפליין עדיין יכול למחוק ידנית ← Bucket lock (אתה, דשבורד).
2. גיבוי עצמאי של סרטוני ה-R2 עצמם אינו קיים (Studio קורא in-place).
3. `processed/` ישן: אחרי שחזור בהעתקה יהיו שני עותקים (≈2×6.5GB, ~13GB > 10GB חינם ≈ $0.05/חודש) — מחיקה של עותקי `processed/` היא שלב נפרד שיידרש אישור.
4. CI אדום: Trivy על node-forge — תיקון ב-PR #313 (מחכה למיזוג); בדיקת Android ב-#313 נכשלה בתשתית האמולטור.

## עדכון — אחרי המלאי האמיתי
* סרטון אמיתי ב-`processed/` **אינו חוסם** צפייה ותיוג: הקטלוג כולל `processed/` והזהות מאומתת ב-SHA-256 (הוכח בריצת `plan`). שחזור ל-`raw/` נשאר החלטה נפרדת שלך.
* בדיקת רגרסיה על קובץ במבנה צילום אמיתי (4K HEVC 10-bit, 29.97 fps, אודיו, `moov` בסוף): נפתח מהענן, probe+תמונה ממוזערת תקינים, ועותק התיוג שומר פריים N = פריים N (`annotation-studio/tests/cloud.test.mjs`).
* מסך התיוג מתרענן אוטומטית כשעותק התיוג מוכן (HEVC עלול לא להתנגן בדפדפן לפני כן) ומציג כשל בבנייתו.
* **עדיין NOT_TESTED:** חיבור ה-Studio עצמו ל-R2 האמיתי וצפייה בסרטון אמיתי בדפדפן, והלאנצ'ר ב-Windows — דורשים טוקן קריאה בלבד והפעלה על המחשב שלך.

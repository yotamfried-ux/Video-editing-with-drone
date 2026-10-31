# שלב 1 — דוח חקירה (קריאה בלבד): מצב סרטוני המקור והפייפליין

תאריך: 2026-10-31 · ענף: `ccr-5ce1d535-e7mo2b` (PR #312) · שום פעולה לא שינתה R2, Supabase או Production.
מקורות הראיות: קריאת קוד המאגר; שאילתות **מצטברות בלבד** (ספירות/סכומים, בלי תוכן משתמשים) מול Supabase של SportReel דרך חיבור קריאה.
סטטוסים: **PASS / FAIL / BLOCKED / NOT_TESTED**.

## 1. מה קורה לסרטון מהרגע שמעלים אותו (לפני התיקון)

| שלב | מה הקוד עושה | ראיה |
|---|---|---|
| העלאה | האפליקציה כותבת ל-`raw/<קובץ>` (ישן: `raw/<batch>/<קובץ>`), רשומה ב-`source_uploads` (sha256, גודל, סטטוס) | `web-api/src/lib/r2-storage.ts:126-130`, טבלת `source_uploads` |
| הרצת פייפליין | קורא את כל `raw/` (בכל עומק), מוריד, מחשב SHA-256, בודק כפילויות | `pipeline/r2_batch_scope.py` |
| **סיום עיבוד** | **`mark_as_processed` = העתקה מאומתת ל-`processed/` ואז מחיקת המקור מ-`raw/`** (commit `6614f6c`: "moves sources on") | `r2_batch_scope.py` (לפני התיקון), `integrations/r2_storage.py: move_object_verified` |
| טיוטות | `review/` → אחרי אישור מפעיל `approved/` (העברה) → `pending_payment/`, `previews/` | `operator-draft-approve.ts:101` |
| Reset/Rerun | מחזיר מ-`processed/` ל-`raw/` (העתקה מאומתת ואז מחיקת העותק ב-`processed/`), מוחק `review/` (ו-`approved/` ב-full clean) | `scripts/reset_and_rerun.py` |
| **Cleanup** (`DELETE_OLD_VIDEOS`) | מוחק **כל** סרטון תחת `raw/ processed/ review/ approved/ pending_payment/ pending_uploads/ previews/` + סרטוני Supabase `reels` + מנטרל שורות DB | `web-api/src/lib/video-storage-cleanup.ts` |
| **Dedup** | באצ'-סקופ: מחיקת המקור "הישן" מ-`raw/`; ללא באצ' — נשמר | `pipeline/source_upload_dedup.py` (לפני התיקון) |
| סקריפטי QA | מחיקות נקודתיות של אובייקטי בדיקה | ראה סעיף 4 |

**מסקנה:** המצב הקודם **הוציא את המקור מ-`raw/`** בכל הרצה מוצלחת (ראיה מקומית: `test_stage_folder_flow_e2e` על שרת S3 אמיתי, לפני התיקון: "every source ends flat in processed/, raw/ is empty"). בנוסף Cleanup ו-Dedup יכלו למחוק מקור בפועל.

## 2. מה קיים כיום — רשומות קבועות ב-Supabase (`source_uploads`)

| קבוצה | כמות | נפח | הערות |
|---|---|---|---|
| `verified` (מקורות פעילים) | **29** (29 SHA-256 שונים) | **6,547 MB** | **24 קבצים** באצ'`batch_2026-10-03…ttgvat95` (6,547 MB — הסרטונים האמיתיים), ועוד **5 קבצים זעירים** (0 MB, 16–21.10 — כנראה בדיקות). הגדול ביותר 723 MB |
| `superseded` | 87 | 8 MB | קבצי בדיקה זעירים; לכולם יש מקור קנוני `verified` תקין (0 יתומים) |
| `aborted` + `removed_at` | 185 | 8,112 MB | 20.9–6.10: נמחקו ע"י Cleanup. **לא ניתן לשחזר מהענן** |
| אירועי Cleanup (`video_storage_cleanup_runs`) | 11 ריצות 30.9–3.10 (10 הצליחו, 1 נכשלה) | 113 אובייקטי R2 דווחו כנמחקו | לפי `totals.r2_deleted` |
| Dedup (`source_upload_dedup_audit`) | 750 החלטות; **39 הוסרו** | 3 MB, כולם 27.9 | מחיקות אמיתיות של אובייקטים קטנים — ההוכחה שהמסלול פעיל |
| ריצות פייפליין | 34 הצליחו (אחרונה 16.7), 27 נכשלו (אחרונה 30.10), 5 `no_input` | | |

## 3. איפה הסרטונים עכשיו ב-R2? — **BLOCKED** (לא "חסרים")

אין לסביבה הזו גישת R2 (לא הוגדרו אישורי R2; לא השתמשתי באישורי proxy של הסביבה). לכן **אני לא מצהיר שסרטון חסר**. מה שידוע מהראיות:
* רשומות ה-DB מצביעות על `raw/…` גם לסרטונים שהועברו (`rekey_source_upload` מעדכן את המפתח ל-`raw/`), ולכן **המפתח ב-DB אינו מעיד על מיקום בפועל**.
* מ-commit `f66a3d3` (ריצה אמיתית קודמת): ה-layout האמיתי היה **23 ב-`processed/<batch>/` ו-1 ב-`raw/<batch>/`** — מצב נוכחי לא אומת.

הכלי לקבלת התשובה (קריאה בלבד): `scripts/raw_recovery.py inventory|plan`, או ה-workflow `RAW recovery (inventory / plan / apply)` (הפעלה ידנית). הוא מסווג כל אחד מ-29 המקורות: `raw_ok / raw_alt_key / processed_only / elsewhere / missing`, ובודק אלטרנטיבות (אותו שם+גודל בכל קידומת) **לפני** שהוא קובע "חסר". **דורש אישור שלך להפעלה** (שימוש באישורי Production לקריאה בלבד).

## 4. כל מסלולי המחיקה/העברה בקוד (מלאי מלא)

נסרקו כל קבצי py/ts/js/yml/sh במאגר. הבדיקה `scripts/test_raw_source_protection_contract.py` נועלת את המלאי: **אתר מחיקה חדש שלא נסקר מפיל את ה-CI**.

| מסלול | מה מוחק | לפני | אחרי |
|---|---|---|---|
| `r2_storage.delete_object / move_object / move_object_verified` | כל מפתח | יכל על `raw/` | **מסרב** ל-`raw/` ולכל וידאו ב-`processed/` (`ProtectedSourceError`, ללא override) |
| `mark_as_processed` | `raw/` אחרי העתקה | **מזיז** | כותב marker זעיר ב-`metadata/source_state/`; הסרטון לא נוגע |
| `requeue_video`, `restore_processed_to_raw`, `reconcile_frozen_inputs` | מוחקים עותק `processed/` אחרי שחזור | מזיזים | **העתקה מאומתת בלבד**; `processed/` נשמר |
| Dedup | מקור "ישן" | מוחק (בבאצ') | **מוציא מהריצה, לא מוחק** |
| `reset_and_rerun` | `processed/` + `review/` (+`approved/`) | מוחק processed | מוחק רק `review/`/`approved/` + markers |
| web-api Cleanup | `raw/ processed/ …` | הכול | **רק פלטים נגזרים** (`review/ approved/ pending_* previews/`); `raw/`+`processed/` מדווחים כ"לא ניתן למחיקה" |
| `deleteR2Object` / `moveR2Object` (web-api) | כל מפתח | הכול | מסרבים ל-`raw/` ו-`processed/` |
| `purge-upl01-test-uploads.yml` | 8 אובייקטי בדיקה מפורטים | חד-פעמי | **נשאר** (מפתחות מפורשים, assert על 8) — רשום כחריג מנומק |
| `upload-foundation-release.yml` | אובייקט evidence סינתטי שלו | | נשאר, חריג מנומק |
| `background_upload_evidence.py purge` | `raw/<batch>/` של באצ' בדיקה | | נשאר, חסום ע"י `purge_guard`; חריג מנומק |
| `app_review_delivery_e2e.py cleanup` | 2 קבצים סינתטיים ששתל | | נשאר, חריג מנומק |
| `video_storage_cleanup_e2e.py teardown` | רק מפתחות עם `e2e_clean_` | | נשאר, חריג מנומק |
| Google Drive backend (`integrations/drive.py`) | review/approved | | לא בשימוש (`STORAGE_BACKEND=r2`); ללא מחיקת מקורות |

**חשוב — מגבלת הגנה (לא מוסתרת):** ההגנה היא ברמת *הקוד*. מי שמחזיק את מפתח ה-R2 של הפייפליין (קריאה+כתיבה+מחיקה) עדיין *טכנית* מסוגל למחוק ידנית. הגנה מלאה דורשת שכבת ענן: **Bucket lock/retention על `raw/`** ב-Cloudflare (ללא עלות לפי המסמכים, צריך לאמת) — פעולה שלך בדשבורד, ראה `phase-b/INFRASTRUCTURE-DECISION.md`.

## 5. סיכונים לזמינות סרטוני המקור

| # | סיכון | חומרה | טיפול |
|---|---|---|---|
| 1 | המקורות האמיתיים אולי ב-`processed/` ולא ב-`raw/` | גבוהה | `raw_recovery.py plan` + העתקה בלבד באישורך |
| 2 | אין גיבוי נפרד לסרטוני ה-R2 עצמם | גבוהה | העתקה מקומית (Studio לא מעתיק כרגע; הכלי קורא in-place) — החלטה שלך |
| 3 | מחיקה ידנית/Cleanup עם מפתח כתיבה | בינונית | הקוד נעול; מומלץ Bucket lock |
| 4 | 185 סרטונים (8.1 GB) ישנים נמחקו בעבר | ידוע | לא ניתן לשחזר מהענן; ייתכן עדיין בטלפון/SD של המעלה |
| 5 | כל ריצה מוצלחת מעבירה — **תוקן בקוד, לא נפרס** | | נכנס לתוקף רק אחרי מיזוג ופריסה |

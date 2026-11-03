# הרצה במחשב שלך (Windows) — צעד אחר צעד

מטרה: להפיק במחשב שלך את הראיות שחסרות ל־`CATALOG_GO`. הן לא יכולות להיווצר בענן, כי הסרטונים האמיתיים, הטוקן של R2 והדיסק החיצוני נמצאים רק אצלך.
משך משוער: 60–90 דקות. שום שלב לא כותב ל־R2 ולא נוגע בתיוגים הקיימים שלך.

## 0. מה צריך
- Node.js 22.13 ומעלה ו־FFmpeg (כמו בהפעלה הרגילה של הסטודיו).
- הקובץ `annotation-studio\.studio-cloud.env` שכבר עובד אצלך (טוקן R2 לקריאה בלבד).
- דיסק חיצוני מחובר, למשל `E:`.

## 1. גיבוי של מה שיש לך היום (לפני הכול)
סגור את הסטודיו אם הוא פתוח. העתק את כל תיקיית `STUDIO_HOME` (הנתיב שמופיע ב־`.studio-cloud.env`) לתיקייה אחרת, למשל `C:\Users\<אתה>\studio-backup-before-v2`. זו רשת ביטחון: הגרסה החדשה רק מוסיפה עמודות וטבלאות למסד הקיים ולא מוחקת דבר.

## 2. משיכת הגרסה החדשה (ענף ה־PR, עוד לא ממוזג)
פתח PowerShell בתיקיית הריפו:
```powershell
git fetch origin
git checkout claude/focused-pasteur-16w1dp
git pull
cd annotation-studio
npm ci
```

## 3. הסמכה אוטומטית מול 7 סרטונים אמיתיים
הסקריפט רץ על **עותק חדש ומבודד**. הוא לא פותח את הסטודיו האמיתי שלך, קורא מ־R2 בלבד, ושומר תמונות פרטיות **מחוץ לריפו**.

בחר בלשונית **ענן** בסטודיו 7 סרטונים לפי הסוגים בטבלה, והעתק את השם שלהם בדיוק כפי שהוא מוצג. מותר גם הנתיב המלא, למשל `raw/...`.

| סוג (`--case`) | איזה סרטון |
|---|---|
| `single` | גולש אחד ברור |
| `multi` | שני גולשים או יותר |
| `crossing` | גולשים שחוצים זה את זה |
| `occlusion` | הגולש מוסתר (גל או קצף) |
| `4k_fast` | 4K עם תנועה מהירה |
| `quality_issue` | בעיית איכות או חוסר ודאות |
| `no_events` | סרטון בלי שום אירוע |

```powershell
node --env-file=.studio-cloud.env scripts\qualify-real-footage.mjs --evidence "$env:USERPROFILE\sportreel-qualification" --case single=<שם> --case multi=<שם> --case crossing=<שם> --case occlusion=<שם> --case 4k_fast=<שם> --case quality_issue=<שם> --case no_events=<שם> --probe-delete-permission
```
**מה אמור לצאת:** בסוף ההרצה `Automated part: PASS_AUTOMATED_PART_ONLY`, וגם השורה `token cannot delete` עם `PASS`. הבדיקה הזו שולחת בקשת מחיקה לקובץ שלא קיים, כך ששום נתון לא נמחק.
- אם `token cannot delete` יוצא `FAIL`, לטוקן יש הרשאת מחיקה. צור ב־Cloudflare טוקן **Object Read only** במקומו לפני שאתה ממשיך.
- כל `FAIL` אחר: שלח לי את הקובץ `qualification-*.json` מהתיקייה. הוא לא מכיל סודות.

## 4. בדיקה ידנית בממשק (על העותק המבודד)
הסקריפט יצר תיקייה `isolated-gt-<תאריך>` בתוך `%USERPROFILE%\sportreel-qualification`. פתח עליה את הסטודיו:
```powershell
$env:STUDIO_HOME = "$env:USERPROFILE\sportreel-qualification\isolated-gt-<תאריך>"
node --env-file=.studio-cloud.env server\main.mjs
```
פתח את הכתובת שמודפסת (`http://127.0.0.1:...?t=...`). ההגדרה של STUDIO_HOME בשורה הראשונה גוברת על הקובץ, ולכן אתה עובד על העותק ולא על הנתונים האמיתיים.

בכל אחד מ־7 הסרטונים:
1. בתמונות `review-*.png` שבתיקייה `frames-<תאריך>` רואים את ה־BOX האוטומטי של הבדיקה. **הוא לא אמור להיות על הגולש**, הוא רק בדיקה מכנית.
2. בסטודיו: צור אירוע (`I`/`O`), בחר **מי ביצע**, וקבע שימושיות והחלטה.
3. לחץ `B` וצייר BOX על הגולש. בלשונית **אימות BOX** עבור על **כל נקודות הבדיקה** (תחילה, אמצע, סוף, הצטלבות, הסתרה) וסמן בכל אחת: נכון / גולש שגוי / מוסתר / לא ניתן לקבוע.
4. בסרטון ההצטלבות: סמן בכוונה פעם אחת "גולש שגוי" וודא שכפתור האישור נחסם. אחר כך תקן.
5. סגור את הסטודיו (Ctrl+C בחלון PowerShell), הפעל אותו מחדש באותה פקודה, וודא שהכול נשמר.
6. **אל תאשר גרסת Ground Truth.**

רשום לכל סרטון עבר / נכשל / מה היה לא נוח.

## 5. גיבוי מוצפן לדיסק נפרד
1. צור קובץ מפתח עם משפט סיסמה של 12 תווים לפחות. **שמור את המשפט גם במנהל סיסמאות.** בלי המשפט אי אפשר לשחזר את הגיבוי.
   ```powershell
   notepad "$env:USERPROFILE\.sportreel-backup-key.txt"
   ```
2. גיבוי ראשון ובדיקה, מתוך `annotation-studio`, על הסטודיו האמיתי שלך:
   ```powershell
   node --env-file=.studio-cloud.env scripts\gt-offsite-backup.mjs run --to E:\sportreel-gt --key-file "$env:USERPROFILE\.sportreel-backup-key.txt"
   ```
   ```powershell
   node --env-file=.studio-cloud.env scripts\gt-offsite-backup.mjs verify --to E:\sportreel-gt --key-file "$env:USERPROFILE\.sportreel-backup-key.txt"
   ```
   התוצאה הצפויה היא `"ok":true` ו־`device_check: distinct_physical_disk`. אם מתקבל `BACKUP_SAME_DISK`, הדיסק שבחרת הוא מחיצה על אותו כונן פיזי. בחר דיסק אחר.
3. תזמון יומי, והרצה אחת מיד:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install-backup-schedule.ps1 -To "E:\sportreel-gt" -KeyFile "$env:USERPROFILE\.sportreel-backup-key.txt" -At 21:00
   ```
   ```powershell
   schtasks /Run /TN "SportReel GT Backup"
   ```
   אחרי דקה בדוק את היומן בקובץ `%LOCALAPPDATA%\SportReel\backup.log`.
4. תרגיל שחזור לתיקייה ריקה (לא נוגע בנתונים האמיתיים):
   ```powershell
   $env:STUDIO_HOME = "$env:TEMP\restore-drill"
   node scripts\gt-offsite-backup.mjs restore --to E:\sportreel-gt --key-file "$env:USERPROFILE\.sportreel-backup-key.txt"
   ```
   אחר כך הפעל את הסטודיו על `restore-drill` (כמו בשלב 4) וודא שהגולשים, השיוכים והאירועים קיימים.

## 6. מה לשלוח לי
- הקובץ `qualification-*.json` מתוך `%USERPROFILE%\sportreel-qualification`. **בלי התמונות.**
- את הסיכום שרשמת בשלב 4 לכל אחד מ־7 הסרטונים.
- פלט `verify` ושלוש השורות האחרונות ב־`backup.log`. **בלי המפתח.**

עם החומר הזה אעדכן את `CATALOG-READINESS.md`. אם הכול עבר, ההחלטה תשתנה ל־`CATALOG_GO`. רק אחרי זה מאשרים את התיוג האמיתי הראשון.

# הסטודיו בענן: Supabase הקיים + Vercel

מה מקבלים: הסטודיו עובד מכל מקום, גם כשהמחשב כבוי, בכתובת קבועה `https://studio.d2ryf.com`. נכנסים אליו עם קוד כניסה.

## מה כבר בוצע (ב־4 בנובמבר 2026)
- **Supabase (הפרויקט הקיים `sportreel`):**
  - נוצרה סכמה נפרדת בשם `ground_truth` עם כל טבלאות הקטלוג (35), ותפקיד `gt_studio` לסטודיו.
  - לא נוצר מסד נתונים חדש.
  - לא שונה דבר ב־`public`, ולא בהיסטוריית המיגרציות של הייצור.
- **בדיקה חיה של ההפרדה:**
  - ל־`anon`, `authenticated`, `service_role` ו־`authenticator` אין אף הרשאה על נתוני הקטלוג.
  - ניסיון קריאה כ־`service_role` (המפתח של הפייפליין) נחסם: `permission denied for schema ground_truth`.
  - לסטודיו אין הרשאת מחיקה, ולכל הטבלאות יש RLS.
- **הקוד** (PR בענף `claude/focused-pasteur-16w1dp`):
  - מצב Vercel: הסרטונים מתנגנים ישירות מ־R2 בקישור זמני לקריאה בלבד.
  - כניסה עם קוד.
  - העברה חד־פעמית של הנתונים מהמחשב.

## מה נשאר לך: 4 שלבים, כ־20 דקות
הסודות (סיסמת מסד הנתונים, קוד הכניסה, מפתח R2) מוזנים **רק על ידך**. הם לא עוברים דרך הצ'אט או דרך GitHub.

### שלב 1: סיסמה לתפקיד של הסטודיו ב־Supabase
1. בחר סיסמה ארוכה, 30 תווים לפחות, **מאותיות באנגלית ומספרים בלבד** (בלי `@ : / ? #`). מומלץ ליצור אותה במנהל הסיסמאות ולשמור אותה שם.
2. ב־Supabase ← הפרויקט `sportreel` ← **SQL Editor** הרץ את השורה הבאה, עם הסיסמה שלך:
   ```sql
   alter role gt_studio password 'הסיסמה-שלך';
   ```
3. ב־Supabase לחץ **Connect** בראש העמוד ← **Transaction pooler** והעתק את ה־**host**, שנראה כמו `aws-1-eu-central-1.pooler.supabase.com`.

### שלב 2: יצירת הפרויקט ב־Vercel
1. https://vercel.com ← **Add New…** ← **Project** ← בחר את המאגר `Video-editing-with-drone` ← **Import**.
2. **Project Name:** `sportreel-studio`.
3. **Root Directory:** לחץ **Edit** ובחר `annotation-studio`.
4. **Framework Preset:** `Other`. אל תשנה את פקודות ה־Build, הן מוגדרות בקובץ `vercel.json`.
5. פתח **Environment Variables** והוסף את המשתנים הבאים:

| Key | Value |
|---|---|
| `STUDIO_DB_URL` | `postgresql://gt_studio.bcndgmymnismbxvdeetc:הסיסמה-משלב-1@ה-host-משלב-1:6543/postgres` |
| `STUDIO_DB_SSL` | `require` |
| `STUDIO_TOKEN` | קוד כניסה שתבחר: ארוך, אותיות ומספרים. איתו תיכנס לסטודיו. |
| `STUDIO_SERVERLESS` | `1` |
| `STUDIO_ALLOWED_HOSTS` | `studio.d2ryf.com,sportreel-studio.vercel.app` |
| `STUDIO_CLOUD_INCLUDE` | `DJI` |
| `STUDIO_CLOUD_R2_BUCKET` | `sportreel` |
| `STUDIO_CLOUD_R2_ACCOUNT_ID` | אותו ערך שבקובץ `.studio-cloud.env` שבמחשב |
| `STUDIO_CLOUD_R2_ACCESS_KEY_ID` | אותו ערך שבקובץ `.studio-cloud.env` (הטוקן לקריאה בלבד) |
| `STUDIO_CLOUD_R2_SECRET_ACCESS_KEY` | אותו ערך שבקובץ `.studio-cloud.env` |

6. לחץ **Deploy**.

> הכתובות שהסטודיו מוכן לענות להן הן רק אלה שב־`STUDIO_ALLOWED_HOSTS`, ובנוסף הכתובות האוטומטיות של הפריסה עצמה (Vercel מעביר אותן אוטומטית). אם Vercel נתן לפרויקט שם אחר מ־`sportreel-studio`, תקן את השם במשתנה הזה. כל כתובת אחרת נחסמת.

> **חשוב:** השתמש בטוקן R2 **לקריאה בלבד**, זה שכבר יש לך במחשב. אל תשתמש במפתחות של הפייפליין, שיש להם הרשאת כתיבה.

### שלב 3: בדיקה
1. פתח את הכתובת ש־Vercel נותן, למשל `https://sportreel-studio.vercel.app`.
2. אמור להופיע מסך **כניסה לסטודיו**. הדבק את `STUDIO_TOKEN` ולחץ כניסה.
3. בקטלוג לחץ **עדכן מהענן**. רשימת סרטוני ה־DJI אמורה להופיע.
4. שלח לי את הכתובת. אבדוק מרחוק שהחיבור למסד הנתונים תקין.

> אם מופיעה הודעה "הסטודיו לא הצליח להתחבר למסד הנתונים", היא כוללת את הסיבה (בלי סיסמאות). שלח לי אותה.

### שלב 4: הכתובת הקבועה `studio.d2ryf.com`
1. ב־Vercel: הפרויקט `sportreel-studio` ← **Settings** ← **Domains** ← הוסף `studio.d2ryf.com`.
2. Vercel יציג רשומת **CNAME**, בדרך כלל `cname.vercel-dns.com`.
3. ב־Namecheap ← `d2ryf.com` ← **Advanced DNS** ← **ADD NEW RECORD**:
   - Type: `CNAME Record`
   - Host: `studio`
   - Value: הערך ש־Vercel הציג
   - TTL: Automatic

   זו **רשומה אחת בלבד**. שאר הרשומות (`api`, `app`, `n8n`, המייל) לא משתנות.
4. אחרי כמה דקות Vercel יציג **Valid Configuration** ויפיק אישור HTTPS אוטומטית.

## העברת הנתונים מהמחשב (פעם אחת)
אחרי שהכתובת עובדת, הרץ במחשב, מתוך התיקייה `annotation-studio`:
```powershell
node --env-file=.studio-cloud.env scripts\migrate-to-cloud.mjs --url https://studio.d2ryf.com --code הקוד-שלך
```
- הסקריפט קורא את הקטלוג המקומי בלבד ולא משנה אותו.
- הענן מקבל את הנתונים **רק אם מסד הנתונים בענן ריק**, ובודק כל טבלה אחרי הייבוא.
- אם עבדת כבר בסטודיו בענן לפני ההעברה, הייבוא ייחסם (`IMPORT_TARGET_NOT_EMPTY`) כדי לא לדרוס נתונים. במקרה כזה פנה אליי.

## אבטחה: שדרוג מומלץ
- **אימות מלא של החיבור למסד הנתונים:**
  1. ב־Supabase ← **Database Settings** ← **SSL Configuration** ← הורד את התעודה.
  2. ב־Vercel הוסף משתנה `STUDIO_DB_CA` ובו תוכן קובץ התעודה.
  3. מחק את `STUDIO_DB_SSL`.
- **גיבוי:** הנתונים נמצאים ב־Supabase. בדוק בהגדרות הפרויקט אילו גיבויים התוכנית שלך כוללת. גיבוי עצמאי נוסף הוא השלב הבא שמומלץ להוסיף.

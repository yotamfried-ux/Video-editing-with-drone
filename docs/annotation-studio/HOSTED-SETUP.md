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

## מעקב BOX אוטומטי בענן: הרשאת CORS לדלי R2
המעקב האוטומטי קורא את פיקסלי הווידאו בדפדפן. במחשב זה עובד בלי שום הגדרה. בכתובת בענן הווידאו מגיע ישירות מ־R2, ולכן הדלי צריך לאשר קריאה מהכתובות של הסטודיו. בלי ההרשאה הסטודיו מציג הודעה, וה־BOX נשמר רק בפריים שציירת.

ההגדרה לא נוגעת בסרטונים. היא רק מתירה לדפדפן לקרוא אותם מהכתובות האלה.

1. Cloudflare ← **R2** ← הדלי `sportreel` ← **Settings** ← **CORS Policy** ← **Add CORS policy**.
2. הדבק:
   ```json
   [
     {
       "AllowedOrigins": ["https://studio.d2ryf.com", "https://sportreel-studio.vercel.app"],
       "AllowedMethods": ["GET", "HEAD"],
       "AllowedHeaders": ["Range"],
       "ExposeHeaders": ["Content-Length", "Content-Range", "Accept-Ranges"],
       "MaxAgeSeconds": 3600
     }
   ]
   ```
3. שמור, ורענן את הסטודיו.

## עותקי צפייה קלים (720p) במקום 4K
המקוריים הם 4K ב־60 פריימים לשנייה, בערך 167 Mb/s, ולכן כבדים מדי לצפייה רציפה. הסטודיו מנגן עותק 720p (בערך 4 Mb/s) כשהוא קיים. כל סימון נשאר זהה, כי לעותק יש בדיוק אותם פריימים ואותו קצב. הסקריפט בודק זאת לפני ההעלאה.

**איפה נשמרים העותקים:** בדלי הקיים `sportreel`, בתיקייה `studio/previews/` בלבד. לא נוצר דלי חדש.

**איך המקוריים מוגנים** (הבידוד נאכף על ידי R2 עצמו, לא רק על ידי הקוד):
- כל העלאה נעשית עם **הרשאה זמנית** (שעה) שנחתמת במחשב שלך. ההרשאה מתירה **פעולה אחת בלבד**, `PutObject`, ו**רק** תחת `studio/previews/`. עם ההרשאה הזו R2 מסרב לכתוב, לדרוס, למחוק או אפילו לקרוא קובץ מקור.
- כל העלאה היא "יצירה בלבד" (`If-None-Match: *`): R2 מסרב לדרוס עותק שכבר קיים.
- הקוד מסרב לשלוח בכלל בקשה לנתיב מחוץ ל־`studio/previews/`.
- הסטודיו עצמו (באתר) רק קורא, עם הטוקן לקריאה בלבד.
- קטלוג הסטודיו סורק רק את `raw/` ו־`processed/`, ולכן העותקים לא מופיעים כ"סרטונים".

### שלב א: מפתח־אב לחתימה (Cloudflare)
1. **R2** ← **Manage API tokens** ← **Create API token**.
2. **Permissions**: **Object Read & Write**. **Specify bucket**: `sportreel` בלבד.
3. **TTL**: קבע תאריך תפוגה קרוב, למשל שבוע. אפשר ליצור מפתח חדש בכל פעם שצריך.
4. שמור את ה־Access Key ID וה־Secret.
5. **חשוב:** למפתח הזה יש הרשאת כתיבה לכל הדלי. הוא משמש **רק לחתימה מקומית** של ההרשאה הזמנית ואף פעם לא נשלח ל־R2. לכן:
   - הוא לא נכנס ל־Vercel.
   - הוא לא נכנס ל־`.studio-cloud.env`.
   - הוא נשמר בקובץ נפרד `.studio-previews.env`. אחרי ההרצה מוחקים את הקובץ, ובסוף מבטלים את הטוקן ב־Cloudflare.

### שלב ב: יצירת העותקים במחשב שלך
1. צור בתיקייה `annotation-studio` את הקובץ `.studio-previews.env`:
   ```
   STUDIO_PREVIEW_PARENT_ACCESS_KEY_ID=...
   STUDIO_PREVIEW_PARENT_SECRET_ACCESS_KEY=...
   ```
2. בדיקה יבשה, שלא כותבת כלום:
   ```powershell
   node --env-file=.studio-cloud.env --env-file=.studio-previews.env scripts\make-previews.mjs --dry-run
   ```
3. יצירה (בערך דקה לכל סרטון). הרצה חוזרת מדלגת על מה שכבר נוצר:
   ```powershell
   node --env-file=.studio-cloud.env --env-file=.studio-previews.env scripts\make-previews.mjs
   ```
4. מחק את `.studio-previews.env` ובטל את הטוקן ב־Cloudflare.

### שלב ג: האתר
- אין צורך בשום הגדרה. הסטודיו באתר מוצא את העותקים לבד, עם הטוקן לקריאה בלבד הקיים.
- כל עוד לסרטון אין עותק, הוא מנוגן מהמקור.
- `STUDIO_CLOUD_PREVIEWS=0` מכבה את השימוש בעותקים.
- הרשאת ה־CORS של הדלי `sportreel` כבר מכסה גם את העותקים (נדרשת למעקב ה־BOX).

## אבטחה: שדרוג מומלץ
- **אימות מלא של החיבור למסד הנתונים:**
  1. ב־Supabase ← **Database Settings** ← **SSL Configuration** ← הורד את התעודה.
  2. ב־Vercel הוסף משתנה `STUDIO_DB_CA` ובו תוכן קובץ התעודה.
  3. מחק את `STUDIO_DB_SSL`.
- **גיבוי:** הנתונים נמצאים ב־Supabase. בדוק בהגדרות הפרויקט אילו גיבויים התוכנית שלך כוללת. גיבוי עצמאי נוסף הוא השלב הבא שמומלץ להוסיף.

# כתובת קבועה לסטודיו: `https://studio.הדומיין-שלך`

מה מקבלים: כתובת אחת שלא משתנה, שעובדת מכל מקום (גם מהטלפון) ונכנסים אליה עם קוד שנשלח למייל שלך.

איך זה עובד:
- הסטודיו ממשיך לרוץ **במחשב שלך**, והנתונים, מפתח R2 ועותקי הצפייה נשארים שם.
- תוכנה קטנה של Cloudflare (`cloudflared`) פותחת חיבור מוצפן **מהמחשב החוצה** אל Cloudflare. לא פותחים פורט בראוטר.
- בפתח הכתובת עומדת כניסה של Cloudflare Access. רק המייל שתגדיר יכול להיכנס.
- הסטודיו עצמו בודק את חתימת הכניסה של Cloudflare בכל בקשה. אם הכניסה לא מוגדרת, הכתובת הקבועה **נחסמת**, ולא נפתחת לכולם.
- **עלות:** אין. החבילה החינמית של Cloudflare מספיקה.

**תנאי:** המחשב והסטודיו צריכים לפעול. כשהם כבויים, הכתובת תציג עמוד שגיאה של Cloudflare. שום נתון לא נחשף.

זמן משוער: 30–45 דקות, ועוד המתנה של עד כמה שעות להעברת ה־DNS.

---

## שלב 1: הוספת הדומיין ל־Cloudflare (חינם)
1. היכנס ל־https://dash.cloudflare.com עם החשבון שבו נמצא R2.
2. לחץ **Add a domain** (או Add site), הקלד את הדומיין שלך (בלי `www`) ובחר **Free**.
3. Cloudflare סורק את רשומות ה־DNS הקיימות ומציג אותן. **עבור על הרשימה** וודא שמופיעות הרשומות של האתר ושל המייל. בדרך כלל אלה רשומות `A` או `CNAME` לאתר, ו־`MX` ו־`TXT` למייל. אם חסרה רשומה, העתק אותה מ־Namecheap: Domain List ← Manage ← Advanced DNS.
4. בסוף Cloudflare מציג **שני nameservers**, למשל `xxx.ns.cloudflare.com`. השאר את החלון פתוח.

## שלב 2: החלפת ה־nameservers ב־Namecheap
1. ב־Namecheap: **Domain List** ← לחץ **Manage** ליד הדומיין.
2. תחת **Nameservers** בחר **Custom DNS**, הדבק את שני ה־nameservers של Cloudflare ושמור (✓).
3. חזור ל־Cloudflare ולחץ **Check nameservers**. הסטטוס יהפוך ל־**Active** תוך דקות, ולפעמים עד 24 שעות.
4. **בדוק שהאתר והמייל שלך ממשיכים לעבוד.** אם משהו לא עובד, הוסף ב־Cloudflare (לשונית DNS) את הרשומה שחסרה.

> המעבר הזה מעביר את ניהול ה־DNS של **כל** הדומיין ל־Cloudflare. הדומיין עצמו נשאר רשום ב־Namecheap. אפשר לחזור אחורה בכל רגע: מחזירים ב־Namecheap את האפשרות **Namecheap BasicDNS**.

## שלב 3: יצירת Zero Trust (חינם, פעם אחת)
1. ב־Cloudflare, בתפריט הצד: **Zero Trust**.
2. בחר **team name**, למשל `yotam-sportreel`. שמור את השם, הוא יידרש בשלב 6.
3. בחר בחבילה **Free**. ייתכן שתתבקש להזין אמצעי תשלום לאימות; החבילה החינמית לא מחויבת.

## שלב 4: חיבור המחשב (Tunnel)
1. ב־Zero Trust: **Networks** ← **Tunnels** ← **Create a tunnel** ← **Cloudflared**.
2. שם למנהרה: `sportreel-studio` ← **Save tunnel**.
3. בחר **Windows** והעתק את הפקודה שמופיעה, שמתחילה ב־`cloudflared.exe service install`.
4. פתח **PowerShell כמנהל** (לחיצה ימנית ← Run as administrator) והרץ:
   ```powershell
   winget install --id Cloudflare.cloudflared
   ```
   סגור את החלון, פתח שוב PowerShell כמנהל, והדבק את הפקודה מסעיף 3. מעכשיו המנהרה עולה אוטומטית עם המחשב.
5. חזור לדפדפן ולחץ **Next**. תחת **Public hostname**:
   - **Subdomain:** `studio`
   - **Domain:** הדומיין שלך
   - **Service:** סוג `HTTP`, כתובת `localhost:4173`
   - לחץ **Save tunnel**.

## שלב 5: כניסה רק למייל שלך (Access)
1. ב־Zero Trust: **Access** ← **Applications** ← **Add an application** ← **Self-hosted**.
2. **Application name:** `SportReel Studio`. **Domain:** `studio` ובחר את הדומיין שלך.
3. **Policy:** שם `owner`, Action **Allow**, ותחת Include בחר **Emails** והקלד את המייל שלך.
4. שיטת כניסה: **One-time PIN**, כלומר קוד למייל.
5. שמור. בעמוד האפליקציה (**Overview**) העתק את **Application Audience (AUD) Tag**, מחרוזת ארוכה.

## שלב 6: הגדרה בסטודיו
פתח את `annotation-studio\.studio-cloud.env` והוסף שלוש שורות:
```
STUDIO_PUBLIC_HOST=studio.הדומיין-שלך
STUDIO_ACCESS_TEAM=שם-הצוות-משלב-3
STUDIO_ACCESS_AUD=המחרוזת-משלב-5
```
הפעל מחדש את הסטודיו מהקיצור בשולחן העבודה. בחלון ההפעלה תופיע השורה `Permanent address: https://studio.…/#/catalog`.

## שלב 7: כניסה ראשונה
1. כדי לראות את הטוקן, הרץ מתוך `annotation-studio`:
   ```powershell
   $h = (Select-String -Path .studio-cloud.env -Pattern '^STUDIO_HOME=(.*)$').Matches[0].Groups[1].Value.Trim('"'); Get-Content "$h\token"
   ```
2. פתח בדפדפן `https://studio.הדומיין-שלך/?t=הטוקן`. תתבקש להזין את המייל ואת הקוד שקיבלת.
3. מעכשיו הכתובת הקבועה היא **`https://studio.הדומיין-שלך/#/catalog`**. שמור אותה במועדפים. בכל מכשיר חדש עושים פעם אחת את סעיף 2.

## בדיקה
- מהטלפון, **לא** דרך ה־Wi‑Fi של הבית: פתח את הכתובת. צריך להתבקש קוד מייל, ואחריו נפתח הסטודיו.
- ממייל אחר: הכניסה צריכה להיחסם.

## אם משהו לא עובד
| מה רואים | מה לעשות |
|---|---|
| עמוד Cloudflare עם השגיאה 502 או 1033 | הסטודיו או המחשב כבויים, או שהמנהרה לא רצה. הפעל את הסטודיו. ב־Zero Trust ← Tunnels הסטטוס צריך להיות Healthy. |
| "הכתובת הקבועה עוד לא מוגנת בכניסה" | חסרות השורות `STUDIO_ACCESS_TEAM` או `STUDIO_ACCESS_AUD` (שלב 6), או שהסטודיו לא הופעל מחדש. |
| "נדרשת כניסה דרך Cloudflare Access" | האפליקציה בשלב 5 לא מכסה את הכתובת, או שהועתק AUD לא נכון. |
| "הדפדפן הזה עוד לא מחובר לסטודיו" | בצע את שלב 7 בדפדפן הזה. |

## ביטול
- **הכתובת בלבד:** ב־Zero Trust ← Tunnels ← sportreel-studio מחק את ה־Public hostname. בנוסף, הסר את שלוש השורות מ־`.studio-cloud.env`.
- **כל המנהרה:** ב־PowerShell כמנהל הרץ `cloudflared.exe service uninstall`.

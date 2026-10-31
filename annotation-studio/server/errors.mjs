// Stable error codes (spec §16.1) with operator-facing Hebrew messages. Messages never
// carry credentials or internal paths.
const HE = {
  INVALID_INTERVAL: 'טווח פריימים לא תקין',
  INVALID_BBOX: 'תיבת תיחום לא תקינה',
  VERSION_CONFLICT: 'הטיוטה עודכנה במקום אחר — יש לטעון מחדש',
  ARCHIVE_UNVERIFIED: 'ארכיון המקור לא אומת',
  SOURCE_UNAVAILABLE: 'הסרטון אינו זמין',
  PERMISSION_DENIED: 'אין הרשאה',
  EDL_UNVERIFIED: 'מיפוי פלט→מקור לא מאומת',
  INGEST_RETRYABLE: 'קליטה נכשלה זמנית — ניתן לנסות שוב',
  INVALID_INPUT: 'קלט לא תקין',
  NOT_FOUND: 'לא נמצא',
  UNRESOLVED_ITEMS: 'יש פריטים לא פתורים — נדרש אישור מפורש',
  CLOUD_NOT_CONFIGURED: 'חיבור הענן אינו מוגדר — ראה את מדריך ההפעלה (טוקן קריאה בלבד ל-R2)',
  SOURCE_UNVERIFIED: 'זהות הסרטון בענן טרם אומתה (SHA-256) — יש להריץ אימות לפני אישור Ground Truth',
  SPORT_EVENT_MISMATCH: 'סוג האירוע אינו תואם לענף הספורט',
  SPORT_INCOMPATIBLE: 'לשינוי הענף יש מקטעים עם סוגי אירוע לא תואמים — יש למפות מחדש או לאשר במפורש',
};
const STATUS = { VERSION_CONFLICT: 409, PERMISSION_DENIED: 401, NOT_FOUND: 404, SOURCE_UNAVAILABLE: 503, ARCHIVE_UNVERIFIED: 409, UNRESOLVED_ITEMS: 409, SPORT_INCOMPATIBLE: 409, SOURCE_UNVERIFIED: 409, CLOUD_NOT_CONFIGURED: 503 };

export class ApiError extends Error {
  constructor(code, detail) {
    super(detail || HE[code] || code);
    this.code = code; this.status = STATUS[code] ?? 400; this.he = HE[code] ?? code;
  }
}

"""Monitor Google's public Gemini model policy without running inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

DEPRECATIONS_URL = "https://ai.google.dev/gemini-api/docs/deprecations.md"
PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing.md"
BILLING_URL = "https://aistudio.google.com/usage"
MODEL_ID = r"gemini-[a-z0-9][a-z0-9.-]{0,70}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_public(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20) as result:
        data = result.read(1_000_001)
    if len(data) > 1_000_000:
        raise ValueError("Google documentation exceeds the response size limit")
    return data.decode("utf-8")


def pipeline_model(workflow: str, configured: str) -> str:
    match = re.search(r"GEMINI_MODEL:.*?vars\.GEMINI_MODEL\s*\|\|\s*'([^']+)'", workflow)
    selected = configured.strip() or (match[1] if match else "")
    if not re.fullmatch(MODEL_ID, selected):
        raise ValueError("Could not determine the configured Gemini model")
    return selected


def transition_for(document: str, model: str) -> dict | None:
    for table in re.findall(r"{% table %}(.*?){% /table %}", document, re.S):
        if "Shutdown date" not in table or "Recommended replacement" not in table:
            continue
        for row in re.split(r"^\s*---\s*$", table, flags=re.M):
            cells = re.findall(r"^\s*\*\s+(.+)$", row, flags=re.M)
            if len(cells) != 4 or cells[0].split(" ")[0] != f"`{model}`":
                continue
            replacement = re.search(rf"`({MODEL_ID})`", cells[3])
            return {"date": cells[2], "replacement": replacement[1] if replacement else None}
    if "{% table %}" not in document:
        raise ValueError("Unrecognized Google deprecation document")
    return None


def standard_pricing(document: str, model: str) -> dict | None:
    heading = re.search(rf'^## .+?{{% id="{re.escape(model)}" %}}\s*$', document, re.M)
    if not heading:
        return None
    section = re.split(r"^## ", document[heading.end():], maxsplit=1, flags=re.M)[0]
    standard = re.search(r'{% tab title="Standard" %}(.*?)({% /tab %}|{% tab title=)', section, re.S)
    table = standard[1] if standard else section
    pricing: dict[str, str] = {}
    for row in re.split(r"^\s*---\s*$", table, flags=re.M):
        cells = re.findall(r"^\s*\*\s+(.+)$", row, flags=re.M)
        if len(cells) < 3 or not cells[0].startswith(("Input price", "Output price")):
            continue
        name = cells[0].split(" ", 1)[0].lower()
        if name in pricing:
            continue
        pricing[name] = cells[1].strip()
    if set(pricing) != {"input", "output"}:
        return None
    if all(value.lower() == "free of charge" for value in pricing.values()):
        return {"free": "listed"}
    if any(value.lower() == "not available" for value in pricing.values()):
        return {"free": "unavailable"}
    return {"free": "check terms", **pricing}


def model_access(model: str, key: str) -> str:
    if not key:
        return "secret missing"
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}",
        headers={"x-goog-api-key": key},
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            return f"HTTP {response.status}"
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}"


def snapshot(model: str, deprecations: str, pricing: str, access: str, today: date | None = None) -> dict:
    transition = transition_for(deprecations, model)
    replacement = transition["replacement"] if transition else None
    if transition:
        try:
            published_date = datetime.strptime(transition["date"], "%B %d, %Y").date()
        except ValueError:
            pass
        else:
            transition["date_reached"] = (today or date.today()) >= published_date
    return {
        "model": model,
        "access": access,
        "transition": transition,
        "model_pricing": standard_pricing(pricing, model),
        "replacement_pricing": standard_pricing(pricing, replacement) if replacement else None,
    }


def needs_notice(previous: dict | None, current: dict) -> bool:
    if previous is not None:
        return previous != current
    return bool(current["transition"] or current["access"] != "HTTP 200" or
                current["model_pricing"] != {"free": "listed"})


def mail_message(previous: dict | None, status: dict) -> str:
    transition = status["transition"]
    lines = [
        "בדיקת מודל Gemini בפייפליין של SportReel",
        f"המודל המוגדר: {status['model']}",
        f"גישת קריאה לקטלוג: {status['access']}",
    ]
    if previous and previous["model"] != status["model"]:
        lines.append(f"המודל הקודם: {previous['model']}")
    if transition:
        lines.append(f"המועד שפורסם: {transition['date']}; מודל חלופי: {transition['replacement'] or 'טרם צוין'}.")
        if transition.get("date_reached"):
            lines.append("המועד שפרסמה Google הגיע. בדוק את המודל ואת תנאי החיוב לפני עיבוד וידאו.")
    for label, price in (("המודל הנוכחי", status["model_pricing"]), ("המודל החלופי", status["replacement_pricing"])):
        if price:
            terms = {
                "listed": "מפורסם מסלול חינמי ל־Standard.",
                "unavailable": "אין מסלול חינמי מלא ל־Standard. בדוק חיוב לפני הרצה.",
                "check terms": "תנאי המסלול החינמי דורשים בדיקה ידנית.",
            }
            lines.append(f"{label} — {terms[price['free']]}")
        elif label == "המודל הנוכחי" or (transition and transition["replacement"]):
            lines.append(f"{label} — תנאי המסלול החינמי לא זוהו בתיעוד. נדרשת בדיקה.")
    lines += [
        "קריאת הקטלוג אינה בודקת מכסה או הרשאת עיבוד בפרויקט. בדיקה זו אינה מפעילה מודל או חיוב.",
        f"סטטוס החיוב בפרויקט: {BILLING_URL}",
        f"הודעות מעבר: {DEPRECATIONS_URL.removesuffix('.md')}",
        f"מחירים: {PRICING_URL.removesuffix('.md')}",
    ]
    return "\n".join(lines)


def send_notice(body: str, fingerprint: str):
    key = os.environ.get("RESEND_API_KEY")
    sender = os.environ.get("RESEND_FROM_EMAIL")
    recipient = os.environ.get("NOTIFY_EMAIL")
    if not all((key, sender, recipient)):
        raise ValueError("Email needs RESEND_API_KEY, RESEND_FROM_EMAIL and an owner recipient")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({"from": sender, "to": [recipient],
                         "subject": "SportReel | שינוי במודל Gemini או בתנאי הגישה", "text": body}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "Idempotency-Key": f"sportreel-gemini/{fingerprint}"},
        method="POST",
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as result:
            if not json.load(result).get("id"):
                raise ValueError("Resend did not return a message ID")
    except urllib.error.HTTPError as error:
        raise ValueError(f"Resend rejected the alert (HTTP {error.code})") from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    previous = json.loads(args.state.read_text()) if args.state.exists() else None
    model = pipeline_model(Path(".github/workflows/pipeline-run.yml").read_text(),
                           os.environ.get("GEMINI_MODEL", ""))
    current = snapshot(model, read_public(DEPRECATIONS_URL), read_public(PRICING_URL),
                       model_access(model, os.environ.get("GEMINI_API_KEY", "")))
    if needs_notice(previous, current):
        print(mail_message(previous, current))
        if args.send:
            digest = hashlib.sha256(json.dumps([previous, current], sort_keys=True).encode()).hexdigest()
            send_notice(mail_message(previous, current), digest)
    else:
        print("Gemini model policy and catalog access are unchanged.")
    if args.send:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(current, sort_keys=True))


if __name__ == "__main__":
    main()

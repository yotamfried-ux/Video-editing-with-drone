"""Face recognition — compute embeddings for registered athletes and match against reel persons."""

import io
import logging

logger = logging.getLogger(__name__)


def compute_pending_embeddings() -> None:
    """For every athlete_profile with a photo but no face_embedding, compute and store it."""
    try:
        import face_recognition
        from integrations.supabase_uploader import _supabase
    except ImportError:
        logger.warning("face_recognition not installed — skipping embedding computation")
        return

    sb = _supabase()
    profiles = sb.table("athlete_profiles").select("id, photo_path").is_("face_embedding", "null").execute()

    for p in profiles.data:
        if not p.get("photo_path"):
            continue
        try:
            img_bytes = sb.storage.from_("athlete-photos").download(p["photo_path"])
            img = face_recognition.load_image_file(io.BytesIO(img_bytes))
            encs = face_recognition.face_encodings(img)
            if encs:
                sb.table("athlete_profiles").update(
                    {"face_embedding": encs[0].tolist()}
                ).eq("id", p["id"]).execute()
                logger.info("Computed embedding for athlete %s", p["id"])
        except Exception:
            logger.exception("Failed to compute embedding for athlete %s", p["id"])


def match_and_notify(persons: list[dict], video_path: str) -> None:
    """Match each person from the pipeline against registered athletes; push-notify on match."""
    try:
        import face_recognition
        from integrations.supabase_uploader import _supabase
    except ImportError:
        logger.warning("face_recognition not installed — skipping face matching")
        return

    compute_pending_embeddings()
    sb = _supabase()

    for person in persons:
        if not person.get("events"):
            continue
        try:
            from pipeline.stages.editor import extract_frame
            best_event = person["events"][0]
            frame_path = extract_frame(video_path, best_event["start"] + 0.5)

            img = face_recognition.load_image_file(frame_path)
            encs = face_recognition.face_encodings(img)
            if not encs:
                continue

            result = sb.rpc("match_athlete_face", {
                "query_embedding": encs[0].tolist(),
                "threshold": 0.60,
            }).execute()

            if not result.data:
                continue

            match = result.data[0]
            sb.table("reels").update(
                {"matched_athlete": match["id"]}
            ).eq("athlete_desc", person.get("description", "")).execute()

            if match.get("push_token"):
                _send_push_notification(match["push_token"], person)

        except Exception:
            logger.exception("Face matching failed for person: %s", person.get("description"))


def match_reel_and_notify(reel_id: str, frame_path: str) -> None:
    """Match a pre-extracted video frame against registered athletes.

    Called at Phase 2a (approval) with an already-extracted frame image path.
    On match: updates reels.matched_athlete, sends push notification + email.
    """
    try:
        import face_recognition
        from integrations.supabase_uploader import _supabase
    except ImportError:
        logger.warning("face_recognition not installed — skipping face matching")
        return

    compute_pending_embeddings()
    sb = _supabase()

    try:
        img = face_recognition.load_image_file(frame_path)
        encs = face_recognition.face_encodings(img)
        if not encs:
            logger.debug("No face found in frame for reel %s", reel_id)
            return

        result = sb.rpc("match_athlete_face", {
            "query_embedding": encs[0].tolist(),
            "threshold": 0.60,
        }).execute()

        if not result.data:
            logger.debug("No athlete match for reel %s", reel_id)
            return

        match = result.data[0]
        sb.table("reels").update(
            {"matched_athlete": match["id"]}
        ).eq("id", reel_id).execute()
        logger.info("Matched reel %s to athlete %s", reel_id, match["id"])

        if match.get("push_token"):
            _send_push_notification(match["push_token"], {"events": [{}]})

        # match_athlete_face RPC returns the athlete's email directly
        athlete_email = match.get("email") or ""
        if athlete_email:
            try:
                from integrations.notifier import send_summary_email
                import config
                domain = getattr(config, "APP_DOMAIN", "sportreel.app")
                reel_row = sb.table("reels").select("token").eq("id", reel_id).limit(1).execute()
                reel_url = (
                    f"https://{domain}/reel/{reel_row.data[0]['token']}"
                    if reel_row.data
                    else f"https://{domain}/discover"
                )
                send_summary_email(
                    recipients=[athlete_email],
                    clips_links=[reel_url],
                    sport_type="mixed",
                    video_name="Your highlight clip is ready",
                )
                logger.info("Sent match notification email to %s for reel %s", athlete_email, reel_id)
            except Exception:
                logger.warning("Failed to send match email to %s for reel %s", athlete_email, reel_id)

    except Exception:
        logger.exception("Face matching failed for reel %s", reel_id)


def _send_push_notification(push_token: str, person: dict) -> None:
    """Send Expo push notification to athlete."""
    import requests
    clip_count = len(person.get("events", []))
    body = (
        f"You have {clip_count} new highlight clip{'s' if clip_count != 1 else ''}!"
        if clip_count > 1
        else "You have a new highlight clip ready!"
    )
    payload = {
        "to": push_token,
        "title": "Your SportReel highlight is ready 🎬",
        "body": body,
        "data": {"screen": "highlights"},
    }
    try:
        resp = requests.post(
            "https://exp.host/--/api/v2/push/send",
            json=payload,
            headers={"Accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception:
        logger.warning("Failed to send push notification to %s", push_token)

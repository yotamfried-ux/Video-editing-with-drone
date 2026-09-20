"""Regression tests for approval -> Discover delivery invariants."""
import sys, types
from unittest.mock import MagicMock, patch

# Import with lightweight config/integration stubs so this contract test never uses credentials.
sys.modules.setdefault("config", types.SimpleNamespace(REEL_METADATA_FILE="/nonexistent", OWNER_EMAIL="owner@example.test"))
sys.modules.setdefault("integrations.delivery_status", types.SimpleNamespace(mark_delivery_run=lambda **k: None))
drive=types.SimpleNamespace(download_video=lambda *a: "/tmp/x.mp4",get_approved_drafts=lambda:[],get_pending_payment_drafts=lambda:[],mark_draft_delivered=lambda *a:None,move_to_pending_payment=lambda *a:None,upload_preview=lambda *a:"preview")
sys.modules.setdefault("integrations.drive", drive)
sys.modules.setdefault("integrations.notifier", types.SimpleNamespace(send_summary_email=lambda **k:None))
sys.modules.setdefault("pipeline.stages.editor", types.SimpleNamespace(create_preview=lambda *a,**k:"/tmp/p.mp4"))
sys.modules.setdefault("pipeline.stages.feedback", types.SimpleNamespace(record_approval=lambda **k:None))
sys.modules.setdefault("services.client_manager", types.SimpleNamespace(find_client=lambda *a:None))

import services.delivery as d

def test_discover_failure_does_not_advance_to_payment():
    draft={"id":"approved/test.mp4","name":"test.mp4","webViewLink":"https://example.test/test","createdTime":"2026-09-20T12:00:00+00:00"}
    moved=MagicMock()
    status=MagicMock()
    fake_uploader=types.SimpleNamespace(publish_reel_approved=MagicMock(side_effect=RuntimeError("publish failed")))
    with patch.object(d,"get_approved_drafts",return_value=[draft]), patch.object(d,"download_video",return_value="/tmp/x.mp4"), patch.object(d,"create_preview",return_value="/tmp/p.mp4"), patch.object(d,"upload_preview",return_value="preview"), patch.object(d,"move_to_pending_payment",moved), patch.object(d,"_remove"), patch.object(d,"mark_delivery_run",status), patch.dict(sys.modules,{"integrations.supabase_uploader":fake_uploader}):
        try:
            d.deliver_preview()
            raise AssertionError("expected delivery failure")
        except RuntimeError as exc:
            assert "Discover publish failed" in str(exc)
    moved.assert_not_called()
    assert any(call.kwargs.get("status")=="failed" and call.kwargs.get("stage")=="discover_publish_failed" for call in status.mock_calls)

def test_delivery_passes_storage_metadata_date():
    draft={"id":"approved/test.mp4","name":"test.mp4","webViewLink":"https://example.test/test","createdTime":"2026-09-20T12:00:00+00:00"}
    publish=MagicMock(return_value="reel-1")
    fake_uploader=types.SimpleNamespace(publish_reel_approved=publish)
    with patch.object(d,"get_approved_drafts",return_value=[draft]), patch.object(d,"download_video",return_value="/tmp/x.mp4"), patch.object(d,"create_preview",return_value="/tmp/p.mp4"), patch.object(d,"upload_preview",return_value="preview"), patch.object(d,"move_to_pending_payment"), patch.object(d,"_remove"), patch.object(d,"mark_delivery_run"), patch.object(d,"send_summary_email"), patch.object(d,"_mark_previewed"), patch.dict(sys.modules,{"integrations.supabase_uploader":fake_uploader}):
        d.deliver_preview()
    assert publish.call_args.kwargs["recording_date"]=="2026-09-20"

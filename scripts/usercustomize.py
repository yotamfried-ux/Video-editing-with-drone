"""Extra bootstrap after sitecustomize."""

for _module in [
    "pipeline.source_evidence_patch",
    "pipeline.surf_ride_gate",
]:
    try:
        __import__(_module, fromlist=["install"]).install()
    except Exception:
        pass

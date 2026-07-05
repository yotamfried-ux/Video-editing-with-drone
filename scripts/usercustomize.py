"""Extra bootstrap after sitecustomize."""
try:
    from pipeline.source_evidence_patch import install
    install()
except Exception:
    pass

"""Isolated real-R2 conditional copy probe; touches only a unique test prefix."""
import concurrent.futures
import hashlib
import json
import os
import uuid

from botocore.exceptions import ClientError
from integrations import r2_storage as r2

def main():
    prefix = "integration-probes/conditional-copy/" + uuid.uuid4().hex + "/"
    keys = [prefix + name for name in ("source", "target", "race")]
    client, bucket = r2._client(), r2._bucket()
    evidence = {"prefix": prefix, "bucket": bucket, "checks": {}, "cleanup": "pending"}
    path = os.environ.get("R2_PROBE_EVIDENCE_PATH", "/tmp/r2-conditional-copy-evidence.json")
    def record():
        with open(path, "w", encoding="utf-8") as f:
            json.dump(evidence, f, indent=2)
    def payload(key):
        return client.get_object(Bucket=bucket, Key=key)["Body"].read()
    try:
        client.put_object(Bucket=bucket, Key=keys[0], Body=b"source-content")
        r2.copy_object_if_absent(keys[0], keys[1])
        assert payload(keys[1]) == b"source-content"
        evidence["checks"]["create_if_absent"] = "passed"
        try:
            r2.copy_object_if_absent(keys[0], keys[1])
        except RuntimeError:
            pass
        else:
            raise AssertionError("existing destination was overwritten")
        assert payload(keys[1]) == b"source-content"
        evidence["checks"]["existing_destination_preserved"] = "passed"
        def attempt(_):
            try:
                r2.copy_object_if_absent(keys[0], keys[2])
                return "created"
            except RuntimeError:
                return "conflict"
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, range(2)))
        assert sorted(outcomes) == ["conflict", "created"], outcomes
        assert payload(keys[2]) == b"source-content"
        assert payload(keys[0]) == b"source-content"
        evidence["checks"]["concurrent_create_only"] = "passed"
        evidence["checks"]["source_preserved"] = "passed"
    finally:
        errors = []
        for key in keys:
            try:
                client.delete_object(Bucket=bucket, Key=key)
            except Exception as exc:
                errors.append(type(exc).__name__ + ": " + str(exc))
        evidence["cleanup"] = "failed" if errors else "completed"
        if errors:
            evidence["cleanup_errors"] = errors
        record()
        if errors:
            raise RuntimeError("R2 probe cleanup failed: " + "; ".join(errors))
    print(json.dumps(evidence, indent=2))

if __name__ == "__main__":
    main()

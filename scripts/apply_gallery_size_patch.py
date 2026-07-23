#!/usr/bin/env python3
"""One-shot deterministic patch for gallery source-size evidence."""

from pathlib import Path

PATH = Path("mobile/src/app/(operator)/pipeline.tsx")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    source = PATH.read_text(encoding="utf-8")

    source = replace_once(
        source,
        "  mimeType: string;\n  progress: number;",
        "  mimeType: string;\n  sourceSizeBytes?: number;\n  progress: number;",
        "UploadFileState source size",
    )

    source = replace_once(
        source,
        "  const requestUploadSession = async (item: UploadFileState): Promise<UploadSession> => {\n    const uploadInit = await operatorFetch<UploadInit>(",
        "  const requestUploadSession = async (item: UploadFileState): Promise<UploadSession> => {\n    let sourceSizeBytes = item.sourceSizeBytes;\n    if (!Number.isSafeInteger(sourceSizeBytes) || Number(sourceSizeBytes) <= 0) {\n      const info = await FileSystem.getInfoAsync(item.uri, { size: true });\n      if (!info.exists || info.isDirectory || !Number.isSafeInteger(info.size) || Number(info.size) <= 0) {\n        throw new Error(`Cannot determine a stable positive source size for ${item.filename}.`);\n      }\n      sourceSizeBytes = Number(info.size);\n      item.sourceSizeBytes = sourceSizeBytes;\n    }\n\n    const uploadInit = await operatorFetch<UploadInit>(",
        "gallery source inspection",
    )

    source = replace_once(
        source,
        "          mimeType: item.mimeType,\n          batch_id: item.batch_id ?? activeBatchId,",
        "          mimeType: item.mimeType,\n          size: sourceSizeBytes,\n          batch_id: item.batch_id ?? activeBatchId,",
        "gallery upload init size",
    )

    source = replace_once(
        source,
        "        mimeType: selectedAssetMimeType(asset),\n        progress: 0,",
        "        mimeType: selectedAssetMimeType(asset),\n        sourceSizeBytes: asset.fileSize ?? undefined,\n        progress: 0,",
        "ImagePicker file size",
    )

    required = [
        "sourceSizeBytes?: number;",
        "FileSystem.getInfoAsync(item.uri, { size: true })",
        "size: sourceSizeBytes,",
        "sourceSizeBytes: asset.fileSize ?? undefined,",
    ]
    missing = [token for token in required if token not in source]
    if missing:
        raise SystemExit(f"gallery size patch incomplete: {missing}")

    PATH.write_text(source, encoding="utf-8")
    print("Gallery source-size patch applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

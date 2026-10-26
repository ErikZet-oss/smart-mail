# ADR-002: SeaweedFS instead of MinIO for local S3 storage

- Status: accepted (Phase 0, 26 October 2026)
- Context: CLAUDE.md §2 lists "S3-compatible storage (MinIO in compose)". The CI run of 26 October 2026 could not pull
  any MinIO image: `minio/minio` no longer exists on Docker Hub and `quay.io/minio/minio` requires authentication.

## Decision
The compose service `s3` runs the SeaweedFS S3 gateway (`chrislusf/seaweedfs`, port 8333). The application only uses
the S3 API (`S3_ENDPOINT`, bucket, access/secret key), so production can use any S3-compatible storage without code
changes.

## Consequences
- No web console in dev (MinIO had one on :9001); objects can be inspected with any S3 client.
- CLAUDE.md §2 wording "MinIO in compose" is superseded by this ADR.

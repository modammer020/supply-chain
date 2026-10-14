# minio-local (optioneel, offline builds)

`compose.yaml` gebruikt standaard de publieke images `minio/minio:latest` en
`minio/mc:latest` — deze folder is alleen nodig als je host **geen internet**
heeft en je de images zelf wilt bouwen.

Binary's `minio` (~100 MB) en `mc` (~30 MB) staan hier **niet** in de repo
(GitHub-limiet 100 MB per bestand). Haal ze zo op:

```bash
# minio
curl -fsSL https://dl.min.io/server/minio/release/linux-amd64/minio -o minio
# mc (client)
curl -fsSL https://dl.min.io/client/mc/release/linux-amd64/mc -o mc
chmod +x minio mc

podman build -f Dockerfile.minio -t aegis/minio-local .
podman build -f Dockerfile.mc   -t aegis/mc-local .
```

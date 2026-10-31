#!/usr/bin/env bash
# Smart Mail – kľúč pre schvaľovacie tokeny zápisov do Money (fáza 3f, #144).
#   ./deploy/approval-key.sh
# Ak v deploy/.env ešte nie je APPROVAL_JWT_PRIVATE_KEY, vytvorí ho (súkromný kľúč nikdy nevypíše).
# Potom vypíše VEREJNÝ kľúč – ten skopírujte do C:\SmartMail\bridge\.env ako APPROVAL_JWT_PUBLIC_KEY=…
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=lib.sh
source ./lib.sh
ENV_FILE="${ENV_FILE:-.env}"
[ -f "$ENV_FILE" ] || { echo "Chýba $ENV_FILE – najprv spustite install.sh."; exit 1; }
need_cmd openssl
if ! grep -q '^APPROVAL_JWT_PRIVATE_KEY=.\+' "$ENV_FILE"; then
  umask 077
  key="$(ed25519_private_b64)"
  [ -n "$key" ] || { echo "openssl nevytvoril kľúč Ed25519 (treba OpenSSL 1.1.1+)."; exit 1; }
  sed -i '/^APPROVAL_JWT_PRIVATE_KEY=/d' "$ENV_FILE"
  printf 'APPROVAL_JWT_PRIVATE_KEY=%s\n' "$key" >>"$ENV_FILE"
  chmod 600 "$ENV_FILE"
  unset key
  echo "Nový kľúč je uložený v $ENV_FILE (súkromný kľúč sa nikde nevypisuje). Spustite ./update.sh."
fi
private="$(grep '^APPROVAL_JWT_PRIVATE_KEY=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
public="$(printf '%s' "$private" | ed25519_public_b64)"
unset private
[ -n "$public" ] || { echo "Verejný kľúč sa nepodarilo odvodiť."; exit 1; }
echo
echo "Verejný kľúč pre most (skopírujte celý riadok do C:\\SmartMail\\bridge\\.env):"
echo "APPROVAL_JWT_PUBLIC_KEY=${public}"

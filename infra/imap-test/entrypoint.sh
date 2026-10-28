#!/bin/bash
# Start Dovecot (IMAP/Sieve/LMTP) then the AUTH SMTP→LMTP bridge on :587 (GitHub #20).
set -euo pipefail
dovecot -F &
DOVECOT_PID=$!
# Wait until LMTP is accepting before binding submission
for _ in $(seq 1 50); do
  if bash -c 'echo > /dev/tcp/127.0.0.1/24' 2>/dev/null; then
    break
  fi
  sleep 0.1
done
python3 /usr/local/bin/smtp_auth_lmtp.py &
SMTP_PID=$!
trap 'kill $DOVECOT_PID $SMTP_PID 2>/dev/null || true' EXIT
wait -n $DOVECOT_PID $SMTP_PID
exit $?
